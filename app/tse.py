"""Acesso aos dados públicos do TSE (DivulgaCandContas), com cache local.

O site do TSE bloqueia clientes HTTP comuns (erro 403), por isso usamos
curl_cffi imitando um navegador Chrome. Tudo que é baixado fica em cache no
disco; se o TSE estiver fora do ar, usamos a última cópia salva.
"""
import json
import os
import threading
import time
import unicodedata
from pathlib import Path

from curl_cffi import requests

BASE = "https://divulgacandcontas.tse.jus.br/divulga/rest/v1"
BASE_FOTOS = "https://divulgacandcontas.tse.jus.br/divulga/rest/arquivo/img"
ANO = 2026
ELEICAO = 20322002026  # "Eleição Geral Federal 2026"

UFS = {
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS", "MG", "PA",
    "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO",
}
CARGOS = {
    1: "Presidente",
    3: "Governador",
    5: "Senador",
    6: "Deputado Federal",
    7: "Deputado Estadual",
    8: "Deputado Distrital",
}
CARGOS_PROPORCIONAIS = {6, 7, 8}

HORA = 3600
TTL_LISTA = 6 * HORA
TTL_FICHA = 6 * HORA
TTL_CONTAS = 3 * HORA
TTL_FOTO = 30 * 24 * HORA

_cache_dir = Path("cache")
_listas = {}  # (uf, cargo) -> (baixado_em, [candidatos resumidos])
_lock = threading.Lock()


class TSEIndisponivel(Exception):
    pass


def configurar(cache_dir):
    global _cache_dir
    _cache_dir = Path(cache_dir)
    _cache_dir.mkdir(parents=True, exist_ok=True)


def _baixar(url, chave, ttl):
    arq = _cache_dir / chave
    if arq.exists() and time.time() - arq.stat().st_mtime < ttl:
        return arq.read_bytes()
    try:
        r = requests.get(url, impersonate="chrome", timeout=40)
        if r.status_code == 404:
            return None
        r.raise_for_status()
    except Exception as e:
        if arq.exists():  # sem internet ou TSE fora do ar: usa a cópia antiga
            return arq.read_bytes()
        raise TSEIndisponivel(str(e)) from e
    arq.parent.mkdir(parents=True, exist_ok=True)
    tmp = arq.with_name(f"{arq.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_bytes(r.content)
    tmp.replace(arq)
    return r.content


def _json(caminho, chave, ttl):
    dados = _baixar(BASE + caminho, chave, ttl)
    if not dados:
        return None
    return json.loads(dados.decode("utf-8"))


def uf_consulta(uf, cargo):
    """Presidente é consultado na circunscrição 'BR'; os demais, na UF."""
    return "BR" if cargo == 1 else uf


def _normalizar(texto):
    sem_acento = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode()
    return sem_acento.upper().strip()


def _prioridade(c):
    """Candidaturas válidas primeiro; indeferidas/renunciadas por último."""
    s = (c.get("situacao") or "").lower()
    if s == "deferido":
        return 0
    if "indeferido" in s or "cancelado" in s or "renúncia" in s or "falecido" in s:
        return 2
    return 1


def _resumo(c):
    return {
        "id": c["id"],
        "numero": c["numero"],
        "nomeUrna": c.get("nomeUrna"),
        "nomeCompleto": c.get("nomeCompleto"),
        "partido": (c.get("partido") or {}).get("sigla"),
        "coligacao": c.get("nomeColigacao"),
        "situacao": c.get("descricaoSituacao"),
        "totalizacao": c.get("descricaoTotalizacao"),
    }


def listar_bruto(uf, cargo):
    """Lista completa do TSE, com campos internos (ex.: título de eleitor). Não enviar ao navegador."""
    ufc = uf_consulta(uf, cargo)
    chave = (ufc, cargo)
    with _lock:
        em_memoria = _listas.get(chave)
    if em_memoria and time.time() - em_memoria[0] < TTL_LISTA:
        return em_memoria[1]
    bruto = _json(
        f"/candidatura/listar/{ANO}/{ufc}/{ELEICAO}/{cargo}/candidatos",
        f"lista_{ufc}_{cargo}.json",
        TTL_LISTA,
    )
    candidatos = (bruto or {}).get("candidatos", [])
    with _lock:
        _listas[chave] = (time.time(), candidatos)
    return candidatos


def listar(uf, cargo):
    return [_resumo(c) for c in listar_bruto(uf, cargo)]


def buscar_numero(uf, cargo, numero):
    """Retorna (candidatos, legenda). Com 2 dígitos em cargo proporcional é voto de legenda."""
    candidatos = listar(uf, cargo)
    if cargo in CARGOS_PROPORCIONAIS and len(numero) == 2:
        do_partido = [c for c in candidatos if str(c["numero"]).startswith(numero)]
        if not do_partido:
            return [], None
        ref = min(do_partido, key=_prioridade)
        return [], {
            "numero": numero,
            "partido": ref["partido"],
            "coligacao": ref["coligacao"],
            "qtdCandidatos": len(do_partido),
        }
    achados = [c for c in candidatos if str(c["numero"]) == numero]
    return sorted(achados, key=_prioridade), None


def buscar_nome(uf, cargo, q, limite=10):
    alvo = _normalizar(q)
    achados = [
        c for c in listar(uf, cargo)
        if alvo in _normalizar(c["nomeUrna"]) or alvo in _normalizar(c["nomeCompleto"])
    ]
    achados.sort(key=lambda c: (_prioridade(c), not _normalizar(c["nomeUrna"]).startswith(alvo), c["nomeUrna"]))
    return achados[:limite]


def _ficha_limpa(d, ufc):
    """Mantém só o que interessa ao eleitor. CPF, título e dados de contato ficam de fora."""
    atual = str(d["id"])
    historico = [
        {
            "ano": e.get("nrAno"),
            "cargo": e.get("cargo"),
            "local": e.get("local"),
            "partido": e.get("partido"),
            "numero": e.get("nrCandidato"),
            "resultado": e.get("situacaoTotalizacao"),
            "link": e.get("txLink"),
        }
        for e in d.get("eleicoesAnteriores") or []
        if str(e.get("id")) != atual
    ]
    bens = sorted(
        (
            {"tipo": b.get("descricaoDeTipoDeBem"), "descricao": b.get("descricao"), "valor": b.get("valor") or 0}
            for b in d.get("bens") or []
        ),
        key=lambda b: -b["valor"],
    )
    vices = [
        {
            "id": v.get("sq_CANDIDATO"),
            "uf": v.get("sg_UE") or ufc,
            "nomeUrna": v.get("nm_URNA"),
            "nomeCompleto": v.get("nm_CANDIDATO"),
            "cargo": v.get("ds_CARGO"),
            "partido": v.get("sg_PARTIDO"),
        }
        for v in d.get("vices") or []
    ]
    partido = d.get("partido") or {}
    cargo = d.get("cargo") or {}
    return {
        "id": d["id"],
        "numero": d.get("numero"),
        "nomeUrna": d.get("nomeUrna"),
        "nomeCompleto": d.get("nomeCompleto"),
        "cargo": cargo.get("nome"),
        "codCargo": cargo.get("codigo"),
        "uf": ufc,
        "partido": {"sigla": partido.get("sigla"), "nome": partido.get("nome"), "numero": partido.get("numero")},
        "coligacao": d.get("nomeColigacao"),
        "composicao": d.get("composicaoColigacao") if d.get("composicaoColigacao") not in (None, "**") else None,
        "tipoAgremiacao": d.get("descricaoTipoDrap"),
        "situacao": d.get("descricaoSituacao"),
        "situacaoUrna": d.get("descricaoSituacaoCandidato"),
        "totalizacao": d.get("descricaoTotalizacao"),
        "reeleicao": bool(d.get("st_REELEICAO")),
        "nascimento": d.get("dataDeNascimento"),
        "sexo": d.get("descricaoSexo"),
        "corRaca": d.get("descricaoCorRaca"),
        "estadoCivil": d.get("descricaoEstadoCivil"),
        "instrucao": d.get("grauInstrucao"),
        "ocupacao": d.get("ocupacao"),
        "naturalidade": d.get("descricaoNaturalidade"),
        "bens": bens,
        "totalBens": d.get("totalDeBens") or sum(b["valor"] for b in bens),
        "sites": d.get("sites") or [],
        "historico": historico,
        "vices": vices,
        "atualizadoEm": d.get("dataUltimaAtualizacao"),
        "linkTse": f"https://divulgacandcontas.tse.jus.br/divulga/#/candidato/{ANO}/{ELEICAO}/{ufc}/{d['id']}",
    }


def _contas_limpas(c):
    if not c or not c.get("dadosConsolidados"):
        return None
    dc = c["dadosConsolidados"]
    desp = c.get("despesas") or {}
    origens = [
        ("Pessoas físicas", dc.get("totalReceitaPF")),
        ("Partidos", dc.get("totalPartidos")),
        ("Recursos próprios", dc.get("totalProprios")),
        ("Outros candidatos", dc.get("totalReceitaOutCand")),
        ("Financiamento coletivo", dc.get("totalInternet")),
        ("Comercialização de bens/eventos", dc.get("totalReceitaComercializacao")),
        ("Aplicações financeiras", dc.get("totalDoacaoAplicacaoFinanceira")),
        ("Origem não identificada", dc.get("totalRoni")),
    ]
    return {
        "atualizadoEm": c.get("dataUltimaAtualizacaoContas"),
        "totalRecebido": dc.get("totalRecebido") or 0,
        "estimaveis": dc.get("totalEstimados") or 0,
        "origens": [{"origem": o, "valor": v} for o, v in origens if v],
        "fundoEleitoral": dc.get("graphVrReceitaFinFefc") or 0,
        "fundoPartidario": dc.get("graphVrReceitaFinFundo") or 0,
        "despesasContratadas": desp.get("totalDespesasContratadas") or 0,
        "despesasPagas": desp.get("totalDespesasPagas") or 0,
        "limiteGastos": desp.get("valorLimiteDeGastos") or 0,
        "categorias": [
            {"categoria": x.get("dsDRD"), "qtd": int(x.get("qtdeDespesas") or 0), "valor": x.get("valor") or 0}
            for x in c.get("concentracaoDespesas") or []
        ],
        # Nomes de doadores e fornecedores são públicos no TSE; CPFs não são exibidos aqui.
        "doadores": [
            {"nome": x.get("nome"), "qtd": int(x.get("qntd") or 0), "valor": x.get("valor") or 0}
            for x in (c.get("rankingDoadores") or [])[:10]
        ],
        # CNPJ de empresa é público; CPF de fornecedor pessoa física fica de fora.
        "fornecedores": [
            {
                "nome": x.get("nome"), "qtd": int(x.get("qntd") or 0), "valor": x.get("valor") or 0,
                "cnpj": x.get("cpfCnpj") if len(x.get("cpfCnpj") or "") == 14 else None,
            }
            for x in (c.get("rankingFornecedores") or [])[:10]
        ],
    }


def ficha_bruta(uf, cargo, id_candidato):
    """Registro completo do TSE, com CPF e marcações internas. Não enviar ao navegador."""
    ufc = uf_consulta(uf, cargo)
    bruto = _json(
        f"/candidatura/buscar/{ANO}/{ufc}/{ELEICAO}/candidato/{id_candidato}",
        f"ficha_{id_candidato}.json",
        TTL_FICHA,
    )
    return bruto if bruto and bruto.get("id") else None


def ficha_anterior(ano, sg_ue, id_eleicao, id_candidato):
    """Registro de uma candidatura antiga (ex.: 2022 ou 2024). Não muda mais, então o cache é longo."""
    try:
        bruto = _json(
            f"/candidatura/buscar/{ano}/{sg_ue}/{id_eleicao}/candidato/{id_candidato}",
            f"anteriores/ficha_{id_candidato}.json",
            TTL_FOTO,
        )
    except (TSEIndisponivel, ValueError):
        return None
    return bruto if bruto and bruto.get("id") else None


def contas(uf, cargo, id_candidato, partido, numero):
    """Resumo das contas de campanha, ou None se ainda não houver prestação publicada."""
    ufc = uf_consulta(uf, cargo)
    try:
        bruto = _json(
            f"/prestador/consulta/{ELEICAO}/{ANO}/{ufc}/{cargo}/{partido}/{numero}/{id_candidato}",
            f"contas_{id_candidato}.json",
            TTL_CONTAS,
        )
    except (TSEIndisponivel, ValueError):
        return None
    return _contas_limpas(bruto)


def ficha(uf, cargo, id_candidato):
    bruto = ficha_bruta(uf, cargo, id_candidato)
    if not bruto:
        return None
    f = _ficha_limpa(bruto, uf_consulta(uf, cargo))
    f["contas"] = contas(uf, cargo, id_candidato, f["partido"]["numero"], f["numero"])
    return f


def arquivo(url, nome, ttl):
    """Baixa (com cache) um arquivo grande de dados abertos."""
    return _baixar(url, nome, ttl)


def foto(uf, id_candidato):
    return _baixar(f"{BASE_FOTOS}/{ELEICAO}/{id_candidato}/{uf}", f"fotos/{id_candidato}.jpg", TTL_FOTO)
