"""Presença dos senadores nas votações nominais do plenário (API de dados abertos legislativos do Senado).

Serve para os senadores que disputam 2026 (reeleição, governo ou presidência). Conta, desde fevereiro de 2023, em
quantas votações nominais cada um votou, e separa as ausências justificadas (licença, missão oficial, atividade
parlamentar) das que não têm justificativa. É informação sobre o mandato, como a presença dos deputados: não entra
na nota de integridade.

O senador é ligado à candidatura de 2026 pelo nome parlamentar e pela data de nascimento (API administrativa do
Senado e arquivo de candidatos do TSE). Refeito uma vez por semana em segundo plano.
"""
import bisect
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


URL_LISTA = "https://legis.senado.leg.br/dadosabertos/senador/lista/atual"
URL_PROCESSOS = "https://legis.senado.leg.br/dadosabertos/processo?codigoParlamentarAutor={cod}&dataInicioApresentacao=2023-02-01"
URL_CEAPS = "https://adm.senado.gov.br/adm-dadosabertos/api/v1/senadores/despesas_ceaps/{ano}"
PROJETOS = ("PL ", "PLP ", "PEC ", "PLS ")
CRITERIOS = [
    ("presenca", "Presença nas votações", 1, True),
    ("leis", "Leis aprovadas que mudam regras", 1, True),
    ("simbolicos", "Poucos projetos simbólicos", 2, False),
    ("cota", "Economia na cota parlamentar", 1, False),
]


def _desempenho(s, conta):
    """Nota de desempenho dos senadores atuais, pelo mesmo método dos deputados: cada critério compara o senador
    com os colegas pela posição no grupo, e a nota é a média ponderada."""
    import alesp
    norm = camara._normalizar
    H = {"Accept": "application/json"}
    lista = s.get(URL_LISTA, headers=H, timeout=120).json()["ListaParlamentarEmExercicio"]["Parlamentares"]["Parlamentar"]
    gastos, meses = {}, set()
    hoje = time.localtime()
    for ano in range(2023, hoje.tm_year + 1):
        r = s.get(URL_CEAPS.format(ano=ano), timeout=300)
        for g in r.json() if r.status_code == 200 else []:
            if (g.get("ano"), g.get("mes")) >= (2023, 2):
                gastos[g["codSenador"]] = gastos.get(g["codSenador"], 0) + (g.get("valorReembolsado") or 0)
                meses.add((g["ano"], g["mes"]))
    base = {}
    for p in lista:
        ip = p["IdentificacaoParlamentar"]
        cod, nome = ip["CodigoParlamentar"], norm(ip["NomeParlamentar"])
        r = s.get(URL_PROCESSOS.format(cod=cod), headers=H, timeout=120)
        procs = r.json() if r.status_code == 200 else []
        projetos = [x for x in procs if (x.get("identificacao") or "").startswith(PROJETOS)]
        leis = [x for x in projetos if str(x.get("normaGerada") or "").startswith(("Lei", "Emenda Constitucional"))]
        simb = [x for x in projetos if alesp.simbolico(x.get("ementa") or "")]
        v = conta.get(nome) or {}
        base[nome] = {"presenca": v["votou"] / v["total"] if v.get("total", 0) >= 50 else None,
                      "leis": sum(1 for x in leis if not alesp.simbolico(x.get("ementa") or "")),
                      "simbolicos": len(simb) / len(projetos) if projetos else None,
                      "cota": gastos.get(int(cod)) / len(meses) if gastos.get(int(cod)) and meses else None,
                      "projetos": len(projetos)}
        time.sleep(0.3)
    ordenados = {k: sorted(d[k] for d in base.values() if d[k] is not None) for k, *_ in CRITERIOS}
    saida = {}
    for nome, d in base.items():
        notas, soma, pesos = {}, 0, 0
        for chave, _rot, peso, maior in CRITERIOS:
            v, lst = d[chave], ordenados[chave]
            if v is None or len(lst) < 5:
                continue
            pos = bisect.bisect_left(lst, v) / max(len(lst) - 1, 1)
            pos += (bisect.bisect_right(lst, v) - bisect.bisect_left(lst, v) - 1) / 2 / max(len(lst) - 1, 1)
            notas[chave] = pos if maior else 1 - pos
            soma += notas[chave] * peso
            pesos += peso
        if pesos:
            saida[nome] = {"nota": round(100 * soma / pesos), "criterios": notas,
                           "dados": {k: (round(v, 3) if isinstance(v, float) else v) for k, v in d.items()}}
    return saida


def desempenho(id_candidato):
    return ((_indice or {}).get("desempenho") or {}).get(str(id_candidato))


def criterios_rotulados(criterios):
    return [{"chave": k, "rotulo": rot, "peso": peso, "valor": criterios[k]} for k, rot, peso, _ in CRITERIOS if k in criterios]


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
        _estado["etapa"] = "lendo projetos e cota dos senadores"
        with requests.Session(impersonate="chrome") as s:
            desempenho = _desempenho(s, conta)
        dados = {"geradoEm": time.strftime("%d/%m/%Y"), "votacoes": len(votacoes),
                 "mediana": round(statistics.median(taxas), 3) if taxas else None,
                 "senadores": {candidatura[n]: dict(c, nome=n.title()) for n, c in conta.items() if n in candidatura},
                 "desempenho": {candidatura[n]: d for n, d in desempenho.items() if n in candidatura}}
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
    velho = not arq.exists() or time.time() - arq.stat().st_mtime > TTL or "desempenho" not in (_indice or {})
    if velho and not _rodando.is_set():
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
