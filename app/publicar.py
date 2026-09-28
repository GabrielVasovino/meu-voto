"""Coloca a versão pública do Meu Voto na internet a partir deste computador, de graça.

Sobe o servidor em modo público (sem login, sem guardar votos) na porta 8780, só para este computador,
e abre um túnel da Cloudflare (cloudflared) que dá um endereço público *.trycloudflare.com.
O endereço muda cada vez que o túnel reinicia; ele aparece na tela e fica salvo em endereco-publico.txt.
O app público usa uma cópia própria do cache (~/.meuvoto/cache-publico) para não disputar arquivos com
o servidor pessoal.

Uso: python app/publicar.py      (Ctrl+C encerra tudo)
"""
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
PORTA = 8780
CACHE = Path.home() / ".meuvoto" / "cache-publico"
CACHE_PESSOAL = Path.home() / ".meuvoto" / "cache"
ARQ_ENDERECO = RAIZ.parent / "endereco-publico.txt"


def achar_cloudflared():
    for c in (shutil.which("cloudflared"), r"C:\Program Files (x86)\cloudflared\cloudflared.exe",
              r"C:\Program Files\cloudflared\cloudflared.exe"):
        if c and Path(c).exists():
            return c
    sys.exit("Não encontrei o cloudflared. Instale com: winget install Cloudflare.cloudflared")


def preparar_cache():
    """Na primeira vez, copia o cache pessoal para não baixar tudo de novo."""
    if CACHE.exists() or not CACHE_PESSOAL.exists():
        return
    print("Copiando os dados públicos já baixados (só na primeira vez, cerca de 1 minuto)...")
    shutil.copytree(CACHE_PESSOAL, CACHE, ignore=shutil.ignore_patterns("*.tmp"))


def esperar_servidor():
    for _ in range(60):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{PORTA}/api/login", timeout=2)
            return True
        except OSError:
            time.sleep(1)
    return False


def main():
    cloudflared = achar_cloudflared()
    preparar_cache()
    servidor = subprocess.Popen([sys.executable, str(RAIZ / "server.py"), "--publico", "--sem-navegador",
                                 "--porta", str(PORTA), "--cache", str(CACHE)])
    if not esperar_servidor():
        servidor.terminate()
        sys.exit("O servidor público não subiu. Veja as mensagens acima.")
    tunel = subprocess.Popen([cloudflared, "tunnel", "--no-autoupdate", "--protocol", "http2", "--url", f"http://127.0.0.1:{PORTA}"],
                             stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
    endereco = None
    try:
        for linha in tunel.stderr:
            if not endereco:
                m = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", linha)
                if m:
                    endereco = m.group(0)
                    ARQ_ENDERECO.write_text(endereco + "\n", encoding="utf-8")
                    print("\n" + "=" * 64)
                    print(f"  Meu Voto público no ar: {endereco}")
                    print("  Mande esse endereço para quem vai testar. Deixe esta janela aberta.")
                    print("  O endereço também ficou salvo em endereco-publico.txt.")
                    print("=" * 64 + "\n", flush=True)
            if "ERR" in linha:
                print("túnel:", linha.strip(), flush=True)
    except KeyboardInterrupt:
        pass
    finally:
        tunel.terminate()
        servidor.terminate()
        ARQ_ENDERECO.unlink(missing_ok=True)
        print("Versão pública encerrada.")


if __name__ == "__main__":
    main()
