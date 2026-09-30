"""Contratos do governo federal com empresas de candidatos (Portal da Transparência, arquivos mensais de compras).

Vender para o governo não é irregular, mas quem vai ter mandato e é sócio de empresa que depende de contrato público
tem conflito de interesse que vale conhecer. Por isso é só informação, sem tirar pontos. Só contratos federais:
estados e municípios não publicam num arquivo único.

Os arquivos mensais são pequenos, mas são dezenas; tudo é montado no computador pessoal e vai junto com o site em
PACOTE. Para montar: python app/contratos.py
"""
import csv
import gzip
import io
import json
import sys
import threading
import time
import zipfile
from pathlib import Path

from curl_cffi import requests

import empresas
import tse

PACOTE = Path(__file__).resolve().parent / "dados_publicos" / "contratos_federais.json.gz"
URL = "https://portaldatransparencia.gov.br/download-de-dados/compras/{mes}"
DESDE = (2023, 1)

_dados = None
_lock = threading.Lock()


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


def da_empresa(basico):
    return ((_dados or {}).get("empresas") or {}).get(basico)


def periodo():
    return (_dados or {}).get("periodo")


def _valor(txt):
    try:
        return float((txt or "0").replace(".", "").replace(",", ".")) if "," in (txt or "") else float(txt or 0)
    except ValueError:
        return 0.0


def montar():
    empresas._carregar()
    basicos = {e["basico"] for lista in (empresas._indice or {}).get("candidatos", {}).values() for e in lista}
    print(f"{len(basicos)} empresas de candidatos")
    achados, meses = {}, []
    hoje = time.localtime()
    ano, mes = DESDE
    with requests.Session(impersonate="chrome") as s:
        while (ano, mes) <= (hoje.tm_year, hoje.tm_mon):
            ref = f"{ano}{mes:02d}"
            for tentativa in range(4):  # o portal às vezes recusa (405/403) pedidos seguidos: espera e tenta de novo
                r = s.get(URL.format(mes=ref), timeout=300)
                if r.status_code == 200 or r.status_code == 404:
                    break
                time.sleep(20 * (tentativa + 1))
            if r.status_code == 200 and r.content[:2] == b"PK":
                z = zipfile.ZipFile(io.BytesIO(r.content))
                nome = next((n for n in z.namelist() if n.endswith("_Compras.csv")), None)
                if nome:
                    meses.append(ref)
                    for l in csv.DictReader(io.TextIOWrapper(z.open(nome), encoding="latin-1"), delimiter=";"):
                        doc = "".join(c for c in l.get("Código Contratado", "") if c.isdigit())
                        if len(doc) == 14 and doc[:8] in basicos:
                            e = achados.setdefault(doc[:8], {"total": 0.0, "contratos": []})
                            v = _valor(l.get("Valor Final Compra") or l.get("Valor Inicial Compra"))
                            e["total"] += v
                            e["contratos"].append({"orgao": (l.get("Nome Órgão") or "").strip(), "objeto": (l.get("Objeto") or "")[:200],
                                                   "valor": round(v), "assinatura": l.get("Data Assinatura Contrato")})
            print(f"  {ref}: {r.status_code}, {len(achados)} empresas até aqui")
            mes += 1
            if mes > 12:
                ano, mes = ano + 1, 1
            time.sleep(3)
    for e in achados.values():
        e["total"] = round(e["total"])
        e["contratos"].sort(key=lambda c: -c["valor"])
        e["quantos"] = len(e["contratos"])
        e["contratos"] = e["contratos"][:5]
    dados = {"geradoEm": time.strftime("%d/%m/%Y"), "periodo": f"{meses[0][4:]}/{meses[0][:4]} a {meses[-1][4:]}/{meses[-1][:4]}" if meses else None,
             "empresas": achados}
    PACOTE.parent.mkdir(parents=True, exist_ok=True)
    PACOTE.write_bytes(gzip.compress(json.dumps(dados, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), 9))
    print(f"{PACOTE.name}: {len(achados)} empresas de candidatos com contrato federal ({dados['periodo']})")


if __name__ == "__main__":
    tse.configurar(Path.home() / ".meuvoto" / "cache-publico")
    montar()
