"""Análise dos gastos de campanha: fornecedores, cruzamentos entre candidatos e histórico.

Fontes:
- TSE, prestação de contas de 2026 (despesas contratadas, pagamentos e receitas de
  todos os candidatos do país) e despesas de 2022 (histórico dos fornecedores);
- Receita Federal, via BrasilAPI, para dados cadastrais das empresas (abertura,
  situação, MEI, capital social, atividades e sócios).

Os dados do TSE vão para um banco SQLite local, refeito uma vez por dia em
segundo plano. Os sinais são indícios que valem conferir, nunca acusações.
"""
import json
import math
import re
import sqlite3
import statistics
import sys
import threading
import time
import traceback
import unicodedata
from collections import Counter, defaultdict
from datetime import date, datetime

from curl_cffi import requests

import tse
import zipremoto

URL_2026 = "https://cdn.tse.jus.br/estatistica/sead/odsele/prestacao_contas/prestacao_de_contas_eleitorais_candidatos_2026.zip"
URL_2022 = "https://cdn.tse.jus.br/estatistica/sead/odsele/prestacao_contas/prestacao_de_contas_eleitorais_candidatos_2022.zip"
URL_CNPJ = "https://brasilapi.com.br/api/cnpj/v1/{cnpj}"
TTL_BANCO = 20 * tse.HORA
TTL_CNPJ = 30 * 24 * tse.HORA
INICIO_CAMPANHA = date(2026, 8, 16)
LIMITE_MEI = 81_000
LIMITE_MEI_TOLERANCIA = 97_200  # até 20% acima, o MEI ainda fica no regime até dezembro
CATEGORIA_REPASSE = "Doações financeiras a outros candidatos/partidos"
# Fornecedores com mais clientes que isso são plataformas ou gigantes (ex.: redes sociais),
# e "ter em comum" com elas não diz nada.
MAX_CLIENTES_COMPARTILHADO = 30
# Fornecedores que atendem mais campanhas que isto no país são plataformas (Meta, Google, meios de pagamento):
# concentrar o gasto nelas é o normal para quem faz campanha na internet.
MIN_CLIENTES_PLATAFORMA = 100
TTL_PANORAMA = tse.HORA

# Atividades (divisões da CNAE, 2 primeiros dígitos) que combinam com cada tipo de despesa.
# Aluguel de espaço e alimentação ficam de fora: qualquer entidade pode alugar um salão ou servir um evento.
ATIVIDADES_ESPERADAS = {
    "Despesa com Impulsionamento de Conteúdos": {"58", "59", "60", "62", "63", "70", "73", "74", "82"},
    "Publicidade por materiais impressos": {"17", "18", "46", "47", "58", "73", "74", "82"},
    "Publicidade por adesivos": {"17", "18", "22", "46", "47", "73", "74", "82"},
    "Serviços advocatícios": {"69"},
    "Serviços contábeis": {"69", "70", "82"},
    "Produção de programas de rádio, televisão ou vídeo": {"59", "60", "73", "74", "90"},
    "Produção de jingles, vinhetas e slogans": {"59", "73", "74", "90"},
    "Cessão ou locação de veículos": {"45", "49", "77", "79"},  # agências de turismo também alugam veículos
    "Combustíveis e lubrificantes": {"46", "47", "49", "77"},  # locadoras (com ou sem motorista) também faturam combustível
    "Pesquisas ou testes eleitorais": {"70", "72", "73", "74"},
    "Criação e inclusão de páginas na internet": {"62", "63", "73", "74"},
    "Despesas com transporte ou deslocamento": {"49", "50", "51", "52", "77", "79"},
    "Publicidade por carros de som": {"49", "59", "73", "74", "77", "82", "90"},
}

_lock = threading.Lock()
_rodando = threading.Event()
_estado = {"etapa": "parado", "erro": None}
_sobrenomes = None
_nomes_candidatos = None


def registrar_falha(e):
    """Deixa no log do servidor em que etapa a base falhou, com o erro completo."""
    print(f"[{__name__}] falhou em \"{_estado.get('etapa')}\": {e}", file=sys.stderr)
    traceback.print_exc()


# ---------- utilidades ----------

def _norm(txt):
    sem = unicodedata.normalize("NFKD", txt or "").encode("ascii", "ignore").decode()
    return " ".join(re.sub(r"[^A-Za-z ]", " ", sem).upper().split())


def _valor(txt):
    txt = (txt or "0").strip()
    if "," in txt:
        txt = txt.replace(".", "").replace(",", ".")
    try:
        return float(txt)
    except ValueError:
        return 0.0


def _milhar(v):
    """12345.6 -> "12.346" (separador de milhar brasileiro)."""
    return f"{v:,.0f}".replace(",", ".")


def _data_iso(txt):
    try:
        return datetime.strptime(txt, "%d/%m/%Y").date().isoformat()
    except (TypeError, ValueError):
        return None


def _int(txt):
    try:
        return int(txt)
    except (TypeError, ValueError):
        return -1


def _pasta():
    p = tse._cache_dir / "gastos"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _banco():
    return _pasta() / "gastos.sqlite"


def _conectar():
    c = sqlite3.connect(f"file:{_banco()}?mode=ro", uri=True, check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c


def _fonte_curta(txt):
    t = (txt or "").lower()
    if "especial" in t:
        return "FEFC"
    if "partid" in t:
        return "FP"
    return "OUTROS"


# ---------- montagem do banco ----------

ESQUEMA = """
CREATE TABLE despesas (sq_despesa INTEGER, sq_candidato INTEGER, uf TEXT, cargo INTEGER, partido TEXT,
  doc TEXT, tipo TEXT, nome TEXT, cnae TEXT, cnae_desc TEXT, uf_forn TEXT, mun_forn TEXT,
  sq_cand_forn INTEGER, cargo_forn TEXT, partido_forn TEXT, origem TEXT, descricao TEXT, data TEXT, valor REAL);
CREATE TABLE pagamentos (sq_despesa INTEGER, fonte TEXT, valor REAL);
CREATE TABLE receitas (sq_candidato INTEGER, doc TEXT, nome TEXT, fonte TEXT, origem TEXT,
  sq_cand_doador INTEGER, valor REAL);
CREATE TABLE candidatos (sq_candidato INTEGER PRIMARY KEY, nome TEXT, numero TEXT, uf TEXT, cargo INTEGER,
  partido TEXT, genero TEXT);
CREATE TABLE hist2022 (doc TEXT PRIMARY KEY, nome TEXT, candidatos INTEGER, partidos INTEGER, total REAL);
CREATE TABLE meta (chave TEXT PRIMARY KEY, valor TEXT);
"""
INDICES = """
CREATE INDEX i_desp_cand ON despesas(sq_candidato);
CREATE INDEX i_desp_doc ON despesas(doc);
CREATE INDEX i_desp_uf ON despesas(uf, cargo);
CREATE INDEX i_pag ON pagamentos(sq_despesa);
CREATE INDEX i_rec_cand ON receitas(sq_candidato);
CREATE INDEX i_rec_doador ON receitas(sq_cand_doador);
"""


def _inserir(conn, sql, linhas, tamanho=20_000):
    lote = []
    for linha in linhas:
        lote.append(linha)
        if len(lote) >= tamanho:
            conn.executemany(sql, lote)
            lote.clear()
    if lote:
        conn.executemany(sql, lote)


def _montar():
    destino = _banco()
    tmp = destino.with_suffix(".montando")
    tmp.unlink(missing_ok=True)
    conn = sqlite3.connect(tmp)
    conn.executescript(ESQUEMA)
    candidatos = {}

    def lembrar(r, genero=None):
        sq = _int(r["SQ_CANDIDATO"])
        c = candidatos.setdefault(sq, [r["NM_CANDIDATO"], r["NR_CANDIDATO"], r["SG_UF"], _int(r["CD_CARGO"]), r["SG_PARTIDO"], None])
        if genero:
            c[5] = genero
        return sq

    _estado["etapa"] = "despesas de 2026"
    _inserir(conn, "INSERT INTO despesas VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
        (
            _int(r["SQ_DESPESA"]), lembrar(r), r["SG_UF"], _int(r["CD_CARGO"]), r["SG_PARTIDO"],
            r["NR_CPF_CNPJ_FORNECEDOR"] if r["NR_CPF_CNPJ_FORNECEDOR"] not in ("-1", "") else None,
            {"PESSOA JURÍDICA": "PJ", "PESSOA FÍSICA": "PF"}.get(r["DS_TIPO_FORNECEDOR"], ""),
            r["NM_FORNECEDOR_RFB"] if r["NM_FORNECEDOR_RFB"] not in ("#NULO", "#NULO#") else r["NM_FORNECEDOR"],
            r["CD_CNAE_FORNECEDOR"], r["DS_CNAE_FORNECEDOR"], r["SG_UF_FORNECEDOR"], r["NM_MUNICIPIO_FORNECEDOR"],
            _int(r["SQ_CANDIDATO_FORNECEDOR"]), r["DS_CARGO_FORNECEDOR"], r["SG_PARTIDO_FORNECEDOR"],
            r["DS_ORIGEM_DESPESA"], (r["DS_DESPESA"] or "")[:200], _data_iso(r["DT_DESPESA"]),
            _valor(r["VR_DESPESA_CONTRATADA"]),
        )
        for r in zipremoto.linhas_csv(URL_2026, "despesas_contratadas_candidatos_2026_BRASIL.csv")
    ))

    _estado["etapa"] = "pagamentos de 2026"
    _inserir(conn, "INSERT INTO pagamentos VALUES (?,?,?)", (
        (_int(r["SQ_DESPESA"]), _fonte_curta(r["DS_FONTE_DESPESA"]), _valor(r["VR_PAGTO_DESPESA"]))
        for r in zipremoto.linhas_csv(URL_2026, "despesas_pagas_candidatos_2026_BRASIL.csv")
    ))

    _estado["etapa"] = "receitas de 2026"
    _inserir(conn, "INSERT INTO receitas VALUES (?,?,?,?,?,?,?)", (
        (
            lembrar(r, r.get("DS_GENERO")), r["NR_CPF_CNPJ_DOADOR"],
            r["NM_DOADOR_RFB"] if r["NM_DOADOR_RFB"] not in ("#NULO", "#NULO#") else r["NM_DOADOR"],
            _fonte_curta(r["DS_FONTE_RECEITA"]), r["DS_ORIGEM_RECEITA"], _int(r["SQ_CANDIDATO_DOADOR"]),
            _valor(r["VR_RECEITA"]),
        )
        for r in zipremoto.linhas_csv(URL_2026, "receitas_candidatos_2026_BRASIL.csv")
    ))
    conn.executemany("INSERT INTO candidatos VALUES (?,?,?,?,?,?,?)", ((sq, *c) for sq, c in candidatos.items()))

    _estado["etapa"] = "histórico de fornecedores (2022)"
    hist = defaultdict(lambda: [None, set(), set(), 0.0])
    for r in zipremoto.linhas_csv(URL_2022, "despesas_contratadas_candidatos_2022_BRASIL.csv"):
        doc = r["NR_CPF_CNPJ_FORNECEDOR"]
        if len(doc) != 14:
            continue
        h = hist[doc]
        h[0] = h[0] or r["NM_FORNECEDOR_RFB"] or r["NM_FORNECEDOR"]
        h[1].add(r["SQ_CANDIDATO"])
        h[2].add(r["SG_PARTIDO"])
        h[3] += _valor(r["VR_DESPESA_CONTRATADA"])
    conn.executemany("INSERT INTO hist2022 VALUES (?,?,?,?,?)",
                     ((d, h[0], len(h[1]), len(h[2]), h[3]) for d, h in hist.items()))
    del hist

    _estado["etapa"] = "índices"
    conn.executescript(INDICES)
    conn.execute("INSERT INTO meta VALUES ('geradoEm', ?)", (time.strftime("%Y-%m-%d %H:%M"),))
    conn.commit()
    conn.close()
    # No Windows o banco não pode ser trocado enquanto alguém o lê (uma consulta em andamento): espera e tenta de novo.
    for tentativa in range(30):
        try:
            tmp.replace(destino)
            break
        except PermissionError:
            if tentativa == 29:
                raise
            time.sleep(2)


def _preparar():
    global _sobrenomes, _nomes_candidatos
    try:
        _montar()
        _sobrenomes = _nomes_candidatos = None
        _estado.update(etapa="pronto", erro=None)
    except Exception as e:  # noqa: BLE001 - mostramos o erro na interface
        registrar_falha(e)
        _estado.update(etapa="erro", erro=f"{_estado.get('etapa')}: {e}")
    finally:
        _rodando.clear()


def iniciar():
    """Usa o banco salvo e, se estiver com mais de um dia, refaz em segundo plano."""
    existe = _banco().exists()
    if existe:
        _estado["etapa"] = "pronto"
    velho = not existe or time.time() - _banco().stat().st_mtime > TTL_BANCO
    if velho and not _rodando.is_set():
        _rodando.set()
        if not existe:
            _estado["etapa"] = "baixando"
        threading.Thread(target=_preparar, daemon=True).start()


def status():
    pronto = _banco().exists()
    gerado = None
    if pronto:
        with _conectar() as c:
            gerado = c.execute("SELECT valor FROM meta WHERE chave='geradoEm'").fetchone()[0]
    return {"pronto": pronto, "etapa": _estado["etapa"], "erro": _estado["erro"], "geradoEm": gerado}


def financas(ids):
    """Arrecadação, dinheiro público e gastos de vários candidatos de uma vez, pelo banco local.

    Retorna None se o banco ainda não existe (aí quem chama usa a API do TSE, candidato a candidato).
    """
    if not _banco().exists() or not ids:
        return None
    c = _conectar()
    try:
        saida = {i: {"arrecadado": 0.0, "publico": 0.0, "gastos": 0.0} for i in ids}
        for i in range(0, len(ids), 500):
            lote = ids[i:i + 500]
            marcas = ",".join("?" * len(lote))
            for r in c.execute(
                f"""SELECT sq_candidato, sum(valor) total, sum(CASE WHEN fonte IN ('FEFC','FP') THEN valor ELSE 0 END) publico
                    FROM receitas WHERE sq_candidato IN ({marcas}) GROUP BY sq_candidato""", lote):
                saida[r["sq_candidato"]].update(arrecadado=r["total"] or 0, publico=r["publico"] or 0)
            for r in c.execute(
                f"SELECT sq_candidato, sum(valor) total FROM despesas WHERE sq_candidato IN ({marcas}) GROUP BY sq_candidato", lote):
                saida[r["sq_candidato"]]["gastos"] = r["total"] or 0
        return saida
    finally:
        c.close()


# ---------- Receita Federal ----------

def cnpj(doc):
    """Cadastro da empresa na Receita (via BrasilAPI), com cache de 30 dias. None se indisponível."""
    arq = _pasta() / "cnpj" / f"{doc}.json"
    if arq.exists() and time.time() - arq.stat().st_mtime < TTL_CNPJ:
        return json.loads(arq.read_text(encoding="utf-8")) or None
    try:
        r = requests.get(URL_CNPJ.format(cnpj=doc), impersonate="chrome", timeout=30)
    except Exception:  # noqa: BLE001
        return None
    if r.status_code == 404:
        dados = {}
    elif r.status_code != 200:
        return None
    else:
        d = r.json()
        dados = {
            "razaoSocial": d.get("razao_social"),
            "nomeFantasia": d.get("nome_fantasia"),
            "abertura": d.get("data_inicio_atividade"),
            "situacao": d.get("descricao_situacao_cadastral"),
            "porte": d.get("porte") or d.get("descricao_porte"),
            "mei": bool(d.get("opcao_pelo_mei")),
            "capitalSocial": d.get("capital_social"),
            "cnae": str(d.get("cnae_fiscal") or ""),
            "cnaeDescricao": d.get("cnae_fiscal_descricao"),
            "cnaesSecundarios": [str(x.get("codigo")) for x in d.get("cnaes_secundarios") or [] if x.get("codigo")],
            "municipio": d.get("municipio"),
            "uf": d.get("uf"),
            "socios": [
                {"nome": s.get("nome_socio"), "qualificacao": s.get("qualificacao_socio")}
                for s in d.get("qsa") or []
            ],
        }
    arq.parent.mkdir(parents=True, exist_ok=True)
    arq.write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")
    return dados or None


# ---------- índices auxiliares ----------

def _indices_nomes(c):
    """Sobrenomes (para achar raros) e nomes de todos os candidatos de 2026."""
    global _sobrenomes, _nomes_candidatos
    with _lock:
        if _sobrenomes is None:
            nomes = [_norm(n) for (n,) in c.execute("SELECT nome FROM candidatos")]
            nomes += [_norm(n) for (n,) in c.execute("SELECT DISTINCT nome FROM receitas WHERE length(doc) = 11")]
            _sobrenomes = Counter(n.split()[-1] for n in nomes if n)
            _nomes_candidatos = {
                _norm(r["nome"]): dict(r) for r in c.execute("SELECT sq_candidato, nome, numero, uf, cargo, partido FROM candidatos")
            }
    return _sobrenomes, _nomes_candidatos


def _sobrenome_raro(sobrenomes, nome):
    partes = [p for p in _norm(nome).split() if p not in {"DE", "DA", "DO", "DAS", "DOS", "E", "FILHO", "JUNIOR", "NETO", "SOBRINHO"}]
    if len(partes) < 2:
        return None
    s = partes[-1]
    return s if len(s) >= 4 and sobrenomes.get(s, 0) <= 25 else None


# ---------- rede de um fornecedor ----------

def _rede(c, doc):
    base = c.execute(
        """SELECT count(DISTINCT sq_candidato) candidatos, count(DISTINCT partido) partidos,
                  count(DISTINCT NULLIF(uf, 'BR')) ufs, sum(valor) total, min(data) primeira, max(nome) nome
           FROM despesas WHERE doc = ?""", (doc,)).fetchone()
    por_partido = c.execute(
        "SELECT partido, sum(valor) v FROM despesas WHERE doc = ? GROUP BY partido ORDER BY v DESC", (doc,)).fetchall()
    fontes = dict(c.execute(
        """SELECT p.fonte, sum(p.valor) FROM pagamentos p JOIN despesas d ON d.sq_despesa = p.sq_despesa
           WHERE d.doc = ? GROUP BY p.fonte""", (doc,)).fetchall())
    h = c.execute("SELECT candidatos, partidos, total FROM hist2022 WHERE doc = ?", (doc,)).fetchone()
    total = base["total"] or 0
    pago = sum(fontes.values())
    return {
        "candidatos": base["candidatos"],
        "partidos": base["partidos"],
        "ufs": base["ufs"],
        "total": total,
        "primeiraDespesa": base["primeira"],
        "partidoPrincipal": por_partido[0]["partido"] if por_partido else None,
        "concentracaoPartido": (por_partido[0]["v"] / total) if por_partido and total else None,
        "pago": pago,
        "publico": (fontes.get("FEFC", 0) + fontes.get("FP", 0)) / pago if pago else None,
        "em2022": {"candidatos": h["candidatos"], "partidos": h["partidos"], "total": h["total"]} if h else None,
    }


def _sinais_fornecedor(doc, rede, receita, categorias, candidato=None, doadores=frozenset(), sobrenomes=None, nomes_cand=None,
                       valor=None, parte=None):
    """Indícios sobre um fornecedor. `candidato` = registro do candidato que está sendo analisado."""
    s = []

    def add(nivel, titulo, detalhe, cnpj=None):
        s.append({"nivel": nivel, "titulo": titulo, "detalhe": detalhe, "cnpj": cnpj})

    if receita:
        if receita.get("situacao") and receita["situacao"].upper() != "ATIVA":
            add("alerta", "CNPJ não está ativo", f"Na Receita Federal, a empresa aparece como {receita['situacao'].lower()}.")
        if receita.get("mei") and rede["total"] > LIMITE_MEI:
            desta = valor if valor is not None else rede["total"]
            nivel = "alerta" if desta > LIMITE_MEI_TOLERANCIA else "atencao"
            add(nivel, "MEI recebendo acima do limite anual",
                f"A empresa é MEI e já recebeu R$ {_milhar(rede['total'])} de campanhas em 2026, acima do limite de "
                "R$ 81 mil por ano que um MEI pode faturar. O excesso é um problema do fornecedor; para esta campanha, "
                "pesa conforme o quanto ela pagou.")
        cap = receita.get("capitalSocial")
        if cap is not None and cap < 10_000 and rede["total"] > 1_000_000:
            add("info", "Capital social baixo para o volume",
                f"A empresa declara capital social de R$ {_milhar(cap)} e já recebeu R$ {_milhar(rede['total'])} de campanhas.")
        atividades = {receita.get("cnae", "")[:2]} | {x[:2] for x in receita.get("cnaesSecundarios", [])}
        for cat in categorias if (valor if valor is not None else rede["total"]) >= 20_000 else []:
            esperadas = ATIVIDADES_ESPERADAS.get(cat)
            if esperadas and not (esperadas & atividades):
                add("atencao", "Atividade registrada não combina com o serviço",
                    f"A empresa foi contratada para {cat.lower()}, mas nenhuma das atividades registradas na Receita é "
                    f"desse ramo. A atividade principal dela é {(receita.get('cnaeDescricao') or 'não informada').lower()}.")
                break
        if candidato:
            nome_cand = _norm(candidato["nome"])
            raro = _sobrenome_raro(sobrenomes or {}, candidato["nome"])
            for socio in receita.get("socios", []):
                n = _norm(socio["nome"])
                if not n:
                    continue
                if n == nome_cand:
                    add("alerta", "Empresa do próprio candidato", f"{socio['nome']} aparece entre os sócios da empresa.")
                elif n in doadores:
                    add("atencao", "Sócio do fornecedor doou para a campanha",
                        f"{socio['nome']} é sócio da empresa e também doou para esta campanha.")
                elif n in candidato.get("pagosPf", ()):
                    add("atencao", "Sócio do fornecedor também foi pago pela campanha",
                        f"{socio['nome']} é sócio da empresa e também recebeu pagamento desta campanha como pessoa física "
                        "(por exemplo, como coordenador ou prestador de serviço).")
                elif nomes_cand and n in nomes_cand and nomes_cand[n]["uf"] == receita.get("uf"):
                    # Mesmo estado da empresa, para não confundir homônimos.
                    o = nomes_cand[n]
                    add("info", "Sócio é candidato em 2026",
                        f"{socio['nome']}, sócio da empresa, disputa o cargo de {tse.CARGOS.get(o['cargo'], 'cargo').lower()} "
                        f"pelo {o['partido']} em {o['uf']}.")
                elif raro and n.split()[-1] == raro:
                    add("atencao", "Sócio com o mesmo sobrenome do candidato",
                        f"{socio['nome']}, sócio da empresa, tem o sobrenome {raro.title()}, que é pouco comum. Pode ser "
                        "coincidência ou parentesco.")
    if rede["candidatos"] == 1 and rede["total"] > 200_000 and not rede["em2022"]:
        add("info", "Fornecedor exclusivo e estreante",
            "A empresa atende só esta campanha em 2026 e não trabalhou em campanhas em 2022.")
    if rede["concentracaoPartido"] and rede["candidatos"] >= 5 and rede["concentracaoPartido"] > 0.9:
        add("info", "Atende quase só um partido",
            f"{rede['concentracaoPartido']:.0%} do que a empresa recebeu veio de campanhas do {rede['partidoPrincipal']}.")
    if receita and receita.get("abertura"):
        abertura = date.fromisoformat(receita["abertura"])
        dias = (INICIO_CAMPANHA - abertura).days
        if dias < 180:
            quando = "depois que a campanha começou" if dias < 0 else f"{dias} dias antes de a campanha começar"
            clientes = ("e atende só esta campanha" if rede["candidatos"] == 1 else
                        f"e atende {rede['candidatos']} campanhas em 2026")
            # Empresa nova, sozinha, é comum (negócios abrem o tempo todo). Só tira pontos se atende só esta campanha
            # (ou quase) e há mais um indício: aberta às vésperas, peso grande nos gastos ou outro problema acima.
            exclusiva = rede["candidatos"] <= 3
            outro = any(x["nivel"] in ("atencao", "alerta") for x in s)
            socios = [x["nome"].title() for x in receita.get("socios", []) if x.get("nome")]
            quem = (f" Sócio(s): {', '.join(socios[:3])}." if socios else "")
            capital = receita.get("capitalSocial")
            if capital and valor and valor >= 20 * capital:
                quem += f" O capital declarado é de R$ {_milhar(capital)}, bem menor que o valor recebido."
            vespera = dias < 60
            # Proporção, não valor absoluto: R$ 1 milhão é muito para um deputado e pouco para uma campanha presidencial.
            muito = (parte or 0) >= 0.20 and (valor or 0) >= 10_000  # e um piso, para campanhas minúsculas não levarem alerta por troco
            recebido = f"recebeu R$ {_milhar(valor or 0)}" + (f", {parte:.1%} dos gastos da campanha".replace(".", ",") if parte else "")
            motivo = (recebido if dias < 60 else
                      f"recebeu {parte:.0%} dos gastos da campanha" if parte and parte >= 0.10 else
                      "há outro ponto sobre ela acima" if outro else None)
            if exclusiva and vespera and muito:
                add("alerta", "Empresa aberta às vésperas recebeu grande parte dos gastos",
                    f"A empresa foi aberta em {abertura:%d/%m/%Y}, {quando}, {clientes}, e recebeu R$ {_milhar(valor or 0)}"
                    f"{f' ({parte:.0%} dos gastos)' if parte else ''}. É o padrão de empresa criada para a campanha.{quem}")
            elif exclusiva and motivo:
                add("atencao", "Empresa aberta pouco antes da campanha",
                    f"A empresa foi aberta em {abertura:%d/%m/%Y}, {quando}, {clientes}, e {motivo}. "
                    f"Às vezes ela é criada justamente para a campanha.{quem}")
            else:
                add("info", "Empresa aberta pouco antes da campanha",
                    f"A empresa foi aberta em {abertura:%d/%m/%Y}, {quando}, {clientes}. "
                    + ("Empresa nova não é problema por si só; não tira pontos." if exclusiva else
                       "Por atender várias campanhas, tende a ser um negócio novo do ramo, e não tira pontos.") + quem)
    return s


# ---------- análise de um candidato ----------

_cache_pares = {}


def _gastos_por_candidato(c, uf, cargo):
    """Gastos por categoria de todas as campanhas de um cargo no estado (guardado enquanto o banco não muda)."""
    chave = (uf, cargo, _banco().stat().st_mtime)
    with _lock:
        if chave in _cache_pares:
            return _cache_pares[chave]
    linhas = c.execute(
        "SELECT sq_candidato, origem, sum(valor) v FROM despesas WHERE uf = ? AND cargo = ? GROUP BY 1, 2", (uf, cargo)).fetchall()
    por_cand = defaultdict(dict)
    for r in linhas:
        por_cand[r["sq_candidato"]][r["origem"]] = r["v"]
    totais = {k: sum(v.values()) for k, v in por_cand.items()}
    with _lock:
        _cache_pares[chave] = (por_cand, totais)
    return por_cand, totais


def _medianas_pares(c, uf, cargo, total):
    """Composição mediana dos gastos de campanhas de tamanho parecido (mesmo cargo e UF).

    Comparar uma campanha de R$ 3 milhões com a mediana de todas (a maioria gasta
    quase nada) faria qualquer campanha grande parecer diferente.
    """
    por_cand, totais = _gastos_por_candidato(c, uf, cargo)
    todos = [k for k, t in totais.items() if t >= 10_000]
    mediana_total = statistics.median(totais[k] for k in todos) if todos else None
    validos = todos
    for fator in (2, 4):
        faixa = [k for k in todos if total / fator <= totais[k] <= total * fator]
        if len(faixa) >= 10:
            validos = faixa
            break
    categorias = {o for k in validos for o in por_cand[k]}
    medianas = {
        cat: statistics.median(por_cand[k].get(cat, 0) / totais[k] for k in validos)
        for cat in categorias
    } if validos else {}
    return medianas, len(validos), mediana_total


def analisar_candidato(sq_candidato, ficha_nome=None, max_receita=15, nome_urna=None):
    if not _banco().exists():
        return {"pronto": False, "status": status()}
    c = _conectar()
    try:
        cand = c.execute("SELECT * FROM candidatos WHERE sq_candidato = ?", (sq_candidato,)).fetchone()
        despesas = c.execute("SELECT * FROM despesas WHERE sq_candidato = ?", (sq_candidato,)).fetchall()
        total = sum(d["valor"] for d in despesas)
        # Despesas que somam zero (lançamentos estornados, por exemplo) contam como campanha sem gastos.
        if not cand or not despesas or total <= 0:
            return {"pronto": True, "semDados": True, "status": status()}
        cand = dict(cand)

        # Fontes do dinheiro que já foi pago
        fontes = dict(c.execute(
            """SELECT p.fonte, sum(p.valor) FROM pagamentos p JOIN despesas d ON d.sq_despesa = p.sq_despesa
               WHERE d.sq_candidato = ? GROUP BY p.fonte""", (sq_candidato,)).fetchall())
        pago = sum(fontes.values())

        # Composição comparada aos pares (mesmo cargo e UF)
        por_cat = Counter()
        for d in despesas:
            por_cat[d["origem"]] += d["valor"]
        medianas, n_pares, mediana_total = _medianas_pares(c, cand["uf"], cand["cargo"], total)
        composicao = [
            {"categoria": k, "valor": v, "parte": v / total, "medianaPares": medianas.get(k, 0)}
            for k, v in por_cat.most_common(8)
        ]

        # Pessoas físicas
        pf = [d for d in despesas if d["tipo"] == "PF" and d["origem"] != CATEGORIA_REPASSE]
        por_pessoa = Counter()
        for d in pf:
            por_pessoa[d["doc"] or d["nome"]] += d["valor"]

        # Fornecedores (empresas)
        pj = defaultdict(lambda: {"valor": 0.0, "categorias": Counter(), "nome": None, "cnae": None, "municipio": None,
                                  "candidatoFornecedor": None})
        for d in despesas:
            if d["tipo"] != "PJ" or not d["doc"] or d["origem"] == CATEGORIA_REPASSE:
                continue
            f = pj[d["doc"]]
            f["valor"] += d["valor"]
            f["categorias"][d["origem"]] += d["valor"]
            f["nome"] = f["nome"] or d["nome"]
            f["cnae"] = f["cnae"] or d["cnae_desc"]
            f["municipio"] = f["municipio"] or (f"{d['mun_forn']}/{d['uf_forn']}" if d["mun_forn"] not in ("#NULO", None) else None)
        total_pj = sum(f["valor"] for f in pj.values())
        ordenados = sorted(pj.items(), key=lambda kv: -kv[1]["valor"])

        doadores = {_norm(n) for (n,) in c.execute(
            "SELECT DISTINCT nome FROM receitas WHERE sq_candidato = ? AND length(doc) = 11", (sq_candidato,))}
        sobrenomes, nomes_cand = _indices_nomes(c)
        nome_ref = {"nome": ficha_nome or cand["nome"], "pagosPf": {_norm(d["nome"]) for d in pf if d["nome"]}}

        fornecedores = []
        for i, (doc, f) in enumerate(ordenados[:25]):
            rede = _rede(c, doc)
            receita = cnpj(doc) if i < max_receita else None
            fornecedores.append({
                "cnpj": doc, "nome": f["nome"], "valor": f["valor"], "parte": f["valor"] / total if total else 0,
                "categorias": [k for k, _ in f["categorias"].most_common(3)],
                "atividade": f["cnae"], "municipio": f["municipio"],
                "rede": rede,
                "receita": {k: receita.get(k) for k in ("abertura", "situacao", "porte", "mei", "capitalSocial")} if receita else None,
                "sinais": _sinais_fornecedor(doc, rede, receita, list(f["categorias"]), nome_ref, doadores, sobrenomes, nomes_cand,
                                             f["valor"], f["valor"] / total if total else None),
            })

        # Fornecedores em comum com outros candidatos do mesmo partido e estado
        docs = [
            d for d, _ in ordenados
            if c.execute("SELECT count(DISTINCT sq_candidato) FROM despesas WHERE doc = ?", (d,)).fetchone()[0]
            <= MAX_CLIENTES_COMPARTILHADO
        ]
        compartilhados = []
        if docs:
            marcas = ",".join("?" * len(docs))
            rows = c.execute(
                f"""SELECT d.sq_candidato, count(DISTINCT d.doc) n, sum(d.valor) v
                    FROM despesas d WHERE d.doc IN ({marcas}) AND d.sq_candidato != ? AND d.partido = ? AND d.uf = ?
                    GROUP BY d.sq_candidato ORDER BY n DESC, v DESC LIMIT 8""",
                (*docs, sq_candidato, cand["partido"], cand["uf"])).fetchall()
            for r in rows:
                outro = c.execute("SELECT nome, numero, cargo FROM candidatos WHERE sq_candidato = ?", (r["sq_candidato"],)).fetchone()
                comuns = [d for (d,) in c.execute(
                    f"SELECT DISTINCT doc FROM despesas WHERE sq_candidato = ? AND doc IN ({marcas})", (r["sq_candidato"], *docs))]
                gasto_comum = sum(pj[d]["valor"] for d in comuns)
                total_outro = c.execute("SELECT sum(valor) FROM despesas WHERE sq_candidato = ?", (r["sq_candidato"],)).fetchone()[0]
                compartilhados.append({
                    "nome": outro["nome"] if outro else "?", "numero": outro["numero"] if outro else None,
                    "cargo": tse.CARGOS.get(outro["cargo"]) if outro else None,
                    "fornecedoresEmComum": r["n"], "gastoComum": gasto_comum,
                    "parteDoGasto": gasto_comum / total_pj if total_pj else 0, "totalOutro": total_outro,
                })

        # Repasses para outros candidatos e vindos deles
        enviados = [
            {"nome": d["nome"], "valor": d["valor"], "cargo": d["cargo_forn"], "partido": d["partido_forn"]}
            for d in despesas if d["origem"] == CATEGORIA_REPASSE or d["sq_cand_forn"] not in (-1, None)
        ]
        recebidos = [dict(r) for r in c.execute(
            """SELECT c2.nome, c2.cargo, c2.partido, sum(r.valor) valor FROM receitas r
               LEFT JOIN candidatos c2 ON c2.sq_candidato = r.sq_cand_doador
               WHERE r.sq_candidato = ? AND r.sq_cand_doador NOT IN (-1, r.sq_candidato)
               GROUP BY r.sq_cand_doador ORDER BY valor DESC""",
            (sq_candidato,))]
        receitas_total = c.execute("SELECT sum(valor) FROM receitas WHERE sq_candidato = ?", (sq_candidato,)).fetchone()[0] or 0
        receita_fefc = c.execute("SELECT sum(valor) FROM receitas WHERE sq_candidato = ? AND fonte = 'FEFC'",
                                 (sq_candidato,)).fetchone()[0] or 0

        plataformas = {f["cnpj"] for f in fornecedores if f["rede"]["candidatos"] > MIN_CLIENTES_PLATAFORMA}
        nome_urna = _norm(nome_urna or ficha_nome or cand["nome"])
        coletivo = any(p in nome_urna for p in ("BANCADA", "COLETIV", "MANDATO", "JUNTAS", "JUNTOS"))
        # Agência do partido: os fornecedores em comum atendem muitas campanhas do mesmo partido no estado.
        agencia_partido = bool(docs) and c.execute(
            f"""SELECT count(DISTINCT sq_candidato) FROM despesas
                WHERE doc IN ({",".join("?" * len(docs))}) AND partido = ? AND uf = ?""",
            (*docs, cand["partido"], cand["uf"])).fetchone()[0] >= 10
        sinais = _sinais_candidato(cand, total, total_pj, ordenados, composicao, mediana_total, por_pessoa,
                                   compartilhados, receitas_total, receita_fefc, plataformas, coletivo, agencia_partido)
        voltou = _doou_e_recebeu(c, sq_candidato)
        sinais += _sinais_doou_e_recebeu(voltou)
        return {
            "pronto": True,
            "geradoEm": status()["geradoEm"],
            "total": total,
            "pago": pago,
            "fontes": {"fundoEleitoral": fontes.get("FEFC", 0), "fundoPartidario": fontes.get("FP", 0), "outros": fontes.get("OUTROS", 0)},
            "composicao": composicao,
            "pares": {"quantidade": n_pares, "medianaTotal": mediana_total, "cargo": tse.CARGOS.get(cand["cargo"]), "uf": cand["uf"]},
            "concentracao": {
                "maiorFornecedor": ordenados[0][1]["nome"] if ordenados else None,
                "parte": ordenados[0][1]["valor"] / total if ordenados and total else 0,
            },
            "pessoasFisicas": {
                "pessoas": len(por_pessoa), "total": sum(por_pessoa.values()),
                "maiorValor": max(por_pessoa.values()) if por_pessoa else 0,
            },
            "fornecedores": fornecedores,
            "totalFornecedores": len(pj),
            "compartilhados": compartilhados,
            "repasses": {"enviados": enviados, "recebidos": recebidos},
            "sinais": sinais,
            "doouERecebeu": voltou,
            "doadoresRede": _doadores_rede(c, sq_candidato),
        }
    finally:
        c.close()


def _sinais_candidato(cand, total, total_pj, ordenados, composicao, mediana_total, por_pessoa, compartilhados,
                      receitas_total, receita_fefc, plataformas=frozenset(), coletivo=False, agencia_partido=False):
    s = []

    def add(nivel, titulo, detalhe, cnpj=None):
        s.append({"nivel": nivel, "titulo": titulo, "detalhe": detalhe, "cnpj": cnpj})

    principais = [(d, f) for d, f in ordenados if d not in plataformas]
    if principais and total > 100_000 and principais[0][1]["valor"] / total > 0.5:
        add("atencao", "Gasto concentrado em um fornecedor",
            f"{principais[0][1]['valor'] / total:.0%} das despesas da campanha foram para {principais[0][1]['nome']}. "
            "Plataformas de anúncio e de pagamento, que atendem centenas de campanhas, não entram nesta conta.",
            cnpj=principais[0][0] if len(principais[0][0]) == 14 else None)
    for item in composicao[:4]:
        if item["parte"] > 0.3 and item["parte"] > 2.5 * max(item["medianaPares"], 0.02):
            add("info", f"Gasta mais que o comum com {item['categoria'].lower()}",
                f"Esse tipo de despesa leva {item['parte']:.0%} do dinheiro, contra {item['medianaPares']:.0%} numa campanha "
                "típica do mesmo porte para o mesmo cargo no estado.")
    if por_pessoa and max(por_pessoa.values()) > 50_000:
        add("info", "Pagamento alto a uma pessoa física",
            f"Uma só pessoa recebeu R$ {_milhar(max(por_pessoa.values()))} da campanha.")
    feminino = (cand.get("genero") or "").lower().startswith("fem")
    if feminino and not coletivo and not agencia_partido and receitas_total > 50_000             and receita_fefc / receitas_total > 0.8 and compartilhados:
        top = max(compartilhados, key=lambda x: x["parteDoGasto"])
        if top["parteDoGasto"] > 0.5 and (top["totalOutro"] or 0) > total:
            add("info", "Gastos parecidos com os de outra campanha do partido",
                f"A campanha é quase toda paga pelo Fundo Eleitoral, e {top['parteDoGasto']:.0%} do gasto com empresas foi para "
                f"fornecedores que também atendem {top['nome']}, uma candidatura maior do mesmo partido. Esse padrão já apareceu "
                "em candidaturas de mulheres usadas só para cumprir a cota, mas também acontece quando o partido contrata a "
                "mesma agência para todos. Antes da apuração é um indício fraco; a votação e as contas finais ajudam a "
                "tirar a dúvida.")
    return s


# ---------- fornecedor e panorama ----------

def fornecedor(doc):
    if not _banco().exists():
        return {"pronto": False, "status": status()}
    c = _conectar()
    try:
        rede = _rede(c, doc)
        if not rede["candidatos"]:
            return None
        clientes = [dict(r) for r in c.execute(
            """SELECT d.sq_candidato, c.nome, c.numero, c.cargo, d.partido, d.uf, sum(d.valor) valor
               FROM despesas d LEFT JOIN candidatos c ON c.sq_candidato = d.sq_candidato
               WHERE d.doc = ? GROUP BY d.sq_candidato ORDER BY valor DESC LIMIT 40""", (doc,))]
        for x in clientes:
            x["cargo"] = tse.CARGOS.get(x["cargo"])
        categorias = [dict(r) for r in c.execute(
            "SELECT origem categoria, sum(valor) valor FROM despesas WHERE doc = ? GROUP BY origem ORDER BY valor DESC LIMIT 6",
            (doc,))]
        receita = cnpj(doc)
        return {
            "cnpj": doc,
            "nome": c.execute("SELECT max(nome) FROM despesas WHERE doc = ?", (doc,)).fetchone()[0],
            "rede": rede,
            "clientes": clientes,
            "categorias": categorias,
            "receita": receita,
            "sinais": _sinais_fornecedor(doc, rede, receita, [x["categoria"] for x in categorias]),
        }
    finally:
        c.close()


_panoramas = {}


def panorama(uf, limite=200):
    if not _banco().exists():
        return {"pronto": False, "status": status()}
    guardado = _panoramas.get(uf)
    if guardado and time.time() - guardado[0] < TTL_PANORAMA and guardado[1]["geradoEm"] == status()["geradoEm"]:
        return guardado[1]
    resultado = _panorama(uf, limite)
    _panoramas[uf] = (time.time(), resultado)
    return resultado


def _panorama(uf, limite):
    c = _conectar()
    try:
        linhas = c.execute(
            """SELECT doc, max(nome) nome, sum(valor) total, count(DISTINCT sq_candidato) candidatos,
                      count(DISTINCT partido) partidos, max(cnae_desc) atividade
               FROM despesas WHERE uf = ? AND tipo = 'PJ' AND doc IS NOT NULL AND origem != ?
               GROUP BY doc ORDER BY total DESC LIMIT ?""", (uf, CATEGORIA_REPASSE, limite)).fetchall()
        saida = []
        for r in linhas:
            h = c.execute("SELECT candidatos FROM hist2022 WHERE doc = ?", (r["doc"],)).fetchone()
            nacional = c.execute("SELECT count(DISTINCT sq_candidato), count(DISTINCT NULLIF(uf, 'BR')) FROM despesas WHERE doc = ?",
                                 (r["doc"],)).fetchone()
            principal = c.execute(
                "SELECT partido, sum(valor) v FROM despesas WHERE doc = ? AND uf = ? GROUP BY partido ORDER BY v DESC LIMIT 1",
                (r["doc"], uf)).fetchone()
            saida.append({
                "cnpj": r["doc"], "nome": r["nome"], "total": r["total"], "candidatos": r["candidatos"],
                "partidos": r["partidos"], "atividade": r["atividade"],
                "partidoPrincipal": principal["partido"], "concentracaoPartido": principal["v"] / r["total"] if r["total"] else None,
                "candidatosPais": nacional[0], "ufs": nacional[1], "em2022": h["candidatos"] if h else 0,
            })
        total_uf = c.execute("SELECT sum(valor) FROM despesas WHERE uf = ? AND origem != ?", (uf, CATEGORIA_REPASSE)).fetchone()[0]
        return {"pronto": True, "geradoEm": status()["geradoEm"], "uf": uf, "totalUf": total_uf, "fornecedores": saida}
    finally:
        c.close()


# ---------- doadores ----------

# Doação de pessoa física que não é do próprio candidato (recursos próprios ficam de fora).
_DOACAO_PF = "length(doc) = 11 AND origem NOT LIKE '%rópri%' AND origem NOT LIKE '%ropri%'"
DOOU_MINIMO = 5_000


def _doou_e_recebeu(c, sq_candidato):
    """Pessoas que doaram para a campanha e também foram pagas por ela (pelo CPF, que não sai daqui)."""
    doacoes = {r["doc"]: (r["nome"], r["v"]) for r in c.execute(
        f"SELECT doc, max(nome) nome, sum(valor) v FROM receitas WHERE sq_candidato = ? AND {_DOACAO_PF} GROUP BY doc",
        (sq_candidato,))}
    if not doacoes:
        return []
    saida = []
    for r in c.execute("SELECT doc, sum(valor) v FROM despesas WHERE sq_candidato = ? AND length(doc) = 11 GROUP BY doc",
                       (sq_candidato,)):
        if r["doc"] in doacoes:
            nome, doou = doacoes[r["doc"]]
            saida.append({"nome": nome, "doou": doou, "recebeu": r["v"]})
    return sorted(saida, key=lambda x: -x["recebeu"])


def _sinais_doou_e_recebeu(lista):
    """Vale conferir só quando a doação foi relevante (R$ 5 mil ou mais) e a pessoa recebeu de volta mais do que doou.
    Doar pouco e trabalhar na campanha é comum; o padrão que chama atenção é o dinheiro voltar maior."""
    fortes = [x for x in lista if x["doou"] >= DOOU_MINIMO and x["recebeu"] > x["doou"]]
    if not fortes:
        return []
    exemplos = "; ".join(f"{x['nome'].title()} doou R$ {_milhar(x['doou'])} e recebeu R$ {_milhar(x['recebeu'])}"
                         for x in fortes[:3])
    quem = "Uma pessoa doou" if len(fortes) == 1 else f"{len(fortes)} pessoas doaram"
    return [{"nivel": "atencao", "titulo": "Doador recebeu da campanha mais do que doou",
             "detalhe": f"{quem} R$ {_milhar(DOOU_MINIMO)} ou mais para a campanha e depois recebeu dela, como pagamento, "
                        f"mais do que doou: {exemplos}. Pode ser alguém da equipe que também contribuiu, mas também é um "
                        "jeito de o dinheiro doado voltar para quem doou.", "cnpj": None}]


def _doadores_rede(c, sq_candidato, minimo=5):
    """Quem doou para esta campanha e também doou para muitos outros candidatos (5 ou mais), de quantos partidos."""
    doadores = c.execute(
        f"""SELECT doc, max(nome) nome, sum(valor) v FROM receitas WHERE sq_candidato = ? AND {_DOACAO_PF}
            GROUP BY doc ORDER BY v DESC LIMIT 40""", (sq_candidato,)).fetchall()
    if not doadores:
        return []
    aqui = {r["doc"]: (r["nome"], r["v"]) for r in doadores}
    marcas = ",".join("?" * len(aqui))
    saida = []
    for r in c.execute(
            f"""SELECT r.doc, count(DISTINCT r.sq_candidato) candidatos, count(DISTINCT c.partido) partidos, sum(r.valor) total,
                       group_concat(DISTINCT c.partido) siglas
                FROM receitas r LEFT JOIN candidatos c ON c.sq_candidato = r.sq_candidato
                WHERE r.doc IN ({marcas}) AND r.origem NOT LIKE '%rópri%' GROUP BY r.doc""", list(aqui)):
        if r["candidatos"] >= minimo:
            nome, valor = aqui[r["doc"]]
            saida.append({"nome": nome, "aqui": valor, "candidatos": r["candidatos"], "partidos": r["partidos"],
                          "total": r["total"], "siglas": sorted((r["siglas"] or "").split(","))[:8]})
    return sorted(saida, key=lambda x: -x["total"])
