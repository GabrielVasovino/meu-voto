"""Cadastros de punidos do governo federal (CEIS, CNEP, CEAF e CEPIM) e acordos de leniência, pelos arquivos abertos
da CGU.

Os arquivos são baixados do Portal da Transparência sem chave, uma vez por dia, e resumidos num índice
por CPF/CNPJ. Assim a checagem funciona para qualquer pessoa, sem a chave pessoal da API.
No CEAF (expulsos do serviço público) o CPF vem mascarado (***.123.456-**): ali o casamento usa os
6 dígitos do meio junto com o nome completo.
"""
import csv
import io
import json
import sys
import threading
import time
import traceback
import unicodedata
import zipfile
from datetime import date, timedelta

from curl_cffi import requests

import tse

URL = "https://portaldatransparencia.gov.br/download-de-dados/{base}/{dia}"
TTL = 24 * tse.HORA
BASES = {
    "ceis": "Cadastro de empresas e pessoas proibidas de contratar com o governo (CEIS)",
    "cnep": "Cadastro de punidos pela Lei Anticorrupção (CNEP)",
    "ceaf": "Cadastro de expulsos do serviço público federal (CEAF)",
    "cepim": "Cadastro de entidades sem fins lucrativos impedidas de receber verba federal (CEPIM)",
    "acordos-leniencia": "Acordos de leniência: empresas que admitiram atos lesivos contra a administração pública",
}
SIGLAS = {"acordos-leniencia": "Leniência"}

_indice = None
_lock = threading.Lock()
_rodando = threading.Event()
_estado = {"etapa": "parado", "erro": None}


def registrar_falha(e):
    """Deixa no log do servidor em que etapa a base falhou, com o erro completo."""
    print(f"[{__name__}] falhou em \"{_estado.get('etapa')}\": {e}", file=sys.stderr)
    traceback.print_exc()


def _pasta():
    p = tse._cache_dir / "sancoes"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _arquivo():
    return _pasta() / "indice.json"


def _digitos(s):
    return "".join(c for c in str(s or "") if c.isdigit())


def _nome(s):
    s = unicodedata.normalize("NFD", str(s or "").upper())
    return " ".join("".join(c for c in s if not unicodedata.combining(c)).split())


def _baixar(base):
    """Arquivo mais recente publicado (a CGU publica com uns dois dias de atraso)."""
    with requests.Session(impersonate="chrome") as s:
        for dias in range(0, 8):
            dia = (date.today() - timedelta(days=dias)).strftime("%Y%m%d")
            r = s.get(URL.format(base=base, dia=dia), timeout=180)
            if r.status_code == 200 and r.content[:2] == b"PK":
                z = zipfile.ZipFile(io.BytesIO(r.content))
                return dia, z.read(z.namelist()[0]).decode("latin-1")
    raise RuntimeError(f"Arquivo do {base.upper()} não encontrado nos últimos 8 dias")


def _doc(base, linha):
    if base == "cepim":
        return linha.get("CNPJ ENTIDADE") or ""
    if base == "acordos-leniencia":
        return linha.get("CNPJ DO SANCIONADO") or ""
    return linha.get("CPF OU CNPJ DO SANCIONADO") or ""


def _registro(base, linha):
    if base == "cepim":
        return {"cadastro": BASES[base], "sigla": "CEPIM", "nome": linha.get("NOME ENTIDADE") or "",
                "sancao": f"Impedida de receber verba federal: {(linha.get('MOTIVO DO IMPEDIMENTO') or '').lower()}",
                "orgao": linha.get("ÓRGÃO CONCEDENTE") or "", "inicio": "", "fim": ""}
    if base == "acordos-leniencia":
        razao = next((v for k, v in linha.items() if k.startswith("RAZÃO SOCIAL")), "")
        return {"cadastro": BASES[base], "sigla": SIGLAS[base], "nome": razao or "",
                "sancao": f"Acordo de leniência ({(linha.get('SITUAÇÃO DO ACORDO DE LENIÊNICA') or '').lower()})",
                "orgao": linha.get("ÓRGÃO SANCIONADOR") or "", "inicio": linha.get("DATA DE INÍCIO DO ACORDO") or "",
                "fim": linha.get("DATA DE FIM DO ACORDO") or ""}
    return {
        "cadastro": BASES[base],
        "sigla": base.upper(),
        "nome": linha.get("NOME DO SANCIONADO") or "",
        "sancao": linha.get("CATEGORIA DA SANÇÃO") or "",
        "orgao": linha.get("ÓRGÃO SANCIONADOR") or "",
        "inicio": linha.get("DATA INÍCIO SANÇÃO") or "",
        "fim": linha.get("DATA FINAL SANÇÃO") or "",
    }


def _preparar():
    try:
        _estado.update(etapa="baixando", erro=None)
        docs, mascarados, datas = {}, {}, {}
        for base in BASES:
            time.sleep(3)  # o portal recusa downloads em sequência rápida
            dia, texto = _baixar(base)
            datas[base] = dia
            vistos = set()
            for linha in csv.DictReader(io.StringIO(texto), delimiter=";"):
                doc = _doc(base, linha)
                chave_repetida = (linha.get("CÓDIGO DA SANÇÃO") or linha.get("ID DO ACORDO") or linha.get("NÚMERO CONVÊNIO"), doc)
                if chave_repetida in vistos:  # o CEAF repete a mesma sanção em várias linhas
                    continue
                vistos.add(chave_repetida)
                reg = _registro(base, linha)
                if "*" in doc:
                    meio = _digitos(doc)
                    if len(meio) == 6:
                        mascarados.setdefault(f"{meio}|{_nome(reg['nome'])}", []).append(reg)
                elif _digitos(doc):
                    docs.setdefault(_digitos(doc), []).append(reg)
        indice = {"geradoEm": time.strftime("%d/%m/%Y"), "arquivos": datas, "docs": docs, "mascarados": mascarados}
        tmp = _arquivo().with_suffix(".tmp")
        tmp.write_text(json.dumps(indice, ensure_ascii=False), encoding="utf-8")
        tmp.replace(_arquivo())
        _carregar()
        _estado["etapa"] = "pronto"
    except Exception as e:  # sem internet ou Portal fora do ar: segue com o índice anterior, se houver
        registrar_falha(e)
        _estado.update(etapa="erro", erro=f"{_estado.get('etapa')}: {e}")
    finally:
        _rodando.clear()


def _carregar():
    global _indice
    if not _arquivo().exists():
        return False
    try:
        dados = json.loads(_arquivo().read_text(encoding="utf-8"))
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


def pronto():
    return _indice is not None


def status():
    return {"pronto": pronto(), "etapa": _estado["etapa"], "erro": _estado["erro"],
            "geradoEm": (_indice or {}).get("geradoEm")}


def pessoa(cpf, nome):
    """Sanções de uma pessoa física: CEIS e CNEP pelo CPF; CEAF pelos dígitos do meio e o nome."""
    if not _indice:
        return None
    cpf = _digitos(cpf)
    achados = list(_indice["docs"].get(cpf, [])) if len(cpf) == 11 else []
    if len(cpf) == 11 and nome:
        achados += _indice["mascarados"].get(f"{cpf[3:9]}|{_nome(nome)}", [])
    return achados


def empresa(cnpj):
    """Sanções de uma empresa (CEIS e CNEP)."""
    if not _indice:
        return None
    return list(_indice["docs"].get(_digitos(cnpj), []))


def empresa_raiz(basico):
    """Sanções de qualquer estabelecimento (matriz ou filial) de uma empresa, pelos 8 primeiros dígitos do CNPJ."""
    if not _indice:
        return []
    return [r for doc, regs in _indice["docs"].items() if len(doc) == 14 and doc.startswith(basico) for r in regs]
