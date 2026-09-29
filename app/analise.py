"""Análise de um candidato: chance (deputados), orientação e pautas, sinais de atenção.

Os sinais são fatos verificáveis com fonte, nunca acusações. Um sinal de
"atenção" quer dizer "vale conferir", não "é irregular".
"""
import json
import re
import threading
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlencode

from curl_cffi import requests

import alesp
import camara
import emendas
import empresas
import gastos
import historico
import partidos as perfis
import punicoes
import sancoes
import tse

URL_PORTAL = "https://api.portaldatransparencia.gov.br/api-de-dados"
URL_CAMARA = "https://dadosabertos.camara.leg.br/api/v2"
URL_IPCA = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.433/dados?formato=json&dataInicial=01/07/1994&dataFinal=31/12/{ano}"
DURACAO_MANDATO = {"Senador": 8, "1º Suplente": 8, "2º Suplente": 8}
TTL_EXTERNO = 7 * 24 * tse.HORA

MOTIVOS = {
    "st_MOTIVO_FICHA_LIMPA": "Lei da Ficha Limpa",
    "st_MOTIVO_ABUSO_PODER": "abuso de poder",
    "st_MOTIVO_COMPRA_VOTO": "compra de voto",
    "st_MOTIVO_CONDUTA_VEDADA": "conduta vedada a agente público",
    "st_MOTIVO_GASTO_ILICITO": "gasto ilícito de recursos",
    "st_MOTIVO_AUSENCIA_REQUISITO": "falta de requisito para a candidatura",
    "st_MOTIVO_IND_PARTIDO": "indeferimento do partido",
}

# Mudanças de nome e fusões não contam como troca de partido.
MESMO_PARTIDO = {
    "PMDB": "MDB", "PRB": "REPUBLICANOS", "PR": "PL", "PPS": "CIDADANIA", "PSDC": "DC", "PTN": "PODE",
    "PHS": "PODE", "PSC": "PODE", "PT DO B": "AVANTE", "PTDOB": "AVANTE", "DEM": "UNIÃO", "PSL": "UNIÃO",
    "PEN": "PRD", "PATRI": "PRD", "PATRIOTA": "PRD", "PRP": "PRD", "PTB": "PRD", "SD": "SOLIDARIEDADE",
    "PROS": "SOLIDARIEDADE", "PMN": "MOBILIZA", "PC DO B": "PCDOB", "PCDOB": "PCDOB",
}

_config_arq = None
_lock = threading.Lock()


def configurar(arquivo_config):
    global _config_arq
    _config_arq = Path(arquivo_config)


def _config():
    if _config_arq and _config_arq.exists():
        try:
            return json.loads(_config_arq.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def tem_chave_portal():
    return bool(_config().get("chavePortal"))


def salvar_chave_portal(chave):
    with _lock:
        cfg = _config()
        if chave:
            cfg["chavePortal"] = chave
        else:
            cfg.pop("chavePortal", None)
        _config_arq.parent.mkdir(parents=True, exist_ok=True)
        _config_arq.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def _get_json(url, chave_cache, headers=None):
    """GET com cache em disco. Retorna None se a fonte estiver fora do ar."""
    arq = tse._cache_dir / "externo" / chave_cache
    if arq.exists() and datetime.now().timestamp() - arq.stat().st_mtime < TTL_EXTERNO:
        return json.loads(arq.read_text(encoding="utf-8"))
    try:
        r = requests.get(url, impersonate="chrome", timeout=30, headers=headers or {})
    except Exception:  # noqa: BLE001
        return None
    if r.status_code == 404:
        dados = {}
    elif r.status_code != 200:
        return None
    else:
        dados = r.json()
    arq.parent.mkdir(parents=True, exist_ok=True)
    arq.write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")
    return dados


def _sinal(nivel, titulo, detalhe, fonte, link=None, cnpj=None, categoria="integridade"):
    return {"nivel": nivel, "titulo": titulo, "detalhe": detalhe, "fonte": fonte, "link": link, "cnpj": cnpj,
            "categoria": categoria}


def _brl(v):
    return "R$ " + f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _brl0(v):
    """Valor sem centavos, para estimativas e valores corrigidos."""
    return "R$ " + f"{v:,.0f}".replace(",", ".")


# ---------- sinais ----------

def _sinais_candidatura(bruto):
    s = []
    situacao = (bruto.get("descricaoSituacao") or "").lower()
    if "indeferido" in situacao or "cancel" in situacao or "renúncia" in situacao:
        s.append(_sinal("alerta", "Candidatura com registro negado ou cancelado",
                        f"No TSE, a situação é {bruto.get('descricaoSituacao', '').lower()}. Os votos nesta candidatura podem ser anulados.",
                        "TSE"))
    elif "pendente" in situacao or "recurso" in situacao:
        s.append(_sinal("atencao", "Candidatura ainda em julgamento",
                        f"No TSE, a situação é {bruto.get('descricaoSituacao', '').lower()}. Se o registro for negado, os votos podem ser anulados.",
                        "TSE"))
    motivos = [nome for campo, nome in MOTIVOS.items() if bruto.get(campo)]
    if motivos:
        s.append(_sinal("alerta", "Motivos de indeferimento registrados",
                        "O TSE registra estes motivos: " + ", ".join(motivos) + ".", "TSE"))
    return s


# ---------- trajetória ----------

def _ipca_fatores():
    """Fator que leva um valor de julho de cada ano para o preço de hoje, pelo IPCA do Banco Central."""
    hoje = date.today()
    # A API do BCB devolve vazio se faltar a data final.
    d = _get_json(URL_IPCA.format(ano=hoje.year), f"ipca_{hoje:%Y%m}.json")
    if not d:
        return {}
    indice, por_mes = 1.0, {}
    for x in d:
        indice *= 1 + float(x["valor"]) / 100
        por_mes[x["data"][3:]] = indice
    return {ano: indice / por_mes[f"07/{ano}"] for ano in range(1995, hoje.year + 1) if f"07/{ano}" in por_mes}


def _eleito(resultado):
    return (resultado or "").startswith("Eleito") or resultado == "Média"


def listar(itens):
    itens = list(itens)
    if not itens:
        return ""
    return itens[0] if len(itens) == 1 else ", ".join(itens[:-1]) + " e " + itens[-1]


def trajetoria(bruto):
    """Todas as candidaturas da pessoa, com o patrimônio declarado em cada uma corrigido pela inflação."""
    eleicoes = [e for e in bruto.get("eleicoesAnteriores") or [] if e.get("idEleicao") and e.get("nrAno")]
    fatores = _ipca_fatores()

    def ficha(e):
        if str(e["id"]) == str(bruto["id"]):
            return bruto
        return tse.ficha_anterior(e["nrAno"], e["sgUe"], e["idEleicao"], e["id"])

    with ThreadPoolExecutor(max_workers=6) as pool:
        fichas = list(pool.map(ficha, eleicoes))
    linhas = []
    for e, f in sorted(zip(eleicoes, fichas), key=lambda x: x[0]["nrAno"]):
        bens = f.get("totalDeBens") if f else None
        fator = fatores.get(e["nrAno"], 1.0)
        sigla = (e.get("partido") or "").upper()
        linhas.append({
            "ano": e["nrAno"],
            "cargo": e.get("cargo"),
            "local": (e.get("local") or "").title(),
            "municipal": str(e.get("sgUe") or "").isdigit(),
            "partido": e.get("partido"),
            "partidoAtual": MESMO_PARTIDO.get(sigla, sigla),
            "resultado": e.get("situacaoTotalizacao"),
            "eleito": _eleito(e.get("situacaoTotalizacao")),
            "atual": str(e["id"]) == str(bruto["id"]),
            "bens": bens,
            "bensHoje": round(bens * fator, 2) if bens is not None else None,
            "ocupacao": None if ((f or {}).get("ocupacao") or "").upper() == "OUTROS" else (f or {}).get("ocupacao"),
        })
    hoje = date.today().year
    anos_mandato = set()
    for l in linhas:
        if l["eleito"] and not l["atual"]:
            dur = DURACAO_MANDATO.get(l["cargo"], 4)
            anos_mandato |= {a for a in range(l["ano"] + 1, l["ano"] + 1 + dur) if a <= hoje}
    anteriores = [l for l in linhas if not l["atual"]]

    def unicos(xs):
        return list(dict.fromkeys(x for x in xs if x))

    return {
        "linhas": linhas,
        "resumo": {
            "candidaturas": len(anteriores),
            "vitorias": sum(l["eleito"] for l in anteriores),
            "primeiraEleicao": anteriores[0]["ano"] if anteriores else None,
            "anosEmMandato": len(anos_mandato),
            "anosMandato": sorted(anos_mandato),
            "anosDesdePrimeira": hoje - anteriores[0]["ano"] if anteriores else 0,
            "cargosOcupados": unicos(l["cargo"] for l in anteriores if l["eleito"]),
            "municipios": unicos(l["local"] for l in linhas if l["municipal"]),
            "partidos": unicos(l["partidoAtual"] for l in linhas),
            "siglas": unicos(l["partido"] for l in linhas),
            "ocupacoes": unicos(l["ocupacao"] for l in linhas if (l["ocupacao"] or "").upper() not in ("OUTROS", "")),
        },
        "ipca": bool(fatores),
    }


def _sinais_trajetoria(t):
    s = []
    if not t:
        return s
    r = t["resumo"]
    if r["anosEmMandato"] >= 12:
        s.append(_sinal("info", "Político de carreira",
                        f"Esteve em mandato {r['anosEmMandato']} dos últimos {r['anosDesdePrimeira']} anos, como "
                        f"{listar(c.lower() for c in r['cargosOcupados'])}. Isso não é problema em si: a experiência pode ajudar, "
                        "e o que importa é como a pessoa trabalha no mandato.", "TSE", categoria="trajetoria"))
    declarados = [l for l in t["linhas"] if l["bensHoje"]]
    if len(declarados) < 2:
        return s

    def estranho(antes, depois):
        """Cresceu pelo menos metade, mais de R$ 1 milhão e mais de R$ 250 mil por ano, tudo acima da inflação.
        R$ 250 mil por ano é mais do que alguém consegue guardar só com o salário de deputado."""
        anos = max(1, depois["ano"] - antes["ano"])
        ganho = depois["bensHoje"] - antes["bensHoje"]
        return ganho / antes["bensHoje"] >= 0.5 and ganho >= 1_000_000 and ganho / anos >= 250_000

    primeiro, atual = declarados[0], declarados[-1]
    anos = max(1, atual["ano"] - primeiro["ano"])
    crescimento = atual["bensHoje"] - primeiro["bensHoje"]
    razao = crescimento / primeiro["bensHoje"]
    # O período em que o patrimônio mais cresceu por ano acima da inflação, entre quaisquer duas eleições.
    # Só conta se a pessoa ainda tem a maior parte do que ganhou: um salto seguido de queda não é enriquecimento.
    saltos = [(a, b) for i, a in enumerate(declarados) for b in declarados[i + 1:] if (a, b) != (primeiro, atual)]
    saltos = [x for x in saltos if estranho(*x) and atual["bensHoje"] >= 0.75 * x[1]["bensHoje"]]
    maior = max(saltos, key=lambda x: (x[1]["bensHoje"] - x[0]["bensHoje"]) / max(1, x[1]["ano"] - x[0]["ano"]), default=None)
    texto = (f"Em {primeiro['ano']}, declarou {_brl0(primeiro['bens'])}, o que equivale a {_brl0(primeiro['bensHoje'])} hoje, "
             f"já descontada a inflação. Em {atual['ano']}, declarou {_brl0(atual['bens'])}, e em termos reais o patrimônio "
             f"{'mais que dobrou' if razao >= 1 else f'cresceu {razao:.0%}' if razao >= 0 else f'caiu {-razao:.0%}'} em {anos} anos.")
    salto_estranho = maior is not None
    if salto_estranho:
        a, b = maior
        texto += (f" O maior salto foi entre {a['ano']} e {b['ano']}: de {_brl0(a['bensHoje'])} para {_brl0(b['bensHoje'])} "
                  f"em valores de hoje, {_brl0((b['bensHoje'] - a['bensHoje']) / max(1, b['ano'] - a['ano']))} por ano acima da inflação.")
    if estranho(primeiro, atual) or salto_estranho:
        a, b = maior if salto_estranho else (primeiro, atual)
        mandato = set(r.get("anosMandato") or [])
        em_cargo = any(ano in mandato for ano in range(a["ano"] + 1, b["ano"] + 1))
        if em_cargo:
            texto += (" O crescimento aconteceu enquanto a pessoa tinha cargo eletivo, e é mais do que alguém consegue guardar só "
                      "com o salário. Pode ter explicação, como herança, venda de imóvel, valorização de terras ou renda de outra "
                      "atividade, e a lista de bens de cada eleição ajuda a entender de onde veio.")
            s.append(_sinal("atencao", "Patrimônio cresceu bem acima da inflação", texto, "TSE e Banco Central (IPCA)"))
        else:
            texto += (" A pessoa não tinha cargo eletivo nesse período, então o crescimento tende a vir da atividade "
                      "profissional ou empresarial dela. Por isso não tira pontos; a lista de bens de cada eleição mostra de onde veio.")
            s.append(_sinal("info", "Patrimônio cresceu bem acima da inflação", texto, "TSE e Banco Central (IPCA)"))
    else:
        texto += (" Isso não foge do que se espera de quem tem a renda de um cargo público ou de outra atividade." if razao >= 0 else
                  " Parte dessa queda é só aparente: os bens são declarados pelo valor de compra, que não é atualizado, "
                  "enquanto aqui os valores antigos foram corrigidos pela inflação.")
        s.append(_sinal("info", "Evolução do patrimônio", texto, "TSE e Banco Central (IPCA)"))
    s += _sinais_queda_patrimonio(t)
    return s


def _sinais_queda_patrimonio(t):
    """Queda brusca de uma eleição para a seguinte, nos valores declarados (sem correção pela inflação: os bens são
    declarados pelo valor de compra, então corrigir faria parecer que todo mundo empobrece com o tempo).
    Aparece para conferir, sem tirar pontos: venda, divórcio, dívida e doação em vida são explicações comuns, e não há
    como separar isso de patrimônio transferido para outras pessoas."""
    d = [l for l in t["linhas"] if l["bens"] is not None]
    quedas = [(a, b) for a, b in zip(d, d[1:]) if a["bens"] - b["bens"] >= 1_000_000 and a["bens"] - b["bens"] >= 0.5 * a["bens"]]
    if not quedas:
        return []
    a, b = max(quedas, key=lambda x: x[0]["bens"] - x[1]["bens"])
    texto = (f"O patrimônio declarado caiu de {_brl0(a['bens'])} em {a['ano']} para {_brl0(b['bens'])} em {b['ano']}"
             + (", e a declaração ficou zerada" if b["bens"] == 0 else "") + ".")
    depois = [l for l in d if l["ano"] > b["ano"]]
    if depois and depois[-1]["bens"] - b["bens"] >= 1_000_000:
        texto += f" Depois voltou a subir, para {_brl0(depois[-1]['bens'])} em {depois[-1]['ano']}."
    texto += (" Pode ser venda seguida de gasto, divórcio, dívida ou doação em vida a filhos; também pode ser patrimônio "
              "passado para o nome de outras pessoas. A lista de bens de cada eleição, no TSE, mostra o que saiu. "
              "Não tira pontos porque os dados não permitem separar esses casos.")
    return [_sinal("info", "Patrimônio declarado caiu muito de uma eleição para outra", texto, "TSE")]


def _sinais_contas(contas, pares):
    if not contas:
        return [_sinal("info", "Sem prestação de contas publicada",
                       "O TSE ainda não publicou relatórios financeiros desta campanha.", "TSE")]
    s = []
    total = contas["totalRecebido"] or 0
    proprios = next((o["valor"] for o in contas["origens"] if o["origem"] == "Recursos próprios"), 0)
    if total > 50_000 and proprios / total > 0.5:
        s.append(_sinal("info", "Campanha financiada principalmente pelo próprio candidato",
                        f"{proprios / total:.0%} do dinheiro arrecadado, ou {_brl(proprios)}, saiu do bolso do candidato.", "TSE"))
    publico = contas["fundoEleitoral"] + contas["fundoPartidario"]
    if total and publico:
        s.append(_sinal("info", "Dinheiro público na campanha",
                        f"{publico / total:.0%} do dinheiro arrecadado, ou {_brl(publico)}, veio do Fundo Eleitoral ou do Fundo Partidário.",
                        "TSE"))
    if pares and len(pares) >= 5:
        gastos = sorted(p for p in pares)
        posicao = sum(1 for g in gastos if g < contas["despesasContratadas"]) / len(gastos)
        if posicao >= 0.9 and contas["despesasContratadas"] > 0:
            s.append(_sinal("info", "Gasto de campanha entre os maiores da lista",
                            f"A campanha contratou {_brl(contas['despesasContratadas'])} em despesas, mais do que "
                            f"{posicao:.0%} dos colegas da mesma lista.", "TSE"))
    limite = contas["limiteGastos"]
    if limite and contas["despesasContratadas"] > 0.9 * limite:
        s.append(_sinal("info", "Gastos perto do limite legal",
                        f"A campanha já contratou {contas['despesasContratadas'] / limite:.0%} do limite legal de {_brl(limite)}.", "TSE"))
    return s


# Um problema de fornecedor só tira pontos da campanha se ela pagou uma quantia relevante a ele.
VALOR_RELEVANTE = 10_000
PARTE_RELEVANTE = 0.10


def relevante(valor, total):
    return valor >= VALOR_RELEVANTE or bool(total) and valor / total >= PARTE_RELEVANTE


def _sinais_gastos(g):
    """Leva para a lista geral os sinais mais fortes da análise de gastos."""
    if not g or not g.get("pronto") or g.get("semDados"):
        return []
    s = [_sinal(x["nivel"], x["titulo"], x["detalhe"], "prestação de contas ao TSE", cnpj=x.get("cnpj"))
         for x in g["sinais"] if x["nivel"] in ("alerta", "atencao")]
    for f in g["fornecedores"]:
        pesa = relevante(f["valor"], g.get("total"))
        for x in f["sinais"]:
            if x["nivel"] not in ("alerta", "atencao"):
                continue
            detalhe = f"{x['detalhe']} Esta campanha pagou {_brl(f['valor'])} a ela."
            nivel = x["nivel"]
            if not pesa and x["titulo"] != "Empresa do próprio candidato":
                nivel = "info"
                detalhe += " Como o valor é pequeno perto do total da campanha, não tira pontos."
            s.append(_sinal(nivel, f"{x['titulo']}: {f['nome']}", detalhe, "TSE e Receita Federal", cnpj=f["cnpj"]))
    return s


def _sinais_mandato(dep, resumo):
    if not dep:
        return []
    s = []
    cota = dep.get("cota")
    mediana = resumo.get("medianaCotaMensal") if resumo else None
    if cota and mediana:
        nivel = "atencao" if cota["percentil"] >= 0.9 else "info"
        s.append(_sinal(nivel, "Gastos com a cota parlamentar",
                        f"Gasta em média {_brl(cota['mediaMensal'])} por mês da cota desde 2023, enquanto um deputado "
                        f"típico gasta {_brl(mediana)}. Gastou mais do que {cota['percentil']:.0%} dos colegas.",
                        "Câmara dos Deputados",
                        f"https://www.camara.leg.br/deputados/{dep['id']}", categoria="mandato"))
    part = dep.get("participacao")
    if part is not None and resumo:
        todas = sorted(d["participacao"] for d in resumo["deputados"].values()
                       if d["participacao"] is not None and d["votos"] > 200)
        abaixo = sum(1 for p in todas if p < part) / len(todas)
        nivel = "atencao" if abaixo < 0.1 else "info"
        s.append(_sinal(nivel, "Participação nas votações do plenário",
                        f"Votou em {part:.0%} das votações do plenário no período em que exerceu o mandato, enquanto um "
                        f"deputado típico vota em {todas[len(todas) // 2]:.0%}. As faltas podem ter motivo, como licença ou missão oficial.",
                        "Câmara dos Deputados", categoria="mandato"))
    return s


def _sinais_mandato_estadual(dep):
    r = alesp.resumo()
    if not dep or not r:
        return []
    m = r["medianas"]
    s = []
    pr = dep.get("presenca")
    if pr and m.get("presenca"):
        nivel = "atencao" if pr["taxa"] < m["presenca"] / 2 else "info"
        s.append(_sinal(nivel, "Presença nas comissões da ALESP",
                        f"Esteve em {pr['presente']} das {pr['reunioes']} reuniões das comissões de que é membro titular, ou "
                        f"{pr['taxa']:.0%}. Um deputado estadual típico vai a {m['presenca']:.0%}. É nas comissões que os projetos são "
                        "discutidos e votados antes de ir ao plenário.", "ALESP", categoria="mandato"))
    if dep["projetos"] >= 10 and m.get("simbolicos") is not None:
        parte = dep["simbolicos"] / dep["projetos"]
        if parte >= 0.15 and parte >= 2 * m["simbolicos"]:
            s.append(_sinal("info", "Muitos projetos simbólicos",
                            f"{dep['simbolicos']} dos {dep['projetos']} projetos, ou {parte:.0%}, são homenagens, nomes de estradas e "
                            f"viadutos, títulos de utilidade pública ou datas comemorativas. Num deputado estadual típico, são "
                            f"{m['simbolicos']:.0%}.", "ALESP", categoria="mandato"))
    return s


def _sinais_emendas(e):
    if not e or not e.get("sinais"):
        return []
    return [dict(_sinal(x["nivel"], x["titulo"], x["detalhe"], "Portal da Transparência (emendas)", cnpj=x.get("cnpj"),
                        categoria="emendas"), empresas=x.get("empresas")) for x in e["sinais"]]


def _sinais_portal(cpf, contas, nome=None):
    """Candidato e principais fornecedores nos cadastros de punidos. Usa os arquivos abertos da CGU
    (sancoes.py); a API com chave só entra se esses arquivos ainda não tiverem sido baixados."""
    if sancoes.pronto():
        return _sinais_sancoes(cpf, contas, nome), True
    chave = _config().get("chavePortal")
    if not chave:
        return [], False
    cab = {"chave-api-dados": chave, "Accept": "application/json"}
    s = []
    consultas = [("ceis", "codigoSancionado", "cadastro de empresas e pessoas proibidas de contratar com o governo (CEIS)"),
                 ("cnep", "codigoSancionado", "cadastro de punidos pela Lei Anticorrupção (CNEP)"),
                 ("ceaf", "cpfSancionado", "cadastro de expulsos do serviço público federal (CEAF)")]
    for base, param, nome in consultas:
        d = _get_json(f"{URL_PORTAL}/{base}?{param}={cpf}&pagina=1", f"portal_{base}_{cpf}.json", cab)
        if d:
            s.append(_sinal("alerta", f"Candidato aparece no {base.upper()}",
                            f"{'Há um registro' if len(d) == 1 else f'Há {len(d)} registros'} no {nome}.", "Portal da Transparência",
                            f"https://portaldatransparencia.gov.br/sancoes/{base}"))
    for f in (contas or {}).get("fornecedores", [])[:5]:
        if not f.get("cnpj"):
            continue
        for base, param, nome in consultas[:2]:
            d = _get_json(f"{URL_PORTAL}/{base}?{param}={f['cnpj']}&pagina=1", f"portal_{base}_{f['cnpj']}.json", cab)
            if d:
                s.append(_sinal("alerta", f"Fornecedor aparece no {base.upper()}",
                                f"{f['nome']}, que recebeu {_brl(f['valor'])} desta campanha, "
                                f"{'tem um registro' if len(d) == 1 else f'tem {len(d)} registros'} no {nome}.",
                                "Portal da Transparência"))
    if not s:
        s.append(_sinal("ok", "Nada encontrado nos cadastros de sanções",
                        "Nem o candidato nem os principais fornecedores aparecem nos cadastros de punidos do governo federal.",
                        "Portal da Transparência"))
    return s, True


def _sinais_sancoes(cpf, contas, nome):
    s = []
    for r in sancoes.pessoa(cpf, nome) or []:
        desde = f", desde {r['inicio']}" if r["inicio"] else ""
        s.append(_sinal("alerta", f"Candidato aparece no {r['sigla']}",
                        f"{r['sancao'] or 'Sanção'} aplicada por {r['orgao'] or 'órgão público'}{desde}. "
                        f"Registro no {r['cadastro']}.",
                        "Portal da Transparência (arquivos da CGU)", f"https://portaldatransparencia.gov.br/sancoes/{r['sigla'].lower()}"))
    for f in (contas or {}).get("fornecedores", [])[:5]:
        if not f.get("cnpj"):
            continue
        achados = sancoes.empresa(f["cnpj"]) or []
        if achados:
            siglas = sorted({r["sigla"] for r in achados})
            s.append(_sinal("atencao" if relevante(f["valor"], (contas or {}).get("despesasContratadas")) else "info",
                            f"Fornecedor aparece no {' e no '.join(siglas)}",
                            f"{f['nome']}, que recebeu {_brl(f['valor'])} desta campanha, "
                            f"{'tem um registro' if len(achados) == 1 else f'tem {len(achados)} registros'} nos cadastros nacionais de punidos.",
                            "Portal da Transparência (arquivos da CGU)"))
    if not s:
        s.append(_sinal("ok", "Nada encontrado nos cadastros de sanções",
                        "Nem o candidato nem os principais fornecedores aparecem nos cadastros nacionais de punidos "
                        f"(CEIS, CNEP e CEAF, atualizados em {sancoes.status()['geradoEm']}).",
                        "Portal da Transparência (arquivos da CGU)"))
    return s


FONTE_RECEITA = "Receita Federal (dados abertos do CNPJ)"


def _sinais_empresas(lista, nome_dep=None, ja_sinalizadas=frozenset()):
    """Empresas em que o candidato é sócio, cruzadas com dinheiro de campanha, emendas e sanções."""
    s = []
    for e in lista or []:
        nome = e.get("razao") or f"CNPJ {e['basico']}"
        if e.get("campanhaPropria") and e["basico"] not in ja_sinalizadas:
            s.append(_sinal("atencao" if e["campanhaPropria"] >= VALOR_RELEVANTE else "info",
                            "Campanha pagou empresa do próprio candidato",
                            f"{nome}, de que é sócio(a), recebeu {_brl(e['campanhaPropria'])} desta campanha. "
                            "A lei permite, mas o dinheiro de campanha volta para o próprio candidato.", FONTE_RECEITA))
        outras = e.get("outrasCampanhas") or {}
        if outras.get("quantas"):
            quem = ", ".join(f"{(x['nome'] or 'candidato').title()} ({x['partido']})" for x in outras["principais"][:3])
            s.append(_sinal("atencao" if outras["total"] >= VALOR_RELEVANTE else "info",
                            "Empresa do candidato recebeu de outras campanhas",
                            f"{nome} recebeu {_brl(outras['total'])} de {outras['quantas']} "
                            f"{'outra campanha' if outras['quantas'] == 1 else 'outras campanhas'} em 2026"
                            f"{_texto_partidos(outras.get('porPartido'), outras['quantas'])}. As que mais pagaram: {quem}.",
                            FONTE_RECEITA + " e TSE"))
        em = e.get("emendas") or {}
        if em.get("total"):
            proprio = nome_dep and any(emendas.normalizar(x["nome"]) == emendas.normalizar(nome_dep) for x in em["principais"])
            nivel = "alerta" if proprio else "atencao" if em["total"] >= VALOR_RELEVANTE else "info"
            s.append(_sinal(nivel, "Empresa do candidato recebeu dinheiro de emendas",
                            f"{nome} recebeu {_brl(em['total'])} pagos com emendas de {em['parlamentares']} "
                            f"{'parlamentar' if em['parlamentares'] == 1 else 'parlamentares'}"
                            f"{', inclusive do próprio candidato' if proprio else ''}.",
                            FONTE_RECEITA + " e Portal da Transparência", categoria="emendas"))
        if e.get("sancoes"):
            siglas = sorted({x["sigla"] for x in e["sancoes"]})
            s.append(_sinal("atencao", "Empresa do candidato tem sanção",
                            f"{nome} aparece no {' e no '.join(siglas)}, cadastro nacional de empresas punidas.",
                            FONTE_RECEITA + " e CGU"))
    return s


# Vices e suplentes também podem ser sócios de empresas; o TSE usa estes códigos para eles.
NOMES_CARGOS = {**tse.CARGOS, 2: "Vice-presidente", 4: "Vice-governador", 9: "1º suplente de senador", 10: "2º suplente de senador"}


def _texto_partidos(por_partido, quantas):
    """", 12 delas do PL e 3 do PP" (ou ", todas do PL"), a partir de [[partido, quantas, valor]]."""
    if not por_partido:
        return ""
    if len(por_partido) == 1 and quantas > 1:
        return f", todas do {por_partido[0][0]}"
    partes = [f"{n} do {p}" for p, n, _ in por_partido[:3]]
    resto = sum(n for _, n, _ in por_partido[3:])
    if resto:
        partes.append(f"{resto} de outros partidos")
    return f" ({listar(partes)})" if quantas > 1 else f" (do {por_partido[0][0]})"


def _sinais_emenda_campanha(dep, g):
    """Empresa que recebeu emenda indicada pelo próprio deputado e depois foi paga pela campanha dele. Só informativo:
    são poucos casos no país, e plataformas e grandes empresas (que atendem mais de 100 campanhas) ficam de fora."""
    if not dep or not g or not g.get("pronto") or g.get("semDados") or not emendas._banco().exists():
        return []
    pagos = {f["cnpj"]: f for f in g.get("fornecedores") or [] if f["rede"]["candidatos"] <= gastos.MIN_CLIENTES_PLATAFORMA}
    if not pagos:
        return []
    alvo = emendas.normalizar(dep["nome"])
    c = emendas._conectar()
    try:
        linhas = c.execute(f"SELECT doc, autor, sum(valor) v FROM favorecidos WHERE doc IN ({','.join('?' * len(pagos))}) "
                           "GROUP BY doc, autor", list(pagos)).fetchall()
    finally:
        c.close()
    s = []
    for doc, autor, valor in linhas:
        if emendas.normalizar(autor) != alvo or not valor:
            continue
        f = pagos[doc]
        s.append(_sinal("info", f"Empresa que recebeu emenda do candidato atende a campanha: {f['nome']}",
                        f"{f['nome']} recebeu {_brl(valor)} de emendas indicadas por {dep['nome']} e foi paga com "
                        f"{_brl(f['valor'])} por esta campanha. Pode ser um fornecedor comum da região, mas mostra o mesmo "
                        "dinheiro público e de campanha passando pela mesma empresa.",
                        "Portal da Transparência (emendas) e TSE", cnpj=doc, categoria="emendas"))
    return s


def _sinais_fornecedor_candidato(lista, total=None):
    """A campanha pagou empresa de outro candidato de 2026. Quando a mesma empresa atende outras campanhas, o aviso
    mostra essa rede, para ninguém achar que é um caso isolado (ou que é uma rede quando não é)."""
    s = []
    for f in lista or []:
        quem = "; ".join(f"{d['nome'].title()} ({d['partido']}, {NOMES_CARGOS.get(d['cargo'], 'candidato').lower()} "
                         f"{d['numero']} em {d['uf']})" for d in f["donos"])
        rede = f.get("rede") or {}
        texto_rede = ""
        if rede.get("quantas"):
            outras = "outra campanha" if rede["quantas"] == 1 else f"outras {rede['quantas']} campanhas"
            texto_rede = (f" A mesma empresa também recebeu {_brl(rede['total'])} de {outras}"
                          f"{_texto_partidos(rede.get('porPartido'), rede['quantas'])}.")
        s.append(_sinal("atencao" if relevante(f["valor"], total) else "info",
                        f"Fornecedor é empresa de outro candidato: {' '.join((f['nome'] or '').split())}",
                        f"Esta campanha pagou {_brl(f['valor'])} a essa empresa, que tem como sócio(a) quem também disputa "
                        f"a eleição de 2026: {quem}.{texto_rede} Pode ser um serviço comum, mas também é um caminho para o "
                        "dinheiro de campanha chegar a um aliado.", FONTE_RECEITA + " e TSE", cnpj=f["cnpj"]))
    return s


def _agrupar(regs):
    """Registros por fonte, sem repetir o mesmo processo (o TCU põe o mesmo processo em mais de uma lista)."""
    por = {}
    for r in regs:
        por.setdefault(r["fonte"], []).append(r)
    eleitorais = {r.get("processo") for r in por.get("tcu_eleitoral", [])}
    por["tcu_irregular"] = [r for r in por.get("tcu_irregular", []) if r.get("processo") not in eleitorais]
    return {k: v for k, v in por.items() if v}


def _dbr(iso):
    return f"{iso[8:10]}/{iso[5:7]}/{iso[:4]}" if iso and len(iso) >= 10 else "data não informada"


def _qtd(n, um, varios):
    return um if n == 1 else f"{n} {varios}"


def _processos(regs):
    ps = list(dict.fromkeys(r.get("processo") for r in regs if r.get("processo")))
    return f" (processo {', '.join(ps[:3])})" if ps else ""


FONTE_TCU = "TCU (listas públicas de responsáveis)"
FONTE_IBAMA = "Ibama (termos de embargo)"
LINK_IBAMA = "https://servicos.ibama.gov.br/ctf/publico/areasembargadas/ConsultaPublicaAreasEmbargadas.php"


def _sinais_punicoes(cpf, socio_de):
    """Candidato e empresas dele nas listas do TCU, na lista suja do trabalho escravo e nos embargos do Ibama."""
    if not punicoes.pronto():
        return []
    s = []
    por = _agrupar(punicoes.pessoa(cpf) or []) if cpf else {}
    regs = por.get("tcu_eleitoral")
    if regs:
        ate = max(r.get("ate") or "" for r in regs)
        s.append(_sinal("alerta", "Contas julgadas irregulares pelo TCU (lista para a Justiça Eleitoral)",
                        f"O TCU julgou irregulares, em decisão definitiva, contas sob responsabilidade do candidato"
                        f"{_processos(regs)} e o incluiu na lista que envia à Justiça Eleitoral, válida até {_dbr(ate)}. "
                        "Isso pode tornar a pessoa inelegível pela Lei da Ficha Limpa, mas quem decide é a Justiça Eleitoral, "
                        "caso a caso.", FONTE_TCU, "https://certidoes.apps.tcu.gov.br/lista-implicacao-eleitoral"))
    regs = por.get("tcu_irregular")
    if regs:
        desde = min(r.get("desde") or "9999" for r in regs)
        s.append(_sinal("atencao", "Contas julgadas irregulares pelo TCU",
                        f"O TCU julgou irregulares contas sob responsabilidade do candidato{_processos(regs)}, com decisão "
                        f"definitiva desde {_dbr(desde)}. Já fora do prazo que conta para a eleição, mas mostra problema na "
                        "gestão de dinheiro público.", FONTE_TCU, "https://certidoes.apps.tcu.gov.br/lista-responsaveis"))
    regs = [r for r in por.get("tcu_inabilitado", []) if r["vigente"]]
    if regs:
        s.append(_sinal("alerta", "Inabilitado pelo TCU para cargo público",
                        f"O TCU proibiu o candidato de ocupar cargo em comissão ou função de confiança na administração "
                        f"federal até {_dbr(max(r.get('ate') or '' for r in regs))}{_processos(regs)}.", FONTE_TCU,
                        "https://certidoes.apps.tcu.gov.br/lista-inabilitados"))
    regs = por.get("escravo")
    if regs:
        r = regs[0]
        qtd = f", {r['trabalhadores']} trabalhador(es) envolvidos" if r.get("trabalhadores") else ""
        s.append(_sinal("alerta", "Na lista suja do trabalho escravo",
                        f"Aparece como empregador no cadastro do Ministério do Trabalho de quem submeteu trabalhadores a "
                        f"condições análogas à escravidão (ação fiscal de {r.get('ano') or 'ano não informado'}{qtd}).",
                        "Ministério do Trabalho", punicoes.URL_ESCRAVO))
    regs = por.get("ibama")
    if regs:
        ativos = [r for r in regs if r["vigente"]]
        if ativos:
            area = sum(r.get("area") or 0 for r in ativos)
            area_txt = f", somando {area:,.0f} hectares".replace(",", ".") if area else ""
            s.append(_sinal("atencao", "Área embargada pelo Ibama",
                            f"Tem {_qtd(len(ativos), 'um embargo ambiental em vigor', 'embargos ambientais em vigor')}"
                            f"{area_txt}, por infração ambiental ({ativos[0].get('local') or 'local não informado'}).",
                            FONTE_IBAMA, LINK_IBAMA))
        else:
            s.append(_sinal("info", "Já teve área embargada pelo Ibama",
                            f"Teve {_qtd(len(regs), 'um embargo ambiental', 'embargos ambientais')}, hoje suspensos.",
                            FONTE_IBAMA, LINK_IBAMA))
    for e in socio_de or []:
        nome = e.get("razao") or f"CNPJ {e['basico']}"
        por = _agrupar(e.get("punicoes") or [])
        if por.get("escravo"):
            s.append(_sinal("alerta", "Empresa do candidato na lista suja do trabalho escravo",
                            f"{nome}, de que é sócio(a), está no cadastro do Ministério do Trabalho de empregadores "
                            "flagrados com trabalho análogo à escravidão.", "Ministério do Trabalho", punicoes.URL_ESCRAVO))
        irregulares = por.get("tcu_eleitoral", []) + por.get("tcu_irregular", [])
        inidoneo = [r for r in por.get("tcu_inidoneo", []) if r["vigente"]]
        if irregulares or inidoneo:
            partes = (["teve contas julgadas irregulares pelo TCU"] if irregulares else []) + \
                     (["está proibida pelo TCU de participar de licitações federais"] if inidoneo else [])
            s.append(_sinal("atencao", "Empresa do candidato com condenação no TCU",
                            f"{nome}, de que é sócio(a), {' e '.join(partes)}{_processos(irregulares + inidoneo)}.",
                            FONTE_TCU))
        ativos = [r for r in por.get("ibama", []) if r["vigente"]]
        if ativos:
            s.append(_sinal("atencao", "Empresa do candidato com área embargada pelo Ibama",
                            f"{nome}, de que é sócio(a), tem "
                            f"{_qtd(len(ativos), 'um embargo ambiental em vigor', 'embargos ambientais em vigor')}.",
                            FONTE_IBAMA, LINK_IBAMA))
        dinheiro = (e.get("campanhaPropria") or (e.get("outrasCampanhas") or {}).get("quantas")
                    or (e.get("emendas") or {}).get("total"))
        if e.get("situacao") in ("Inapta", "Suspensa") and dinheiro:
            s.append(_sinal("atencao", "Empresa irregular na Receita recebeu dinheiro",
                            f"{nome} está {e['situacao'].lower()} na Receita Federal e mesmo assim recebeu dinheiro de "
                            "campanha ou de emendas.", FONTE_RECEITA))
    return s


def _sinais_punicoes_fornecedores(contas):
    """Principais fornecedores da campanha na lista suja do trabalho escravo ou proibidos de licitar pelo TCU."""
    if not punicoes.pronto():
        return []
    s, total = [], (contas or {}).get("despesasContratadas")
    for f in (contas or {}).get("fornecedores", [])[:10]:
        if not f.get("cnpj"):
            continue
        por = _agrupar(punicoes.empresa(f["cnpj"]) or [])
        motivos = (["está na lista suja do trabalho escravo"] if por.get("escravo") else []) + \
                  (["está proibido pelo TCU de participar de licitações federais"]
                   if any(r["vigente"] for r in por.get("tcu_inidoneo", [])) else [])
        if motivos:
            s.append(_sinal("atencao" if relevante(f["valor"], total) else "info",
                            f"Fornecedor com punição: {f['nome']}",
                            f"{f['nome']}, que recebeu {_brl(f['valor'])} desta campanha, {' e '.join(motivos)}.",
                            "Ministério do Trabalho e TCU", cnpj=f["cnpj"]))
    return s


def sancoes_empresa(cnpj):
    """Registros da empresa nos cadastros de punidos do governo federal. None se não houver como consultar."""
    if sancoes.pronto():
        return [{k: r[k] for k in ("cadastro", "sancao", "orgao", "inicio", "fim")} for r in sancoes.empresa(cnpj)]
    chave = _config().get("chavePortal")
    if not chave:
        return None
    cab = {"chave-api-dados": chave, "Accept": "application/json"}
    achados = []
    for base, nome in (("ceis", "Cadastro de empresas proibidas de contratar com o governo (CEIS)"),
                       ("cnep", "Cadastro de punidos pela Lei Anticorrupção (CNEP)")):
        d = _get_json(f"{URL_PORTAL}/{base}?codigoSancionado={cnpj}&pagina=1", f"portal_{base}_{cnpj}.json", cab)
        for r in d or []:
            achados.append({
                "cadastro": nome,
                "sancao": ((r.get("tipoSancao") or {}).get("descricaoResumida")
                           or (r.get("tipoSancao") or {}).get("descricaoPortal")),
                "orgao": (r.get("orgaoSancionador") or {}).get("nome"),
                "inicio": r.get("dataInicioSancao"),
                "fim": r.get("dataFimSancao"),
            })
    return achados


PENALIDADE = {"atencao": 20, "alerta": 50}


def integridade(sinais):
    """Começa em 100; cada ponto que vale conferir tira 20 e cada alerta sério tira 50.

    Presença e gasto da cota falam de desempenho no mandato e já entram lá, então ficam de fora aqui.
    """
    return max(0, 100 - sum(PENALIDADE.get(s["nivel"], 0) for s in sinais if s.get("categoria") != "mandato"))


def nota_pessoa(integ, desempenho):
    """A integridade; para quem tem mandato, o desempenho soma ou tira até 20 pontos em relação ao deputado típico."""
    if integ is None:
        return None
    ajuste = 0.4 * (desempenho - 50) if desempenho is not None else 0
    return round(min(100, max(0, integ + ajuste)))


def desempenho_de(dep, dep_est):
    """Desempenho no mandato: Câmara para deputado federal, ALESP para deputado estadual de SP."""
    if dep:
        d = camara.tabela_desempenho().get(dep["id"])
        if d:
            return d, "federal", camara.criterios_rotulados(d["criterios"])
    if dep_est:
        d = alesp.tabela_desempenho().get(dep_est["id"])
        if d:
            return d, "estadual", alesp.criterios_rotulados(d["criterios"])
    return None, None, None


def pontuacao(sinais, dep, dep_est):
    d, casa, criterios = desempenho_de(dep, dep_est)
    integ = integridade(sinais)
    return {
        "integridade": integ,
        "desempenho": d["nota"] if d else None,
        "casa": casa,
        "criterios": criterios,
        "nota": nota_pessoa(integ, d["nota"] if d else None),
        "descontos": [{"titulo": x["titulo"], "nivel": x["nivel"], "pontos": PENALIDADE[x["nivel"]]}
                      for x in sinais if x["nivel"] in PENALIDADE and x.get("categoria") != "mandato"],
    }


def _sinais_partidos(bruto):
    partidos = {
        MESMO_PARTIDO.get(e["partido"].upper(), e["partido"].upper())
        for e in bruto.get("eleicoesAnteriores") or [] if e.get("partido")
    }
    if len(partidos) >= 3:
        return [_sinal("info", "Trocou de partido algumas vezes",
                       f"Já concorreu por {len(partidos)} partidos diferentes: {', '.join(sorted(partidos)[:-1])} e {sorted(partidos)[-1]}.", "TSE")]
    return []


# ---------- trabalho no mandato ----------

RE_PARECER_APROVACAO = re.compile(r"^Parecer d[oa] Relator.{0,200}pela aprova", re.I | re.S)
RE_APROVA_SUBSTITUTIVO = re.compile(r"^Aprovad[oa] (o Substitutivo|a Emenda Substitutiva|a Subemenda Substitutiva)", re.I)
RE_APROVA_TEXTO = re.compile(r"^Aprovad[oa] (o Projeto|a Proposta|a Medida)", re.I)
RE_APROVA_EMENDA = re.compile(r"^Aprovad[oa]s? (a|as) (Emenda|Subemenda)", re.I)


def _tipo_parecer(texto):
    t = texto.lower()
    if "substitutivo" in t:
        return "substitutivo"
    if re.search(r"com (as )?(sub)?emendas?", t):
        return "emendas"
    return "original"


def alteracao(id_proposicao):
    """Indício de quanto o texto mudou até ser aprovado, lendo o histórico de tramitação da Câmara."""
    d = _get_json(f"{URL_CAMARA}/proposicoes/{id_proposicao}/tramitacoes",
                  f"camara_tramitacoes_{id_proposicao}.json", {"Accept": "application/json"})
    eventos = sorted((d or {}).get("dados") or [], key=lambda e: (e.get("dataHora") or "", e.get("sequencia") or 0))
    parecer = comissao = plenario = None
    for e in eventos:
        t = (e.get("despacho") or "").strip()
        if RE_PARECER_APROVACAO.search(t):
            parecer = _tipo_parecer(t)
        elif t.startswith("Aprovado o Parecer") and parecer:
            comissao = parecer
        elif RE_APROVA_SUBSTITUTIVO.search(t):
            plenario = "substitutivo"
        elif RE_APROVA_TEXTO.search(t):
            plenario = "original"
        elif RE_APROVA_EMENDA.search(t) and plenario == "original":
            plenario = "emendas"
    return plenario or comissao


def _valor_br(txt):
    try:
        return float((txt or "0").replace(".", "").replace(",", "."))
    except ValueError:
        return 0.0


def _sem_acento(txt):
    return unicodedata.normalize("NFKD", txt).encode("ascii", "ignore").decode()


def _emendas(nome):
    """Emendas individuais ao Orçamento desde 2023, pelo Portal da Transparência (precisa da chave)."""
    chave = _config().get("chavePortal")
    if not chave or not nome:
        return None
    cab = {"chave-api-dados": chave, "Accept": "application/json"}

    def buscar(nome_autor):
        achadas = []
        for ano in range(2023, date.today().year + 1):
            for pagina in range(1, 11):
                q = urlencode({"nomeAutor": nome_autor, "ano": ano, "pagina": pagina})
                d = _get_json(f"{URL_PORTAL}/emendas?{q}", f"portal_emendas_{_sem_acento(nome_autor)}_{ano}_{pagina}.json", cab)
                if d is None:
                    return None
                achadas += [e for e in d if (e.get("nomeAutor") or "").upper() == nome_autor]
                if len(d) < 15:
                    break
        return achadas

    alvo = nome.upper()
    lista = buscar(alvo)
    if lista == [] and _sem_acento(alvo) != alvo:
        lista = buscar(_sem_acento(alvo))
    if lista is None:
        return None
    empenhado = sum(_valor_br(e.get("valorEmpenhado")) for e in lista)
    pago = sum(_valor_br(e.get("valorPago")) + _valor_br(e.get("valorRestoPago")) for e in lista)
    pix = sum(_valor_br(e.get("valorEmpenhado")) for e in lista if "Transferências Especiais" in (e.get("tipoEmenda") or ""))
    areas, anos = {}, {}
    for e in lista:
        v = _valor_br(e.get("valorEmpenhado"))
        areas[e.get("funcao") or "Não informada"] = areas.get(e.get("funcao") or "Não informada", 0) + v
        anos[e.get("ano")] = anos.get(e.get("ano"), 0) + v
    return {
        "quantidade": len(lista),
        "empenhado": empenhado,
        "pago": pago,
        "transferenciasEspeciais": pix,
        "areas": sorted(({"area": a, "valor": v} for a, v in areas.items() if v), key=lambda x: -x["valor"])[:6],
        "anos": [{"ano": a, "valor": anos[a]} for a in sorted(anos)],
        "link": "https://portaldatransparencia.gov.br/emendas",
    }


def _trabalho(dep, resumo, emendas_dep=None):
    prod = dep.get("producao") or {}
    destaques = [dict(x) for x in prod.get("destaques", [])[:12]]
    with ThreadPoolExecutor(max_workers=6) as pool:
        futuro_emendas = pool.submit(_emendas, dep.get("nome")) if emendas_dep is None else None
        for x, alt in zip(destaques, pool.map(lambda x: alteracao(x["id"]), destaques)):
            x["alteracao"] = alt
        emendas_dep = futuro_emendas.result() if futuro_emendas else emendas_dep
    return {
        "projetos": dep.get("projetos", 0),
        "etapas": prod.get("etapas", {}),
        "simbolicos": prod.get("simbolicos", 0),
        "destaques": destaques,
        "relatorias": prod.get("relatorias", 0),
        "relatoriasLei": prod.get("relatoriasLei", 0),
        "medianas": (resumo or {}).get("medianasProducao"),
        "emendas": emendas_dep,
        "emendasAtivo": emendas._banco().exists() or tem_chave_portal(),
    }


def _trabalho_estadual(dep):
    r = alesp.resumo()
    if not dep or not r:
        return None
    return {**dep, "medianas": r["medianas"], "inicio": r["inicio"], "geradoEm": r["geradoEm"],
            "desempenho": alesp.tabela_desempenho().get(dep["id"]),
            "link": f"https://www.al.sp.gov.br/deputado/?matricula={dep['id']}"}


# ---------- análise ----------

def _medianas_camara(resumo):
    """Medianas da Câmara, para os textos de interpretação compararem o deputado com o normal."""
    ativos = [d for d in resumo["deputados"].values() if d["votos"] > 200]

    def mediana(chave):
        v = sorted(d[chave] for d in ativos if d.get(chave) is not None)
        return v[len(v) // 2] if v else None

    return {"governismo": mediana("governismo"), "fidelidade": mediana("fidelidade"), "participacao": mediana("participacao")}


def _orientacao(bruto, uf):
    resumo = camara.resumo()
    dep = None
    if resumo:
        for u in {uf, bruto.get("ufCandidatura"), bruto.get("sgUfNascimento")} - {None, "BR"}:
            dep = camara.deputado(bruto.get("nomeCompleto"), u, bruto.get("nomeUrna"))
            if dep:
                break
    sigla = (bruto.get("partido") or {}).get("sigla")
    return dep, {
        "pronto": resumo is not None,
        "status": camara.status(),
        "periodo": {"inicio": resumo["inicio"], "geradoEm": resumo["geradoEm"]} if resumo else None,
        "deputado": dep,
        "partido": dict(camara.partido(sigla) or {}, sigla=sigla) if resumo and camara.partido(sigla) else None,
        "planoDeGoverno": any(a.get("codTipo") == "5" for a in bruto.get("arquivos") or []),
        "medianas": _medianas_camara(resumo) if resumo else None,
    }


def grupo(uf, cargo, id_grupo):
    """Retrato de quem a lista (federação ou partido) elegeria pela estimativa, e onde o voto pesa mais."""
    r = historico.ranking(uf, cargo, id_grupo)
    if not r:
        return None
    proj = historico.projecao(uf, cargo)
    info = next(g for g in proj["grupos"] if g["id"] == id_grupo)
    vagas = r["vagasEstimadas"]
    aptos = [c for c in r["candidatos"] if c["posicao"]]
    eleitos = aptos[:vagas]
    faixa = max(2, round(vagas * 0.25))
    disputa = [c for c in aptos if vagas - faixa < c["posicao"] <= vagas + faixa]

    brutos = {c["id"]: c for c in tse.listar_bruto(uf, cargo)}
    with ThreadPoolExecutor(max_workers=6) as pool:
        fichas = list(pool.map(lambda c: tse.ficha_bruta(uf, cargo, c["id"]), eleitos[:25]))
    membros = []
    for c, fb in zip(eleitos, fichas + [None] * (len(eleitos) - len(fichas))):
        nome = (fb or brutos.get(c["id"]) or {}).get("nomeCompleto")
        dep = camara.deputado(nome, uf, c["nomeUrna"]) if camara.resumo() else None
        nasc = (fb or {}).get("dataDeNascimento")
        membros.append({
            **{k: c[k] for k in ("id", "numero", "nomeUrna", "partido", "posicao", "chance", "forca", "situacao2022", "cargo2022")},
            "mulher": (fb or {}).get("descricaoSexo") == "FEM.",
            "idade": (date.today().year - int(nasc[:4])) if nasc else None,
            "ocupacao": (fb or {}).get("ocupacao"),
            "patrimonio": (fb or {}).get("totalDeBens") or 0,
            "deputado": bool(dep),
            "governismo": dep.get("governismo") if dep else None,
        })

    def mediana(valores):
        v = sorted(x for x in valores if x is not None)
        return v[len(v) // 2] if v else None

    governismos = [m["governismo"] for m in membros if m["governismo"] is not None]
    ocupacoes = {}
    for m in membros:
        if m["ocupacao"]:
            ocupacoes[m["ocupacao"]] = ocupacoes.get(m["ocupacao"], 0) + 1
    partidos = {}
    for m in membros:
        partidos[m["partido"]] = partidos.get(m["partido"], 0) + 1
    return {
        "grupo": id_grupo,
        "perfil": perfis.perfil(id_grupo, uf, cargo),
        "vagas": vagas,
        "totalCandidatos": len(aptos),
        "margem": {"faltamParaMaisUma": info["faltamParaMaisUma"], "folgaDaUltima": info["folgaDaUltima"],
                   "votos2022": info["votos2022"], "quociente": proj["quociente"]},
        "membros": membros,
        "disputa": [{k: c[k] for k in ("id", "numero", "nomeUrna", "partido", "posicao", "chance", "forca")} for c in disputa],
        "retrato": {
            "partidos": sorted(({"partido": p, "quantidade": n} for p, n in partidos.items()), key=lambda x: -x["quantidade"]),
            "mulheres": sum(m["mulher"] for m in membros),
            "deputadosAtuais": sum(m["deputado"] for m in membros),
            "jaEleitos2022": sum(1 for m in membros if (m["situacao2022"] or "").startswith("Eleito")),
            "idadeMediana": mediana(m["idade"] for m in membros),
            "patrimonioMediano": mediana(m["patrimonio"] for m in membros),
            "governismoMedio": sum(governismos) / len(governismos) if governismos else None,
            "governismoMin": min(governismos) if governismos else None,
            "governismoMax": max(governismos) if governismos else None,
            "ocupacoes": sorted(ocupacoes.items(), key=lambda x: -x[1])[:4],
        },
    }



def rede_lista(uf, cargo, id_grupo):
    """Dinheiro entre candidatos de uma lista (federação ou partido): empresas de candidatos da lista pagas por outras
    campanhas e repasses recebidos de outros candidatos. None se a lista não existe."""
    membros = {str(c["id"]): c for c in tse.listar_bruto(uf, cargo) if c.get("nomeColigacao") == id_grupo}
    if not membros:
        return None
    if not gastos._banco().exists():
        return {"pronto": False}
    c = gastos._conectar()
    try:
        empresas_lista, vistas = [], set()
        for sq, cand in membros.items() if empresas.pronto() else ():
            for e in empresas.do_candidato(sq) or []:
                if e["basico"] in vistas:
                    continue
                pagam = [x for x in empresas._campanhas_que_pagam(c, e["basico"]) if str(x["sq_candidato"]) != sq]
                if not pagam:
                    continue
                vistas.add(e["basico"])
                da_lista = [x for x in pagam if str(x["sq_candidato"]) in membros]
                empresas_lista.append({
                    "dono": {"id": cand["id"], "nomeUrna": cand.get("nomeUrna"), "partido": (cand.get("partido") or {}).get("sigla")},
                    "empresa": e.get("razao"), "cnpj": empresas.cnpj_matriz(e["basico"]),
                    "quantas": len(pagam), "total": sum(x["valor"] or 0 for x in pagam),
                    "daLista": len(da_lista), "totalDaLista": sum(x["valor"] or 0 for x in da_lista),
                    "porPartido": empresas._por_partido(pagam),
                })
        empresas_lista.sort(key=lambda x: -x["total"])
        ids = [int(x) for x in membros]
        linhas = c.execute(f"""SELECT sq_cand_doador doador, fonte, sum(valor) valor FROM receitas
                               WHERE sq_candidato IN ({",".join("?" * len(ids))}) AND sq_cand_doador NOT IN (-1)
                               AND sq_cand_doador != sq_candidato GROUP BY 1, 2""", ids).fetchall()
        total = sum(r["valor"] for r in linhas)
        publico = sum(r["valor"] for r in linhas if r["fonte"] in ("FEFC", "FP"))
        interno = sum(r["valor"] for r in linhas if str(r["doador"]) in membros)
        por_doador = {}
        for r in linhas:
            por_doador[r["doador"]] = por_doador.get(r["doador"], 0) + r["valor"]
        doadores = []
        for sq_d, v in sorted(por_doador.items(), key=lambda kv: -kv[1])[:6]:
            p = empresas._pessoa(c, sq_d) or {}
            doadores.append({"nome": p.get("nome"), "partido": p.get("partido"), "cargo": NOMES_CARGOS.get(p.get("cargo")),
                             "daLista": str(sq_d) in membros, "valor": v})
        return {"pronto": True, "grupo": id_grupo, "empresas": empresas_lista[:12], "totalEmpresas": len(empresas_lista),
                "repasses": {"total": total, "publico": publico, "daLista": interno, "doadores": doadores}}
    finally:
        c.close()


def analisar(uf, cargo, id_candidato):
    bruto = tse.ficha_bruta(uf, cargo, id_candidato)
    if not bruto:
        return None
    ufc = tse.uf_consulta(uf, cargo)
    sigla_num = (bruto.get("partido") or {}).get("numero")
    contas = tse.contas(uf, cargo, id_candidato, sigla_num, bruto.get("numero"))

    chance, pares = None, None
    # Sem a base de 2022 pronta (só nos primeiros minutos de um servidor novo), a ficha sai sem a chance.
    if cargo in tse.CARGOS_PROPORCIONAIS and uf != "BR" and historico.pronto(uf):
        r = historico.ranking(uf, cargo, bruto.get("nomeColigacao"))
        if r:
            linha = next((c for c in r["candidatos"] if c["id"] == bruto["id"]), None)
            eleitos = [c for c in r["candidatos"] if c.get("posicao") and c["posicao"] <= r["vagasEstimadas"]]
            chance = {"grupo": r["grupo"], "vagasEstimadas": r["vagasEstimadas"], "candidato": linha,
                      "total": sum(1 for c in r["candidatos"] if c["apto"]), "eleitosProvaveis": eleitos}
            pares = [c["gastos"] for c in r["candidatos"] if c["apto"]]

    dep, orientacao = _orientacao(bruto, ufc)
    dep_est = alesp.deputado_da_ficha(bruto) if "SP" in (uf, bruto.get("ufCandidatura")) else None
    traj = trajetoria(bruto)
    emendas_dep = emendas.autor(dep["nome"], int(id_candidato)) if dep and emendas._banco().exists() else None
    sinais = []
    sinais += _sinais_candidatura(bruto)
    sinais += _sinais_trajetoria(traj)
    sinais += _sinais_contas(contas, pares)
    sinais += _sinais_mandato(dep, camara.resumo())
    sinais += _sinais_mandato_estadual(dep_est)
    sinais += _sinais_partidos(bruto)
    sinais += _sinais_emendas(emendas_dep)
    portal, portal_ativo = (_sinais_portal(bruto.get("cpf"), contas, bruto.get("nomeCompleto"))
                              if bruto.get("cpf") else ([], False))
    sinais += portal
    trabalho = _trabalho(dep, camara.resumo(), emendas_dep) if dep and dep.get("producao") else None
    analise_gastos = gastos.analisar_candidato(int(id_candidato), nome_urna=bruto.get("nomeUrna"))
    sinais += _sinais_gastos(analise_gastos)
    sinais += _sinais_emenda_campanha(dep, analise_gastos)
    socio_de = empresas.cruzamentos(id_candidato)
    sinais += _sinais_punicoes(bruto.get("cpf"), socio_de)
    sinais += _sinais_punicoes_fornecedores(contas)
    ja = {(s.get("cnpj") or "")[:8] for s in sinais if s["titulo"].startswith("Empresa do próprio candidato")}
    sinais += _sinais_empresas(socio_de, dep["nome"] if dep else None, ja)
    de_candidatos = empresas.fornecedores_de_candidatos(id_candidato)
    if de_candidatos:
        # Substitui o aviso mais fraco da análise de gastos ("Sócio é candidato em 2026"), que só vale para o mesmo nome e estado.
        cobertos = {f["basico"] for f in de_candidatos}
        sinais = [x for x in sinais if not (x["titulo"].startswith("Sócio é candidato em 2026") and (x.get("cnpj") or "")[:8] in cobertos)]
        sinais += _sinais_fornecedor_candidato(de_candidatos, (contas or {}).get("despesasContratadas"))
    ordem = {"alerta": 0, "atencao": 1, "info": 2, "ok": 3}
    sinais.sort(key=lambda s: ordem[s["nivel"]])
    anteriores = [l for l in traj["linhas"] if not l["atual"] and l["bens"] is not None]
    return {"chance": chance, "orientacao": orientacao, "trabalho": trabalho, "estadual": _trabalho_estadual(dep_est),
            "gastos": analise_gastos, "trajetoria": traj,
            "empresas": {"lista": socio_de, "status": empresas.status()},
            # Ligações de dinheiro com outros candidatos: empresas deles que esta campanha pagou e empresas deste
            # candidato pagas por outras campanhas (aba Dinheiro, "Ligações com candidatos").
            "rede": {"pagas": de_candidatos or [], "pronto": de_candidatos is not None,
                     "minhas": [e for e in socio_de or [] if (e.get("outrasCampanhas") or {}).get("quantas")]},
            "patrimonioAnterior": {"ano": anteriores[-1]["ano"], "valor": anteriores[-1]["bens"]} if anteriores else None,
            "sinais": sinais, "portalAtivo": portal_ativo, "pontuacao": pontuacao(sinais, dep, dep_est)}
