"""Dívida ativa com a União (PGFN): impostos, contribuições previdenciárias e FGTS que viraram dívida cobrada pela
Procuradoria-Geral da Fazenda Nacional, do próprio candidato e das empresas em que ele é sócio.

A PGFN publica tudo a cada trimestre, por devedor (dados abertos, sem cadastro). O CNPJ vem completo; o CPF vem com
parte escondida (***123456**), então a pessoa é ligada ao candidato pelos 6 dígitos do meio e pelo nome completo,
como no cruzamento de sócios da Receita. Os arquivos somam mais de 1 GB, então tudo é montado no computador pessoal e
vai junto com o site em PACOTE, sem CPF.

Situações: "Em cobrança" é a dívida que está sendo cobrada; "negociada" (parcelamento ou transação), "garantia" e
"suspensa por decisão judicial" não estão sendo cobradas agora, e o site mostra, mas não tira pontos por elas.

Para montar: python app/pgfn.py [AAAA_trimestre_NN]
"""
import gzip
import json
import sys
import threading
import time
from pathlib import Path

import empresas
import tse
import zipremoto

PACOTE = Path(__file__).resolve().parent / "dados_publicos" / "divida_ativa.json.gz"
URL = "https://dadosabertos.pgfn.gov.br/{trimestre}/Dados_abertos_{tipo}.zip"
TIPOS = {"Nao_Previdenciario": "tributos", "Previdenciario": "previdência", "FGTS": "FGTS"}

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


def do_candidato(id_candidato):
    """{"proprio": {...} ou None, "empresas": [{...}]} ou None."""
    return ((_dados or {}).get("candidatos") or {}).get(str(id_candidato))


def referencia():
    return (_dados or {}).get("referencia")


# ---------- montagem (só no computador pessoal) ----------

def _situacao(tipo_situacao):
    t = (tipo_situacao or "").lower()
    if "cobran" in t:
        return "cobranca"
    if "negoci" in t or "parcel" in t or "benef" in t:
        return "negociada"
    if "garant" in t:
        return "garantia"
    if "suspens" in t or "judicial" in t:
        return "suspensa"
    return "outra"


def _somar(destino, r, tipo):
    v = float(r.get("VALOR_CONSOLIDADO") or 0)
    s = _situacao(r.get("TIPO_SITUACAO_INSCRICAO"))
    destino["total"] = destino.get("total", 0) + v
    por_situacao = destino.setdefault("porSituacao", {})
    por_situacao[s] = por_situacao.get(s, 0) + v
    por_tipo = destino.setdefault("porTipo", {})
    por_tipo[tipo] = por_tipo.get(tipo, 0) + v
    destino["inscricoes"] = destino.get("inscricoes", 0) + 1
    if (r.get("INDICADOR_AJUIZADO") or "").upper().startswith("S"):
        destino["ajuizadas"] = destino.get("ajuizadas", 0) + 1


def montar(trimestre):
    print("lendo candidatos e empresas…")
    chaves = empresas._candidatos()  # "meio|NOME" -> {sq}
    empresas._carregar()
    donos = {}  # cnpj básico -> {(sq, razao)}
    for sq, lista in (empresas._indice or {}).get("candidatos", {}).items():
        for e in lista:
            donos.setdefault(e["basico"], set()).add((sq, e.get("razao") or ""))
    print(f"{len(chaves)} candidatos, {len(donos)} empresas de candidatos")
    proprio, das_empresas = {}, {}
    for tipo, rotulo in TIPOS.items():
        url = URL.format(trimestre=trimestre, tipo=tipo)
        for nome in [n for n in zipremoto.listar(url) if n.lower().endswith(".csv")]:
            for r in zipremoto.linhas_csv(url, nome):
                doc = empresas._digitos(r.get("CPF_CNPJ"))
                if len(doc) == 14:
                    for sq, razao in donos.get(doc[:8], ()):
                        e = das_empresas.setdefault(sq, {}).setdefault(doc[:8], {"nome": razao or r.get("NOME_DEVEDOR")})
                        _somar(e, r, rotulo)
                elif len(doc) == 6:  # CPF mascarado: sobram os 6 dígitos do meio
                    for sq in chaves.get(f"{doc}|{empresas._nome(r.get('NOME_DEVEDOR'))}", ()):
                        _somar(proprio.setdefault(sq, {}), r, rotulo)
            print(f"  {rotulo}: {nome} lido")
    candidatos = {}
    for sq in set(proprio) | set(das_empresas):
        candidatos[sq] = {
            "proprio": {k: (round(v) if isinstance(v, float) else v) for k, v in proprio[sq].items()} if sq in proprio else None,
            "empresas": sorted(({"basico": b, **e} for b, e in das_empresas.get(sq, {}).items()), key=lambda x: -x["total"]),
        }
        for e in candidatos[sq]["empresas"]:
            e["total"] = round(e["total"])
            e["porSituacao"] = {k: round(v) for k, v in e["porSituacao"].items()}
            e["porTipo"] = {k: round(v) for k, v in e["porTipo"].items()}
        if candidatos[sq]["proprio"]:
            p = candidatos[sq]["proprio"]
            p["porSituacao"] = {k: round(v) for k, v in p["porSituacao"].items()}
            p["porTipo"] = {k: round(v) for k, v in p["porTipo"].items()}
    ano, tri = trimestre.split("_trimestre_")
    dados = {"geradoEm": time.strftime("%d/%m/%Y"), "referencia": f"{int(tri)}º trimestre de {ano}", "candidatos": candidatos}
    PACOTE.parent.mkdir(parents=True, exist_ok=True)
    PACOTE.write_bytes(gzip.compress(json.dumps(dados, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), 9))
    print(f"{PACOTE.name}: {len(candidatos)} candidatos com dívida ativa própria ou de empresa")


if __name__ == "__main__":
    tse.configurar(Path.home() / ".meuvoto" / "cache-publico")
    montar(sys.argv[1] if len(sys.argv) > 1 else "2026_trimestre_02")
