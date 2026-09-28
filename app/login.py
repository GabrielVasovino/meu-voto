"""Login do Meu Voto: um usuário, senha com PBKDF2 e sessões por cookie.

Tudo fica em dados/login.json. A senha nunca é gravada, só o hash com sal; as
sessões também são gravadas como hash, então quem ler o arquivo não consegue
entrar com elas.
"""
import hashlib
import hmac
import json
import re
import secrets
import threading
import time
from pathlib import Path

ITERACOES = 600_000
DURACAO_SESSAO = 30 * 24 * 3600
MAX_FALHAS = 5
ESPERA_FALHAS = 60

_arq = None
_lock = threading.Lock()
_falhas = []  # horários das últimas tentativas erradas


def configurar(arquivo):
    global _arq
    _arq = Path(arquivo)


def _ler():
    if _arq and _arq.exists():
        try:
            return json.loads(_arq.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def _gravar(dados):
    _arq.parent.mkdir(parents=True, exist_ok=True)
    tmp = _arq.with_suffix(".tmp")
    tmp.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(_arq)


def _hash_senha(senha, sal, iteracoes=ITERACOES):
    return hashlib.pbkdf2_hmac("sha256", senha.encode("utf-8"), bytes.fromhex(sal), iteracoes).hex()


def _hash_token(token):
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def existe():
    return bool(_ler().get("hash"))


def validar_novo(usuario, senha):
    """Mensagem de erro para um cadastro inválido, ou None."""
    if not re.fullmatch(r"[\w.@-]{3,40}", usuario or ""):
        return "O usuário precisa ter de 3 a 40 letras, números ou . _ @ -"
    if len(senha or "") < 8:
        return "A senha precisa ter pelo menos 8 caracteres"
    if len(senha) > 200:
        return "Senha longa demais"
    return None


def criar(usuario, senha):
    """Cria o login (só se ainda não existir) e já devolve uma sessão."""
    with _lock:
        dados = _ler()
        if dados.get("hash"):
            return None
        sal = secrets.token_hex(16)
        dados = {"usuario": usuario, "sal": sal, "iteracoes": ITERACOES,
                 "hash": _hash_senha(senha, sal), "sessoes": {}}
        return _nova_sessao(dados)


def entrar(usuario, senha):
    """Devolve (token, None) se certo; (None, mensagem) se errado ou bloqueado."""
    agora = time.time()
    with _lock:
        _falhas[:] = [t for t in _falhas if agora - t < ESPERA_FALHAS]
        if len(_falhas) >= MAX_FALHAS:
            espera = int(ESPERA_FALHAS - (agora - _falhas[0])) + 1
            return None, f"Muitas tentativas erradas. Tente de novo em {espera} segundos."
        dados = _ler()
        if not dados.get("hash"):
            return None, "Nenhum login criado ainda"
        certo_usuario = hmac.compare_digest(usuario.lower(), dados["usuario"].lower())
        certo_senha = hmac.compare_digest(
            _hash_senha(senha, dados["sal"], dados.get("iteracoes", ITERACOES)), dados["hash"])
        if not (certo_usuario and certo_senha):
            _falhas.append(agora)
            return None, "Usuário ou senha incorretos"
        _falhas.clear()
        return _nova_sessao(dados), None


def _nova_sessao(dados):
    token = secrets.token_urlsafe(32)
    agora = time.time()
    sessoes = {h: exp for h, exp in dados.get("sessoes", {}).items() if exp > agora}
    sessoes[_hash_token(token)] = agora + DURACAO_SESSAO
    dados["sessoes"] = sessoes
    _gravar(dados)
    return token


def sessao_valida(token):
    if not token or len(token) > 100:
        return False
    exp = _ler().get("sessoes", {}).get(_hash_token(token))
    return bool(exp and exp > time.time())


def sair(token):
    if not token:
        return
    with _lock:
        dados = _ler()
        if dados.get("sessoes", {}).pop(_hash_token(token), None) is not None:
            _gravar(dados)


def usuario():
    return _ler().get("usuario")
