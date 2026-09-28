"""Lê um único arquivo de dentro de um ZIP remoto, baixando só os bytes necessários.

Os arquivos de dados abertos do TSE juntam todos os estados num ZIP de centenas
de MB; com requisições parciais (HTTP Range) baixamos só o CSV que interessa.
"""
import csv
import io
import struct
import zlib

from curl_cffi import requests


def _faixa(url, inicio, fim):
    r = requests.get(url, impersonate="chrome", timeout=300, headers={"Range": f"bytes={inicio}-{fim}"})
    if r.status_code != 206:
        raise IOError(f"o servidor não aceitou leitura parcial ({r.status_code})")
    return r.content


def listar(url):
    """Retorna {nome: (offset_cabecalho_local, tamanho_compactado, metodo)}."""
    r = requests.get(url, impersonate="chrome", timeout=60, headers={"Range": "bytes=0-0"})
    total = int(r.headers["content-range"].split("/")[-1])
    fim = _faixa(url, max(0, total - 1_000_000), total - 1)
    i = fim.rfind(b"PK\x05\x06")
    tam_cd, off_cd = struct.unpack("<II", fim[i + 12:i + 20])
    if off_cd == 0xFFFFFFFF:
        j = fim.rfind(b"PK\x06\x06")
        tam_cd, off_cd = struct.unpack("<QQ", fim[j + 40:j + 56])
    cd = _faixa(url, off_cd, off_cd + tam_cd - 1)
    arquivos, p = {}, 0
    while cd[p:p + 4] == b"PK\x01\x02":
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
    return arquivos


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
    offset, compactado, metodo = listar(url)[nome]
    cab = _faixa(url, offset, offset + 29)
    nl, el = struct.unpack("<HH", cab[26:30])
    inicio = offset + 30 + nl + el
    with requests.Session(impersonate="chrome") as s:
        r = s.get(url, stream=True, timeout=900, headers={"Range": f"bytes={inicio}-{inicio + compactado - 1}"})
        if r.status_code != 206:
            raise IOError(f"o servidor não aceitou leitura parcial ({r.status_code})")
        bruto = io.BufferedReader(_Fluxo(r.iter_content(chunk_size=1 << 20), zlib.decompressobj(-15) if metodo == 8 else None),
                                  buffer_size=1 << 20)
        yield from csv.DictReader(io.TextIOWrapper(bruto, encoding=encoding, newline=""), delimiter=";")


def baixar_membro(url, nome, destino):
    """Grava em `destino` o conteúdo descompactado de `nome` dentro do ZIP remoto."""
    offset, compactado, metodo = listar(url)[nome]
    cab = _faixa(url, offset, offset + 29)
    nl, el = struct.unpack("<HH", cab[26:30])
    inicio = offset + 30 + nl + el
    descompactar = zlib.decompressobj(-15) if metodo == 8 else None
    tmp = destino.with_suffix(destino.suffix + ".parcial")
    with requests.Session(impersonate="chrome") as s, open(tmp, "wb") as f:
        r = s.get(url, stream=True, timeout=900, headers={"Range": f"bytes={inicio}-{inicio + compactado - 1}"})
        if r.status_code != 206:
            raise IOError(f"o servidor não aceitou leitura parcial ({r.status_code})")
        for bloco in r.iter_content(chunk_size=1 << 20):
            f.write(descompactar.decompress(bloco) if descompactar else bloco)
        if descompactar:
            f.write(descompactar.flush())
    tmp.replace(destino)
    return destino
