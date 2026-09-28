"""Dados abertos da Câmara dos Deputados: votações, orientação do governo, projetos e cota parlamentar.

Baixa os arquivos em lote da legislatura atual (desde fev/2023), processa e guarda
só um resumo pequeno (camara_resumo.json). Os arquivos originais, que somam
centenas de MB, são apagados depois do processamento.

Indicadores por deputado (métodos inspirados no projeto mandato-aberto):
- alinhamento com o governo: votos iguais à orientação da bancada "Governo"
  no plenário (obstrução conta como "Não");
- fidelidade ao partido: votos iguais aos da maioria da própria bancada;
- participação: votos registrados / votações nominais do plenário entre o
  primeiro e o último voto do deputado na legislatura;
- temas: temas oficiais dos projetos (PL, PLP, PEC) de que é o primeiro autor;
- cota parlamentar: gasto médio por mês com a CEAP, comparado aos colegas;
- produção: o que aconteceu com os projetos de que é primeiro autor (virou lei,
  passou na Câmara, anexado a outro, arquivado...), parte simbólica
  (homenagens, datas, nomes de obras) e relatorias.
"""
import bisect
import csv
import io
import json
import re
import statistics
import threading
import time
import unicodedata
import zipfile
from collections import Counter, defaultdict
from datetime import date

from curl_cffi import requests

import tse

BASE = "https://dadosabertos.camara.leg.br/arquivos"
URL_COTA = "https://www.camara.leg.br/cotas/Ano-{ano}.csv.zip"
INICIO = "2023-02-01"
TTL_RESUMO = 7 * 24 * tse.HORA
TIPOS_PROJETO = {"PL", "PLP", "PEC"}
TIPOS_RELATORIA = {"PL", "PLP", "PEC", "MPV", "PDL"}

# Situação atual de uma proposição -> etapa, do mais avançado ao mais parado.
ETAPAS = {
    "Transformado em Norma Jurídica": "lei",
    "Aguardando Sanção": "aprovada",
    "Aguardando Apreciação do Veto": "aprovada",
    "Aguardando Apreciação pelo Senado Federal": "aprovada",
    "Aguardando Autógrafos na Mesa": "aprovada",
    "Aguardando Redação Final": "aprovada",
    "Pronta para Pauta": "pronta",
    "Tramitando em Conjunto": "anexada",
    "Arquivada": "arquivada",
    "Retirado pelo(a) Autor(a)": "arquivada",
    "Devolvida ao(à) Autor(a)": "arquivada",
}
SIMBOLICO = re.compile(
    r"\b(denomina|confere (o )?t[ií]tulo|institui o dia|institui a semana|institui o m[eê]s|declara .{0,60}(patrono|patrimônio|capital nacional)"
    r"|inscreve o nome|livro dos her[oó]is|dia nacional|semana nacional)",
    re.I,
)
# Partidos que se fundiram durante a legislatura: somamos no sucessor.
FUSOES = {"PTB": "PRD", "PATRIOTA": "PRD", "PSC": "PODE", "PROS": "SOLIDARIEDADE"}

_lock = threading.Lock()
_rodando = threading.Event()
_estado = {"etapa": "parado", "erro": None}
_resumo = None
_indice_nomes = None


def _normalizar(texto):
    sem_acento = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode()
    return " ".join(sem_acento.upper().split())


def chave_partido(sigla):
    n = _normalizar(sigla)
    return FUSOES.get(n, n)


def _destaques(contagem, geral, minimo):
    """Temas em que a pessoa/partido se concentra mais que a média da Câmara."""
    total, total_geral = sum(contagem.values()), sum(geral.values())
    if not total or not total_geral:
        return []
    lifts = [
        (t, n, (n / total) / (geral[t] / total_geral))
        for t, n in contagem.items() if n >= minimo and geral.get(t)
    ]
    return [(t, n, round(l, 2)) for t, n, l in sorted(lifts, key=lambda x: -x[2]) if l >= 1.5][:3]


def _pasta():
    p = tse._cache_dir / "camara"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _baixar(url, destino):
    tmp = destino.with_suffix(destino.suffix + ".parcial")
    with requests.Session(impersonate="chrome") as s:
        r = s.get(url, stream=True, timeout=600)
        r.raise_for_status()
        with open(tmp, "wb") as f:
            for bloco in r.iter_content(chunk_size=1 << 20):
                f.write(bloco)
    tmp.replace(destino)
    return destino


def _linhas(nome, ano):
    """Baixa um CSV anual da Câmara, entrega as linhas e apaga o arquivo no fim."""
    arq = _baixar(f"{BASE}/{nome}/csv/{nome}-{ano}.csv", _pasta() / f"{nome}-{ano}.csv")
    try:
        with open(arq, encoding="utf-8-sig", newline="") as f:
            yield from csv.DictReader(f, delimiter=";")
    finally:
        arq.unlink(missing_ok=True)


def _valor(txt):
    txt = (txt or "0").strip()
    if "," in txt:
        txt = txt.replace(".", "").replace(",", ".")
    try:
        return float(txt)
    except ValueError:
        return 0.0


def _alinhado(voto, orientacao):
    if orientacao == "Sim":
        return voto == "Sim"
    return voto in ("Não", "Obstrução")


def _montar():
    anos = list(range(2023, date.today().year + 1))
    deps = {}
    partidos = defaultdict(lambda: {"govOk": 0, "govN": 0, "temas": Counter(), "projetos": 0})
    datas_plenario = []
    candidatas_quiz = {}
    concordancia = defaultdict(lambda: [0, 0])  # "A|B" -> [votações em que as maiorias votaram igual, votações com as duas]

    for ano in anos:
        _estado["etapa"] = f"votações de {ano}"
        votacoes = {
            v["id"]: v for v in _linhas("votacoes", ano)
            if v["siglaOrgao"] == "PLEN" and v["data"] >= INICIO
        }
        governo = {
            o["idVotacao"]: o["orientacao"] for o in _linhas("votacoesOrientacoes", ano)
            if o["siglaBancada"] == "Governo" and o["orientacao"] in ("Sim", "Não", "Obstrução")
        }
        _estado["etapa"] = f"votos de {ano}"
        por_votacao = defaultdict(list)
        for v in _linhas("votacoesVotos", ano):
            if v["idVotacao"] in votacoes and v["deputado_id"]:
                por_votacao[v["idVotacao"]].append(
                    (v["deputado_id"], v["deputado_siglaPartido"], v["deputado_siglaUf"], v["deputado_nome"], v["voto"])
                )

        for idv, votos in por_votacao.items():
            data = votacoes[idv]["data"]
            datas_plenario.append(data)
            contagem = defaultdict(Counter)
            for _, partido, _, _, voto in votos:
                if voto in ("Sim", "Não"):
                    contagem[partido][voto] += 1
            maioria = {}
            for partido, c in contagem.items():
                (a, na), *resto = c.most_common(2) + [(None, 0)]
                if sum(c.values()) >= 3 and na > resto[0][1]:
                    maioria[partido] = a
            por_chave = {}
            for partido, voto in maioria.items():
                por_chave.setdefault(chave_partido(partido), voto)
            chaves = sorted(por_chave)
            for i, a in enumerate(chaves):
                for b in chaves[i + 1:]:
                    par = concordancia[f"{a}|{b}"]
                    par[0] += por_chave[a] == por_chave[b]
                    par[1] += 1
            orient = governo.get(idv)
            for dep_id, partido, uf, nome, voto in votos:
                d = deps.setdefault(dep_id, {
                    "nome": nome, "partido": partido, "uf": uf, "votos": 0,
                    "govOk": 0, "govN": 0, "partOk": 0, "partN": 0, "primeiro": data, "ultimo": data,
                })
                d["votos"] += 1
                d["primeiro"] = min(d["primeiro"], data)
                if data >= d["ultimo"]:
                    d["ultimo"], d["nome"], d["partido"], d["uf"] = data, nome, partido, uf
                if orient and voto in ("Sim", "Não", "Obstrução"):
                    ok = _alinhado(voto, orient)
                    d["govN"] += 1
                    d["govOk"] += ok
                    partidos[chave_partido(partido)]["govN"] += 1
                    partidos[chave_partido(partido)]["govOk"] += ok
                if voto in ("Sim", "Não") and partido in maioria:
                    d["partN"] += 1
                    d["partOk"] += voto == maioria[partido]

            v = votacoes[idv]
            sim, nao = int(v["votosSim"] or 0), int(v["votosNao"] or 0)
            if sim + nao >= 300 and v["descricao"].startswith(("Aprovad", "Rejeitad")):
                por_partido = defaultdict(Counter)
                for p, c in contagem.items():
                    por_partido[chave_partido(p)].update(c)
                candidatas_quiz[idv] = {
                    "id": idv, "data": data, "descricao": v["descricao"][:500],
                    "proposicao": v["ultimaApresentacaoProposicao_idProposicao"],
                    "apresentacao": v["ultimaApresentacaoProposicao_descricao"][:600],
                    "sim": sim, "nao": nao, "governo": orient,
                    "partidos": {p: dict(c) for p, c in por_partido.items()},
                    "deputados": {dep: voto for dep, _, _, _, voto in votos if voto in ("Sim", "Não")},
                }

    datas_plenario.sort()
    for d in deps.values():
        possiveis = bisect.bisect_right(datas_plenario, d["ultimo"]) - bisect.bisect_left(datas_plenario, d["primeiro"])
        d["participacao"] = d["votos"] / possiveis if possiveis else None

    # Projetos: situação atual, relator e ementa
    props = {}
    relatorias = defaultdict(lambda: {"total": 0, "lei": 0})
    for ano in anos:
        _estado["etapa"] = f"projetos de {ano}"
        for pr in _linhas("proposicoes", ano):
            tipo = pr["siglaTipo"]
            situacao = pr["ultimoStatus_descricaoSituacao"]
            relator = (pr["ultimoStatus_uriRelator"] or "").rsplit("/", 1)[-1]
            if tipo in TIPOS_RELATORIA and relator:
                relatorias[relator]["total"] += 1
                relatorias[relator]["lei"] += situacao == "Transformado em Norma Jurídica"
            if tipo in TIPOS_PROJETO:
                props[pr["id"]] = {
                    "nome": f"{tipo} {pr['numero']}/{pr['ano']}",
                    "ementa": (pr["ementa"] or "")[:300],
                    "situacao": situacao or "Em análise",
                    "etapa": ETAPAS.get(situacao, "analise"),
                    "data": (pr["ultimoStatus_dataHora"] or "")[:10],
                }

    # Temas
    temas = {}
    for ano in anos:
        _estado["etapa"] = f"temas dos projetos de {ano}"
        for t in _linhas("proposicoesTemas", ano):
            if t["siglaTipo"] in TIPOS_PROJETO and (t["ano"] or "0") >= "2023":
                temas.setdefault(t["uriProposicao"].rsplit("/", 1)[-1], set()).add(t["tema"])
    autores = {}
    for ano in anos:
        _estado["etapa"] = f"autores dos projetos de {ano}"
        for a in _linhas("proposicoesAutores", ano):
            if a["idDeputadoAutor"] and a["proponente"] == "1" and a["ordemAssinatura"] == "1" and a["idProposicao"] in props:
                autores[a["idProposicao"]] = (a["idDeputadoAutor"], a["siglaPartidoAutor"])
    temas_dep = defaultdict(Counter)
    temas_geral = Counter()
    projetos_dep = Counter()
    producao = defaultdict(lambda: {"etapas": Counter(), "simbolicos": 0, "aprovadasSimbolicas": 0, "destaques": []})
    for prop, (dep_id, partido) in autores.items():
        # A sigla do arquivo de autores vem abreviada (ex.: "REPUBLIC"); a dos votos vem completa.
        partido = deps.get(dep_id, {}).get("partido") or partido
        projetos_dep[dep_id] += 1
        partidos[chave_partido(partido)]["projetos"] += 1
        info = props[prop]
        pr = producao[dep_id]
        pr["etapas"][info["etapa"]] += 1
        if "Homenagens e Datas Comemorativas" in temas.get(prop, ()) or SIMBOLICO.search(info["ementa"]):
            pr["simbolicos"] += 1
            pr["aprovadasSimbolicas"] += info["etapa"] in ("lei", "aprovada")
            info = dict(info, simbolico=True)
        if info["etapa"] in ("lei", "aprovada"):
            pr["destaques"].append(dict(info, id=prop))
        for t in temas.get(prop, ()):
            temas_dep[dep_id][t] += 1
            temas_geral[t] += 1
            partidos[chave_partido(partido)]["temas"][t] += 1

    # Cota parlamentar (CEAP)
    cota = defaultdict(lambda: {"total": 0.0, "meses": set(), "categorias": Counter()})
    for ano in anos:
        _estado["etapa"] = f"cota parlamentar de {ano}"
        arq = _baixar(URL_COTA.format(ano=ano), _pasta() / f"cota-{ano}.zip")
        try:
            with zipfile.ZipFile(arq) as z, z.open(z.namelist()[0]) as bruto:
                for row in csv.DictReader(io.TextIOWrapper(bruto, encoding="utf-8-sig"), delimiter=";"):
                    dep_id = row["ideCadastro"]
                    if not dep_id or row["codLegislatura"] != "57":
                        continue
                    valor = _valor(row["vlrLiquido"])
                    c = cota[dep_id]
                    c["total"] += valor
                    c["meses"].add((row["numAno"], row["numMes"]))
                    c["categorias"][row["txtDescricao"].capitalize()] += valor
        finally:
            arq.unlink(missing_ok=True)
    medias = {d: c["total"] / len(c["meses"]) for d, c in cota.items() if c["meses"]}
    ordenadas = sorted(medias.values())

    _estado["etapa"] = "nomes dos deputados"
    arq = _baixar(f"{BASE}/deputados/json/deputados.json", _pasta() / "deputados.json")
    try:
        civil = {d["uri"].rsplit("/", 1)[-1]: d["nomeCivil"] for d in json.loads(arq.read_text(encoding="utf-8"))["dados"]}
    finally:
        arq.unlink(missing_ok=True)

    def taxa(dep_id, chave):
        pr, total = producao.get(dep_id), projetos_dep.get(dep_id, 0)
        if not pr or not total:
            return None
        if chave == "simbolicos":
            return pr["simbolicos"] / total
        return (pr["etapas"]["lei"] + pr["etapas"]["aprovada"]) / total

    ativos = [d for d, x in deps.items() if x["votos"] > 200]
    medianas_producao = {
        "projetos": statistics.median(projetos_dep.get(d, 0) for d in ativos) if ativos else None,
        "avancaram": statistics.median(t for d in ativos if (t := taxa(d, "avancaram")) is not None) if ativos else None,
        "simbolicos": statistics.median(t for d in ativos if (t := taxa(d, "simbolicos")) is not None) if ativos else None,
        "relatorias": statistics.median(relatorias[d]["total"] if d in relatorias else 0 for d in ativos) if ativos else None,
    }

    resumo_deps = {}
    for dep_id, d in deps.items():
        c = cota.get(dep_id)
        media = medias.get(dep_id)
        resumo_deps[dep_id] = {
            "id": dep_id,
            "nome": d["nome"],
            "nomeCivil": civil.get(dep_id),
            "partido": d["partido"],
            "uf": d["uf"],
            "votos": d["votos"],
            "governismo": d["govOk"] / d["govN"] if d["govN"] else None,
            "votacoesComGoverno": d["govN"],
            "fidelidade": d["partOk"] / d["partN"] if d["partN"] else None,
            "participacao": d["participacao"],
            "primeiroVoto": d["primeiro"],
            "ultimoVoto": d["ultimo"],
            "projetos": projetos_dep.get(dep_id, 0),
            "temas": temas_dep[dep_id].most_common(6),
            "temasDestaque": _destaques(temas_dep[dep_id], temas_geral, 3),
            "producao": {
                "etapas": dict(producao[dep_id]["etapas"]) if dep_id in producao else {},
                "simbolicos": producao[dep_id]["simbolicos"] if dep_id in producao else 0,
                "aprovadasSimbolicas": producao[dep_id]["aprovadasSimbolicas"] if dep_id in producao else 0,
                "destaques": sorted(producao[dep_id]["destaques"], key=lambda x: (x["etapa"] != "lei", x["data"]))[:20]
                if dep_id in producao else [],
                "relatorias": relatorias[dep_id]["total"] if dep_id in relatorias else 0,
                "relatoriasLei": relatorias[dep_id]["lei"] if dep_id in relatorias else 0,
            },
            "cota": {
                "total": round(c["total"], 2),
                "mediaMensal": round(media, 2),
                "meses": len(c["meses"]),
                "percentil": bisect.bisect_left(ordenadas, media) / len(ordenadas),
                "categorias": [(k, round(v, 2)) for k, v in c["categorias"].most_common(5)],
            } if c and media is not None else None,
        }
    return {
        "geradoEm": time.strftime("%Y-%m-%d %H:%M"),
        "inicio": INICIO,
        "votacoesPlenario": len(datas_plenario),
        "medianaCotaMensal": statistics.median(ordenadas) if ordenadas else None,
        "medianasProducao": medianas_producao,
        "deputados": resumo_deps,
        "partidos": {
            p: {
                "governismo": v["govOk"] / v["govN"] if v["govN"] else None,
                "votos": v["govN"],
                "projetos": v["projetos"],
                "temas": v["temas"].most_common(6),
                "temasDestaque": _destaques(v["temas"], temas_geral, 10),
            }
            for p, v in partidos.items()
        },
        "concordancia": {k: v for k, v in concordancia.items() if v[1] >= 30},
        "quiz": list(candidatas_quiz.values()),
    }


def _arquivo_resumo():
    return _pasta() / "camara_resumo.json"


def _carregar():
    global _resumo, _indice_nomes
    arq = _arquivo_resumo()
    if not arq.exists():
        return False
    r = json.loads(arq.read_text(encoding="utf-8"))
    indice = {}
    for d in r["deputados"].values():
        for nome in (d.get("nomeCivil"), d.get("nome")):
            if nome:
                indice.setdefault((_normalizar(nome), d["uf"]), d)
    with _lock:
        _resumo, _indice_nomes = r, indice
    return True


def _preparar():
    try:
        r = _montar()
        _arquivo_resumo().write_text(json.dumps(r, ensure_ascii=False), encoding="utf-8")
        _carregar()
        _estado.update(etapa="pronto", erro=None)
    except Exception as e:  # noqa: BLE001 - mostramos o erro na interface
        _estado.update(etapa="erro", erro=str(e))
    finally:
        _rodando.clear()


def iniciar():
    """Carrega o resumo salvo e, se estiver velho ou ausente, recalcula em segundo plano."""
    arq = _arquivo_resumo()
    tem = _carregar()
    if tem:
        _estado["etapa"] = "pronto"
    velho = not arq.exists() or time.time() - arq.stat().st_mtime > TTL_RESUMO
    if velho and not _rodando.is_set():
        _rodando.set()
        if not tem:
            _estado["etapa"] = "baixando"
        threading.Thread(target=_preparar, daemon=True).start()


def status():
    return {"pronto": _resumo is not None, "etapa": _estado["etapa"], "erro": _estado["erro"]}


def resumo():
    return _resumo


def deputado(nome_completo, uf, nome_urna=None):
    """Encontra o deputado federal (legislatura atual) pelo nome civil e UF."""
    if not _indice_nomes:
        return None
    for nome in (nome_completo, nome_urna):
        d = _indice_nomes.get((_normalizar(nome), uf))
        if d:
            return d
    return None


def partido(sigla):
    """Indicadores da bancada. A Câmara e o TSE escrevem algumas siglas diferente (PCdoB/PCDOB)."""
    if not _resumo:
        return None
    return _resumo["partidos"].get(chave_partido(sigla))


# ---------- desempenho no mandato (usado pela ficha e pelos cartões de lista) ----------

_desempenho = {"gerado": None, "tabela": {}}


CRITERIOS = [
    # chave, rótulo, peso, maior é melhor
    ("presenca", "Presença nas votações", 1, True),
    ("aprovacao", "Projetos aprovados que mudam regras", 1, True),
    ("relatorias", "Relatorias", 1, True),
    ("simbolicos", "Poucos projetos simbólicos", 2, False),
    ("cota", "Economia na cota parlamentar", 1, False),
    ("pix", "Menos emendas Pix", 1, False),
]


def _valores_desempenho(d, pix):
    pr = d["producao"]
    total = d["projetos"]
    aprovadas = pr["etapas"].get("lei", 0) + pr["etapas"].get("aprovada", 0) - pr.get("aprovadasSimbolicas", 0)
    return {
        "presenca": d.get("participacao") or 0,
        "aprovacao": aprovadas / total if total else 0,
        "relatorias": pr["relatorias"],
        "simbolicos": pr["simbolicos"] / total if total else 0,
        "cota": (d.get("cota") or {}).get("mediaMensal", 0),
        "pix": pix.get(d["nome"]),
    }


def _calcular_desempenho():
    """Para cada deputado federal, a posição (0 a 1) em cada critério comparado aos colegas.
    Projeto simbólico (homenagem, data, nome de obra) pesa em dobro e não conta como aprovação."""
    import emendas  # importado aqui para não criar ciclo na inicialização
    r = _resumo
    if not r:
        return {}
    ativos = [d for d in r["deputados"].values() if d["votos"] > 200 and d.get("producao")]
    por_autor = emendas.por_autor_mandato()
    pix = {}
    for d in ativos:
        e = por_autor.get(emendas.normalizar(d["nome"]))
        if e and e["empenhado"] > 1_000_000:
            pix[d["nome"]] = e["pix"] / e["empenhado"]
    valores = {d["id"]: _valores_desempenho(d, pix) for d in ativos}
    ordenados = {k: sorted(v[k] for v in valores.values() if v[k] is not None) for k, *_ in CRITERIOS}
    tabela = {}
    for d in ativos:
        notas, soma, pesos = {}, 0, 0
        for chave, _, peso, maior in CRITERIOS:
            v = valores[d["id"]][chave]
            lista = ordenados[chave]
            if v is None or len(lista) < 10:
                continue
            n = max(len(lista) - 1, 1)
            # Empatados (muita gente com zero relatorias, por exemplo) ficam no meio do grupo empatado.
            pos = (bisect.bisect_left(lista, v) + (bisect.bisect_right(lista, v) - bisect.bisect_left(lista, v) - 1) / 2) / n
            notas[chave] = pos if maior else 1 - pos
            soma += notas[chave] * peso
            pesos += peso
        tabela[d["id"]] = {"nota": round(100 * soma / pesos), "criterios": notas, "valores": valores[d["id"]]}
    return tabela


def criterios_rotulados(criterios):
    return [{"chave": k, "rotulo": rot, "peso": peso, "valor": criterios[k]} for k, rot, peso, _ in CRITERIOS if k in criterios]


def concordancia(a, b):
    """Parte das votações em que as maiorias de dois partidos votaram igual."""
    if not _resumo:
        return None
    x, y = sorted((chave_partido(a), chave_partido(b)))
    par = _resumo.get("concordancia", {}).get(f"{x}|{y}")
    return {"iguais": par[0], "votacoes": par[1], "taxa": par[0] / par[1]} if par else None


def tabela_desempenho():
    """Posição (0 a 1) de cada deputado federal em cada critério, comparado aos colegas; guardada por resumo."""
    if not _resumo:
        return {}
    import emendas
    versao = (_resumo["geradoEm"], emendas.status().get("geradoEm"))
    if _desempenho["gerado"] != versao:
        _desempenho.update(gerado=versao, tabela=_calcular_desempenho())
    return _desempenho["tabela"]
