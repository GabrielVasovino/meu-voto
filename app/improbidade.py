"""Condenações por improbidade administrativa: Cadastro Nacional do CNJ (CNCIAI), consultado pelo CPF do candidato.

O cadastro só registra condenação com trânsito em julgado ou decisão de órgão colegiado, que são as que valem para a
Lei da Ficha Limpa. Não há arquivo com tudo: a consulta pública é feita pessoa a pessoa, pelo CPF completo que o TSE
publica. São uns 21 mil candidatos, então a varredura é lenta (uma consulta por vez, com pausa) e roda no computador
pessoal; o resultado vai junto com o site em PACOTE, sem CPF, só com o número da candidatura.

Para atualizar: python app/improbidade.py --atualizar   (retoma de onde parou se for interrompido)
"""
import gzip
import json
import re
import sys
import threading
import time
import urllib.parse
from pathlib import Path

from curl_cffi import requests

import empresas
import tse
import zipremoto

BASE = "https://www.cnj.jus.br/improbidade_adm/"
PACOTE = Path(__file__).resolve().parent / "dados_publicos" / "improbidade_cnj.json.gz"
PAUSA = 1.2

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
    """Lista de condenações da pessoa (vazia se não houver) ou None se o cadastro não foi consultado para ela."""
    if not _dados:
        return None
    return _dados["achados"].get(str(id_candidato), [] if str(id_candidato) in _dados["consultados"] else None)


# ---------- varredura (só no computador pessoal) ----------

def _plano(html):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " | ", html.replace("&nbsp;", " ")))


def _valor(texto, rotulo):
    m = re.search(re.escape(rotulo) + r"\? \|[ |]*SIM[ |]*Valor[ |]*R\$ ([\d.,]+)", texto)
    if not m:
        return None
    v = float(m.group(1).replace(".", "").replace(",", "."))
    return v or None


def _condenacao(s, seq):
    html = s.get(f"{BASE}visualizar_condenacao.php?seq_condenacao={seq}", timeout=120).text
    t = _plano(html)
    tipo = re.search(r'name="tipo_pena" checked=checked value="(\w)"', html)
    data = re.search(r"Penas Aplicadas[ |]*(\d{2}/\d{2}/\d{4})", t)
    # O primeiro órgão da hierarquia depois da esfera é o tribunal (TJ, TRF, TRE...).
    tribunal = re.search(r"hierarquia-label-direita-descendente-0'[^>]*>\s*([^<]+?)\s*<", html)
    processo = re.search(r"seq_processo=\d+\">\s*<font[^>]*>\s*([\d.\-/]+)", html)
    return {
        "processo": processo.group(1) if processo else None,
        "tribunal": tribunal.group(1) if tribunal else None,
        "tipo": {"J": "trânsito em julgado", "C": "decisão de órgão colegiado"}.get(tipo.group(1)) if tipo else None,
        "data": data.group(1) if data else None,
        "ressarcimento": _valor(t, "Ressarcimento integral do dano"),
        "multa": _valor(t, "Pagamento de multa"),
        "suspensaoDireitos": bool(re.search(r"Suspensão dos Direitos Políticos\? \|[ |]*SIM", t)),
        "perdaCargo": bool(re.search(r"Perda de Emprego/Cargo/Função Pública\? \|[ |]*SIM", t)),
        "link": f"{BASE}visualizar_condenacao.php?seq_condenacao={seq}",
    }


def _consultar(s, cpf):
    """Números internos (seq_condenacao) das condenações registradas para o CPF."""
    args = ["", "", "", cpf, "", "F", "I", "0", "POSICAO_INICIAL_PAGINACAO_PHP0", "QUANTIDADE_REGISTROS_PAGINACAO15"]
    corpo = f"rs=pesquisarRequeridoGetTabela&rst=&rsrnd={int(time.time() * 1000)}" + \
        "".join("&rsargs[]=" + urllib.parse.quote(a) for a in args)
    t = s.post(f"{BASE}consultar_requerido.php", data=corpo, timeout=120,
               headers={"Content-Type": "application/x-www-form-urlencoded"}).text
    if "Nenhum Requerido" in t:
        return []
    seqs = re.findall(r"seq_condenacao=(\d+)", t)
    if not seqs and "Nome Pessoa" not in t:
        raise IOError("resposta inesperada do CNJ")
    return list(dict.fromkeys(seqs))


def atualizar():
    parcial = tse._cache_dir / "improbidade_parcial.json"
    feito = json.loads(parcial.read_text(encoding="utf-8")) if parcial.exists() else {"consultados": [], "achados": {}}
    consultados = set(feito["consultados"])
    cands = [(r["SQ_CANDIDATO"], r["NR_CPF_CANDIDATO"], r["NM_URNA_CANDIDATO"])
             for r in zipremoto.linhas_csv(empresas.URL_CAND_2026, "consulta_cand_2026_BRASIL.csv")
             if len(r["NR_CPF_CANDIDATO"]) == 11]
    faltam = [c for c in cands if c[0] not in consultados]
    print(f"{len(cands)} candidatos, faltam {len(faltam)}")
    with requests.Session(impersonate="chrome") as s:
        s.get(f"{BASE}consultar_requerido.php", timeout=120)
        for i, (sq, cpf, nome) in enumerate(faltam, 1):
            for tentativa in range(3):
                try:
                    seqs = _consultar(s, cpf)
                    if seqs:
                        feito["achados"][sq] = [_condenacao(s, x) for x in seqs]
                        print(f"  {nome}: {len(seqs)} condenação(ões)")
                    break
                except Exception as e:  # noqa: BLE001 - site fora do ar por um instante: tenta de novo
                    print(f"  {nome}: {e}; tentando de novo", file=sys.stderr)
                    time.sleep(30 * (tentativa + 1))
            else:
                continue
            feito["consultados"].append(sq)
            if i % 200 == 0:
                parcial.write_text(json.dumps(feito, ensure_ascii=False), encoding="utf-8")
                print(f"{i} de {len(faltam)}")
            time.sleep(PAUSA)
    parcial.write_text(json.dumps(feito, ensure_ascii=False), encoding="utf-8")
    empacotar(feito)


def empacotar(feito=None):
    if feito is None:
        feito = json.loads((tse._cache_dir / "improbidade_parcial.json").read_text(encoding="utf-8"))
    dados = {"geradoEm": time.strftime("%d/%m/%Y"), "consultados": sorted(set(feito["consultados"])),
             "achados": feito["achados"]}
    PACOTE.parent.mkdir(parents=True, exist_ok=True)
    PACOTE.write_bytes(gzip.compress(json.dumps(dados, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), 9))
    print(f"{PACOTE.name}: {len(dados['consultados'])} consultados, {len(dados['achados'])} com condenação")


if __name__ == "__main__":
    tse.configurar(Path.home() / ".meuvoto" / "cache")
    if "--empacotar" in sys.argv:
        empacotar()
    else:
        atualizar()
