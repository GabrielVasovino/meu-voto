"""Histórico de quem trabalhou em cada gabinete da ALERJ, tirado do Diário Oficial do RJ (Parte II, Poder Legislativo).

A ALERJ só publica a lista atual de assessores. O histórico está nos atos da Mesa Diretora publicados no Diário
Oficial desde julho de 2005 ("NOMEAR Fulano, matrícula nº ..., para exercer o cargo em comissão ... junto ao Gabinete
do Deputado X"; "EXONERAR Fulano, matrícula nº ..., ... que vinha exercendo junto ao Gabinete do Deputado X").
A matrícula liga a nomeação à exoneração da mesma pessoa.

Caminho no site da Imprensa Oficial (IOERJ), sem cadastro: calendário (do_seleciona_data.php) -> cadernos do dia
(do_seleciona_edicao.php) -> "Parte II (Poder Legislativo)" (mostra_edicao.php?session=, identificador em base64
três vezes) -> PDF (mostra_edicao.php?k=, com um "P" inserido na posição 12 do identificador). O texto do PDF é nativo;
o PDF é apagado depois de extraído. Roda no computador pessoal, uma edição por vez, com pausa, e retoma de onde parou.

Para rodar: python app/alerj_historico.py            (coleta; várias horas)
            python app/alerj_historico.py --datas 20120315 20080610   (teste com alguns dias)
"""
import base64
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from curl_cffi import requests

BASE = "https://www.ioerj.com.br/portal/modules/conteudoonline/"
PASTA = Path.home() / ".meuvoto" / "cache" / "alerj_historico"
EVENTOS = PASTA / "eventos.jsonl"
FEITOS = PASTA / "dias_feitos.txt"
PAUSA = 1.5

ATO = re.compile(r"(NOMEAR|EXONERAR)\s*,?\s*(?:a pedido,\s*)?([A-ZÀ-Ý][A-ZÀ-Ý\s'.]+?),\s*matr[íi]cula\s*n?\s*[º°o]?\s*"
                 r"([\d.\-\s]{5,14}?)\s*,(.{0,500}?)(?=Rio de Janeiro,|NOMEAR|EXONERAR|ATO\s|$)")
GABINETE = re.compile(r"Gabinete\s+d[oa]\s+Deputad[oa]\s+(.+?)(?=,|\.|;|\s+na\s+vaga|\s+que\s|\s+a\s+contar|$)")
CARGO = re.compile(r"cargo em comissão de\s+(.+?)(?:,|\s+símbolo)")


def _b64(x, vezes):
    for _ in range(vezes):
        x = base64.b64decode(x + "=" * (-len(x) % 4)).decode()
    return x


def _pedir(s, url, **kw):
    for tentativa in range(5):
        try:
            r = s.get(url, timeout=180, **kw)
            if r.status_code == 200:
                return r
        except Exception:  # noqa: BLE001 - o servidor às vezes derruba a conexão; a próxima tentativa funciona
            pass
        time.sleep(5 * (tentativa + 1))
    return None


def dias(s):
    r = _pedir(s, BASE + "do_seleciona_data.php")
    return sorted({_b64(d, 1) for d in re.findall(r"do_seleciona_edicao\.php\?data=([A-Za-z0-9=]+)", r.text)})


def pdf_legislativo(s, dia):
    r = _pedir(s, BASE + "do_seleciona_edicao.php?data=" + base64.b64encode(dia.encode()).decode())
    if not r:
        return None
    for href, nome in re.findall(r'<a[^>]*href=["\'](mostra_edicao\.php\?session=[^"\']+)["\'][^>]*>(.*?)</a>', r.text, re.S):
        if "Legislativo" in re.sub("<[^>]+>", "", nome):
            ident = _b64(href.split("session=")[1], 3)[:36]
            p = _pedir(s, BASE + "mostra_edicao.php?k=" + ident[:12] + "P" + ident[12:], headers={"Referer": BASE})
            if p and p.content[:4] == b"%PDF":
                return p.content
    return None


def texto(pdf):
    """pdftotext lê as colunas na ordem certa; sem ele, pdfplumber."""
    with tempfile.TemporaryDirectory() as tmp:
        arq = Path(tmp) / "e.pdf"
        arq.write_bytes(pdf)
        if shutil.which("pdftotext"):
            subprocess.run(["pdftotext", "-enc", "UTF-8", str(arq), str(arq.with_suffix(".txt"))], check=True)
            t = arq.with_suffix(".txt").read_text(encoding="utf-8", errors="replace")
        else:
            import pdfplumber
            with pdfplumber.open(arq) as p:
                t = "\n".join(pg.extract_text() or "" for pg in p.pages)
    t = re.sub(r"-\n(?=[a-zà-ú])", "", t)
    return re.sub(r"\s+", " ", t)


def atos(t, dia):
    for acao, nome, matricula, resto in ATO.findall(t):
        g = GABINETE.search(resto)
        if not g:
            continue  # comissões, lideranças e setores administrativos não são gabinete de deputado
        c = CARGO.search(resto)
        yield {"dia": dia, "acao": acao.lower(), "nome": " ".join(nome.split()), "matricula": re.sub(r"\D", "", matricula),
               "deputado": " ".join(g.group(1).split())[:60], "cargo": c.group(1).strip() if c else None}


def coletar(somente=None):
    PASTA.mkdir(parents=True, exist_ok=True)
    feitos = set(FEITOS.read_text().split()) if FEITOS.exists() else set()
    with requests.Session(impersonate="chrome") as s:
        todos = somente or [d for d in dias(s) if d not in feitos]
        print(f"{len(todos)} dias para ler ({len(feitos)} já lidos)")
        for i, dia in enumerate(todos, 1):
            pdf = pdf_legislativo(s, dia)
            n = 0
            if pdf:
                with open(EVENTOS, "a", encoding="utf-8") as f:
                    for a in atos(texto(pdf), dia):
                        f.write(json.dumps(a, ensure_ascii=False) + "\n")
                        n += 1
            if not somente:
                with open(FEITOS, "a") as f:
                    f.write(dia + "\n")
            if somente or i % 50 == 0:
                print(f"  {dia}: {'sem Parte II' if pdf is None else f'{n} atos de gabinete'} ({i} de {len(todos)})")
            time.sleep(PAUSA)


# ---------- pacote para o site ----------

PACOTE = Path(__file__).resolve().parent / "dados_publicos" / "alerj_historico.json.gz"


def empacotar():
    """Deputado -> pessoas que passaram pelo gabinete (nome, primeiro e último ato), ligado à candidatura de 2026."""
    import gzip
    import gabinetes
    import tse
    tse.configurar(Path.home() / ".meuvoto" / "cache-publico")
    urna = gabinetes._por_urna(gabinetes._candidatos(), "RJ")
    por = {}
    for linha in open(EVENTOS, encoding="utf-8"):
        e = json.loads(linha)
        sq = urna.get(gabinetes.norm(e["deputado"]))
        if not sq:
            continue
        g = por.setdefault(sq, {"politico": e["deputado"], "assessores": {}})
        a = g["assessores"].setdefault(e["matricula"] or e["nome"], {"nome": e["nome"].title(), "desde": e["dia"][:4], "ate": e["dia"][:4]})
        a["desde"], a["ate"] = min(a["desde"], e["dia"][:4]), max(a["ate"], e["dia"][:4])
    dados = {"geradoEm": time.strftime("%d/%m/%Y"), "gabinetes": {sq: {"politico": g["politico"], "assessores": list(g["assessores"].values())}
                                                                 for sq, g in por.items()}}
    PACOTE.write_bytes(gzip.compress(json.dumps(dados, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), 9))
    print(f"{PACOTE.name}: {len(por)} deputados e ex-deputados que disputam 2026, "
          f"{sum(len(g['assessores']) for g in por.values())} pessoas")


if __name__ == "__main__":
    if "--empacotar" in sys.argv:
        empacotar()
    elif "--datas" in sys.argv:
        coletar(sys.argv[sys.argv.index("--datas") + 1:])
    else:
        coletar()
