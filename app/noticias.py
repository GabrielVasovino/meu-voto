"""Notícias recentes sobre um candidato, pelo RSS público de busca do Google Notícias.

Guarda só título, veículo, data e link (nunca o texto das matérias). A busca usa o nome de urna entre aspas junto
com o cargo ou o partido, para não misturar homônimos, e filtra os títulos que citam o nome. Das manchetes saem os
assuntos mais frequentes e a marcação das que falam de investigação ou processo. Notícia não é prova: isso aparece
na ficha como contexto e não entra na nota.
"""
import hashlib
import html
import json
import re
import threading
import time
import unicodedata
from collections import Counter
from email.utils import parsedate_to_datetime
from urllib.parse import urlencode

from curl_cffi import requests

import tse

URL = "https://news.google.com/rss/search"
TTL = 12 * tse.HORA
JANELA = "180d"
INTERVALO = 2.0  # segundos entre buscas, para não sobrecarregar o serviço

CARGO_BUSCA = {1: "presidente OR presidência", 3: "governador OR governadora OR governo", 5: "senador OR senadora OR Senado",
               6: "deputado OR deputada OR Câmara", 7: "deputado OR deputada OR Assembleia", 8: "deputado OR deputada OR distrital"}

# Termos que indicam investigação, processo ou punição nas manchetes (em forma normalizada, sem acento).
RISCO = ["investig", "operacao", "policia federal", " pf ", "denuncia", "denunciad", "preso", "prisao", "condena",
         "improbidade", "corrupc", "lavagem", "desvio", "fraude", "cassa", "inelegiv", "ministerio publico", " mp ",
         "busca e apreensao", "reu ", "propina", "peculato", "rachadinha", "indiciad", "acusad", "inquerito"]
PARADAS = set("""a o e é de da do das dos em no na nos nas um uma uns umas para por com sem sobre ao aos à às que se
seu sua seus suas mais menos como diz dizem após ate até entre contra pelo pela pelos pelas já ja não nao sim ser
foi são sao tem têm vai vão está esta estão estao isso este esta essa esse eu ele ela eles elas quem qual onde
quando porque pois nova novo novas novos 2026 ano anos dia dias hoje ontem veja leia vídeo video ao vivo g1 uol
folha estadão cnn globo diz afirma candidato candidata candidatos eleição eleições eleicao eleicoes governo""".split())

# Páginas-perfil de candidatura (agregadores e guias de eleição) não são notícia.
PERFIL = re.compile(r"candidat[oa]s? a (deputad|senad|govern|presiden|vice)|elei[cç][oõ]es 2026$|\| elei[cç][oõ]es|"
                    r"— (dep\.|deputad|senad|govern|presiden)|^\W*$")

_lock = threading.Lock()
_ultimo = [0.0]


def _pasta():
    p = tse._cache_dir / "noticias"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _norm(s):
    s = unicodedata.normalize("NFD", (s or "").lower())
    return "".join(c for c in s if not unicodedata.combining(c))


def _buscar(consulta):
    with _lock:  # uma busca por vez, com intervalo
        espera = INTERVALO - (time.time() - _ultimo[0])
        if espera > 0:
            time.sleep(espera)
        _ultimo[0] = time.time()
    r = requests.get(URL + "?" + urlencode({"q": consulta, "hl": "pt-BR", "gl": "BR", "ceid": "BR:pt-419"}),
                     impersonate="chrome", timeout=30)
    r.raise_for_status()
    itens = []
    for bloco in re.findall(r"<item>(.*?)</item>", r.text, re.S):
        def campo(nome):
            m = re.search(rf"<{nome}[^>]*>(.*?)</{nome}>", bloco, re.S)
            return html.unescape(m.group(1)).strip() if m else ""
        fonte = re.search(r'<source url="([^"]*)">(.*?)</source>', bloco, re.S)
        titulo = campo("title")
        veiculo = html.unescape(fonte.group(2)).strip() if fonte else ""
        if veiculo and titulo.endswith(" - " + veiculo):
            titulo = titulo[: -len(veiculo) - 3]
        try:
            data = parsedate_to_datetime(campo("pubDate")).date().isoformat()
        except (TypeError, ValueError):
            data = None
        itens.append({"titulo": titulo, "link": campo("link"), "veiculo": veiculo,
                      "site": fonte.group(1) if fonte else "", "data": data})
    return itens


def _assuntos(titulos, nome):
    ignorar = {_norm(p) for p in PARADAS} | {_norm(p) for p in re.findall(r"\w+", nome)}
    cont = Counter()
    for t in titulos:
        vistas = set()
        for p in re.findall(r"[\wÀ-ÿ]+", t):
            n = _norm(p)
            if len(n) < 4 or n in ignorar or n.isdigit() or n in vistas:
                continue
            vistas.add(n)
            cont[p.lower() if not p.isupper() else p] += 1
    return [{"termo": k, "vezes": v} for k, v in cont.most_common(10) if v >= 2]


def do_candidato(nome_urna, partido, cargo):
    """Notícias dos últimos 6 meses. Devolve {"noticias": [...], "assuntos": [...], "comRisco": n, ...}."""
    nome = " ".join((nome_urna or "").split())
    if not nome:
        return {"noticias": [], "assuntos": [], "comRisco": 0}
    extra = CARGO_BUSCA.get(int(cargo), "")
    if partido:
        extra = f"{extra} OR {partido}" if extra else partido
    consulta = f'"{nome}" ({extra}) when:{JANELA}' if extra else f'"{nome}" when:{JANELA}'
    arq = _pasta() / (hashlib.sha1(consulta.encode()).hexdigest()[:16] + ".json")
    if arq.exists() and time.time() - arq.stat().st_mtime < TTL:
        return json.loads(arq.read_text(encoding="utf-8"))
    itens = _buscar(consulta)
    alvo = _norm(nome)
    vistos, noticias = set(), []
    for i in itens:
        t = _norm(i["titulo"])
        chave = re.sub(r"\W+", " ", t)[:80]
        # Só manchetes que citam o nome e dizem algo além dele, sem repetir a mesma matéria.
        if alvo not in t or chave in vistos or PERFIL.search(t) or len(t.replace(alvo, "").split()) < 3:
            continue
        vistos.add(chave)
        i["risco"] = any(r in f" {t} " for r in RISCO)
        noticias.append(i)
    noticias.sort(key=lambda i: i["data"] or "", reverse=True)
    saida = {"consulta": consulta, "geradoEm": time.strftime("%d/%m/%Y %H:%M"), "noticias": noticias[:40],
             "assuntos": _assuntos([i["titulo"] for i in noticias], nome), "comRisco": sum(i["risco"] for i in noticias),
             "total": len(noticias)}
    arq.write_text(json.dumps(saida, ensure_ascii=False), encoding="utf-8")
    return saida
