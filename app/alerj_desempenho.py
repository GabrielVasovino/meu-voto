"""Desempenho dos deputados estaduais do Rio (ALERJ) na legislatura atual (desde fevereiro de 2023).

Mesmo método da ALESP (alesp.py): cada critério compara o deputado com os colegas da mesma Casa, pela posição no
grupo, e a nota é a média ponderada.
- Presença: faltas nas sessões, pelos relatórios mensais de presença da ALERJ (ordemdia.nsf);
- Leis aprovadas que mudam regras: leis de autoria ou coautoria do deputado (contlei.nsf), sem as simbólicas;
- Poucos projetos simbólicos: parte das leis dele que só dá nome, título ou data comemorativa (pesa em dobro).
Não há dado aberto de verba de gabinete da ALERJ por deputado, então esse critério fica de fora.

O sistema da ALERJ (Lotus Domino) é instável e não pagina; a coleta usa as buscas que devolvem tudo de uma vez. Tudo é
montado no computador pessoal e vai junto com o site em PACOTE. Para montar: python app/alerj_desempenho.py
"""
import bisect
import gzip
import json
import re
import threading
import time
from pathlib import Path

from curl_cffi import requests

import alesp
import camara

PACOTE = Path(__file__).resolve().parent / "dados_publicos" / "alerj_desempenho.json.gz"
BASE = "https://alerjln1.alerj.rj.gov.br/"
DESDE = "2023-02"
CRITERIOS = [
    ("presenca", "Presença nas sessões", 1, True),
    ("leis", "Leis aprovadas que mudam regras", 1, True),
    ("simbolicos", "Poucos projetos simbólicos", 2, False),
]

_dados = None
_lock = threading.Lock()
norm = camara._normalizar


def _carregar():
    global _dados
    if not PACOTE.exists():
        return False
    try:
        dados = json.loads(gzip.decompress(PACOTE.read_bytes()))
    except (OSError, ValueError):
        return False
    with _lock:
        _dados = dados
    return True


def iniciar():
    _carregar()


def status():
    return {"pronto": _dados is not None, "etapa": "pronto" if _dados is not None else "parado", "erro": None,
            "geradoEm": (_dados or {}).get("geradoEm")}


def do_candidato(id_candidato):
    """{"nota", "criterios", "dados"} do deputado que é esta candidatura, ou None."""
    return ((_dados or {}).get("candidatos") or {}).get(str(id_candidato))


def criterios_rotulados(criterios):
    return [{"chave": k, "rotulo": rot, "peso": peso, "valor": criterios[k]} for k, rot, peso, _ in CRITERIOS if k in criterios]


# ---------- montagem (só no computador pessoal) ----------

def _pedir(s, metodo, url, **kw):
    for tentativa in range(6):
        try:
            r = s.request(metodo, url, timeout=180, **kw)
            if r.status_code == 200:
                return r.content.decode("utf-8", "replace") if b"\xc3" in r.content[:200000] else r.content.decode("latin-1")
        except Exception:  # noqa: BLE001 - o Domino derruba conexões de vez em quando
            pass
        time.sleep(5 * (tentativa + 1))
    raise IOError(f"sem resposta de {url}")


def _celulas(html):
    for linha in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S):
        yield [" ".join(re.sub(r"<[^>]+>", " ", td).split()) for td in re.findall(r"<td[^>]*>(.*?)</td>", linha, re.S)]


def _presencas(s):
    """{deputado: {"faltas": n, "meses": n}} desde DESDE."""
    lista = _pedir(s, "GET", BASE + "ordemdia.nsf/85ef985c696ead9083256cf50081437a?SearchView&Query=deputado&SearchMax=0")
    docs = re.findall(r'href="([^"]+OpenDocument[^"]*)"[^>]*>\s*(?:<[^>]+>)*\s*(\d{2})/(\d{2})/(\d{4})', lista)
    conta = {}
    for href, mes, _dia, ano in docs:
        if f"{ano}-{mes}" < DESDE:
            continue
        html = _pedir(s, "GET", BASE + href.lstrip("/").replace("&amp;", "&"))
        vistos = set()
        for cel in _celulas(html):
            # Cada linha traz dois deputados, cada um seguido das faltas e dos dias em que faltou; as células vazias
            # variam, então vale a ordem: um nome e, depois dele, o primeiro número são as faltas.
            atual, faltas_lidas = None, False
            for c in (x.strip() for x in cel):
                if re.fullmatch(r"[A-ZÀ-Ý][A-ZÀ-Ý .'\-]{2,}", c) and c not in ("DEPUTADO", "FALTAS", "DIAS"):
                    atual, faltas_lidas = norm(c), False
                    if atual not in vistos:
                        vistos.add(atual)
                        e = conta.setdefault(atual, {"faltas": 0, "meses": 0, "nome": c.title()})
                        e["meses"] += 1
                elif atual and not faltas_lidas and re.fullmatch(r"\d{1,2}", c):
                    conta[atual]["faltas"] += int(c)
                    faltas_lidas = True
        time.sleep(1)
    return conta


def _leis(s, deputados):
    """{deputado: {"leis": n substantivas, "simbolicas": n, "total": n}} desde DESDE (ano >= 2023)."""
    conta = {}
    url = BASE + "contlei.nsf/35d3e73a008ab6db83257dc50046d255?CreateDocument"
    for nome in deputados:
        dados = {"Busca": "lei", "%%Surrogate_ConectorParlamentar": "1", "ConectorParlamentar": "And",
                 "ParlamentarBusca": nome, "%%Surrogate_ConectorProposicao": "1", "ConectorProposicao": "OR",
                 "ProposicaoBusca": "", "%%Surrogate_MaxResults": "1", "MaxResults": "0"}
        html = _pedir(s, "POST", url, data=dados)
        c = {"leis": 0, "simbolicas": 0, "total": 0}
        for cel in _celulas(html):
            cel = [x for x in cel if x]
            if len(cel) < 5 or not cel[1].isdigit() or int(cel[1]) < 2023:
                continue
            if norm(nome) not in {norm(a) for a in cel[-1].split(",")}:
                continue
            c["total"] += 1
            if alesp.simbolico(cel[3]):
                c["simbolicas"] += 1
            else:
                c["leis"] += 1
        conta[norm(nome)] = c
        time.sleep(1.5)
    return conta


def montar():
    import gabinetes
    import tse
    tse.configurar(Path.home() / ".meuvoto" / "cache-publico")
    with requests.Session(impersonate="chrome") as s:
        print("lendo as presenças…")
        pres = _presencas(s)
        print(f"  {len(pres)} deputados nos relatórios de presença")
        print("lendo as leis de cada deputado…")
        leis = _leis(s, [p["nome"] for p in pres.values()])
    todos = {}
    for n, p in pres.items():
        l = leis.get(n) or {"leis": 0, "simbolicas": 0, "total": 0}
        todos[n] = {"nome": p["nome"], "faltasPorMes": p["faltas"] / p["meses"] if p["meses"] else None, "meses": p["meses"],
                    "faltas": p["faltas"], **l}

    def valor(d, k):
        if k == "presenca":
            return -d["faltasPorMes"] if d["faltasPorMes"] is not None and d["meses"] >= 6 else None
        if k == "leis":
            return d["leis"]
        if k == "simbolicos":
            return d["simbolicas"] / d["total"] if d["total"] else None

    ordenados = {k: sorted(v for d in todos.values() if (v := valor(d, k)) is not None) for k, *_ in CRITERIOS}
    urna = gabinetes._por_urna(gabinetes._candidatos(), "RJ")
    candidatos = {}
    for n, d in todos.items():
        notas, soma, pesos = {}, 0, 0
        for chave, _rot, peso, maior in CRITERIOS:
            v, lista = valor(d, chave), ordenados[chave]
            if v is None or len(lista) < 5:
                continue
            pos = bisect.bisect_left(lista, v) / max(len(lista) - 1, 1)
            pos += (bisect.bisect_right(lista, v) - bisect.bisect_left(lista, v) - 1) / 2 / max(len(lista) - 1, 1)
            notas[chave] = pos if maior else 1 - pos
            soma += notas[chave] * peso
            pesos += peso
        sq = urna.get(n)
        if sq and pesos:
            candidatos[sq] = {"nota": round(100 * soma / pesos), "criterios": notas,
                              "dados": {k: d[k] for k in ("nome", "faltas", "meses", "leis", "simbolicas", "total")}}
    dados = {"geradoEm": time.strftime("%d/%m/%Y"), "desde": DESDE, "candidatos": candidatos}
    PACOTE.write_bytes(gzip.compress(json.dumps(dados, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), 9))
    print(f"{PACOTE.name}: {len(todos)} deputados avaliados, {len(candidatos)} disputam 2026")


if __name__ == "__main__":
    montar()
