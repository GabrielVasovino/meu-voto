"""Presença dos senadores nas votações nominais do plenário (API de dados abertos legislativos do Senado).

Serve para os senadores que disputam 2026 (reeleição, governo ou presidência). Conta, desde fevereiro de 2023, em
quantas votações nominais cada um votou, e separa as ausências justificadas (licença, missão oficial, atividade
parlamentar) das que não têm justificativa. É informação sobre o mandato, como a presença dos deputados: não entra
na nota de integridade.

O senador é ligado à candidatura de 2026 pelo nome parlamentar e pela data de nascimento (API administrativa do
Senado e arquivo de candidatos do TSE). Refeito uma vez por semana em segundo plano.
"""
import calendar
import json
import statistics
import sys
import threading
import time
import traceback

from curl_cffi import requests

import camara
import gabinetes
import tse

URL_VOTACOES = "https://legis.senado.leg.br/dadosabertos/votacao?dataInicio={ini}&dataFim={fim}"
DESDE = (2023, 2)
TTL = 7 * 24 * tse.HORA
VOTOU = {"Votou", "Sim", "Não", "Abstenção", "P-NRV", "Presidente (art. 51 RISF)"}
JUSTIFICADA = {"AP", "LS", "LP", "MIS", "LAP", "LAT", "LC", "LG", "REP"}

_indice = None
_lock = threading.Lock()
_rodando = threading.Event()
_estado = {"etapa": "parado", "erro": None}


def _arquivo():
    p = tse._cache_dir / "senado"
    p.mkdir(parents=True, exist_ok=True)
    return p / "presenca.json"


def _preparar():
    try:
        norm = camara._normalizar
        with requests.Session(impersonate="chrome") as s:
            _estado["etapa"] = "baixando as votações do Senado"
            votacoes, (ano, mes) = [], DESDE
            hoje = time.localtime()
            while (ano, mes) <= (hoje.tm_year, hoje.tm_mon):
                fim = calendar.monthrange(ano, mes)[1]
                r = s.get(URL_VOTACOES.format(ini=f"{ano}-{mes:02d}-01", fim=f"{ano}-{mes:02d}-{fim}"),
                          headers={"Accept": "application/json"}, timeout=120)
                votacoes += r.json() if r.status_code == 200 else []
                ano, mes = (ano + 1, 1) if mes == 12 else (ano, mes + 1)
                time.sleep(0.3)
            senadores = s.get(gabinetes.URL_SENADORES, timeout=120).json()["data"]
        _estado["etapa"] = "ligando senadores às candidaturas"
        cands = gabinetes._candidatos()
        por_nascimento = {}
        for c in cands:
            por_nascimento.setdefault(c["nascimento"], []).append(c)
        candidatura = {}
        for p in senadores:
            nome = norm(p["nomeParlamentar"])
            achados = [c for c in por_nascimento.get(p.get("dataNascimento"), []) if set(nome.split()) & set(c["urna"].split())]
            if len(achados) == 1:
                candidatura[nome] = achados[0]["sq"]
        conta = {}
        for v in votacoes:
            for x in v.get("votos") or []:
                c = conta.setdefault(norm(x.get("nomeParlamentar")), {"total": 0, "votou": 0, "justificada": 0})
                c["total"] += 1
                sigla = x.get("siglaVotoParlamentar")
                if sigla in VOTOU:
                    c["votou"] += 1
                elif sigla in JUSTIFICADA:
                    c["justificada"] += 1
        taxas = [c["votou"] / c["total"] for c in conta.values() if c["total"] >= 50]
        dados = {"geradoEm": time.strftime("%d/%m/%Y"), "votacoes": len(votacoes),
                 "mediana": round(statistics.median(taxas), 3) if taxas else None,
                 "senadores": {candidatura[n]: dict(c, nome=n.title()) for n, c in conta.items() if n in candidatura}}
        tmp = _arquivo().with_suffix(".tmp")
        tmp.write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")
        tmp.replace(_arquivo())
        _carregar()
        _estado.update(etapa="pronto", erro=None)
    except Exception as e:  # noqa: BLE001 - mostramos o erro na interface
        print(f"[{__name__}] falhou em \"{_estado.get('etapa')}\": {e}", file=sys.stderr)
        traceback.print_exc()
        _estado.update(etapa="erro", erro=f"{_estado.get('etapa')}: {e}")
    finally:
        _rodando.clear()


def _carregar():
    global _indice
    arq = _arquivo()
    if not arq.exists():
        return False
    try:
        dados = json.loads(arq.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    with _lock:
        _indice = dados
    return True


def iniciar():
    if _carregar():
        _estado["etapa"] = "pronto"
    arq = _arquivo()
    if (not arq.exists() or time.time() - arq.stat().st_mtime > TTL) and not _rodando.is_set():
        _rodando.set()
        threading.Thread(target=_preparar, daemon=True).start()


def status():
    return {"pronto": _indice is not None, "etapa": _estado["etapa"], "erro": _estado["erro"],
            "geradoEm": (_indice or {}).get("geradoEm")}


def presenca(id_candidato):
    """{"total", "votou", "justificada", "mediana", "votacoes"} do senador que é esta candidatura, ou None."""
    if not _indice:
        return None
    p = _indice["senadores"].get(str(id_candidato))
    return dict(p, mediana=_indice.get("mediana"), votacoes=_indice.get("votacoes")) if p else None
