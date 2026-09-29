"""Registros públicos de punição por CPF ou CNPJ completos, em listas abertas e gratuitas:

- TCU: contas julgadas irregulares para fins eleitorais (a lista que o TCU envia à Justiça Eleitoral),
  contas julgadas irregulares (todas), inabilitados para cargo público e licitantes inidôneos;
- Ministério do Trabalho: Cadastro de Empregadores que submeteram trabalhadores a condições análogas à
  escravidão (a "lista suja", publicada em PDF);
- Ibama: termos de embargo ambiental (área ou atividade interditada por infração ambiental).

Tudo vira um índice só, por documento (CPF com 11 dígitos, CNPJ com 14), refeito a cada 3 dias em segundo plano.
O casamento com candidatos usa o CPF completo que o TSE publica; com empresas, os 8 primeiros dígitos do CNPJ.
"""
import csv
import io
import json
import sys
import threading
import time
import traceback
from datetime import date, datetime
from pathlib import Path

from curl_cffi import requests

import tse

TCU_API = "https://certidoes.apps.tcu.gov.br/api/publico/"
TCU_ORDS = "https://contas.tcu.gov.br/ords/condenacao/consulta/"
URL_ESCRAVO = ("https://www.gov.br/trabalho-e-emprego/pt-br/assuntos/inspecao-do-trabalho/areas-de-atuacao/"
               "cadastro_de_empregadores.pdf")
URL_IBAMA = ("https://stibamadadosabertosprd.blob.core.windows.net/dados-abertos/dados/TERMOS_DE_EMBARGO/"
             "TERMO_EMBARGO/termo_de_embargo.csv")
TTL = 3 * 24 * tse.HORA

FONTES = {
    "tcu_eleitoral": "TCU, contas julgadas irregulares para fins eleitorais",
    "tcu_irregular": "TCU, contas julgadas irregulares",
    "tcu_inabilitado": "TCU, inabilitados para cargo em comissão ou função de confiança",
    "tcu_inidoneo": "TCU, licitantes inidôneos",
    "escravo": "Ministério do Trabalho, cadastro de empregadores flagrados com trabalho análogo à escravidão",
    "ibama": "Ibama, termos de embargo ambiental",
}

_indice = None
_prefixos = {}
_lock = threading.Lock()
_rodando = threading.Event()
_estado = {"etapa": "parado", "erro": None}


def registrar_falha(e):
    """Deixa no log do servidor em que etapa a base falhou, com o erro completo."""
    print(f"[{__name__}] falhou em \"{_estado.get('etapa')}\": {e}", file=sys.stderr)
    traceback.print_exc()


def _arquivo():
    p = tse._cache_dir / "punicoes"
    p.mkdir(parents=True, exist_ok=True)
    return p / "indice.json"


def _digitos(s):
    return "".join(c for c in str(s or "") if c.isdigit())


def _data_br(s):
    """'2024-05-09T03:00:00Z' ou '09/05/2024' -> '2024-05-09'."""
    s = (s or "").strip()
    if not s:
        return None
    if "/" in s:
        d, m, a = s[:10].split("/")
        return f"{a}-{m}-{d}"
    return s[:10]


# ---------- TCU ----------

def _tcu_paginado(sessao, rota, extra=""):
    pagina, total = 1, 1
    while pagina <= total:
        r = sessao.post(f"{TCU_API}{rota}?paginaAtual={pagina}&tamanhoPagina=5000{extra}", json={}, timeout=120)
        r.raise_for_status()
        j = r.json()
        total = j.get("totalPaginas") or 0
        yield from j.get("elementos", [])
        pagina += 1


def _tcu(sessao, add):
    ano = sessao.get(TCU_API + "eleicoes/ultimoAno", timeout=60).json()["ano"]
    for e in _tcu_paginado(sessao, "responsaveis-fins-eleitorais-com-paginacao", f"&anoEleicao={ano}"):
        add(e.get("numeroRegistro"), {"fonte": "tcu_eleitoral", "nome": e.get("nome"), "processo": e.get("numeroProcessoFormatado"),
                                      "acordao": e.get("numeroAcordaoFormatado"), "desde": _data_br(e.get("dataTransitoEmJulgado")),
                                      "ate": _data_br(e.get("dataFinalFinsEleitorais")), "link": e.get("linkDeliberacoesProcesso"),
                                      "local": f"{e.get('municipio') or ''}/{e.get('uf') or ''}".strip("/")})
    for e in _tcu_paginado(sessao, "responsaveis-contas-irregulares-com-paginacao"):
        add(e.get("numeroRegistro"), {"fonte": "tcu_irregular", "nome": e.get("nome"), "processo": e.get("numeroProcessoFormatado"),
                                      "acordao": e.get("numeroAcordaoFormatado"), "desde": _data_br(e.get("dataTransitoEmJulgado")),
                                      "link": e.get("linkDeliberacoesProcesso"),
                                      "local": f"{e.get('municipio') or ''}/{e.get('uf') or ''}".strip("/")})
    for lista, fonte, campo in (("inabilitados", "tcu_inabilitado", "cpf"), ("inidoneos", "tcu_inidoneo", "cpf_cnpj")):
        offset = 0
        while True:
            j = sessao.get(f"{TCU_ORDS}{lista}?limit=500&offset={offset}", timeout=120).json()
            for e in j.get("items", []):
                add(e.get(campo), {"fonte": fonte, "nome": e.get("nome"), "processo": e.get("processo"),
                                   "acordao": e.get("deliberacao"), "desde": _data_br(e.get("data_transito_julgado")),
                                   "ate": _data_br(e.get("data_final")), "local": e.get("uf")})
            if not j.get("hasMore"):
                break
            offset += len(j.get("items", [])) or 500


# ---------- trabalho escravo (PDF) ----------

def _escravo(sessao, add):
    import pdfplumber
    r = sessao.get(URL_ESCRAVO, timeout=180)
    r.raise_for_status()
    with pdfplumber.open(io.BytesIO(r.content)) as pdf:
        for pagina in pdf.pages:
            for tabela in pagina.extract_tables():
                for l in tabela:
                    # ID; ano da ação fiscal; UF; empregador; CPF/CNPJ; estabelecimento; trabalhadores; CNAE; decisão; inclusão
                    if len(l) < 10 or not (l[0] or "").strip().isdigit():
                        continue
                    add(l[4], {"fonte": "escravo", "nome": " ".join((l[3] or "").split()), "ano": (l[1] or "").strip(),
                               "trabalhadores": _digitos(l[6]) or None, "desde": _data_br(l[9]),
                               "local": " ".join((l[5] or "").split())[:120]})


# ---------- Ibama (CSV grande, lido aos poucos) ----------

class _Linhas(io.RawIOBase):
    def __init__(self, it):
        self._it, self._sobra = it, b""

    def readable(self):
        return True

    def readinto(self, b):
        while not self._sobra:
            try:
                self._sobra = next(self._it)
            except StopIteration:
                return 0
        n = min(len(b), len(self._sobra))
        b[:n], self._sobra = self._sobra[:n], self._sobra[n:]
        return n


def _ibama(sessao, add):
    csv.field_size_limit(2**31 - 1)  # a coluna com o polígono da área embargada passa do limite padrão
    r = sessao.get(URL_IBAMA, stream=True, timeout=1800)
    try:
        r.raise_for_status()
        texto = io.TextIOWrapper(io.BufferedReader(_Linhas(r.iter_content(chunk_size=1 << 20)), buffer_size=1 << 20),
                                 encoding="utf-8-sig", newline="")
        for l in csv.DictReader(texto, delimiter=";"):
            if l.get("SIT_CANCELADO") == "S":
                continue
            area = (l.get("QTD_AREA_EMBARGADA") or "").replace(",", ".")
            add(l.get("CPF_CNPJ_EMBARGADO"), {
                "fonte": "ibama", "nome": l.get("NOME_EMBARGADO"), "processo": l.get("NUM_PROCESSO"),
                "desde": (l.get("DAT_EMBARGO") or "")[:10] or None,
                "desembargo": (l.get("DAT_DESEMBARGO") or "")[:10] or None if l.get("SIT_DESEMBARGO") == "S" else None,
                "area": round(float(area), 1) if area.replace(".", "", 1).isdigit() else None,
                "local": f"{l.get('MUNICIPIO') or ''}/{l.get('UF') or ''}".strip("/"),
                "descricao": " ".join((l.get("DES_TAD") or "").split())[:240],
            })
    finally:
        r.close()


# ---------- índice ----------

def _preparar():
    try:
        docs, contagem = {}, {}

        def add(doc, reg):
            d = _digitos(doc)
            if len(d) not in (11, 14):
                return
            docs.setdefault(d, []).append({k: v for k, v in reg.items() if v not in (None, "")})
            contagem[reg["fonte"]] = contagem.get(reg["fonte"], 0) + 1

        erros = []
        with requests.Session(impersonate="chrome") as s:
            for nome, etapa in (("TCU", _tcu), ("lista suja do trabalho escravo", _escravo), ("Ibama", _ibama)):
                _estado["etapa"] = f"baixando {nome}"
                try:
                    etapa(s, add)
                except Exception as e:  # uma fonte fora do ar não impede as outras
                    erros.append(f"{nome}: {e}")
        if not docs:
            raise RuntimeError("; ".join(erros) or "nenhuma fonte respondeu")
        indice = {"geradoEm": time.strftime("%d/%m/%Y"), "contagem": contagem, "erros": erros, "docs": docs}
        tmp = _arquivo().with_suffix(".tmp")
        tmp.write_text(json.dumps(indice, ensure_ascii=False), encoding="utf-8")
        tmp.replace(_arquivo())
        _carregar()
        _estado.update(etapa="pronto", erro="; ".join(erros) or None)
    except Exception as e:
        registrar_falha(e)
        _estado.update(etapa="erro", erro=f"{_estado.get('etapa')}: {e}")
    finally:
        _rodando.clear()


def _carregar():
    global _indice, _prefixos
    arq = _arquivo()
    pessoal = Path.home() / ".meuvoto" / "cache" / "punicoes" / "indice.json"
    if not arq.exists() and pessoal.exists() and pessoal != arq:
        arq.write_bytes(pessoal.read_bytes())
    if not arq.exists():
        return False
    try:
        dados = json.loads(arq.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    prefixos = {}
    for d in dados["docs"]:
        if len(d) == 14:
            prefixos.setdefault(d[:8], []).append(d)
    with _lock:
        _indice, _prefixos = dados, prefixos
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
            "geradoEm": (_indice or {}).get("geradoEm"), "contagem": (_indice or {}).get("contagem")}


def _vigente(r):
    """Registros com prazo (TCU) valem até a data final; embargo do Ibama vale até o desembargo."""
    if r.get("desembargo"):
        return False
    ate = r.get("ate")
    return not ate or ate >= date.today().isoformat()


def _com_rotulo(regs):
    return [dict(r, rotulo=FONTES[r["fonte"]], vigente=_vigente(r)) for r in regs]


def pessoa(cpf):
    """Registros de uma pessoa pelo CPF completo."""
    if _indice is None:
        return None
    return _com_rotulo(_indice["docs"].get(_digitos(cpf), []))


def empresa(basico_ou_cnpj):
    """Registros de uma empresa (matriz e filiais) pelos 8 primeiros dígitos do CNPJ."""
    if _indice is None:
        return None
    b = _digitos(basico_ou_cnpj)[:8]
    return _com_rotulo([r for d in _prefixos.get(b, []) for r in _indice["docs"][d]])
