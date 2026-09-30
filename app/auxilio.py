"""Auxílio Emergencial (2020 e 2021) recebido por quem disputa em 2026 (Portal da Transparência, CGU).

O benefício era para quem tinha renda baixa. Receber não é problema; o que chama atenção é receber tendo declarado ao
TSE, perto daquela época, um patrimônio alto, porque pode indicar que a pessoa não tinha direito. O cruzamento usa
um mês de cada rodada (julho de 2020 e junho de 2021), que pega quase todo mundo que recebeu.

O CPF vem com parte escondida (***123456**): a pessoa é ligada ao candidato pelos 6 dígitos do meio e pelo nome
completo. Os arquivos somam quase 2 GB; tudo é montado no computador pessoal e vai junto com o site em PACOTE, sem
CPF. Para montar: python app/auxilio.py
"""
import gzip
import json
import threading
import time
from pathlib import Path

import empresas
import tse
import zipremoto

PACOTE = Path(__file__).resolve().parent / "dados_publicos" / "auxilio_emergencial.json.gz"
URL = "https://dadosabertos-download.cgu.gov.br/PortalDaTransparencia/saida/auxilio-emergencial/{mes}_AuxilioEmergencial.zip"
MESES = ("202007", "202106")

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
    """{"meses": ["2020-07", ...]} ou None."""
    return ((_dados or {}).get("candidatos") or {}).get(str(id_candidato))


def montar():
    chaves = empresas._candidatos()  # "meio|NOME" -> {sq}
    candidatos = {}
    for mes in MESES:
        url = URL.format(mes=mes)
        nome = next(n for n in zipremoto.listar(url) if n.lower().endswith(".csv"))
        lidas = 0
        for r in zipremoto.linhas_csv(url, nome):
            lidas += 1
            meio = empresas._digitos(r.get("CPF BENEFICIÁRIO"))
            if len(meio) != 6:
                continue
            for sq in chaves.get(f"{meio}|{empresas._nome(r.get('NOME BENEFICIÁRIO'))}", ()):
                m = f"{mes[:4]}-{mes[4:]}"
                c = candidatos.setdefault(sq, {"meses": []})
                if m not in c["meses"]:
                    c["meses"].append(m)
        print(f"  {mes}: {lidas} pagamentos lidos, {len(candidatos)} candidatos até aqui")
    dados = {"geradoEm": time.strftime("%d/%m/%Y"), "candidatos": candidatos}
    PACOTE.parent.mkdir(parents=True, exist_ok=True)
    PACOTE.write_bytes(gzip.compress(json.dumps(dados, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), 9))
    print(f"{PACOTE.name}: {len(candidatos)} candidatos de 2026 receberam o auxílio")


if __name__ == "__main__":
    tse.configurar(Path.home() / ".meuvoto" / "cache-publico")
    montar()
