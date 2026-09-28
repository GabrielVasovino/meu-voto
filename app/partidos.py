"""Perfil de um partido ou federação pelo histórico das bancadas atuais.

A lista de um partido em 2026 tem muita gente sem mandato, e a nota de cada pessoa diz
pouco sobre o que o partido faz quando chega lá. Este perfil olha quem o partido já tem:
- na Câmara dos Deputados: apoio ao governo, união nas votações, desempenho médio,
  parte simbólica dos projetos, cota, uso de emendas Pix e entidades privadas que
  dependem das emendas de algum deputado da bancada;
- na ALESP (listas de SP para deputado estadual): desempenho médio, homenagens e verba;
- nas federações: o quanto os partidos votam juntos na Câmara.
"""
import re
import statistics
import threading
import time
from collections import Counter

import alesp
import camara
import emendas

TTL = 12 * 3600
_cache = {}
_lock = threading.Lock()


def chave(sigla):
    return camara.chave_partido(sigla).replace(" ", "")


def siglas_do_grupo(grupo):
    """"FEDERAÇÃO PSOL REDE(50-PSOL/18-REDE)" -> ["PSOL", "REDE"]; "MDB" -> ["MDB"]."""
    dentro = re.search(r"\((.*)\)", grupo or "")
    if dentro:
        return [re.sub(r"^\d+-", "", p).strip() for p in dentro.group(1).split("/") if p.strip()]
    return [grupo.strip()] if grupo else []


_memo = {}


def _memorizado(nome, funcao):
    """Guarda o resultado enquanto o banco de emendas não mudar."""
    versao = emendas.status().get("geradoEm")
    guardado = _memo.get(nome)
    if not guardado or guardado[0] != versao:
        guardado = (versao, funcao())
        _memo[nome] = guardado
    return guardado[1]


def _dependentes_por_autor():
    return _memorizado("dependentes", _calcular_dependentes)


def _por_autor():
    return _memorizado("porAutor", emendas.por_autor_mandato)


def _calcular_dependentes():
    """Autores com pelo menos uma entidade privada que depende das suas emendas (mesma regra da ficha)."""
    if not emendas._banco().exists():
        return {}
    c = emendas._conectar()
    try:
        linhas = c.execute("""
            WITH autores AS (SELECT doc, count(DISTINCT autor) n FROM favorecidos GROUP BY doc)
            SELECT f.autor, f.doc, max(f.nome) nome, sum(f.valor) valor, a.n
            FROM favorecidos f JOIN autores a ON a.doc = f.doc
            WHERE f.ano >= ? AND f.grupo IN ('semFins', 'empresas') AND a.n <= 2
            GROUP BY f.autor, f.doc HAVING sum(f.valor) >= ?""", (emendas.MANDATO_ATUAL, emendas.LIMITE_DEPENDENTE)).fetchall()
    finally:
        c.close()
    out = Counter()
    for r in linhas:
        if not any(p in emendas.normalizar(r["nome"]) for p in emendas.FILANTROPIA_COMUM):
            out[r["autor"]] += 1
    return out


def _bancada_federal(siglas):
    r = camara.resumo()
    if not r:
        return None
    alvo = {chave(s) for s in siglas}
    membros = [d for d in r["deputados"].values()
               if chave(d["partido"]) in alvo and d["ultimoVoto"] >= time.strftime("%Y-01-01") and d["votos"] > 200]
    if not membros:
        return None
    tab = camara.tabela_desempenho()
    por_autor = _por_autor()
    dependentes = _dependentes_por_autor()
    notas = [tab[d["id"]]["nota"] for d in membros if d["id"] in tab]
    projetos = sum(d["projetos"] for d in membros)
    simbolicos = sum(d["producao"]["simbolicos"] for d in membros if d.get("producao"))
    cotas = [d["cota"]["mediaMensal"] for d in membros if d.get("cota")]
    emp = [por_autor.get(emendas.normalizar(d["nome"])) for d in membros]
    emp = [e for e in emp if e and e["empenhado"] > 1_000_000]
    partidos = [r["partidos"].get(chave(s)) or r["partidos"].get(camara.chave_partido(s)) for s in siglas]
    gov_n = sum(p["votos"] for p in partidos if p and p.get("governismo") is not None)
    gov = sum(p["governismo"] * p["votos"] for p in partidos if p and p.get("governismo") is not None) / gov_n if gov_n else None
    fidelidade = [d["fidelidade"] for d in membros if d.get("fidelidade") is not None]
    return {
        "membros": len(membros),
        "porPartido": Counter(chave(d["partido"]) for d in membros).most_common(),
        "governismo": gov,
        "coesao": statistics.median(fidelidade) if fidelidade else None,
        "desempenho": round(statistics.mean(notas)) if notas else None,
        "parteSimbolica": simbolicos / projetos if projetos else None,
        "cotaMensal": statistics.mean(cotas) if cotas else None,
        "partePix": sum(e["pix"] for e in emp) / sum(e["empenhado"] for e in emp) if emp else None,
        "comEntidadeDependente": sum(1 for d in membros if dependentes.get(emendas.normalizar(d["nome"]))),
        "temasDestaque": [t for p in partidos if p for t in p.get("temasDestaque", [])][:4],
    }


def _referencias_federais():
    """Médias de toda a Câmara, para comparar a bancada."""
    r = camara.resumo()
    todos = [d for d in r["deputados"].values() if d["ultimoVoto"] >= time.strftime("%Y-01-01") and d["votos"] > 200]
    siglas = {d["partido"] for d in todos}
    geral = _bancada_federal(list(siglas))
    return geral


def _dinamica(siglas):
    pares = []
    for i, a in enumerate(siglas):
        for b in siglas[i + 1:]:
            c = camara.concordancia(chave(a), chave(b))
            if c:
                pares.append({"a": a, "b": b, **c})
    return pares


def perfis(uf, cargo, grupos):
    """Resumo curto do perfil de várias listas, para os cartões."""
    out = {}
    for g in grupos:
        p = perfil(g, uf, cargo)
        base = p["estadual"] if p["casaDoIndice"] == "estadual" else p["federal"]
        out[g] = {"indice": p["indice"], "casa": p["casaDoIndice"], "membros": base["membros"] if base else 0,
                  "federacao": p["federacao"], "siglas": p["siglas"],
                  "referencia": ((p["referenciaEstadual"] if p["casaDoIndice"] == "estadual" else p["referenciaFederal"]) or {}).get("desempenho")}
    return out


def perfil(grupo, uf, cargo):
    chave_cache = (grupo, uf, cargo)
    with _lock:
        guardado = _cache.get(chave_cache)
    if guardado and time.time() - guardado[0] < TTL:
        return guardado[1]
    siglas = siglas_do_grupo(grupo)
    federal = _bancada_federal(siglas)
    estadual = alesp.bancada(siglas) if uf == "SP" else None
    usa_estadual = cargo == 7 and estadual
    base = estadual if usa_estadual else federal
    r = camara.resumo()
    referencia = _referencias_federais() if r else None
    ref_estadual = alesp.bancada([d["partido"] for d in alesp.resumo()["deputados"].values()]) if uf == "SP" and alesp.resumo() else None
    dados = {
        "grupo": grupo,
        "siglas": siglas,
        "federacao": len(siglas) > 1,
        "federal": federal,
        "estadual": estadual,
        "referenciaFederal": referencia,
        "referenciaEstadual": ref_estadual,
        "casaDoIndice": "estadual" if usa_estadual else "federal",
        "indice": base["desempenho"] if base else None,
        "dinamica": _dinamica(siglas) if len(siglas) > 1 else [],
    }
    with _lock:
        _cache[chave_cache] = (time.time(), dados)
    return dados
