"""Cassações e indeferimentos em eleições anteriores (TSE, 2014 a 2024) de quem disputa em 2026.

O TSE publica, para cada eleição, o motivo pelo qual uma candidatura foi cassada ou teve o registro negado. Muitos
motivos são burocráticos (documento faltando, partido que não registrou a lista) e não dizem nada sobre a pessoa;
esses ficam de fora. Os que importam:
- abuso de poder, compra de votos, gasto ilícito e conduta vedada: a Justiça Eleitoral julgou que a pessoa violou a
  lei eleitoral;
- Ficha Limpa (Lei Complementar 64/90): a pessoa estava inelegível naquela eleição;
- fraude à cota de gênero: a lista do partido foi cassada por candidaturas femininas de fachada; atinge todos da
  lista, culpados ou não, então só informa.

A pessoa é ligada entre as eleições pelo CPF; em 2024 o TSE passou a esconder o CPF, e aí vale o nome completo com a
data de nascimento. Tudo é montado no computador pessoal e vai junto com o site em PACOTE, sem CPF.

Para montar: python app/cassacoes.py
"""
import gzip
import json
import threading
import time
import unicodedata
from pathlib import Path

import empresas
import tse
import zipremoto

PACOTE = Path(__file__).resolve().parent / "dados_publicos" / "cassacoes.json.gz"
BASE = "https://cdn.tse.jus.br/estatistica/sead/odsele/"
ANOS = (2014, 2016, 2018, 2020, 2022, 2024)

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
    return ((_dados or {}).get("candidatos") or {}).get(str(id_candidato))


def tipo_motivo(motivo):
    m = unicodedata.normalize("NFKD", motivo or "").encode("ascii", "ignore").decode().lower()
    if any(x in m for x in ("abuso", "compra de voto", "captacao", "gasto ilicito", "conduta vedada", "arrecadacao ilicita")):
        return "grave"
    if "ficha limpa" in m or "inelegib" in m:
        return "ficha"
    if "cota de genero" in m:
        return "cota"
    return None


# ---------- montagem (só no computador pessoal) ----------

def montar():
    nome = empresas._nome
    por_cpf, por_nome = {}, {}
    for r in zipremoto.linhas_csv(empresas.URL_CAND_2026, "consulta_cand_2026_BRASIL.csv"):
        if len(r["NR_CPF_CANDIDATO"]) == 11:
            por_cpf[r["NR_CPF_CANDIDATO"]] = r["SQ_CANDIDATO"]
        por_nome.setdefault(f"{nome(r['NM_CANDIDATO'])}|{r['DT_NASCIMENTO']}", set()).add(r["SQ_CANDIDATO"])
    candidatos = {}
    for ano in ANOS:
        motivos = {}
        for r in zipremoto.linhas_csv(f"{BASE}motivo_cassacao/motivo_cassacao_{ano}.zip", f"motivo_cassacao_{ano}_BRASIL.csv"):
            m = r.get("DS_MOTIVO") or r.get("DS_MOTIVO_CASSACAO") or ""
            if tipo_motivo(m):
                motivos.setdefault(r["SQ_CANDIDATO"], set()).add(m.strip())
        achados = 0
        for r in zipremoto.linhas_csv(f"{BASE}consulta_cand/consulta_cand_{ano}.zip", f"consulta_cand_{ano}_BRASIL.csv"):
            ms = motivos.get(r["SQ_CANDIDATO"])
            if not ms:
                continue
            cpf = r.get("NR_CPF_CANDIDATO") or ""
            sqs = {por_cpf[cpf]} if len(cpf) == 11 and cpf in por_cpf else \
                por_nome.get(f"{nome(r['NM_CANDIDATO'])}|{r.get('DT_NASCIMENTO')}", set())
            if len(sqs) != 1:
                continue
            achados += 1
            candidatos.setdefault(next(iter(sqs)), []).append({
                "ano": ano, "cargo": (r.get("DS_CARGO") or "").title(), "local": (r.get("NM_UE") or "").title(),
                "uf": r.get("SG_UF"), "motivos": sorted(ms), "situacao": (r.get("DS_SITUACAO_CANDIDATURA") or "").lower(),
                "resultado": (r.get("DS_SIT_TOT_TURNO") or "").lower()})
        print(f"  {ano}: {len(motivos)} candidaturas com motivo relevante, {achados} de quem disputa em 2026")
    dados = {"geradoEm": time.strftime("%d/%m/%Y"), "candidatos": candidatos}
    PACOTE.parent.mkdir(parents=True, exist_ok=True)
    PACOTE.write_bytes(gzip.compress(json.dumps(dados, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), 9))
    print(f"{PACOTE.name}: {len(candidatos)} candidatos de 2026")


if __name__ == "__main__":
    tse.configurar(Path.home() / ".meuvoto" / "cache-publico")
    montar()
