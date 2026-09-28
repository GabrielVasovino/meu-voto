"""Empresas em que cada candidato de 2026 é sócio, pelos dados abertos do CNPJ da Receita Federal.

A Receita publica todo mês a lista de sócios de todas as empresas do país (arquivos Socios0..9) e o cadastro
das empresas (Empresas0..9), num compartilhamento público do Nextcloud (SERPRO). O CPF dos sócios vem
mascarado (***123456**): o casamento com o candidato usa esses 6 dígitos do meio, tirados do CPF completo que
o TSE publica, junto com o nome completo. Só as linhas que casam com algum candidato são guardadas; os
arquivos baixados são apagados logo depois de lidos. Refeito uma vez por mês, em segundo plano.
"""
import csv
import io
import json
import re
import tempfile
import threading
import time
import unicodedata
import zipfile
from pathlib import Path
from urllib.parse import unquote

from curl_cffi import requests

import tse
import zipremoto

WEBDAV = "https://arquivos.receitafederal.gov.br/public.php/webdav"
TOKEN = "gn672Ad4CF8N6TK"  # compartilhamento público "Arquivos da Receita Federal"
PASTA_CNPJ = "/Dados/Cadastros/CNPJ/"
URL_CAND_2026 = "https://cdn.tse.jus.br/estatistica/sead/odsele/consulta_cand/consulta_cand_2026.zip"
TTL = 30 * 24 * tse.HORA

_indice = None
_lock = threading.Lock()
_rodando = threading.Event()
_estado = {"etapa": "parado", "erro": None, "progresso": None}


def _pasta():
    p = tse._cache_dir / "empresas"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _arquivo():
    return _pasta() / "indice.json"


def _nome(s):
    s = unicodedata.normalize("NFD", str(s or "").upper())
    return " ".join("".join(c for c in s if not unicodedata.combining(c)).split())


def _digitos(s):
    return "".join(c for c in str(s or "") if c.isdigit())


# ---------- acesso ao compartilhamento da Receita ----------

def _listar(sessao, caminho):
    r = sessao.request("PROPFIND", WEBDAV + caminho, auth=(TOKEN, ""), headers={"Depth": "1"}, timeout=120)
    if r.status_code != 207:
        raise IOError(f"a Receita respondeu {r.status_code} ao listar {caminho}")
    return [unquote(h).replace("/public.php/webdav", "") for h in re.findall(r"<d:href>([^<]+)</d:href>", r.text)]


def _mes_mais_recente(sessao):
    meses = sorted(m for m in _listar(sessao, PASTA_CNPJ) if re.search(r"/\d{4}-\d{2}/$", m))
    if not meses:
        raise IOError("nenhum mês publicado na pasta do CNPJ")
    return meses[-1]


def _baixar(sessao, caminho, destino):
    r = sessao.get(WEBDAV + caminho, auth=(TOKEN, ""), stream=True, timeout=1800)
    try:
        if r.status_code != 200:
            raise IOError(f"a Receita respondeu {r.status_code} ao baixar {caminho}")
        with open(destino, "wb") as f:
            for bloco in r.iter_content(chunk_size=1 << 20):
                f.write(bloco)
    finally:
        r.close()


def _linhas(caminho_zip):
    """Linhas do CSV (sem cabeçalho, separado por ;) de dentro do ZIP da Receita."""
    with zipfile.ZipFile(caminho_zip) as z:
        with z.open(z.namelist()[0]) as f:
            yield from csv.reader(io.TextIOWrapper(f, encoding="latin-1", newline=""), delimiter=";")


def _tabela_codigos(sessao, mes, nome):
    """Tabelas pequenas de códigos (Qualificacoes.zip, Naturezas.zip): código -> descrição."""
    with tempfile.TemporaryDirectory() as tmp:
        destino = Path(tmp) / nome
        _baixar(sessao, mes + nome, destino)
        return {l[0]: l[1] for l in _linhas(destino) if len(l) >= 2}


SITUACOES = {"01": "Nula", "02": "Ativa", "03": "Suspensa", "04": "Inapta", "08": "Baixada"}


def _data(s):
    s = (s or "").strip()
    return f"{s[:4]}-{s[4:6]}-{s[6:]}" if len(s) == 8 and s != "00000000" else None


# ---------- montagem do índice ----------

def _candidatos():
    """(6 dígitos do meio do CPF, nome) -> [sq_candidato], para todos os candidatos de 2026 do país."""
    chaves = {}
    arquivos = [n for n in zipremoto.listar(URL_CAND_2026) if n.endswith(".csv")]
    for nome in arquivos:
        for r in zipremoto.linhas_csv(URL_CAND_2026, nome):
            cpf = _digitos(r.get("NR_CPF_CANDIDATO"))
            if len(cpf) != 11:
                continue
            chave = f"{cpf[3:9]}|{_nome(r['NM_CANDIDATO'])}"
            chaves.setdefault(chave, set()).add(r["SQ_CANDIDATO"])
    return chaves


def _estabelecimentos(s, mes, basicos, tmp):
    """Completa cada empresa (dict por cnpj_basico) com dados da matriz: situação na Receita, abertura,
    atividade principal e cidade."""
    cnaes = _tabela_codigos(s, mes, "Cnaes.zip")
    municipios = _tabela_codigos(s, mes, "Municipios.zip")
    for i in range(10):
        _estado.update(etapa="lendo estabelecimentos", progresso=f"{i + 1} de 10")
        destino = tmp / f"Estabelecimentos{i}.zip"
        _baixar(s, f"{mes}Estabelecimentos{i}.zip", destino)
        for l in _linhas(destino):
            # cnpj_basico; ordem; dv; matriz(1)/filial(2); fantasia; situação; data da situação; motivo; cidade no
            # exterior; país; início da atividade; CNAE principal; secundários; ...; UF (19); município (20)
            if len(l) < 21 or l[3] != "1" or l[0] not in basicos:
                continue
            basicos[l[0]].update(
                situacao=SITUACOES.get(l[5], l[5]), dataSituacao=_data(l[6]), abertura=_data(l[10]),
                atividade=cnaes.get(l[11], l[11]), cidade=f"{municipios.get(l[20], '').title()}/{l[19]}".strip("/"),
            )
        destino.unlink()


def _preparar():
    try:
        _estado.update(etapa="lendo candidatos", erro=None)
        cand = _candidatos()
        with requests.Session() as s:
            mes = _mes_mais_recente(s)
            qualif = _tabela_codigos(s, mes, "Qualificacoes.zip")
            naturezas = _tabela_codigos(s, mes, "Naturezas.zip")
            por_candidato, basicos = {}, {}
            with tempfile.TemporaryDirectory() as tmp:
                for i in range(10):
                    _estado.update(etapa="lendo sócios", progresso=f"{i + 1} de 10")
                    destino = Path(tmp) / f"Socios{i}.zip"
                    _baixar(s, f"{mes}Socios{i}.zip", destino)
                    for l in _linhas(destino):
                        # cnpj_basico; identificador (2 = pessoa física); nome; cpf mascarado; qualificação; data de entrada
                        if len(l) < 6 or l[1] != "2":
                            continue
                        meio = _digitos(l[3])
                        if len(meio) != 6:
                            continue
                        sqs = cand.get(f"{meio}|{_nome(l[2])}")
                        if not sqs:
                            continue
                        data = l[5]
                        registro = {"basico": l[0], "qualificacao": qualif.get(l[4], l[4]),
                                    "entrada": f"{data[:4]}-{data[4:6]}-{data[6:]}" if len(data) == 8 else None}
                        for sq in sqs:
                            por_candidato.setdefault(sq, []).append(registro)
                        basicos[l[0]] = None
                    destino.unlink()
                for i in range(10):
                    _estado.update(etapa="lendo empresas", progresso=f"{i + 1} de 10")
                    destino = Path(tmp) / f"Empresas{i}.zip"
                    _baixar(s, f"{mes}Empresas{i}.zip", destino)
                    for l in _linhas(destino):
                        # cnpj_basico; razão social; natureza jurídica; qualificação do responsável; capital; porte
                        if len(l) >= 6 and l[0] in basicos:
                            basicos[l[0]] = {
                                "razao": l[1].strip(), "natureza": naturezas.get(l[2], l[2]),
                                "capital": float(l[4].replace(".", "").replace(",", ".") or 0),
                                "porte": {"01": "Microempresa", "03": "Empresa de pequeno porte", "05": "Demais"}.get(l[5], ""),
                            }
                    destino.unlink()
                _estabelecimentos(s, mes, {b: e for b, e in basicos.items() if e is not None}, Path(tmp))
        for regs in por_candidato.values():
            for r in regs:
                r.update(basicos.get(r["basico"]) or {})
        indice = {"geradoEm": time.strftime("%d/%m/%Y"), "mes": mes.strip("/").split("/")[-1],
                  "candidatos": por_candidato}
        tmp_arq = _arquivo().with_suffix(".tmp")
        tmp_arq.write_text(json.dumps(indice, ensure_ascii=False), encoding="utf-8")
        tmp_arq.replace(_arquivo())
        _carregar()
        _estado.update(etapa="pronto", progresso=None)
    except Exception as e:  # sem internet ou Receita fora do ar: segue com o índice anterior, se houver
        _estado.update(etapa="erro", erro=str(e), progresso=None)
    finally:
        _rodando.clear()


def _carregar():
    global _indice
    arq = _arquivo()
    # A versão pública do app usa outra pasta de cache; aproveita o índice do cache pessoal em vez de baixar de novo.
    pessoal = Path.home() / ".meuvoto" / "cache" / "empresas" / "indice.json"
    if not arq.exists() and pessoal.exists() and pessoal != arq:
        arq.write_bytes(pessoal.read_bytes())
    if not arq.exists():
        return False
    try:
        dados = json.loads(arq.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    # Índice invertido: empresa (8 primeiros dígitos do CNPJ) -> candidatos sócios.
    donos = {}
    for sq, regs in dados["candidatos"].items():
        for r in regs:
            donos.setdefault(r["basico"], set()).add(sq)
    dados["donos"] = donos
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
    return {"pronto": pronto(), "etapa": _estado["etapa"], "progresso": _estado["progresso"], "erro": _estado["erro"],
            "mes": (_indice or {}).get("mes")}


def do_candidato(sq_candidato):
    """Empresas em que o candidato é sócio (lista vazia se nenhuma; None se o índice ainda não existe)."""
    if _indice is None:
        return None
    vistos, out = set(), []
    for r in _indice["candidatos"].get(str(sq_candidato), []):
        if r["basico"] not in vistos:
            vistos.add(r["basico"])
            out.append(r)
    return sorted(out, key=lambda r: -(r.get("capital") or 0))


def cnpj_matriz(basico):
    """CNPJ completo da matriz (ordem 0001), com os dígitos verificadores."""
    base = [int(x) for x in basico + "0001"]
    for pesos in ([5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2], [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]):
        r = sum(d * p for d, p in zip(base, pesos)) % 11
        base.append(0 if r < 2 else 11 - r)
    return "".join(map(str, base))


def _por_prefixo(c, sql, basico):
    # Faixa de texto em vez de LIKE, para usar o índice da coluna doc.
    return c.execute(sql, (basico, basico + ":")).fetchall()


def cruzamentos(sq_candidato):
    """Empresas do candidato com o que o dinheiro público e de campanha diz delas: quanto esta campanha e as outras
    pagaram, emendas recebidas e sanções. None se o índice ainda não existe."""
    import emendas
    import gastos
    import punicoes
    import sancoes
    lista = do_candidato(sq_candidato)
    if lista is None:
        return None
    sq = int(sq_candidato)
    cg = gastos._conectar() if gastos._banco().exists() else None
    ce = emendas._conectar() if emendas._banco().exists() else None
    saida = []
    try:
        for r in lista:
            b = r["basico"]
            e = dict(r, cnpj=cnpj_matriz(b))
            if cg:
                linhas = _por_prefixo(cg, """SELECT d.sq_candidato, sum(d.valor) valor, max(c.nome) nome, max(c.partido) partido,
                           max(c.uf) uf FROM despesas d LEFT JOIN candidatos c ON c.sq_candidato = d.sq_candidato
                           WHERE d.doc >= ? AND d.doc < ? GROUP BY d.sq_candidato ORDER BY valor DESC""", b)
                propria = sum(x["valor"] for x in linhas if x["sq_candidato"] == sq)
                outras = [dict(x) for x in linhas if x["sq_candidato"] != sq]
                e["campanhaPropria"] = propria
                e["outrasCampanhas"] = {"total": sum(x["valor"] for x in outras), "quantas": len(outras),
                                        "principais": [{k: x[k] for k in ("nome", "partido", "uf", "valor")} for x in outras[:5]]}
            if ce:
                linhas = _por_prefixo(ce, """SELECT autor, sum(valor) valor FROM favorecidos WHERE doc >= ? AND doc < ?
                                             GROUP BY autor ORDER BY valor DESC""", b)
                e["emendas"] = {"total": sum(x["valor"] for x in linhas), "parlamentares": len(linhas),
                                "principais": [{"nome": x["autor"], "valor": x["valor"]} for x in linhas[:5]]}
            e["sancoes"] = [{k: s.get(k) for k in ("sigla", "sancao", "orgao", "inicio")}
                            for s in sancoes.empresa_raiz(b)] if sancoes.pronto() else []
            e["punicoes"] = punicoes.empresa(b) or []
            saida.append(e)
    finally:
        for c in (cg, ce):
            if c:
                c.close()
    return saida


def fornecedores_de_candidatos(sq_candidato):
    """Empresas de outros candidatos de 2026 que esta campanha pagou (o outro lado do aviso
    "Empresa do candidato recebeu de outras campanhas"). None se o índice ou o banco de gastos não existem."""
    import gastos
    if _indice is None or not gastos._banco().exists():
        return None
    sq = str(sq_candidato)
    c = gastos._conectar()
    try:
        pagos = {}
        for r in c.execute("SELECT doc, max(nome) nome, sum(valor) valor FROM despesas WHERE sq_candidato = ? AND length(doc) = 14 "
                           "GROUP BY doc", (int(sq),)):
            x = pagos.setdefault(r["doc"][:8], {"nome": r["nome"], "valor": 0.0, "cnpj": r["doc"]})
            x["valor"] += r["valor"]
        saida = []
        for basico, x in pagos.items():
            donos = _indice["donos"].get(basico, set()) - {sq}
            if not donos:
                continue
            pessoas = []
            for d in donos:
                cand = c.execute("SELECT nome, numero, uf, cargo, partido FROM candidatos WHERE sq_candidato = ?", (int(d),)).fetchone()
                if cand:
                    pessoas.append(dict(cand, sq=d))
            if pessoas:
                saida.append(dict(x, basico=basico, donos=pessoas))
    finally:
        c.close()
    return sorted(saida, key=lambda x: -x["valor"])
