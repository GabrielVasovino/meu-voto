"""Lê um único arquivo de dentro de um ZIP remoto, baixando só os bytes necessários.

Os arquivos de dados abertos do TSE juntam todos os estados num ZIP de centenas
de MB; com requisições parciais (HTTP Range) baixamos só o CSV que interessa.
"""
import csv
import io
import struct
import time
import zlib

from curl_cffi import requests

TENTATIVAS = 4
ESPERA_ENTRE_TENTATIVAS = 30


class ArquivoMudou(IOError):
    """O TSE publicou uma versão nova do ZIP entre a leitura do índice e a dos dados."""


# O TSE refaz esses ZIPs várias vezes ao dia. Sem conferir a versão, o índice de uma e os bytes de outra se
# misturam e a descompactação falha ("invalid block type"). Cada leitura guarda a versão (ETag) vista no índice
# e manda If-Range: se o arquivo mudou, o servidor responde 200 em vez de 206 e lemos tudo de novo.
def _cabecalhos(inicio, fim, versao):
    cab = {"Range": f"bytes={inicio}-{fim}"}
    if versao:
        cab["If-Range"] = versao
    return cab


def _conferir(r):
    if r.status_code == 200:
        raise ArquivoMudou("o TSE publicou uma versão nova do arquivo durante a leitura")
    if r.status_code != 206:
        raise IOError(f"o servidor não aceitou leitura parcial ({r.status_code})")


def _faixa(url, inicio, fim, versao=None):
    r = requests.get(url, impersonate="chrome", timeout=300, headers=_cabecalhos(inicio, fim, versao))
    _conferir(r)
    return r.content


def listar(url):
    """Retorna {nome: (offset_cabecalho_local, tamanho_compactado, metodo)}."""
    return _listar(url)[0]


def _listar(url):
    """Índice do ZIP e a versão do arquivo em que ele foi lido."""
    r = requests.get(url, impersonate="chrome", timeout=60, headers={"Range": "bytes=0-0"})
    versao = r.headers.get("etag") or r.headers.get("last-modified")
    total = int(r.headers["content-range"].split("/")[-1])
    fim = _faixa(url, max(0, total - 1_000_000), total - 1, versao)
    i = fim.rfind(b"PK")
    tam_cd, off_cd = struct.unpack("<II", fim[i + 12:i + 20])
    if off_cd == 0xFFFFFFFF:
        j = fim.rfind(b"PK")
        tam_cd, off_cd = struct.unpack("<QQ", fim[j + 40:j + 56])
    cd = _faixa(url, off_cd, off_cd + tam_cd - 1, versao)
    arquivos, p = {}, 0
    while cd[p:p + 4] == b"PK":
        metodo = struct.unpack("<H", cd[p + 10:p + 12])[0]
        compactado = struct.unpack("<I", cd[p + 20:p + 24])[0]
        nl, el, cl = struct.unpack("<HHH", cd[p + 28:p + 34])
        offset = struct.unpack("<I", cd[p + 42:p + 46])[0]
        nome = cd[p + 46:p + 46 + nl].decode("cp437")
        extra = cd[p + 46 + nl:p + 46 + nl + el]
        # ZIP64: tamanhos e offset grandes ficam no campo extra 0x0001
        q = 0
        while q + 4 <= len(extra):
            tipo, tam = struct.unpack("<HH", extra[q:q + 4])
            if tipo == 1:
                valores = list(struct.unpack(f"<{tam // 8}Q", extra[q + 4:q + 4 + tam]))
                if struct.unpack("<I", cd[p + 24:p + 28])[0] == 0xFFFFFFFF:
                    valores.pop(0)
                if compactado == 0xFFFFFFFF:
                    compactado = valores.pop(0)
                if offset == 0xFFFFFFFF:
                    offset = valores.pop(0)
            q += 4 + tam
        arquivos[nome] = (offset, compactado, metodo)
        p += 46 + nl + el + cl
    return arquivos, versao


def _abrir(sessao, url, nome):
    """Resposta em fluxo com os bytes compactados de `nome`, todos da mesma versão do ZIP. Se o TSE trocar o
    arquivo no meio, espera um pouco e recomeça: isso é percebido antes de qualquer linha ser lida."""
    for tentativa in range(TENTATIVAS):
        try:
            arquivos, versao = _listar(url)
            offset, compactado, metodo = arquivos[nome]
            cab = _faixa(url, offset, offset + 29, versao)
            nl, el = struct.unpack("<HH", cab[26:30])
            inicio = offset + 30 + nl + el
            r = sessao.get(url, stream=True, timeout=900, headers=_cabecalhos(inicio, inicio + compactado - 1, versao))
            _conferir(r)
            return r, metodo
        except ArquivoMudou:
            if tentativa == TENTATIVAS - 1:
                raise
            time.sleep(ESPERA_ENTRE_TENTATIVAS)


class _Fluxo(io.RawIOBase):
    """Arquivo somente-leitura que descompacta os bytes à medida que chegam da rede."""

    def __init__(self, blocos, descompactar):
        self._blocos = blocos
        self._desc = descompactar
        self._sobra = b""

    def readable(self):
        return True

    def readinto(self, b):
        while not self._sobra:
            try:
                bloco = next(self._blocos)
            except StopIteration:
                if self._desc:
                    self._sobra, self._desc = self._desc.flush(), None
                    if self._sobra:
                        break
                return 0
            self._sobra = self._desc.decompress(bloco) if self._desc else bloco
        n = min(len(b), len(self._sobra))
        b[:n] = self._sobra[:n]
        self._sobra = self._sobra[n:]
        return n


def linhas_csv(url, nome, encoding="latin-1"):
    """Lê um CSV (separado por ;) de dentro do ZIP remoto, linha a linha, sem gravar em disco."""
    with requests.Session(impersonate="chrome") as s:
        r, metodo = _abrir(s, url, nome)
        bruto = io.BufferedReader(_Fluxo(r.iter_content(chunk_size=1 << 20), zlib.decompressobj(-15) if metodo == 8 else None),
                                  buffer_size=1 << 20)
        yield from csv.DictReader(io.TextIOWrapper(bruto, encoding=encoding, newline=""), delimiter=";")


def baixar_membro(url, nome, destino):
    """Grava em `destino` o conteúdo descompactado de `nome` dentro do ZIP remoto."""
    tmp = destino.with_suffix(destino.suffix + ".parcial")
    with requests.Session(impersonate="chrome") as s, open(tmp, "wb") as f:
        r, metodo = _abrir(s, url, nome)
        descompactar = zlib.decompressobj(-15) if metodo == 8 else None
        for bloco in r.iter_content(chunk_size=1 << 20):
            f.write(descompactar.decompress(bloco) if descompactar else bloco)
        if descompactar:
            f.write(descompactar.flush())
    tmp.replace(destino)
    return destino
