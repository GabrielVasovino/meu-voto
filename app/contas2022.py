"""A campanha de 2022 de quem disputa de novo em 2026: os mesmos cruzamentos de dinheiro, olhando para trás.

As contas de 2022 já estão fechadas e não mudam, então tudo é calculado uma vez no computador pessoal e vai junto com
o site em PACOTE (sem CPF, só com o número da candidatura de 2026). A pessoa é ligada entre as duas eleições pelo
CPF completo que o TSE publica nas duas.

O que se procura em 2022:
- doador que deu R$ 5 mil ou mais e recebeu da campanha mais do que doou;
- campanha que pagou empresa do próprio candidato (sócios pela Receita Federal);
- assessor do gabinete (Senado, Câmara ou ALESP) que doou para a campanha.

Para montar: python app/contas2022.py   (depois de o índice dos gabinetes existir no cache)
"""
import gzip
import json
import sys
import threading
import time
from pathlib import Path

import camara
import empresas
import gabinetes
import gastos
import tse
import zipremoto

PACOTE = Path(__file__).resolve().parent / "dados_publicos" / "contas2022.json.gz"
DOOU_MINIMO = 5_000

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


# ---------- montagem (só no computador pessoal) ----------

def _valor(txt):
    try:
        return float((txt or "0").replace(",", "."))
    except ValueError:
        return 0.0


def montar():
    norm = camara._normalizar
    cpf_para_sq, nome_de = {}, {}
    for r in zipremoto.linhas_csv(empresas.URL_CAND_2026, "consulta_cand_2026_BRASIL.csv"):
        if len(r["NR_CPF_CANDIDATO"]) == 11:
            cpf_para_sq[r["NR_CPF_CANDIDATO"]] = r["SQ_CANDIDATO"]
            nome_de[r["SQ_CANDIDATO"]] = norm(r["NM_CANDIDATO"])
    print(f"{len(cpf_para_sq)} candidatos de 2026 com CPF")

    info, doacoes, pagos_pf, pagos_pj = {}, {}, {}, {}
    for r in zipremoto.linhas_csv(gastos.URL_2022, "receitas_candidatos_2022_BRASIL.csv"):
        sq = cpf_para_sq.get(r["NR_CPF_CANDIDATO"])
        if not sq:
            continue
        info.setdefault(sq, {"cargo": r["DS_CARGO"].title(), "uf": r["SG_UF"]})
        doc = r["NR_CPF_CNPJ_DOADOR"]
        origem = (r["DS_ORIGEM_RECEITA"] or "").lower()
        if len(doc) == 11 and doc != r["NR_CPF_CANDIDATO"] and "própri" not in origem and "propri" not in origem:
            d = doacoes.setdefault(sq, {}).setdefault(doc, {"nome": r["NM_DOADOR"], "valor": 0.0})
            d["valor"] += _valor(r["VR_RECEITA"])
    print(f"receitas de 2022 lidas: {len(info)} pessoas disputaram as duas eleições")
    for r in zipremoto.linhas_csv(gastos.URL_2022, "despesas_contratadas_candidatos_2022_BRASIL.csv"):
        sq = cpf_para_sq.get(r["NR_CPF_CANDIDATO"])
        if not sq:
            continue
        info.setdefault(sq, {"cargo": r["DS_CARGO"].title(), "uf": r["SG_UF"]})
        doc, v = r["NR_CPF_CNPJ_FORNECEDOR"], _valor(r["VR_DESPESA_CONTRATADA"])
        if len(doc) == 11:
            pagos_pf.setdefault(sq, {})[doc] = pagos_pf.get(sq, {}).get(doc, 0) + v
        elif len(doc) == 14:
            p = pagos_pj.setdefault(sq, {}).setdefault(doc[:8], {"nome": r["NM_FORNECEDOR_RFB"] or r["NM_FORNECEDOR"], "valor": 0.0})
            p["valor"] += v
    print("despesas de 2022 lidas")

    empresas._carregar()
    gabinetes._carregar()
    saida = {}
    for sq, dados in info.items():
        item = dict(dados)
        doou = doacoes.get(sq, {})
        item["doouRecebeu"] = sorted(
            ({"nome": d["nome"].title(), "doou": round(d["valor"]), "recebeu": round(pagos_pf[sq][doc])}
             for doc, d in doou.items()
             if d["valor"] >= DOOU_MINIMO and pagos_pf.get(sq, {}).get(doc, 0) > d["valor"]),
            key=lambda x: -x["recebeu"])
        proprias = {e["basico"] for e in empresas.do_candidato(sq) or []}
        item["empresaPropria"] = [{"nome": p["nome"].title(), "valor": round(p["valor"])}
                                  for b, p in pagos_pj.get(sq, {}).items() if b in proprias]
        g = gabinetes.do_candidato(sq)
        equipe = {n for n in (g or {}).get("assessores", {}) if len(n.split()) >= 3} - {nome_de.get(sq)}
        item["assessores"] = sorted(({"nome": d["nome"].title(), "valor": round(d["valor"])}
                                     for d in doou.values() if norm(d["nome"]) in equipe), key=lambda x: -x["valor"])
        if item["doouRecebeu"] or item["empresaPropria"] or item["assessores"]:
            saida[sq] = item
    dados = {"geradoEm": time.strftime("%d/%m/%Y"), "candidatos": saida}
    PACOTE.parent.mkdir(parents=True, exist_ok=True)
    PACOTE.write_bytes(gzip.compress(json.dumps(dados, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), 9))
    print(f"{PACOTE.name}: {len(saida)} candidatos com algo em 2022")


if __name__ == "__main__":
    # O índice de gabinetes fica no cache do servidor público de teste; o da Receita vai junto com o site.
    tse.configurar(Path(sys.argv[1]) if len(sys.argv) > 1 else Path.home() / ".meuvoto" / "cache-publico")
    montar()
