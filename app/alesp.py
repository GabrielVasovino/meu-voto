"""Dados abertos da Assembleia Legislativa de São Paulo (ALESP), legislatura atual.

Para cada deputado estadual em exercício:
- projetos de lei de que é autor ou coautor, separados entre os que mudam alguma
  regra e os simbólicos (nome de viaduto, "utilidade pública", datas e títulos);
- leis aprovadas desde março de 2023, também separadas assim;
- temas: palavras-chave que a própria ALESP atribui aos projetos, agrupadas em temas amplos;
- indicações ao governador (pedidos de obra ou verba) e os municípios citados nelas;
- requerimentos de informação (perguntas formais ao governo, um instrumento de fiscalização);
- presença nas reuniões das comissões de que é membro efetivo;
- verba de gabinete: gasto médio por mês e principais fornecedores.

Os arquivos originais (centenas de MB) ficam só durante o processamento; guardamos um
resumo pequeno (alesp_resumo.json), refeito uma vez por semana.
"""
import bisect
import json
import re
import statistics
import sys
import threading
import time
import traceback
import unicodedata
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter, defaultdict

from curl_cffi import requests

import tse

BASE = "https://www.al.sp.gov.br/repositorioDados/"
ARQUIVOS = {
    "deputados": "deputados/deputados.xml",
    "naturezas": "processo_legislativo/naturezasSpl.xml",
    "proposituras": "processo_legislativo/proposituras.zip",
    "autores": "processo_legislativo/documento_autor.zip",
    "palavras": "processo_legislativo/documento_palavras.zip",
    "palavrasChave": "processo_legislativo/palavras_chave.xml",
    "normas": "legislacao/legislacao_normas.zip",
    "membros": "processo_legislativo/comissoes_membros.xml",
    "reunioes": "processo_legislativo/comissoes_permanentes_reunioes.xml",
    "presencas": "processo_legislativo/comissoes_permanentes_presencas.xml",
    "despesas": "deputados/despesas_gabinetes.xml",
}
INICIO = "2023-03-15"
TTL = 7 * 24 * tse.HORA
PROJETOS = {"PL", "PLC", "PEC", "PDL", "PR"}
TIPOS_LEI = {"9", "2", "55"}  # lei, lei complementar, emenda constitucional

SIMBOLICO = re.compile(
    r"DENOMINA|UTILIDADE PUBLICA|INSTITUI (O|A) \W?(DIA|SEMANA|MES|JORNADA|ANO)|CALENDARIO OFICIAL|INCLUI .{0,60}CALENDARIO"
    r"|TITULO DE CIDADAO|CAPITAL (ESTADUAL|PAULISTA|DO ESTADO)|HOMENAG|COMENDA|MEDALHA|COLAR DE HONRA|PATRIMONIO CULTURAL IMATERIAL"
    r"|PATRIMONIO (HISTORICO|CULTURAL) .{0,40}DECLARA|DECLARA .{0,80}PATRIMONIO|DECLARA O ESTADO DE SAO PAULO|CONFERE .{0,40}TITULO"
)
# Classificar município como turístico ou estância dá acesso a um fundo estadual: não é homenagem,
# mas também não muda regra para o estado todo. Contamos à parte, como benefício local.
LOCAL = re.compile(r"INTERESSE TURISTICO|ESTANCIA (TURISTICA|HIDROMINERAL|CLIMATICA|BALNEARIA)")
MUNICIPIO = re.compile(r"munic[ií]pio de ([A-ZÁÉÍÓÚÂÊÔÃÕÇ][\w'’ -]+?)(?=[,.;:]| para | com | e | no | na | junto|$)")
PALAVRAS_SIMBOLICAS = {"UTILIDADE PUBLICA", "DENOMINACAO", "CALENDARIO OFICIAL", "TITULACAO DE MUNICIPIO",
                       "PATRIMONIO CULTURAL IMATERIAL DO ESTADO", "TITULO HONORIFICO"}

# Temas amplos, reconhecidos nas palavras-chave e na ementa de cada projeto.
TEMAS = [
    ("Saúde", r"SAUDE|HOSPITAL|\bSUS\b|MEDIC|DOENCA|VACINA|ENFERM|CANCER|FARMAC"),
    ("Educação", r"EDUCA|ESCOLA|ENSINO|PROFESSOR|ALUNO|UNIVERSIDADE|CRECHE|ESTUDANT"),
    ("Segurança pública", r"SEGURANCA PUBLICA|POLICIA|POLICIAL|CRIME|CRIMINAL|PRESIDI|PENITENCI|DELEGACIA|GUARDA CIVIL|ARMA DE FOGO"),
    ("Mulheres", r"MULHER|GESTANTE|VIOLENCIA DOMESTICA|FEMINICIDIO|MATERN|GENERO"),
    ("Crianças e jovens", r"CRIANCA|ADOLESCENTE|INFANT|JUVENTUDE|JOVE"),
    ("Pessoas com deficiência e autismo", r"DEFICIENCIA|AUTIS|\bTEA\b|ACESSIBILIDADE|DOENCA RARA|SINDROME"),
    ("Pessoas idosas", r"IDOSO|PESSOA IDOSA"),
    ("Proteção animal", r"ANIMAL|ANIMAIS|CAES|GATOS|PET\b"),
    ("Meio ambiente e clima", r"AMBIENT|CLIMA|FLORESTA|RECICLA|RESIDUO|POLUI|SANEAMENTO|RECURSOS HIDRICOS|SUSTENTAB|PRESERVACAO"),
    ("Agro e abastecimento", r"AGRICULT|AGRO|PECUAR|RURAL|PRODUTOR|PESCA|ABASTECIMENTO|AGROPEC"),
    ("Transporte e rodovias", r"RODOVIA|TRANSPORTE|PEDAGIO|TRANSITO|METRO\b|TREM|ONIBUS|VEICULO|MOBILIDADE"),
    ("Impostos, economia e emprego", r"ICMS|IPVA|IMPOSTO|TRIBUT|BENEFICIO FISCAL|ISENCAO|EMPREGO|TRABALHO|MICROEMPRE|COMERCIO|INDUSTRIA|EMPREENDED"),
    ("Servidores públicos", r"SERVIDOR|FUNCIONALISMO|CARREIRA|IAMSPE|APOSENTADORIA|VENCIMENTO|QUADRO DE PESSOAL"),
    ("Direitos humanos e igualdade", r"RACIAL|RACISMO|LGBT|DIREITOS HUMANOS|INDIGEN|QUILOMB|IGUALDADE|DISCRIMINA"),
    ("Consumidor", r"CONSUMIDOR|PROCON|TARIFA|COBRANCA"),
    ("Cultura, esporte e turismo", r"CULTURA|CULTURAL|ESPORTE|ESPORTIV|TURIS|FESTIVAL|MUSICA"),
    ("Habitação e cidades", r"HABITACAO|HABITACIONAL|MORADIA|URBAN"),
    ("Religião e família", r"RELIGI|IGREJA|TEMPLO|FAMILIA|CRISTA|EVANGEL"),
    ("Transparência e controle", r"TRANSPARENCIA|CORRUPCAO|FISCALIZA|LICITA|CONTROLE SOCIAL"),
]
TEMAS_RE = [(nome, re.compile(p)) for nome, p in TEMAS]

_lock = threading.Lock()
_rodando = threading.Event()
_estado = {"etapa": "parado", "erro": None}
_resumo = None
_indice = None
_desempenho = {"gerado": None, "tabela": {}}


def registrar_falha(e):
    """Deixa no log do servidor em que etapa a base falhou, com o erro completo."""
    print(f"[{__name__}] falhou em \"{_estado.get('etapa')}\": {e}", file=sys.stderr)
    traceback.print_exc()


def normalizar(texto):
    sem = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode()
    return " ".join(re.sub(r"[^A-Z0-9 ]", " ", sem.upper()).split())


def _pasta():
    p = tse._cache_dir / "alesp"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _baixar(chave):
    rel = ARQUIVOS[chave]
    destino = _pasta() / rel.rsplit("/", 1)[-1]
    if destino.exists() and time.time() - destino.stat().st_mtime < 12 * tse.HORA:
        return destino
    _estado["etapa"] = f"baixando {destino.name}"
    tmp = destino.with_suffix(destino.suffix + ".parcial")
    with requests.Session(impersonate="chrome") as s:
        r = s.get(BASE + rel, stream=True, timeout=900)
        r.raise_for_status()
        with open(tmp, "wb") as f:
            for bloco in r.iter_content(chunk_size=1 << 20):
                f.write(bloco)
    tmp.replace(destino)
    return destino


def _elementos(arq, tag):
    """Percorre um XML grande (solto ou dentro de um zip) sem carregá-lo inteiro."""
    if arq.suffix == ".zip":
        with zipfile.ZipFile(arq) as z, z.open(z.namelist()[0]) as f:
            for _, el in ET.iterparse(f):
                if el.tag == tag:
                    yield {c.tag: (c.text or "").strip() for c in el}
                    el.clear()
    else:
        for _, el in ET.iterparse(arq):
            if el.tag == tag:
                yield {c.tag: (c.text or "").strip() for c in el}
                el.clear()


def simbolico(ementa, palavras=()):
    return bool(SIMBOLICO.search(normalizar(ementa))) or any(normalizar(p) in PALAVRAS_SIMBOLICAS for p in palavras)


def classe(ementa, palavras=()):
    """"simbolica", "local" ou "geral"."""
    if simbolico(ementa, palavras):
        return "simbolica"
    if LOCAL.search(normalizar(ementa)):
        return "local"
    return "geral"


def temas_de(ementa, palavras=()):
    texto = normalizar(ementa) + " " + " ".join(normalizar(p) for p in palavras)
    return {nome for nome, rx in TEMAS_RE if rx.search(texto)}


def _montar():
    arqs = {k: _baixar(k) for k in ARQUIVOS}
    _estado["etapa"] = "lendo os deputados"
    deputados = {d["IdSPL"]: d for d in _elementos(arqs["deputados"], "Deputado")}
    naturezas = {n["idNatureza"]: (n.get("sgNatureza") or n["nmNatureza"]).strip() for n in _elementos(arqs["naturezas"], "natureza") if "idNatureza" in n}

    _estado["etapa"] = "lendo as proposituras"
    docs = {}
    for p in _elementos(arqs["proposituras"], "propositura"):
        if (p.get("DtPublicacao") or "") < INICIO:
            continue
        sg = naturezas.get(p["IdNatureza"], "")
        tipo = "projeto" if sg in PROJETOS else "indicacao" if sg.startswith("Indica") else "ri" if sg == "RI" \
            else "mocao" if sg.startswith("Mo") else None
        if tipo:
            docs[p["IdDocumento"]] = {"tipo": tipo, "sigla": sg, "numero": p["NroLegislativo"], "ano": p["AnoLegislativo"],
                                      "ementa": p["Ementa"], "data": p["DtPublicacao"][:10]}

    _estado["etapa"] = "lendo os autores"
    autores = defaultdict(set)
    for a in _elementos(arqs["autores"], "DocumentoAutor"):
        if a["IdDocumento"] in docs:
            autores[a["IdDocumento"]].add(a["IdAutor"])

    _estado["etapa"] = "lendo as palavras-chave"
    nomes_palavras = {p["IdPalavra"]: p["Palavra"] for p in _elementos(arqs["palavrasChave"], "PalavraChave")}
    palavras = defaultdict(list)
    for dp in _elementos(arqs["palavras"], "DocumentoPalavra"):
        d = docs.get(dp["IdDocumento"])
        if d and d["tipo"] in ("projeto", "indicacao"):
            palavras[dp["IdDocumento"]].append(nomes_palavras.get(dp["IdPalavra"], ""))

    # Projetos por deputado
    por_dep = defaultdict(lambda: {"projetos": 0, "simbolicos": 0, "locais": 0, "temas": Counter(), "indicacoes": 0,
                                   "municipios": Counter(), "ri": 0, "mocoes": 0, "exemplos": [], "leis": [], "leisSimbolicas": 0})
    temas_geral = Counter()
    por_ementa = {}
    for doc_id, d in docs.items():
        ids = [i for i in autores.get(doc_id, ()) if i in deputados]
        if d["tipo"] == "projeto":
            cl = classe(d["ementa"], palavras.get(doc_id, ()))
            simb = cl == "simbolica"
            ts = temas_de(d["ementa"], palavras.get(doc_id, ())) if cl == "geral" else set()
            por_ementa[normalizar(d["ementa"])[:120]] = (doc_id, cl)
            for t in ts:
                temas_geral[t] += 1
            for i in ids:
                x = por_dep[i]
                x["projetos"] += 1
                x["simbolicos"] += simb
                x["locais"] += cl == "local"
                x["temas"].update(ts)
                if cl == "geral" and len(x["exemplos"]) < 400:
                    x["exemplos"].append({"nome": f"{d['sigla']} {d['numero']}/{d['ano']}", "ementa": d["ementa"][:300],
                                          "data": d["data"], "coautores": len(ids) - 1})
        elif d["tipo"] == "indicacao":
            for i in ids:
                por_dep[i]["indicacoes"] += 1
                m = MUNICIPIO.search(d["ementa"])
                if m:
                    por_dep[i]["municipios"][m.group(1).strip()] += 1
        elif d["tipo"] == "ri":
            for i in ids:
                por_dep[i]["ri"] += 1
        elif d["tipo"] == "mocao":
            for i in ids:
                por_dep[i]["mocoes"] += 1

    _estado["etapa"] = "lendo as leis aprovadas"
    nome_para_id = {normalizar(d["NomeParlamentar"]): i for i, d in deputados.items()}
    for n in _elementos(arqs["normas"], "LegislacaoNorma"):
        if n.get("IdTipo") not in TIPOS_LEI or (n.get("Data") or "") < INICIO:
            continue
        chave = normalizar(n.get("Ementa"))[:120]
        achado = por_ementa.get(chave)
        ids = set()
        if achado:
            ids = {i for i in autores.get(achado[0], ()) if i in deputados}
            cl = achado[1]
        else:
            cl = classe(n.get("Ementa"))
        for nome in re.split(r",| e ", n.get("Autores") or ""):
            i = nome_para_id.get(normalizar(nome))
            if i:
                ids.add(i)
        for i in ids:
            x = por_dep[i]
            if any(l["numero"] == n["Numero"] and l["tipo"] == n["IdTipo"] for l in x["leis"]):
                continue
            x["leis"].append({"numero": n["Numero"], "tipo": n["IdTipo"], "data": n["Data"][:10], "ementa": (n.get("Ementa") or "")[:300],
                              "classe": cl, "link": n.get("URLFicha")})

    _estado["etapa"] = "lendo a presença nas comissões"
    mandatos = defaultdict(list)  # (IdMembro) -> [(comissao, inicio, fim)]
    for m in _elementos(arqs["membros"], "MembroComissao"):
        if m.get("Efetivo") == "S" and m["IdMembro"] in deputados:
            mandatos[m["IdMembro"]].append((m["IdComissao"], m["DataInicio"][:10], (m.get("DataFim") or "9999")[:10]))
    reunioes = {}
    for r in _elementos(arqs["reunioes"], "ReuniaoComissao"):
        # Só as reuniões realizadas têm lista de presença; as que caem por falta de quórum quase nunca têm.
        if INICIO <= (r.get("Data") or "") <= time.strftime("%Y-%m-%d") and r.get("Situacao") == "REALIZADA":
            reunioes[r["IdReuniao"]] = (r["IdComissao"], r["Data"][:10])
    presentes = defaultdict(set)
    com_lista = set()
    for p in _elementos(arqs["presencas"], "ReuniaoComissaoPresenca"):
        if p["IdReuniao"] in reunioes:
            presentes[p["IdDeputado"]].add(p["IdReuniao"])
            com_lista.add(p["IdReuniao"])
    reunioes = {k: v for k, v in reunioes.items() if k in com_lista}
    por_comissao = defaultdict(list)
    for rid, (com, data) in reunioes.items():
        por_comissao[com].append((data, rid))
    presenca = {}
    for i in deputados:
        esperadas = set()
        for com, ini, fim in mandatos.get(i, ()):
            for data, rid in por_comissao.get(com, ()):
                if ini <= data <= fim:
                    esperadas.add(rid)
        if len(esperadas) >= 10:
            presenca[i] = {"reunioes": len(esperadas), "presente": len(esperadas & presentes.get(i, set()))}

    _estado["etapa"] = "lendo a verba de gabinete"
    matriculas = {d["Matricula"]: i for i, d in deputados.items()}
    verba = defaultdict(lambda: {"total": 0.0, "meses": set(), "categorias": Counter(), "fornecedores": Counter(), "nomes": {}})
    for g in _elementos(arqs["despesas"], "despesa"):
        i = matriculas.get(g.get("Matricula"))
        if not i or f"{g['Ano']}-{int(g['Mes']):02d}" < INICIO[:7]:
            continue
        v = float(g.get("Valor") or 0)
        x = verba[i]
        x["total"] += v
        x["meses"].add((g["Ano"], g["Mes"]))
        x["categorias"][re.sub(r"^[A-Z] - ", "", g.get("Tipo") or "").capitalize()] += v
        doc = re.sub(r"\D", "", g.get("CNPJ") or "")
        if doc:
            x["fornecedores"][doc] += v
            x["nomes"][doc] = g.get("Fornecedor")
    medias_verba = {i: x["total"] / len(x["meses"]) for i, x in verba.items() if x["meses"]}

    resumo = {}
    for i, d in deputados.items():
        x = por_dep[i]
        leis = sorted(x["leis"], key=lambda l: l["data"], reverse=True)
        v = verba.get(i)
        pr = presenca.get(i)
        resumo[i] = {
            "id": i,
            "nome": d["NomeParlamentar"],
            "partido": d.get("Partido"),
            "areas": [a.strip(" ;.") for a in re.split(r"[;\n]", d.get("txtAreaAtuacao") or "") if a.strip(" ;.")][:8],
            "base": [a.strip(" ;.") for a in re.split(r"[;\n]", d.get("txtBaseEleitoral") or "") if a.strip(" ;.")][:6],
            "projetos": x["projetos"],
            "simbolicos": x["simbolicos"],
            "locais": x["locais"],
            "temas": x["temas"].most_common(8),
            "exemplos": sorted(x["exemplos"], key=lambda e: (e["coautores"], e["data"]))[:8],
            "leis": leis[:30],
            "leisTotal": len(leis),
            "leisSubstantivas": sum(1 for l in leis if l["classe"] == "geral"),
            "leisSimbolicas": sum(1 for l in leis if l["classe"] == "simbolica"),
            "leisLocais": sum(1 for l in leis if l["classe"] == "local"),
            "indicacoes": x["indicacoes"],
            "municipiosIndicacoes": x["municipios"].most_common(8),
            "requerimentosInformacao": x["ri"],
            "mocoes": x["mocoes"],
            "presenca": {**pr, "taxa": pr["presente"] / pr["reunioes"]} if pr else None,
            "verba": {
                "total": round(v["total"], 2),
                "mediaMensal": round(medias_verba[i], 2),
                "meses": len(v["meses"]),
                "categorias": [(k, round(val, 2)) for k, val in v["categorias"].most_common(5)],
                "fornecedores": [{"cnpj": doc, "nome": v["nomes"][doc], "valor": round(val, 2)}
                                 for doc, val in v["fornecedores"].most_common(8)],
            } if v and i in medias_verba else None,
        }
    todos = list(resumo.values())

    def mediana(f):
        vals = [x for x in (f(d) for d in todos) if x is not None]
        return statistics.median(vals) if vals else None

    return {
        "geradoEm": time.strftime("%Y-%m-%d %H:%M"),
        "inicio": INICIO,
        "deputados": resumo,
        "temasGeral": temas_geral.most_common(),
        "medianas": {
            "projetos": mediana(lambda d: d["projetos"]),
            "simbolicos": mediana(lambda d: d["simbolicos"] / d["projetos"] if d["projetos"] else None),
            "leisSubstantivas": mediana(lambda d: d["leisSubstantivas"]),
            "leisSimbolicas": mediana(lambda d: d["leisSimbolicas"]),
            "leisLocais": mediana(lambda d: d["leisLocais"]),
            "locais": mediana(lambda d: d["locais"] / d["projetos"] if d["projetos"] else None),
            "presenca": mediana(lambda d: d["presenca"]["taxa"] if d["presenca"] else None),
            "verbaMensal": mediana(lambda d: d["verba"]["mediaMensal"] if d["verba"] else None),
            "indicacoes": mediana(lambda d: d["indicacoes"]),
            "requerimentosInformacao": mediana(lambda d: d["requerimentosInformacao"]),
        },
    }


def _arquivo():
    return _pasta() / "alesp_resumo.json"


def _carregar():
    global _resumo, _indice
    arq = _arquivo()
    if not arq.exists():
        return False
    r = json.loads(arq.read_text(encoding="utf-8"))
    with _lock:
        _resumo = r
        _indice = {normalizar(d["nome"]): d for d in r["deputados"].values()}
    return True


def _preparar():
    try:
        r = _montar()
        _arquivo().write_text(json.dumps(r, ensure_ascii=False), encoding="utf-8")
        _carregar()
        _estado.update(etapa="pronto", erro=None)
        for p in _pasta().iterdir():  # os arquivos brutos só servem para montar o resumo
            if p.name != _arquivo().name:
                p.unlink(missing_ok=True)
    except Exception as e:  # noqa: BLE001 - mostramos o erro na interface
        registrar_falha(e)
        _estado.update(etapa="erro", erro=f"{_estado.get('etapa')}: {e}")
    finally:
        _rodando.clear()


def iniciar():
    arq = _arquivo()
    if _carregar():
        _estado["etapa"] = "pronto"
    if (not arq.exists() or time.time() - arq.stat().st_mtime > TTL) and not _rodando.is_set():
        _rodando.set()
        threading.Thread(target=_preparar, daemon=True).start()


def status():
    return {"pronto": _resumo is not None, "etapa": _estado["etapa"], "erro": _estado["erro"]}


def resumo():
    return _resumo


def deputado_da_ficha(bruto):
    """Deputado estadual de SP correspondente a uma ficha do TSE. O casamento aproximado de nomes só vale
    para quem concorreu a deputado estadual em SP em 2022, para não confundir parentes com o mesmo nome."""
    if not bruto:
        return None
    anteriores = [e for e in bruto.get("eleicoesAnteriores") or []
                  if e.get("nrAno") == 2022 and e.get("cargo") == "Deputado Estadual" and e.get("sgUe") == "SP"]
    d = deputado(bruto.get("nomeUrna"), bruto.get("nomeCompleto"), aproximado=bool(anteriores))
    if not d and anteriores:
        d = deputado(anteriores[0].get("nomeUrna"), None, aproximado=True)
    return d


def deputado(nome_urna, nome_completo=None, aproximado=False):
    """Encontra o deputado estadual pelo nome de urna ou pelo nome civil."""
    if not _indice:
        return None
    for nome in (nome_urna, nome_completo):
        d = _indice.get(normalizar(nome))
        if d:
            return d
    if not aproximado:
        return None
    # Nome parlamentar com prefixo ("Agente Federal Danilo Balas") ou só parte do nome civil.
    urna = set(normalizar(nome_urna).split())
    civil = set(normalizar(nome_completo).split())
    candidatos = []
    for chave, d in _indice.items():
        partes = set(chave.split())
        if len(urna) >= 2 and urna <= partes:
            candidatos.append(d)
        elif len(partes) >= 2 and partes <= civil and partes & urna:
            candidatos.append(d)
    return candidatos[0] if len(candidatos) == 1 else None


# ---------- desempenho ----------

CRITERIOS = [
    # chave, rótulo, peso, maior é melhor
    ("presenca", "Presença nas comissões", 1, True),
    ("leis", "Leis aprovadas que mudam regras", 1, True),
    ("simbolicos", "Poucos projetos simbólicos", 2, False),
    ("verba", "Economia na verba de gabinete", 1, False),
]


def _valor_criterio(d, chave):
    if chave == "presenca":
        return d["presenca"]["taxa"] if d["presenca"] else None
    if chave == "leis":
        return d["leisSubstantivas"]
    if chave == "simbolicos":
        return d["simbolicos"] / d["projetos"] if d["projetos"] else None
    if chave == "verba":
        return d["verba"]["mediaMensal"] if d["verba"] else None


def _calcular_desempenho():
    todos = list(_resumo["deputados"].values())
    ordenados = {k: sorted(v for d in todos if (v := _valor_criterio(d, k)) is not None) for k, *_ in CRITERIOS}
    tabela = {}
    for d in todos:
        notas, pesos = {}, 0
        soma = 0
        for chave, _, peso, maior in CRITERIOS:
            v = _valor_criterio(d, chave)
            lista = ordenados[chave]
            if v is None or len(lista) < 5:
                continue
            pos = bisect.bisect_left(lista, v) / max(len(lista) - 1, 1)
            # Empates (muitos com zero leis, por exemplo) ficam no meio do grupo empatado.
            iguais = bisect.bisect_right(lista, v) - bisect.bisect_left(lista, v)
            pos += (iguais - 1) / 2 / max(len(lista) - 1, 1)
            notas[chave] = pos if maior else 1 - pos
            soma += notas[chave] * peso
            pesos += peso
        if pesos:
            tabela[d["id"]] = {"nota": round(100 * soma / pesos), "criterios": notas}
    return tabela


def tabela_desempenho():
    if not _resumo:
        return {}
    if _desempenho["gerado"] != _resumo["geradoEm"]:
        _desempenho.update(gerado=_resumo["geradoEm"], tabela=_calcular_desempenho())
    return _desempenho["tabela"]


def criterios_rotulados(criterios):
    return [{"chave": k, "rotulo": rot, "peso": peso, "valor": criterios[k]} for k, rot, peso, _ in CRITERIOS if k in criterios]


def bancada(siglas):
    """Médias da bancada estadual de um conjunto de partidos."""
    if not _resumo:
        return None
    alvo = {normalizar(s) for s in siglas}
    membros = [d for d in _resumo["deputados"].values() if normalizar(d["partido"]) in alvo]
    if not membros:
        return None
    tab = tabela_desempenho()
    notas = [tab[d["id"]]["nota"] for d in membros if d["id"] in tab]
    projetos = sum(d["projetos"] for d in membros)
    verbas = [d["verba"]["mediaMensal"] for d in membros if d["verba"]]
    return {
        "membros": len(membros),
        "porPartido": Counter(d["partido"] for d in membros).most_common(),
        "desempenho": round(statistics.mean(notas)) if notas else None,
        "parteSimbolica": sum(d["simbolicos"] for d in membros) / projetos if projetos else None,
        "leisSubstantivas": sum(d["leisSubstantivas"] for d in membros),
        "leisSimbolicas": sum(d["leisSimbolicas"] for d in membros),
        "verbaMensal": statistics.mean(verbas) if verbas else None,
        "temas": sum((Counter(dict(d["temas"])) for d in membros), Counter()).most_common(5),
    }


def fornecedor_gabinete(doc):
    """Deputados estaduais que pagaram este fornecedor com a verba de gabinete (entre os 8 maiores de cada um)."""
    if not _resumo:
        return []
    out = []
    for d in _resumo["deputados"].values():
        for f in (d.get("verba") or {}).get("fornecedores", []):
            if f["cnpj"] == doc:
                out.append({"deputado": d["nome"], "partido": d["partido"], "valor": f["valor"], "nome": f["nome"]})
    return sorted(out, key=lambda x: -x["valor"])
