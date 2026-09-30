"""As campanhas anteriores (2014, 2018 e 2022) de quem disputa de novo em 2026: os mesmos cruzamentos de dinheiro.

As contas dessas eleições estão fechadas e não mudam, então tudo é calculado uma vez no computador pessoal e vai
junto com o site em PACOTE (sem CPF, só com o número da candidatura de 2026). A pessoa é ligada entre as eleições
pelo CPF completo que o TSE publica em todas elas.

O que se procura em cada campanha:
- doador que deu R$ 5 mil ou mais e recebeu da campanha mais do que doou;
- campanha que pagou empresa do próprio candidato (sócios pela Receita Federal);
- pessoa que hoje trabalha ou trabalhou no gabinete (Senado, Câmara ou assembleias) e doou para a campanha.

Para montar: python app/contas_anteriores.py   (depois de o índice dos gabinetes existir no cache)
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
import tse
import zipremoto

PACOTE = Path(__file__).resolve().parent / "dados_publicos" / "contas_anteriores.json.gz"
DOOU_MINIMO = 5_000
BASE_TSE = "https://cdn.tse.jus.br/estatistica/sead/odsele/prestacao_contas/"

# Onde está cada coisa em cada ano. 2018 e 2022 seguem o formato novo do TSE; 2014 tem outros nomes de coluna.
_NOVO = {"cpf": "NR_CPF_CANDIDATO", "cargo": "DS_CARGO", "uf": "SG_UF",
         "doador": "NR_CPF_CNPJ_DOADOR", "nome_doador": "NM_DOADOR", "valor_receita": "VR_RECEITA",
         "origem": "DS_ORIGEM_RECEITA", "fornecedor": "NR_CPF_CNPJ_FORNECEDOR",
         "nome_fornecedor": ("NM_FORNECEDOR_RFB", "NM_FORNECEDOR"), "valor_despesa": "VR_DESPESA_CONTRATADA"}
ANOS = {
    2022: dict(_NOVO, zip="prestacao_de_contas_eleitorais_candidatos_2022.zip",
               receitas="receitas_candidatos_2022_BRASIL.csv", despesas="despesas_contratadas_candidatos_2022_BRASIL.csv"),
    2018: dict(_NOVO, zip="prestacao_de_contas_eleitorais_candidatos_2018.zip",
               receitas="receitas_candidatos_2018_BRASIL.csv", despesas="despesas_contratadas_candidatos_2018_BRASIL.csv"),
    2014: {"zip": "prestacao_final_2014.zip", "receitas": "receitas_candidatos_2014_brasil.txt",
           "despesas": "despesas_candidatos_2014_brasil.txt", "cpf": "CPF do candidato", "cargo": "Cargo", "uf": "UF",
           "doador": "CPF/CNPJ do doador", "nome_doador": "Nome do doador", "valor_receita": "Valor receita",
           "origem": "Tipo receita", "fornecedor": "CPF/CNPJ do fornecedor",
           "nome_fornecedor": ("Nome do fornecedor (Receita Federal)", "Nome do fornecedor"), "valor_despesa": "Valor despesa"},
}

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
    """{"2022": {...}, "2018": {...}} com o que foi achado em cada campanha, ou None."""
    return ((_dados or {}).get("candidatos") or {}).get(str(id_candidato))


# ---------- montagem (só no computador pessoal) ----------

def _valor(txt):
    try:
        return float((txt or "0").replace(",", "."))
    except ValueError:
        return 0.0


def _digitos(s):
    return "".join(c for c in str(s or "") if c.isdigit())


def _ano(ano, col, cpf_para_sq, nome_de):
    norm = camara._normalizar
    url = BASE_TSE + col["zip"]
    info, doacoes, pagos_pf, pagos_pj = {}, {}, {}, {}
    for r in zipremoto.linhas_csv(url, col["receitas"]):
        cpf = _digitos(r.get(col["cpf"])).zfill(11)
        sq = cpf_para_sq.get(cpf)
        if not sq:
            continue
        info.setdefault(sq, {"cargo": (r.get(col["cargo"]) or "").title(), "uf": r.get(col["uf"])})
        doc = _digitos(r.get(col["doador"]))
        origem = (r.get(col["origem"]) or "").lower()
        if len(doc) == 11 and doc != cpf and "própri" not in origem and "propri" not in origem and "jurídic" not in origem:
            d = doacoes.setdefault(sq, {}).setdefault(doc, {"nome": r.get(col["nome_doador"]) or "", "valor": 0.0})
            d["valor"] += _valor(r.get(col["valor_receita"]))
    print(f"  {ano}: receitas lidas, {len(info)} pessoas também disputam em 2026")
    for r in zipremoto.linhas_csv(url, col["despesas"]):
        sq = cpf_para_sq.get(_digitos(r.get(col["cpf"])).zfill(11))
        if not sq:
            continue
        info.setdefault(sq, {"cargo": (r.get(col["cargo"]) or "").title(), "uf": r.get(col["uf"])})
        doc, v = _digitos(r.get(col["fornecedor"])), _valor(r.get(col["valor_despesa"]))
        if len(doc) == 11:
            pagos_pf.setdefault(sq, {})[doc] = pagos_pf.get(sq, {}).get(doc, 0) + v
        elif len(doc) == 14:
            nome = next((r.get(k) for k in col["nome_fornecedor"] if r.get(k) and r.get(k) != "#NULO"), "")
            p = pagos_pj.setdefault(sq, {}).setdefault(doc[:8], {"nome": nome, "valor": 0.0})
            p["valor"] += v
    print(f"  {ano}: despesas lidas")
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
    return saida


def montar():
    norm = camara._normalizar
    cpf_para_sq, nome_de = {}, {}
    for r in zipremoto.linhas_csv(empresas.URL_CAND_2026, "consulta_cand_2026_BRASIL.csv"):
        if len(r["NR_CPF_CANDIDATO"]) == 11:
            cpf_para_sq[r["NR_CPF_CANDIDATO"]] = r["SQ_CANDIDATO"]
            nome_de[r["SQ_CANDIDATO"]] = norm(r["NM_CANDIDATO"])
    print(f"{len(cpf_para_sq)} candidatos de 2026 com CPF")
    empresas._carregar()
    gabinetes._carregar()
    candidatos = {}
    for ano, col in ANOS.items():
        for sq, item in _ano(ano, col, cpf_para_sq, nome_de).items():
            candidatos.setdefault(sq, {})[str(ano)] = item
    dados = {"geradoEm": time.strftime("%d/%m/%Y"), "anos": sorted(ANOS), "candidatos": candidatos}
    PACOTE.parent.mkdir(parents=True, exist_ok=True)
    PACOTE.write_bytes(gzip.compress(json.dumps(dados, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), 9))
    print(f"{PACOTE.name}: {len(candidatos)} candidatos com algo em campanhas anteriores")


if __name__ == "__main__":
    # O índice de gabinetes fica no cache do servidor público de teste; o da Receita vai junto com o site.
    tse.configurar(Path(sys.argv[1]) if len(sys.argv) > 1 else Path.home() / ".meuvoto" / "cache-publico")
    montar()
