"""Quem trabalha ou trabalhou no gabinete de quem já tem mandato, para cruzar com o dinheiro da campanha.

O padrão da "rachadinha" é o assessor devolver parte do salário ao político. Isso não aparece em dado público,
mas dois sinais aparecem: assessor do gabinete que doa para a campanha do chefe e assessor que também é pago pela
campanha. Os dois são permitidos e comuns; por isso aqui só viram informação na ficha, com nomes e valores.

Fontes (todas públicas e sem cadastro):
- Senado: todos os servidores com a última lotação, inclusive quem já saiu (API de dados abertos administrativos);
- Câmara: secretários parlamentares atuais de cada deputado (consulta pública do portal da transparência);
- ALESP: histórico de lotações dos servidores, com datas de entrada e saída;
- outras assembleias que publicam quem está em cada gabinete: ALERJ (relatório da Resolução 178/2019, com salário),
  ALEP/PR (API da folha de comissionados, com salário e datas) e ALESC/SC (lista de servidores com lotação).
  As demais não publicam essa lista de forma que dê para ler; ficam de fora até publicarem.

O político é ligado à candidatura de 2026 pelo arquivo de candidatos do TSE: senador pela data de nascimento e
nome de urna; deputado federal pelo nome civil que a Câmara publica; deputado estadual de SP pelo nome de urna.
Tudo é refeito uma vez por semana em segundo plano.
"""
import html
import io
from pathlib import Path
import json
import re
import sys
import threading
import time
import traceback
import xml.etree.ElementTree as ET

from curl_cffi import requests

import camara
import empresas
import tse
import zipremoto

URL_SENADO_SERVIDORES = "https://adm.senado.gov.br/adm-dadosabertos/api/v1/servidores/servidores?formato=json"
URL_SENADORES = "https://adm.senado.gov.br/adm-dadosabertos/api/v1/senadores?formato=json"
URL_CAMARA_SECRETARIOS = ("https://www2.camara.leg.br/transparencia/recursos-humanos/servidores/lotacao/"
                          "consulta-secretarios-parlamentares/layouts_transpar_quadroremuner_consultaSecretariosParlamentares")
URL_ALESP_LOTACOES = "https://www.al.sp.gov.br/repositorioDados/administracao/funcionarios_lotacoes.xml"
TTL = 7 * 24 * tse.HORA
# Muda quando entra uma fonte nova, para o índice guardado ser refeito na hora em vez de esperar a semana.
VERSAO = 3
# Na ALESP há histórico desde os anos 1990; conta quem esteve no gabinete a partir daqui.
ALESP_DESDE = "2015-01-01"

_indice = None
_lock = threading.Lock()
_rodando = threading.Event()
_estado = {"etapa": "parado", "erro": None}


def registrar_falha(e):
    print(f"[{__name__}] falhou em \"{_estado.get('etapa')}\": {e}", file=sys.stderr)
    traceback.print_exc()


def _arquivo():
    p = tse._cache_dir / "gabinetes"
    p.mkdir(parents=True, exist_ok=True)
    return p / "indice.json"


norm = camara._normalizar


def _candidatos():
    """Candidatos de 2026 com o que serve para achar o político: nome civil, nome de urna, UF e nascimento."""
    return [{"sq": r["SQ_CANDIDATO"], "nome": norm(r["NM_CANDIDATO"]), "urna": norm(r["NM_URNA_CANDIDATO"]),
             "uf": r["SG_UF"], "nascimento": r["DT_NASCIMENTO"]}
            for r in zipremoto.linhas_csv(empresas.URL_CAND_2026, "consulta_cand_2026_BRASIL.csv")]


# ---------- Senado ----------

def _senado(s, cands, add):
    senadores = s.get(URL_SENADORES, timeout=120).json()["data"]
    por_nascimento = {}
    for c in cands:
        por_nascimento.setdefault(c["nascimento"], []).append(c)
    candidatura = {}
    for p in senadores:
        nome = norm(p["nomeParlamentar"])
        achados = [c for c in por_nascimento.get(p.get("dataNascimento"), []) if set(nome.split()) & set(c["urna"].split())]
        if len(achados) == 1:
            candidatura[nome] = achados[0]["sq"]
    for x in s.get(URL_SENADO_SERVIDORES, timeout=300).json():
        m = re.search(r"(?:Gabinete|Escrit[oó]rio de Apoio \d*) d[oa] Senador[a]? (.+)$", (x.get("lotacao") or {}).get("nome") or "")
        sq = candidatura.get(norm(m.group(1))) if m else None
        # O próprio senador aparece na lista (vínculo "PARLAMENTAR"); ele não é assessor.
        if sq and x.get("nome") and x.get("vinculo") != "PARLAMENTAR":
            add(sq, "Senado", m.group(1), {"nome": x["nome"], "atual": x.get("situacao") == "ATIVO",
                                            "desde": str(x.get("ano_admissao") or "")})


# ---------- Câmara ----------

def _camara(s, cands, add):
    r = camara.resumo()
    if not r:
        raise RuntimeError("a base da Câmara ainda não está pronta")
    civil = {}
    for d in r["deputados"].values():
        if d.get("nomeCivil"):
            civil.setdefault(norm(d["nome"]), set()).add(norm(d["nomeCivil"]))
    por_nome = {}
    for c in cands:
        por_nome.setdefault(c["nome"], []).append(c["sq"])
    pagina = s.get(URL_CAMARA_SECRETARIOS, timeout=120).text
    form = re.search(r'<form class="formCamara".*?</form>', pagina, re.S).group(0)
    for valor, nome in re.findall(r'<option value="([^"]+)"[^>]*>([^<]*)</option>', form):
        nome = html.unescape(nome).strip()
        sqs = {sq for n in civil.get(norm(nome), ()) for sq in por_nome.get(n, ())}
        if len(sqs) != 1:
            continue
        _estado["etapa"] = f"baixando os secretários de {nome.title()}"
        t = s.post(URL_CAMARA_SECRETARIOS, data={"lotacao": valor, "form.submitted": "1",
                                                 "form.button.pesquisar": "Pesquisar"}, timeout=120).text
        for linha in re.findall(r"<tr[^>]*>(.*?)</tr>", t[t.find("Ponto"):], re.S):
            cel = [" ".join(html.unescape(re.sub("<[^>]+>", "", c)).split()) for c in re.findall(r"<td[^>]*>(.*?)</td>", linha, re.S)]
            if len(cel) >= 4 and cel[0].isdigit():
                add(next(iter(sqs)), "Câmara", nome, {"nome": cel[1], "atual": True, "desde": ""})
        time.sleep(0.5)  # consulta pública: uma de cada vez, sem pressa


# ---------- ALESP ----------

def _alesp(s, cands, add):
    por_urna = {}
    for c in cands:
        if c["uf"] in ("SP", "BR"):
            por_urna.setdefault(c["urna"], []).append(c["sq"])
    raiz = ET.fromstring(s.get(URL_ALESP_LOTACOES, timeout=300).content)
    for l in raiz:
        m = re.match(r"Gabinete d[oa] Deputad[oa] (.+)$", l.findtext("NomeUA") or "")
        sqs = por_urna.get(norm(m.group(1))) if m else None
        fim = (l.findtext("DataFim") or "")[:10]
        if sqs and len(sqs) == 1 and (not fim or fim >= ALESP_DESDE):
            add(sqs[0], "ALESP", m.group(1).title(), {"nome": l.findtext("NomeFuncionario"), "atual": not fim,
                                                      "desde": (l.findtext("DataInicio") or "")[:4]})


# ---------- outras assembleias ----------

def _por_urna(cands, uf):
    """Nome de urna -> candidatura, para quem disputa no estado ou para presidente. Só nomes que não se repetem."""
    por = {}
    for c in cands:
        if c["uf"] in (uf, "BR"):
            por.setdefault(c["urna"], []).append(c["sq"])
    return {n: sqs[0] for n, sqs in por.items() if len(sqs) == 1}


def _gabinete(lotacao):
    """"GAB.DEP. FULANO", "GAB DEP FULANO", "GAB. DEP. FULANO" -> "FULANO"."""
    m = re.match(r"\s*GAB(?:INETE)?\.?\s*(?:D[OA]\s*)?DEP(?:UTAD[OA])?\.?\s+(.+)$", lotacao or "", re.I)
    return norm(m.group(1)) if m else None


def _dinheiro(txt):
    try:
        return float(str(txt).replace(".", "").replace(",", ".")) if "," in str(txt) else float(txt)
    except (TypeError, ValueError):
        return None


URL_ALERJ_GABINETES = ("https://transparencia.alerj.rj.gov.br/download-spic?file=https%3A%2F%2Fwww2.alerj.rj.gov.br"
                       "%2Fleideacesso%2FverArquivo.asp%3FidArquivo%3D{}")
URL_ALERJ_PAGINA = "https://transparencia.alerj.rj.gov.br/section/report/107"


def _alerj(s, cands, add):
    import pdfplumber
    pagina = s.get(URL_ALERJ_PAGINA, timeout=120).text
    arquivo = re.findall(r"idArquivo%3D(\d+)", pagina)
    if not arquivo:
        raise RuntimeError("relatório de gabinetes não encontrado")
    pdf = s.get(URL_ALERJ_GABINETES.format(arquivo[-1]), timeout=300).content
    urna = _por_urna(cands, "RJ")
    # Histórico desde 2005, tirado do Diário Oficial no computador pessoal (alerj_historico.py) e enviado pronto.
    import gzip
    pacote = Path(__file__).resolve().parent / "dados_publicos" / "alerj_historico.json.gz"
    if pacote.exists():
        for sq, g in json.loads(gzip.decompress(pacote.read_bytes()))["gabinetes"].items():
            for a in g["assessores"]:
                add(sq, "ALERJ", g["politico"], {"nome": a["nome"], "atual": False, "desde": a["desde"]})
    with pdfplumber.open(io.BytesIO(pdf)) as p:
        for pag in p.pages:
            for linha in (pag.extract_text() or "").splitlines():
                m = re.match(r"(.+?) (GAB\.DEP\. .+?) (CCDAL-\d+|\S+-\d+) ([\d.]+,\d{2})$", linha.strip())
                sq = urna.get(_gabinete(m.group(2))) if m else None
                if sq:
                    add(sq, "ALERJ", m.group(2)[9:].title(), {"nome": m.group(1), "atual": True, "desde": "",
                                                              "salario": _dinheiro(m.group(4))})


URL_ALEP = "https://transparencia.assembleia.pr.leg.br/"


def _alep(s, cands, add):
    s.get(URL_ALEP + "pessoal/comissionados", timeout=120)
    urna = _por_urna(cands, "PR")
    cab = {"X-Requested-With": "XMLHttpRequest", "Accept": "application/json"}
    hoje = time.localtime()
    # Mês passado (a folha do mês corrente sai depois) e janeiro de cada ano desde o começo do mandato.
    meses = [(hoje.tm_year if hoje.tm_mon > 1 else hoje.tm_year - 1, hoje.tm_mon - 1 or 12)]
    meses += [(a, 1) for a in range(2023, hoje.tm_year + 1)]
    for ano, mes in meses:
        pagina, ultima = 1, 1
        while pagina <= ultima:
            d = s.get(f"{URL_ALEP}api/remuneracao?t=comissionado&mes={mes}&ano={ano}&page={pagina}&search=&searchType=nome",
                      headers=cab, timeout=120).json()
            ultima = d.get("last_page") or 1
            for x in d.get("remuneracoes") or []:
                sq = urna.get(_gabinete(x.get("lotacao")))
                if sq:
                    add(sq, "ALEP", x["lotacao"].split("DEP.", 1)[-1].strip().title(),
                        {"nome": x["nome"], "atual": not x.get("data_exoneracao"),
                         "desde": (x.get("data_nomeacao") or "")[-4:], "salario": _dinheiro(x.get("valor"))})
            pagina += 1
            time.sleep(0.3)


URL_ALESC = "https://transparencia.alesc.sc.gov.br/servidores"


def _alesc(s, cands, add):
    urna = _por_urna(cands, "SC")
    pagina, ultima = 1, 1
    while pagina <= ultima:
        t = s.get(f"{URL_ALESC}?page={pagina}", timeout=120).text
        ultima = max([ultima] + [int(n) for n in re.findall(r"[?&]page=(\d+)", t)])
        for linha in re.findall(r"<tr[^>]*>(.*?)</tr>", t, re.S):
            cel = [" ".join(html.unescape(re.sub("<[^>]+>", "", c)).split()) for c in re.findall(r"<td[^>]*>(.*?)</td>", linha, re.S)]
            if len(cel) >= 3:
                sq = urna.get(_gabinete(cel[2]))
                if sq:
                    add(sq, "ALESC", cel[2][8:].title(), {"nome": cel[0], "atual": True, "desde": ""})
        pagina += 1
        time.sleep(0.3)


def _preparar():
    try:
        _estado["etapa"] = "lendo os candidatos do TSE"
        cands = _candidatos()
        indice, contagem, erros = {}, {}, []

        def add(sq, casa, politico, pessoa):
            if not pessoa.get("nome"):
                return
            g = indice.setdefault(str(sq), {"casas": [], "politico": politico, "assessores": {}})
            if casa not in g["casas"]:
                g["casas"].append(casa)
            chave = norm(pessoa["nome"])
            atual = g["assessores"].get(chave)
            # A mesma pessoa pode aparecer mais de uma vez (entrou e saiu); fica o registro mais recente.
            if not atual or pessoa["atual"] or pessoa["desde"] > atual["desde"]:
                g["assessores"][chave] = {"nome": pessoa["nome"].title(), "atual": pessoa["atual"], "desde": pessoa["desde"],
                                          "salario": pessoa.get("salario")}
            contagem[casa] = contagem.get(casa, 0) + 1

        with requests.Session(impersonate="chrome") as s:
            for nome, etapa in (("Senado", _senado), ("ALESP", _alesp), ("ALERJ", _alerj), ("ALEP", _alep),
                                ("ALESC", _alesc), ("Câmara", _camara)):
                _estado["etapa"] = f"baixando {nome}"
                try:
                    etapa(s, cands, add)
                except Exception as e:  # uma casa fora do ar não impede as outras
                    erros.append(f"{nome}: {e}")
                    traceback.print_exc()
        if not indice:
            raise RuntimeError("; ".join(erros) or "nenhuma fonte respondeu")
        dados = {"geradoEm": time.strftime("%d/%m/%Y"), "versao": VERSAO, "contagem": contagem, "erros": erros,
                 "gabinetes": indice}
        tmp = _arquivo().with_suffix(".tmp")
        tmp.write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")
        tmp.replace(_arquivo())
        _carregar()
        _estado.update(etapa="pronto", erro="; ".join(erros) or None)
    except Exception as e:  # noqa: BLE001 - mostramos o erro na interface
        registrar_falha(e)
        _estado.update(etapa="erro", erro=f"{_estado.get('etapa')}: {e}")
    finally:
        _rodando.clear()


def _carregar():
    global _indice
    arq = _arquivo()
    if not arq.exists():
        return False
    try:
        dados = json.loads(arq.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    with _lock:
        _indice = dados
    return True


def iniciar():
    if _carregar():
        _estado["etapa"] = "pronto"
    arq = _arquivo()
    # Os deputados federais são ligados pelo nome civil da base da Câmara; sem ela, espera a próxima conferência.
    velho = not arq.exists() or time.time() - arq.stat().st_mtime > TTL or (_indice or {}).get("versao") != VERSAO
    if velho and camara.resumo() and not _rodando.is_set():
        _rodando.set()
        threading.Thread(target=_preparar, daemon=True).start()


def status():
    return {"pronto": _indice is not None, "etapa": _estado["etapa"], "erro": _estado["erro"],
            "geradoEm": (_indice or {}).get("geradoEm")}


def do_candidato(id_candidato):
    """{"casas", "politico", "assessores": {nome normalizado: {nome, atual, desde}}} ou None."""
    return ((_indice or {}).get("gabinetes") or {}).get(str(id_candidato))
