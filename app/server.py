"""Voto Informado 2026: servidor local.

Serve a interface em http://127.0.0.1:8765 e faz a ponte com os dados do TSE.
A cédula fica salva só neste computador, em dados/cedula.json.

Com --tailscale, aceita também aparelhos da sua rede Tailscale (100.64.0.0/10),
como o tablet; qualquer outro endereço é recusado antes de chegar ao app.

Com --publico, é a versão para outras pessoas: sem login, e a cédula e o questionário ficam só no navegador de
cada pessoa; o servidor não recebe nem guarda votos.

Uso: python app/server.py [--porta 8765] [--sem-navegador] [--tailscale] [--publico]
"""
import argparse
import hmac
import os
import ipaddress
import json
import mimetypes
import re
import socket
import sys
import threading
import time
import traceback
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import alesp
import analise
import camara
import emendas
import gastos
import historico
import indicadores
import login
import partidos
import empresas
import noticias
import punicoes
import sancoes
import tse
import uso

RAIZ = Path(__file__).resolve().parent
ESTATICOS = RAIZ / "static"
DADOS = RAIZ.parent / "dados"
CEDULA = DADOS / "cedula.json"
CONFIG = DADOS / "config.json"
LOGIN = DADOS / "login.json"
QUIZ = RAIZ / "quiz.json"
COOKIE = "mv_sessao"
# O que a tela de login precisa para aparecer antes de entrar.
PUBLICOS = {"/login.html", "/login.js", "/style.css", "/manifest.webmanifest", "/icone.svg"}
# Modo público (--publico): sem login e sem guardar cédula no servidor.
MODO = {"publico": False}
# Limite de acessos no modo público: consultas à API por visitante a cada minuto.
LIMITE_POR_MINUTO = 120
_acessos = {}
_lock_acessos = threading.Lock()


def _excedeu_limite(ip):
    agora = time.time()
    with _lock_acessos:
        recentes = [t for t in _acessos.get(ip, []) if agora - t < 60]
        recentes.append(agora)
        _acessos[ip] = recentes
        if len(_acessos) > 5000:  # esquece visitantes antigos para a memória não crescer
            for velho in [k for k, v in _acessos.items() if agora - v[-1] > 60]:
                del _acessos[velho]
        return len(recentes) > LIMITE_POR_MINUTO
# O cache (centenas de MB de dados públicos) fica fora do OneDrive para não ser sincronizado.
# (AppData\Local não serve: o Python da Microsoft Store redireciona gravações ali.)
CACHE = Path.home() / ".meuvoto" / "cache"
TAMANHO_MAX_CEDULA = 64 * 1024

_lock_cedula = threading.Lock()

# Painel de uso (/monitor.html): só para o dono do site. Sem a variável MONITOR_CHAVE, ele não existe.
CHAVE_MONITOR = os.environ.get("MONITOR_CHAVE", "").strip()


def _chave_ok(recebida):
    return bool(CHAVE_MONITOR) and bool(recebida) and hmac.compare_digest(recebida.encode(), CHAVE_MONITOR.encode())


class ErroPedido(Exception):
    def __init__(self, status, mensagem):
        super().__init__(mensagem)
        self.status = status


class Preparando(Exception):
    """A base de 2022 do estado ainda está sendo montada: a tela mostra um aviso e pergunta de novo em seguida,
    em vez de segurar a conexão por minutos (o nginx desistiria antes e mostraria erro)."""


def _param(qs, nome, padrao=None):
    return (qs.get(nome) or [padrao])[0]


def _uf(qs):
    uf = (_param(qs, "uf") or "").upper()
    if uf not in tse.UFS and uf != "BR":
        raise ErroPedido(400, "UF inválida")
    return uf


def _cargo(qs):
    try:
        cargo = int(_param(qs, "cargo", ""))
    except ValueError:
        cargo = None
    if cargo not in tse.CARGOS:
        raise ErroPedido(400, "Cargo inválido")
    return cargo


def _digitos(qs, nome, max_len=15):
    valor = _param(qs, nome) or ""
    if not re.fullmatch(rf"\d{{1,{max_len}}}", valor):
        raise ErroPedido(400, f"Parâmetro '{nome}' inválido")
    return valor


class Handler(BaseHTTPRequestHandler):
    server_version = "MeuVoto/0.1"

    def log_message(self, fmt, *args):
        # Pedidos malformados (ex.: o navegador tentando HTTPS) chegam aqui antes de ter caminho.
        if getattr(self, "path", "").startswith("/api/"):
            sys.stderr.write("%s  %s\n" % (datetime.now().strftime("%H:%M:%S"), fmt % args))

    # -- respostas ---------------------------------------------------------

    def _token(self):
        for parte in (self.headers.get("Cookie") or "").split(";"):
            nome, _, valor = parte.strip().partition("=")
            if nome == COOKIE:
                return valor
        return None

    def _logado(self):
        return MODO["publico"] or login.sessao_valida(self._token())

    def _enviar(self, status, corpo, tipo, cache="no-store", cookie=None):
        self.send_response(status)
        if cookie is not None:
            idade = login.DURACAO_SESSAO if cookie else 0
            self.send_header("Set-Cookie", f"{COOKIE}={cookie}; Path=/; Max-Age={idade}; HttpOnly; SameSite=Strict")
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("Cache-Control", cache)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(corpo)

    def _empresa(self, doc):
        """Tudo o que os dados locais sabem sobre um CNPJ: campanha, emendas e verba de gabinete."""
        campanha = gastos.fornecedor(doc) if len(doc) == 14 else None
        if campanha and not campanha.get("pronto", True):
            campanha = None
        receb = emendas.recebedor(doc)
        gabinete = alesp.fornecedor_gabinete(doc)
        if not (campanha or receb or gabinete):
            raise ErroPedido(404, "Não encontramos esta empresa nas campanhas, nas emendas nem na verba de gabinete")
        receita = (campanha or {}).get("receita") or (gastos.cnpj(doc) if len(doc) == 14 else None)
        return {
            "cnpj": doc,
            "nome": (campanha or {}).get("nome") or (receb or {}).get("nome") or (gabinete[0]["nome"] if gabinete else doc),
            "receita": receita,
            "campanha": campanha,
            "emendas": receb,
            "gabinete": gabinete,
            "sancoes": analise.sancoes_empresa(doc) if len(doc) == 14 else None,
        }

    def _json(self, status, dados, cookie=None):
        self._enviar(status, json.dumps(dados, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8",
                     cookie=cookie)

    def _estatico(self, caminho):
        nome = "index.html" if caminho in ("", "/") else caminho.lstrip("/")
        if nome == "manifest.webmanifest":
            mimetypes.add_type("application/manifest+json", ".webmanifest")
        arq = (ESTATICOS / nome).resolve()
        if ESTATICOS not in arq.parents or not arq.is_file():
            return self._json(404, {"erro": "Não encontrado"})
        tipo = mimetypes.guess_type(arq.name)[0] or "application/octet-stream"
        if tipo.startswith("text/") or tipo in ("application/javascript", "text/javascript"):
            tipo += "; charset=utf-8"
        self._enviar(200, arq.read_bytes(), tipo)

    # -- rotas -------------------------------------------------------------

    def _ip_real(self):
        """IP de quem acessa. Atrás de um intermediário (túnel da Cloudflare ou o nginx do servidor), todo pedido
        chega do mesmo endereço interno, e o IP de verdade vem num cabeçalho que só é aceito nesse caso."""
        direto = self.client_address[0]
        try:
            interno = ipaddress.ip_address(direto).is_private
        except ValueError:
            interno = False
        if not interno:
            return direto
        if self.headers.get("CF-Connecting-IP"):
            return self.headers["CF-Connecting-IP"].strip()
        if self.headers.get("X-Real-IP"):
            return self.headers["X-Real-IP"].strip()
        encaminhado = [x.strip() for x in (self.headers.get("X-Forwarded-For") or "").split(",") if x.strip()]
        # O último da lista é o que o nosso próprio intermediário acrescentou; os anteriores vêm do navegador.
        return encaminhado[-1] if encaminhado else None

    def send_response(self, code, message=None):
        self._status = code
        super().send_response(code, message)

    def handle_one_request(self):
        self._status = None
        inicio = time.perf_counter()
        super().handle_one_request()
        if self._status is not None and MODO["publico"]:
            try:
                ip = self._ip_real()
                uso.registrar(urlparse(self.path).path, self._status, time.perf_counter() - inicio,
                              ip or self.client_address[0], ip is not None)
            except Exception:
                pass

    def do_GET(self):
        url = urlparse(self.path)
        qs = parse_qs(url.query)
        try:
            # Sem o IP real (intermediário que não o informa), todo mundo pareceria uma pessoa só: aí não limita.
            if MODO["publico"] and url.path.startswith("/api/") and self._ip_real() and _excedeu_limite(self._ip_real()):
                raise ErroPedido(429, "Muitas consultas seguidas. Espere um minuto e tente de novo.")
            if url.path == "/api/login":
                logado = self._logado()
                return self._json(200, {"existe": not MODO["publico"] and login.existe(), "logado": logado,
                                        "publico": MODO["publico"],
                                        "usuario": login.usuario() if logado and not MODO["publico"] else None})
            if not self._logado():
                if url.path.startswith("/api/"):
                    raise ErroPedido(401, "Entre com seu usuário e senha")
                if url.path not in PUBLICOS:
                    return self._estatico("/login.html")
                return self._estatico(url.path)
            if url.path == "/login.html":
                return self._redirecionar("/")
            if url.path == "/api/buscar":
                return self._buscar(qs)
            if url.path == "/api/ficha":
                return self._ficha(qs)
            if url.path == "/api/foto":
                return self._foto(qs)
            if url.path == "/api/cedula":
                if MODO["publico"]:
                    raise ErroPedido(404, "No modo público a cédula fica só no seu aparelho")
                return self._json(200, self._ler_cedula())
            if url.path == "/api/candidatos":
                return self._json(200, {"candidatos": tse.listar(_uf(qs), _cargo(qs))})
            if url.path == "/api/analise":
                a = analise.analisar(_uf(qs), _cargo(qs), _digitos(qs, "id"))
                if not a:
                    raise ErroPedido(404, "Candidato não encontrado no TSE")
                return self._json(200, a)
            if url.path == "/api/noticias":
                cargo = _cargo(qs)
                bruto = tse.ficha_bruta(_uf(qs), cargo, _digitos(qs, "id"))
                if not bruto:
                    raise ErroPedido(404, "Candidato não encontrado no TSE")
                try:
                    return self._json(200, noticias.do_candidato(bruto.get("nomeUrna"), (bruto.get("partido") or {}).get("sigla"), cargo))
                except Exception:
                    raise ErroPedido(502, "A busca de notícias não respondeu agora")
            if url.path == "/api/grupo":
                uf, cargo = self._uf_proporcional(qs)
                g = analise.grupo(uf, cargo, _param(qs, "grupo") or "")
                if g is None:
                    raise ErroPedido(404, "Federação ou partido não encontrado")
                return self._json(200, g)
            if url.path == "/api/rede_lista":
                uf, cargo = self._uf_proporcional(qs)
                r = analise.rede_lista(uf, cargo, _param(qs, "grupo") or "")
                if r is None:
                    raise ErroPedido(404, "Federação ou partido não encontrado")
                return self._json(200, r)
            if url.path == "/api/quiz":
                return self._json(200, self._quiz(_uf(qs)))
            if url.path == "/api/gastos/status":
                return self._json(200, gastos.status())
            if url.path == "/api/gastos/fornecedor":
                cnpj = _digitos(qs, "cnpj", 14)
                if len(cnpj) != 14:
                    raise ErroPedido(400, "CNPJ inválido")
                f = gastos.fornecedor(cnpj)
                if f is None:
                    raise ErroPedido(404, "Fornecedor não encontrado nas despesas de 2026")
                if f.get("pronto", True):
                    f["sancoes"] = analise.sancoes_empresa(cnpj)
                return self._json(200, f)
            if url.path == "/api/empresa":
                cnpj = _digitos(qs, "cnpj", 14)
                if len(cnpj) != 14:
                    raise ErroPedido(400, "CNPJ inválido")
                return self._json(200, self._empresa(cnpj))
            if url.path == "/api/gastos/panorama":
                return self._json(200, gastos.panorama(_uf(qs)))
            if url.path == "/api/camara":
                return self._json(200, camara.status())
            if url.path == "/api/config":
                return self._json(200, {"temChavePortal": analise.tem_chave_portal(), "publico": MODO["publico"],
                                        "sancoes": sancoes.status()})
            if url.path == "/api/uso":
                if not (MODO["publico"] and _chave_ok(self.headers.get("X-Chave"))):
                    raise ErroPedido(404, "Rota desconhecida")
                return self._json(200, uso.resumo())
            if url.path == "/monitor.html" and not (MODO["publico"] and _chave_ok(_param(qs, "chave"))):
                return self._json(404, {"erro": "Não encontrado"})
            if url.path == "/api/status":
                return self._json(200, {"bases": _status_bases()})
            if url.path == "/api/projecao":
                uf, cargo = self._uf_proporcional(qs)
                return self._json(200, historico.projecao(uf, cargo))
            if url.path == "/api/indicadores":
                uf, cargo = self._uf_proporcional(qs)
                return self._json(200, indicadores.obter(uf, cargo))
            if url.path == "/api/perfis":
                uf, cargo = self._uf_proporcional(qs)
                grupos = [g["id"] for g in historico.panorama_listas(uf, cargo)["grupos"]]
                return self._json(200, partidos.perfis(uf, cargo, grupos))
            if url.path == "/api/listas":
                uf, cargo = self._uf_proporcional(qs)
                return self._json(200, historico.panorama_listas(uf, cargo))
            if url.path == "/api/ranking":
                uf, cargo = self._uf_proporcional(qs)
                r = historico.ranking(uf, cargo, _param(qs, "grupo") or "")
                if r is None:
                    raise ErroPedido(404, "Federação ou partido não encontrado")
                return self._json(200, r)
            if url.path.startswith("/api/"):
                raise ErroPedido(404, "Rota desconhecida")
            return self._estatico(url.path)
        except ErroPedido as e:
            self._json(e.status, {"erro": str(e)})
        except tse.TSEIndisponivel:
            self._json(503, {"erro": "Não foi possível falar com o TSE agora. Verifique a internet e tente de novo."})
        except Preparando as e:
            self._json(202, {"preparando": True, "etapa": historico.etapa(e.args[0]), "passos": historico.PASSOS})
        except Exception:  # noqa: BLE001 - sem isto a conexão cai sem resposta e o nginx mostra "502 Bad Gateway"
            traceback.print_exc()
            self._json(500, {"erro": "Não conseguimos montar esta parte agora. Tente de novo em alguns minutos."})

    def do_POST(self):
        url = urlparse(self.path)
        try:
            if url.path not in ("/api/cedula", "/api/config", "/api/login", "/api/login/criar", "/api/sair"):
                raise ErroPedido(404, "Rota desconhecida")
            # Evita que outro site aberto no navegador escreva na sua cédula.
            origem = self.headers.get("Origin")
            if origem and urlparse(origem).netloc != self.headers.get("Host"):
                raise ErroPedido(403, "Origem não permitida")
            if url.path == "/api/sair":
                login.sair(self._token())
                return self._json(200, {"ok": True}, cookie="")
            if MODO["publico"]:
                # Nada de voto, login ou chave pessoal chega ao servidor público.
                raise ErroPedido(403, "No modo público nada é guardado no servidor")
            if url.path.startswith("/api/login"):
                return self._entrar(url.path.endswith("/criar"))
            if not self._logado():
                raise ErroPedido(401, "Entre com seu usuário e senha")
            tamanho = int(self.headers.get("Content-Length") or 0)
            if tamanho <= 0 or tamanho > TAMANHO_MAX_CEDULA:
                raise ErroPedido(400, "Tamanho inválido")
            try:
                cedula = json.loads(self.rfile.read(tamanho).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                raise ErroPedido(400, "JSON inválido")
            if not isinstance(cedula, dict):
                raise ErroPedido(400, "Formato inválido")
            if url.path == "/api/config":
                chave = str(cedula.get("chavePortal") or "").strip()
                if chave and not re.fullmatch(r"[A-Za-z0-9-]{16,64}", chave):
                    raise ErroPedido(400, "Chave em formato inesperado")
                analise.salvar_chave_portal(chave)
                return self._json(200, {"temChavePortal": bool(chave)})
            cedula["salvoEm"] = datetime.now().isoformat(timespec="seconds")
            with _lock_cedula:
                DADOS.mkdir(parents=True, exist_ok=True)
                tmp = CEDULA.with_suffix(".tmp")
                tmp.write_text(json.dumps(cedula, ensure_ascii=False, indent=2), encoding="utf-8")
                tmp.replace(CEDULA)
            self._json(200, {"ok": True, "salvoEm": cedula["salvoEm"]})
        except ErroPedido as e:
            self._json(e.status, {"erro": str(e)})

    def _redirecionar(self, destino):
        self.send_response(303)
        self.send_header("Location", destino)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _entrar(self, criar):
        tamanho = int(self.headers.get("Content-Length") or 0)
        if tamanho <= 0 or tamanho > 4096:
            raise ErroPedido(400, "Tamanho inválido")
        try:
            corpo = json.loads(self.rfile.read(tamanho).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ErroPedido(400, "JSON inválido")
        if not isinstance(corpo, dict):
            raise ErroPedido(400, "Formato inválido")
        usuario = str(corpo.get("usuario") or "").strip()
        senha = str(corpo.get("senha") or "")
        if criar:
            if login.existe():
                raise ErroPedido(409, "O login já foi criado. Entre com ele.")
            erro = login.validar_novo(usuario, senha)
            if erro:
                raise ErroPedido(400, erro)
            token = login.criar(usuario, senha)
            if not token:
                raise ErroPedido(409, "O login já foi criado. Entre com ele.")
        else:
            token, erro = login.entrar(usuario, senha)
            if not token:
                raise ErroPedido(401, erro)
        return self._json(200, {"ok": True}, cookie=token)

    def _uf_proporcional(self, qs):
        uf, cargo = _uf(qs), _cargo(qs)
        if uf == "BR" or cargo not in historico.cargos_proporcionais(uf):
            raise ErroPedido(400, "A projeção só vale para deputado federal e estadual/distrital")
        if not historico.pronto(uf):
            historico.preparar(uf)
            raise Preparando(uf)
        return uf, cargo

    def _buscar(self, qs):
        uf, cargo = _uf(qs), _cargo(qs)
        if _param(qs, "numero"):
            numero = _digitos(qs, "numero", 5)
            candidatos, legenda = tse.buscar_numero(uf, cargo, numero)
            return self._json(200, {"candidatos": candidatos, "legenda": legenda})
        q = (_param(qs, "q") or "").strip()
        if len(q) < 2:
            raise ErroPedido(400, "Digite pelo menos 2 letras")
        self._json(200, {"candidatos": tse.buscar_nome(uf, cargo, q[:60]), "legenda": None})

    def _ficha(self, qs):
        ficha = tse.ficha(_uf(qs), _cargo(qs), _digitos(qs, "id"))
        if not ficha:
            raise ErroPedido(404, "Candidato não encontrado no TSE")
        self._json(200, ficha)

    def _foto(self, qs):
        img = tse.foto(_uf(qs), _digitos(qs, "id"))
        if not img:
            raise ErroPedido(404, "Sem foto")
        self._enviar(200, img, "image/jpeg", cache="max-age=86400")

    def _quiz(self, uf):
        base = json.loads(QUIZ.read_text(encoding="utf-8"))
        r = camara.resumo()
        if not r:
            return {"pronto": False, "status": camara.status()}
        votacoes = {v["id"]: v for v in r["quiz"]}

        # Deputados federais atuais que disputam 2026 neste estado.
        deputados = {}
        if uf != "BR":
            cargos = (6, 5, 3) + historico.cargos_proporcionais(uf)[1:]
            for cargo in cargos:
                for c in tse.listar_bruto(uf, cargo):
                    if tse._prioridade({"situacao": c.get("descricaoSituacao")}) == 2:
                        continue
                    d = camara.deputado(c.get("nomeCompleto"), uf, c.get("nomeUrna"))
                    if d:
                        deputados[d["id"]] = {
                            "id": d["id"], "nome": d["nome"], "partido": d["partido"],
                            "candidatura": {"id": c["id"], "nomeUrna": c.get("nomeUrna"), "numero": c["numero"],
                                            "cargo": cargo, "rotulo": tse.CARGOS[cargo]},
                        }
        with ThreadPoolExecutor(max_workers=6) as pool:
            proposicoes = dict(zip(
                (q["id"] for q in base["perguntas"]),
                pool.map(lambda q: _proposicao(q["id"].split("-")[0]), base["perguntas"]),
            ))
        perguntas = []
        for q in base["perguntas"]:
            v = votacoes.get(q["id"])
            if not v:
                continue
            posicoes = {}
            for sigla, cont in v["partidos"].items():
                sim, nao = cont.get("Sim", 0), cont.get("Não", 0)
                if sim + nao >= 3 and sim != nao:
                    posicoes[sigla] = {"voto": "Sim" if sim > nao else "Não", "sim": sim, "nao": nao}
            perguntas.append(dict(q, data=v["data"], sim=v["sim"], nao=v["nao"], governo=v["governo"],
                                  proposicao=proposicoes.get(q["id"]),
                                  partidos=posicoes,
                                  deputados={d: v["deputados"][d] for d in deputados if d in v["deputados"]}))
        return {"pronto": True, "criterio": base["criterio"], "atualizadoEm": base.get("atualizadoEm"),
                "perguntas": perguntas,
                "deputados": list(deputados.values()),
                "federacoes": _federacoes(uf)}

    def _ler_cedula(self):
        with _lock_cedula:
            if not CEDULA.exists():
                return {}
            try:
                return json.loads(CEDULA.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                return {}


def _federacoes(uf):
    """Partido -> todos os partidos da sua federação, ex.: "REDE" -> ["PSOL", "REDE"].

    Federação vota como um bloco só na Câmara, então a afinidade de um candidato a senador, governador ou
    presidente usa a federação inteira. As federações são nacionais; o nome delas vem das candidaturas a deputado
    federal (no Brasil todo, usa SP).
    """
    mapa = {}
    try:
        for c in tse.listar(uf if uf != "BR" else "SP", 6):
            siglas = partidos.siglas_do_grupo(c.get("coligacao"))
            if len(siglas) > 1:
                for s in siglas:
                    mapa[s] = siglas
    except Exception:
        pass
    return mapa


def _proposicao(id_proposicao):
    """Ementa e situação atual da proposição, direto da API da Câmara (com cache de 7 dias)."""
    d = analise._get_json(
        f"https://dadosabertos.camara.leg.br/api/v2/proposicoes/{id_proposicao}",
        f"camara_proposicao_{id_proposicao}.json",
        {"Accept": "application/json"},
    )
    d = (d or {}).get("dados")
    if not d:
        return None
    st = d.get("statusProposicao") or {}
    return {
        "nome": f"{d.get('siglaTipo')} {d.get('numero')}/{d.get('ano')}",
        "ementa": d.get("ementa"),
        "situacao": st.get("descricaoSituacao"),
        "dataSituacao": (st.get("dataHora") or "")[:10],
        "ultimoAndamento": st.get("despacho"),
        "link": f"https://www.camara.leg.br/proposicoesWeb/fichadetramitacao?idProposicao={id_proposicao}",
    }


# Bases de dados públicos que se refazem sozinhas. Cada iniciar() só baixa de novo se a cópia estiver velha,
# faltando ou se a última tentativa falhou, e nunca roda duas vezes ao mesmo tempo.
BASES = (camara, gastos, alesp, emendas, sancoes, empresas, punicoes)
CONFERIR_BASES_A_CADA = 3600


# Para a página "Sobre": o que cada base traz e o arquivo que mostra quando ela foi atualizada.
DESCRICAO_BASES = (
    (gastos, gastos._banco, "Prestação de contas das campanhas de 2026 e 2022", "TSE"),
    (empresas, empresas._arquivo, "Empresas em que cada candidato é sócio", "Receita Federal"),
    (sancoes, sancoes._arquivo, "Cadastros de punidos (CEIS, CNEP e CEAF)", "CGU, Portal da Transparência"),
    (punicoes, punicoes._arquivo, "Contas irregulares, lista suja do trabalho escravo e embargos ambientais",
     "TCU, Ministério do Trabalho e Ibama"),
    (camara, camara._arquivo_resumo, "Votações, presença, projetos e cota dos deputados federais", "Câmara dos Deputados"),
    (emendas, emendas._banco, "Emendas parlamentares e quem recebeu o dinheiro", "Portal da Transparência e Transferegov"),
    (alesp, alesp._arquivo, "Presença, projetos e verba de gabinete dos deputados estaduais de SP", "ALESP"),
)


def _status_bases():
    saida = []
    for modulo, arquivo, descricao, fonte in DESCRICAO_BASES:
        st = modulo.status()
        arq = arquivo()
        saida.append({
            "descricao": descricao, "fonte": fonte, "pronto": bool(st.get("pronto")),
            "atualizando": st.get("etapa") not in ("pronto", "parado", "erro"),
            "falhou": st.get("etapa") == "erro",
            # O índice da Receita chega pronto com o site: vale a data em que foi montado, não a da cópia.
            "atualizadoEm": (st.get("geradoEm") if modulo is empresas else None)
            or (datetime.fromtimestamp(arq.stat().st_mtime).strftime("%d/%m/%Y %H:%M") if arq.exists() else None),
        })
    return saida


def _conferir_bases(sem=()):
    for base in BASES:
        if base in sem:
            continue
        try:
            base.iniciar()
        except Exception:  # noqa: BLE001 - uma base com problema não impede as outras
            traceback.print_exc()


def _manter_dados():
    """Confere as bases de hora em hora. Sem isto, um servidor que fica dias no ar nunca atualizaria os dados,
    e uma falha de download (TSE ou Receita fora do ar) só seria tentada de novo ao reiniciar."""
    while True:
        time.sleep(CONFERIR_BASES_A_CADA)
        _conferir_bases()


# Do maior para o menor eleitorado: os estados com mais visitas ficam prontos primeiro.
ORDEM_ESTADOS = ("SP", "MG", "RJ", "BA", "PR", "RS", "PE", "CE", "PA", "SC", "GO", "MA", "AM", "ES", "PB", "RN",
                 "MT", "AL", "PI", "DF", "MS", "SE", "RO", "TO", "AC", "AP", "RR")


def _preparar_historico():
    """Monta a base de 2022 e os votos de 2024 de todos os estados logo ao abrir, um de cada vez. Na primeira vez
    cada estado leva até 2 minutos; enquanto isso, a aba de deputados daquele estado mostra que está preparando."""
    for uf in ORDEM_ESTADOS:
        try:
            historico.base(uf)
            historico.municipal(uf)
        except Exception:  # noqa: BLE001 - tenta de novo quando alguém abrir o estado
            traceback.print_exc()
    # O índice de sócios da Receita baixa uns 10 GB e leva perto de uma hora (só fora do modo público). Ele fica
    # para depois das listas de deputados e do banco de gastos, que as telas usam primeiro e que ele também cruza.
    if not empresas.BAIXAR_DA_RECEITA:
        return
    for _ in range(120):
        if gastos._banco().exists():
            break
        time.sleep(30)
    empresas.iniciar()


REDE_TAILSCALE = ipaddress.ip_network("100.64.0.0/10")


class ServidorTailscale(ThreadingHTTPServer):
    """Escuta em todas as interfaces, mas só atende este computador e a rede Tailscale."""

    def verify_request(self, request, client_address):
        ip = ipaddress.ip_address(client_address[0])
        return ip.is_loopback or ip in REDE_TAILSCALE


def main():
    ap = argparse.ArgumentParser(description="Voto Informado 2026 (servidor local)")
    ap.add_argument("--porta", type=int, default=8765)
    ap.add_argument("--sem-navegador", action="store_true")
    ap.add_argument("--tailscale", action="store_true", help="aceita aparelhos da sua rede Tailscale")
    ap.add_argument("--publico", action="store_true", help="versão para outras pessoas: sem login e sem guardar votos")
    ap.add_argument("--host", default="127.0.0.1", help="endereço de escuta (use 0.0.0.0 em contêiner)")
    ap.add_argument("--cache", help="pasta do cache de dados públicos (padrão: ~/.meuvoto/cache)")
    args = ap.parse_args()
    MODO["publico"] = args.publico
    cache = Path(args.cache).expanduser() if args.cache else CACHE

    tse.configurar(cache)
    analise.configurar(CONFIG)
    login.configurar(LOGIN)
    # O servidor público usa o índice da Receita que vai junto com o site (empresas.PACOTE), sem baixar 10 GB.
    # No computador pessoal, sem índice ainda, a montagem espera a vez em _preparar_historico.
    empresas.BAIXAR_DA_RECEITA = not args.publico
    _conferir_bases(sem=(empresas,) if empresas.BAIXAR_DA_RECEITA and not empresas._arquivo().exists() else ())
    threading.Thread(target=_manter_dados, daemon=True).start()
    threading.Thread(target=_preparar_historico, daemon=True).start()
    try:
        if args.tailscale:
            servidor = ServidorTailscale(("0.0.0.0", args.porta), Handler)
        else:
            servidor = ThreadingHTTPServer((args.host, args.porta), Handler)
    except OSError:
        sys.exit(f"A porta {args.porta} já está em uso. O app já está aberto? Tente --porta 8766.")

    endereco = f"http://127.0.0.1:{args.porta}"
    print(f"Voto Informado 2026 rodando em {endereco}  (Ctrl+C para encerrar)")
    if args.tailscale:
        print(f"No tablet (com o Tailscale ligado): http://{socket.gethostname().lower()}:{args.porta}")
    if not args.sem_navegador:
        threading.Timer(0.8, webbrowser.open, [endereco]).start()
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nEncerrado.")


if __name__ == "__main__":
    main()
