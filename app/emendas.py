"""Emendas parlamentares federais, pelo arquivo completo do Portal da Transparência.

O arquivo traz, para cada emenda, o autor, o tipo (com finalidade definida ou
transferência especial, a "emenda Pix"), o município e a área, e, para cada pagamento,
quem recebeu o dinheiro (CNPJ, natureza jurídica e município). Guardamos só as emendas
individuais desde 2019 num SQLite local, refeito uma vez por semana.

O que é "estranho" aqui é sempre sobre quem recebeu, nunca sobre a emenda existir:
- entidade privada que também trabalhou para a campanha ou doou para ela;
- uma única entidade privada concentrando boa parte das emendas;
- entidade privada aberta pouco antes de receber, ou com sanção (só na ficha completa).
"""
import csv
import io
import re
import sqlite3
import statistics
import threading
import time
import unicodedata
import zipfile
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor

from curl_cffi import requests

import tse

URL = "https://portaldatransparencia.gov.br/download-de-dados/emendas-parlamentares/UNICO"
URL_TRANSFEREGOV = "https://api.transferegov.gestao.gov.br/transferenciasespeciais/"
TTL = 7 * 24 * tse.HORA
DESDE = 2019
MANDATO_ATUAL = 2023
LIMITE_DEPENDENTE = 2_000_000
# Emendas Pix de até este ano já tiveram tempo para a prefeitura publicar o plano e o relatório.
ANO_COM_PRAZO = time.localtime().tm_year - 1
# Parte do dinheiro com rastro: emenda com finalidade definida (tem objeto e convênio) ou emenda Pix cuja
# prefeitura publicou o relatório de gestão. O plano de trabalho não serve de medida porque, desde que o STF
# passou a exigi-lo, quase todas as emendas Pix o têm.
SQL_RASTREAVEL = """sum(CASE WHEN NOT e.pix THEN e.empenhado
                             WHEN EXISTS (SELECT 1 FROM pix_planos p WHERE p.codigo = e.codigo AND p.relatorio)
                             THEN e.empenhado ELSE 0 END) / sum(e.empenhado)"""

# Natureza jurídica -> grupo que a interface mostra.
PUBLICO_MUNICIPAL = {"Município", "Fundo Público da Administração Direta Municipal", "Órgão Público do Poder Executivo Municipal",
                     "Autarquia Municipal", "Fundação Pública de Direito Público Municipal", "Consórcio Público de Direito Público (Associação Pública)"}
SEM_FINS = {"Associação Privada", "Fundação Privada", "Organização Religiosa", "Organização Social (OS)",
            "Serviço Social Autônomo", "Entidade Sindical", "Cooperativa"}
EMPRESA = {"Sociedade Empresária Limitada", "Empresário (Individual)", "Sociedade Anônima Fechada", "Sociedade Anônima Aberta",
           "Empresa Individual de Responsabilidade Limitada (de Natureza Empresária)", "Sociedade Simples Limitada",
           "Sociedade Simples Pura", "Consórcio de Sociedades", "Sociedade Empresária em Nome Coletivo"}
# Hospitais filantrópicos e APAEs recebem muito por natureza; não contam como concentração estranha.
FILANTROPIA_COMUM = ("SANTA CASA", "HOSPITAL", "IRMANDADE", "APAE", "PESTALOZZI", "BENEFICENCIA", "BENEFICENTE", "MISERICORDIA")

_lock = threading.Lock()
_rodando = threading.Event()
_estado = {"etapa": "parado", "erro": None}


def normalizar(nome):
    sem = unicodedata.normalize("NFKD", nome or "").encode("ascii", "ignore").decode()
    return " ".join(re.sub(r"[^A-Z0-9 ]", " ", sem.upper()).split())


def grupo_natureza(natureza):
    if natureza in PUBLICO_MUNICIPAL:
        return "prefeituras"
    if natureza in SEM_FINS:
        return "semFins"
    if natureza in EMPRESA:
        return "empresas"
    if "Estadual" in natureza or natureza == "Estado ou Distrito Federal":
        return "estados"
    return "outrosPublicos"


def _pasta():
    p = tse._cache_dir / "emendas"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _banco():
    return _pasta() / "emendas.sqlite"


def _valor(txt):
    try:
        return float((txt or "0").replace(".", "").replace(",", "."))
    except ValueError:
        return 0.0


def _tabela_transferegov(nome, campos):
    """Baixa uma tabela inteira da API do Transferegov, em páginas de mil linhas."""
    with requests.Session(impersonate="chrome") as s:
        r = s.get(f"{URL_TRANSFEREGOV}{nome}?select={campos}&limit=1", headers={"Prefer": "count=exact"}, timeout=60)
        r.raise_for_status()
        total = int(r.headers["content-range"].rsplit("/", 1)[-1])

        def pagina(inicio):
            for tentativa in range(4):
                try:
                    resp = s.get(f"{URL_TRANSFEREGOV}{nome}?select={campos}&order=id_plano_acao&limit=1000&offset={inicio}", timeout=120)
                    resp.raise_for_status()
                    return resp.json()
                except Exception:  # noqa: BLE001 - a API às vezes falha numa página; tentamos de novo
                    time.sleep(2 * (tentativa + 1))
            raise RuntimeError(f"Transferegov não respondeu ({nome})")

        with ThreadPoolExecutor(max_workers=4) as pool:
            return [linha for bloco in pool.map(pagina, range(0, total, 1000)) for linha in bloco]


def _rastro_pix(c):
    """Para cada emenda Pix, se a prefeitura publicou plano de trabalho aprovado ou relatório de gestão."""
    _estado["etapa"] = "baixando os planos das emendas Pix"
    planos = _tabela_transferegov("plano_acao_especial",
                                  "id_plano_acao,numero_emenda_parlamentar_plano_acao,situacao_plano_acao,valor_custeio_plano_acao,valor_investimento_plano_acao")
    trabalho = {x["id_plano_acao"]: x["situacao_plano_trabalho"]
                for x in _tabela_transferegov("plano_trabalho_especial", "id_plano_acao,situacao_plano_trabalho")}
    relatorios = {x["id_plano_acao"] for x in _tabela_transferegov("relatorio_gestao_novo_especial", "id_plano_acao,situacao_relatorio_gestao_novo")
                  if x["situacao_relatorio_gestao_novo"] == "DISPONIBILIZADO"}
    relatorios |= {x["id_plano_acao"] for x in _tabela_transferegov("relatorio_gestao_especial", "id_plano_acao,situacao_relatorio_gestao")
                   if x["situacao_relatorio_gestao"] == "DISPONIBILIZADO"}
    c.executemany("INSERT INTO pix_planos VALUES (?,?,?,?,?,?)", [
        (p["numero_emenda_parlamentar_plano_acao"], p["id_plano_acao"], p["situacao_plano_acao"],
         (p["valor_custeio_plano_acao"] or 0) + (p["valor_investimento_plano_acao"] or 0),
         trabalho.get(p["id_plano_acao"]), p["id_plano_acao"] in relatorios)
        for p in planos])


def _montar():
    arq = _pasta() / "EmendasParlamentares.zip"
    if not arq.exists() or time.time() - arq.stat().st_mtime > tse.HORA:
        _estado["etapa"] = "baixando o arquivo de emendas"
        tmp = arq.with_suffix(".parcial")
        with requests.Session(impersonate="chrome") as s:
            r = s.get(URL, stream=True, timeout=900)
            r.raise_for_status()
            with open(tmp, "wb") as f:
                for bloco in r.iter_content(chunk_size=1 << 20):
                    f.write(bloco)
        tmp.replace(arq)

    novo = _banco().with_suffix(".novo")
    novo.unlink(missing_ok=True)
    c = sqlite3.connect(novo)
    c.executescript("""
        CREATE TABLE emendas (codigo TEXT, ano INTEGER, pix INTEGER, autor TEXT, localidade TEXT, uf TEXT,
          funcao TEXT, empenhado REAL, pago REAL);
        CREATE TABLE favorecidos (codigo TEXT, autor TEXT, ano INTEGER, pix INTEGER, doc TEXT, nome TEXT,
          natureza TEXT, grupo TEXT, uf TEXT, municipio TEXT, valor REAL);
        CREATE TABLE pix_planos (codigo TEXT, id_plano INTEGER, situacao TEXT, valor REAL, plano_trabalho TEXT, relatorio INTEGER);
        CREATE TABLE meta (chave TEXT PRIMARY KEY, valor TEXT);
    """)

    def linhas(z, nome):
        with z.open(nome) as f:
            yield from csv.DictReader(io.TextIOWrapper(f, encoding="latin-1"), delimiter=";")

    with zipfile.ZipFile(arq) as z:
        _estado["etapa"] = "lendo as emendas"
        lote = []
        for r in linhas(z, "EmendasParlamentares.csv"):
            tipo = r["Tipo de Emenda"]
            if not tipo.startswith("Emenda Individual") or int(r["Ano da Emenda"] or 0) < DESDE:
                continue
            lote.append((r["Código da Emenda"], int(r["Ano da Emenda"]), "Especiais" in tipo,
                         normalizar(r["Nome do Autor da Emenda"]), r["Localidade de aplicação do recurso"], r["UF"],
                         r["Nome Função"], _valor(r["Valor Empenhado"]),
                         _valor(r["Valor Pago"]) + _valor(r["Valor Restos A Pagar Pagos"])))
        c.executemany("INSERT INTO emendas VALUES (?,?,?,?,?,?,?,?,?)", lote)
        _estado["etapa"] = "lendo quem recebeu"
        lote = []
        for r in linhas(z, "EmendasParlamentares_PorFavorecido.csv"):
            tipo = r["Tipo de Emenda"]
            ano = int((r["Ano/Mês"] or "0")[:4] or 0)
            if not tipo.startswith("Emenda Individual") or ano < DESDE:
                continue
            natureza = r["Natureza Jurídica"]
            lote.append((r["Código da Emenda"], normalizar(r["Nome do Autor da Emenda"]), ano, "Especiais" in tipo,
                         r["Código do Favorecido"], r["Favorecido"], natureza, grupo_natureza(natureza),
                         r["UF Favorecido"], r["Município Favorecido"], _valor(r["Valor Recebido"])))
            if len(lote) >= 50_000:
                c.executemany("INSERT INTO favorecidos VALUES (?,?,?,?,?,?,?,?,?,?,?)", lote)
                lote = []
        c.executemany("INSERT INTO favorecidos VALUES (?,?,?,?,?,?,?,?,?,?,?)", lote)

    try:
        _rastro_pix(c)
        rastro_ok = True
    except Exception:  # noqa: BLE001 - sem o Transferegov, seguimos só com o Portal
        rastro_ok = False
    _estado["etapa"] = "organizando"
    c.executescript("""
        CREATE INDEX i_pix_codigo ON pix_planos(codigo);
        CREATE INDEX i_em_autor ON emendas(autor, ano);
        CREATE INDEX i_fav_autor ON favorecidos(autor, ano);
        CREATE INDEX i_fav_doc ON favorecidos(doc);
    """)
    # Referências de todos os autores no mandato atual, para comparar cada um com os colegas.
    partes = defaultdict(Counter)
    for autor, grupo, valor in c.execute("SELECT autor, grupo, sum(valor) FROM favorecidos WHERE ano >= ? GROUP BY autor, grupo",
                                         (MANDATO_ATUAL,)):
        partes[autor][grupo] += valor
    sem_fins = [p["semFins"] / sum(p.values()) for p in partes.values() if sum(p.values()) > 1_000_000]
    pix = [x for (x,) in c.execute(
        "SELECT sum(CASE WHEN pix THEN empenhado ELSE 0 END) / sum(empenhado) FROM emendas WHERE ano >= ? "
        "GROUP BY autor HAVING sum(empenhado) > 1000000", (MANDATO_ATUAL,))]
    c.executemany("INSERT INTO meta VALUES (?, ?)", [
        ("geradoEm", time.strftime("%Y-%m-%d %H:%M")),
        ("medianaSemFins", str(statistics.median(sem_fins) if sem_fins else 0)),
        ("medianaPix", str(statistics.median(pix) if pix else 0)),
        ("rastroPix", "1" if rastro_ok else "0"),
    ])
    c.commit()
    rastro = [x for (x,) in c.execute(f"SELECT {SQL_RASTREAVEL} FROM emendas e WHERE ano >= ? AND ano <= ? GROUP BY autor "
                                      "HAVING sum(empenhado) > 1000000", (MANDATO_ATUAL, ANO_COM_PRAZO))]
    c.execute("INSERT INTO meta VALUES ('medianaRastreavel', ?)", (str(statistics.median(rastro) if rastro else 0),))
    c.commit()
    c.close()
    with _lock:
        novo.replace(_banco())
    arq.unlink(missing_ok=True)


def _preparar():
    try:
        _montar()
        _estado.update(etapa="pronto", erro=None)
    except Exception as e:  # noqa: BLE001 - mostramos o erro na interface
        _estado.update(etapa="erro", erro=str(e))
    finally:
        _rodando.clear()


def iniciar():
    b = _banco()
    if b.exists():
        _estado["etapa"] = "pronto"
    if (not b.exists() or time.time() - b.stat().st_mtime > TTL) and not _rodando.is_set():
        _rodando.set()
        threading.Thread(target=_preparar, daemon=True).start()


def status():
    b = _banco()
    return {"pronto": b.exists(), "etapa": _estado["etapa"], "erro": _estado["erro"],
            "geradoEm": time.strftime("%Y-%m-%d %H:%M", time.localtime(b.stat().st_mtime)) if b.exists() else None}


def _conectar():
    c = sqlite3.connect(f"file:{_banco()}?mode=ro", uri=True, check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c


def _meta(c):
    return {k: v for k, v in c.execute("SELECT chave, valor FROM meta")}


def _campanha(sq_candidato):
    """Documentos (CNPJ/CPF) de fornecedores e doadores da campanha de 2026."""
    import gastos
    if not sq_candidato or not gastos._banco().exists():
        return {}, {}
    g = gastos._conectar()
    try:
        forn = {r[0]: r[1] for r in g.execute(
            "SELECT doc, sum(valor) FROM despesas WHERE sq_candidato = ? AND doc != '' GROUP BY doc", (sq_candidato,))}
        doad = {r[0]: r[1] for r in g.execute(
            "SELECT doc, sum(valor) FROM receitas WHERE sq_candidato = ? AND doc != '' GROUP BY doc", (sq_candidato,))}
        return forn, doad
    finally:
        g.close()


def listar_nomes(nomes):
    return nomes[0] if len(nomes) == 1 else ", ".join(nomes[:-1]) + " e " + nomes[-1]


def _brl(v):
    return "R$ " + f"{v:,.0f}".replace(",", ".")


def autor(nome, sq_candidato=None, desde=MANDATO_ATUAL):
    """Resumo das emendas individuais de um parlamentar, com para onde o dinheiro foi e os sinais."""
    if not nome or not _banco().exists():
        return None
    a = normalizar(nome)
    c = _conectar()
    try:
        tot = c.execute("""SELECT count(*) n, sum(empenhado) emp, sum(pago) pago,
                                  sum(CASE WHEN pix THEN empenhado ELSE 0 END) pix
                           FROM emendas WHERE autor = ? AND ano >= ?""", (a, desde)).fetchone()
        if not tot["n"]:
            return {"quantidade": 0}
        meta = _meta(c)
        rastro = None
        if meta.get("rastroPix") == "1":
            linha = c.execute(f"""SELECT {SQL_RASTREAVEL} parte, sum(e.empenhado) total,
                                        sum(CASE WHEN e.pix THEN 1 ELSE 0 END) pix_n,
                                        sum(CASE WHEN e.pix AND EXISTS (SELECT 1 FROM pix_planos p WHERE p.codigo = e.codigo AND p.relatorio)
                                                 THEN 1 ELSE 0 END) com_relatorio
                                 FROM emendas e WHERE autor = ? AND ano >= ? AND ano <= ?""", (a, desde, ANO_COM_PRAZO)).fetchone()
            if linha["total"]:
                rastro = {"parte": linha["parte"], "ateAno": ANO_COM_PRAZO, "emendasPix": linha["pix_n"],
                          "pixComRelatorio": linha["com_relatorio"], "mediana": float(meta.get("medianaRastreavel") or 0)}
        anos = [dict(r) for r in c.execute(
            "SELECT ano, sum(empenhado) valor FROM emendas WHERE autor = ? AND ano >= ? GROUP BY ano ORDER BY ano", (a, desde))]
        areas = [dict(r) for r in c.execute(
            """SELECT funcao area, sum(empenhado) valor FROM emendas WHERE autor = ? AND ano >= ?
               GROUP BY funcao ORDER BY valor DESC LIMIT 6""", (a, desde))]
        lugares = [dict(r) for r in c.execute(
            """SELECT municipio, uf, sum(valor) valor FROM favorecidos WHERE autor = ? AND ano >= ? AND municipio != ''
               GROUP BY municipio, uf ORDER BY valor DESC LIMIT 10""", (a, desde))]
        grupos = {r["grupo"]: r["valor"] for r in c.execute(
            "SELECT grupo, sum(valor) valor FROM favorecidos WHERE autor = ? AND ano >= ? GROUP BY grupo", (a, desde))}
        recebido = sum(grupos.values())
        favorecidos = [dict(r) for r in c.execute(
            """SELECT doc, nome, natureza, grupo, municipio, uf, sum(valor) valor, min(ano) primeiro, count(*) pagamentos
               FROM favorecidos WHERE autor = ? AND ano >= ? GROUP BY doc ORDER BY valor DESC LIMIT 25""", (a, desde))]
        docs = [f["doc"] for f in favorecidos]
        outros_autores = dict(c.execute(
            f"SELECT doc, count(DISTINCT autor) FROM favorecidos WHERE doc IN ({','.join('?' * len(docs))}) GROUP BY doc", docs)) if docs else {}
        municipios_total = c.execute(
            "SELECT count(DISTINCT municipio || uf) FROM favorecidos WHERE autor = ? AND ano >= ?", (a, desde)).fetchone()[0]
    finally:
        c.close()

    forn, doad = _campanha(sq_candidato)
    for f in favorecidos:
        f["nome"] = (f["nome"] or "").strip()
        f["privado"] = f["grupo"] in ("semFins", "empresas")
        f["autores"] = outros_autores.get(f["doc"], 1)
        f["campanha"] = {"fornecedor": forn.get(f["doc"]), "doador": doad.get(f["doc"])} if f["doc"] in forn or f["doc"] in doad else None

    sinais = []
    for f in favorecidos:
        if f["privado"] and f["campanha"]:
            papel = []
            if f["campanha"]["fornecedor"]:
                papel.append(f"recebeu {_brl(f['campanha']['fornecedor'])} da campanha de 2026 como fornecedora")
            if f["campanha"]["doador"]:
                papel.append(f"doou {_brl(f['campanha']['doador'])} para a campanha de 2026")
            sinais.append({"nivel": "alerta", "titulo": f"Quem recebeu emenda também trabalhou na campanha: {f['nome']}",
                           "detalhe": f"A entidade recebeu {_brl(f['valor'])} de emendas desta pessoa e também {' e '.join(papel)}. "
                                      "Dinheiro público que volta para a campanha de quem o indicou é o caso mais sério que dá para ver nesses dados.",
                           "cnpj": f["doc"]})
    for f in favorecidos:
        comum = any(p in normalizar(f["nome"]) for p in FILANTROPIA_COMUM)
        # Entidade que recebe de muitos parlamentares (fundações de apoio, hospitais de referência) é destino comum;
        # a que depende de uma ou duas pessoas é a que costuma aparecer em auditorias. Só vale para entidades sem fins
        # lucrativos: quando o dinheiro vai direto a uma empresa, é compra feita por um órgão público (tratores, obras),
        # e não uma entidade que vive das emendas.
        f["dependente"] = (f["grupo"] == "semFins" and not comum and f["autores"] <= 2
                           and f["valor"] >= LIMITE_DEPENDENTE)
    dependentes = [f for f in favorecidos if f["dependente"]]
    if dependentes:
        total_dep = sum(f["valor"] for f in dependentes)
        if len(dependentes) == 1:
            f = dependentes[0]
            outros = "nenhum outro parlamentar manda" if f["autores"] == 1 else "só mais um parlamentar manda"
            titulo = f"Entidade privada que depende das emendas desta pessoa: {f['nome']}"
            texto = (f"A entidade recebeu {_brl(f['valor'])} das emendas desta pessoa "
                     f"desde {desde}, e {outros} emendas para ela.")
        else:
            titulo = f"{len(dependentes)} entidades privadas dependem das emendas desta pessoa"
            texto = (f"Juntas, {listar_nomes([f['nome'] for f in dependentes])} receberam {_brl(total_dep)} das emendas desta pessoa "
                     f"desde {desde}, e quase nenhum outro parlamentar manda emendas para elas.")
        sinais.append({"nivel": "atencao", "titulo": titulo,
                       "detalhe": texto + " Pode ser um projeto legítimo, mas repasses grandes para associações e institutos "
                                          "ligados a um só parlamentar são o que a CGU e o TCU mais encontram com problema. Vale ver o que "
                                          "foi entregue e quem está por trás " + ("da entidade." if len(dependentes) == 1 else "de cada entidade."),
                       "cnpj": dependentes[0]["doc"],
                       "empresas": [{"cnpj": f["doc"], "nome": f["nome"]} for f in dependentes]})
    pix = (tot["pix"] or 0) / tot["emp"] if tot["emp"] else 0
    mediana_pix = float(meta.get("medianaPix") or 0)
    sem_fins = grupos.get("semFins", 0) / recebido if recebido else 0
    mediana_sem_fins = float(meta.get("medianaSemFins") or 0)
    return {
        "quantidade": tot["n"],
        "desde": desde,
        "empenhado": tot["emp"] or 0,
        "pago": tot["pago"] or 0,
        "recebido": recebido,
        "transferenciasEspeciais": tot["pix"] or 0,
        "partePix": pix,
        "medianaPix": mediana_pix,
        "grupos": grupos,
        "parteSemFins": sem_fins,
        "medianaSemFins": mediana_sem_fins,
        "anos": anos,
        "areas": areas,
        "lugares": lugares,
        "municipios": municipios_total,
        "favorecidos": favorecidos[:15],
        "rastro": rastro,
        "sinais": sinais,
        "link": "https://portaldatransparencia.gov.br/emendas",
    }


def por_autor_mandato():
    """Totais do mandato atual por autor, para os perfis de partido."""
    if not _banco().exists():
        return {}
    c = _conectar()
    try:
        out = {}
        for r in c.execute("""SELECT autor, sum(empenhado) emp, sum(CASE WHEN pix THEN empenhado ELSE 0 END) pix
                              FROM emendas WHERE ano >= ? GROUP BY autor""", (MANDATO_ATUAL,)):
            out[r["autor"]] = {"empenhado": r["emp"] or 0, "pix": r["pix"] or 0, "semFins": 0, "recebido": 0}
        for r in c.execute("SELECT autor, grupo, sum(valor) v FROM favorecidos WHERE ano >= ? GROUP BY autor, grupo", (MANDATO_ATUAL,)):
            o = out.setdefault(r["autor"], {"empenhado": 0, "pix": 0, "semFins": 0, "recebido": 0})
            o["recebido"] += r["v"] or 0
            if r["grupo"] == "semFins":
                o["semFins"] += r["v"] or 0
        for r in c.execute(f"SELECT autor, {SQL_RASTREAVEL} parte FROM emendas e WHERE ano >= ? AND ano <= ? GROUP BY autor",
                           (MANDATO_ATUAL, ANO_COM_PRAZO)):
            if r["autor"] in out:
                out[r["autor"]]["rastreavel"] = r["parte"]
        return out
    finally:
        c.close()


def recebedor(doc):
    """Emendas individuais recebidas por uma entidade (CNPJ), por parlamentar."""
    if not _banco().exists():
        return None
    c = _conectar()
    try:
        linhas = [dict(r) for r in c.execute(
            """SELECT autor, sum(valor) valor, min(ano) primeiro, max(ano) ultimo, max(nome) nome, max(natureza) natureza,
                      max(municipio) municipio, max(uf) uf
               FROM favorecidos WHERE doc = ? GROUP BY autor ORDER BY valor DESC""", (doc,))]
    finally:
        c.close()
    if not linhas:
        return None
    return {
        "nome": linhas[0]["nome"].strip(),
        "natureza": linhas[0]["natureza"],
        "grupo": grupo_natureza(linhas[0]["natureza"]),
        "municipio": linhas[0]["municipio"],
        "uf": linhas[0]["uf"],
        "total": sum(x["valor"] for x in linhas),
        "desde": min(x["primeiro"] for x in linhas),
        "parlamentares": [{"nome": x["autor"], "valor": x["valor"], "primeiro": x["primeiro"], "ultimo": x["ultimo"]}
                          for x in linhas[:20]],
        "totalParlamentares": len(linhas),
    }
