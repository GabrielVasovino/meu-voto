"""Gera a versão estática do site, para o GitHub Pages.

Sobe o servidor aqui mesmo (modo público, numa porta local), espera as bases de dados públicos ficarem prontas e
pede cada resposta que as telas usam: listas de candidatos, fichas, análises, listas de deputados, questionário,
fornecedores e empresas. Cada resposta vira um arquivo JSON em --api, com o caminho que o navegador calcula em
arquivoApi() (app.js). No fim, junta a interface (static/) e esses arquivos em --saida.

As respostas ficam em --api entre uma execução e outra: se uma fonte falhar agora, o site segue com a versão anterior.

Uso:
  python app/gerar_estatico.py                    # tudo (a primeira vez leva horas)
  python app/gerar_estatico.py --ufs RR           # só um estado, para testar
  python app/gerar_estatico.py --so-interface     # só copia a interface, com as respostas já geradas
  python -m http.server -d build/site             # abre em http://localhost:8000
"""
import argparse
import json
import re
import shutil
import sys
import threading
import time
import traceback
import unicodedata
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlencode

RAIZ = Path(__file__).resolve().parent
PROJETO = RAIZ.parent
# O que não vai para o site estático: login e painel de uso só existem no servidor.
FORA_DO_SITE = {"login.html", "login.js", "monitor.html"}
# Respostas que dependem de a fonte estar no ar agora: tenta de novo e, se não der, fica a versão anterior.
PASSAGEIRO = {202, 429, 500, 502, 503}
TENTATIVAS = 4


def pedaco(valor):
    """Um valor de parâmetro como pedaço de caminho. Igual a pedaco() em app.js."""
    s = re.sub(r"[\u0300-\u036f]", "", unicodedata.normalize("NFD", str(valor)))
    return re.sub(r"[^A-Za-z0-9-]", "_", s) or "_"


def arquivo(rota, params):
    """/api/ficha?uf=SP&cargo=6&id=1 -> ficha/6/1/SP.json (valores na ordem alfabética das chaves)."""
    if not params:
        return f"{rota}.json"
    return f"{rota}/" + "/".join(pedaco(params[k]) for k in sorted(params)) + ".json"


class Gerador:
    def __init__(self, porta, destino, prazo):
        self.base = f"http://127.0.0.1:{porta}/api/"
        self.destino = destino
        self.prazo = prazo
        self.lock = threading.Lock()
        self.contagem = {"novos": 0, "anteriores": 0, "faltando": 0}
        self.vistos = {}

    def pedir(self, rota, params=None):
        """Busca uma resposta e grava o arquivo. Devolve os dados (ou None se não houver)."""
        params = {k: str(v) for k, v in (params or {}).items()}
        nome = arquivo(rota, params)
        alvo = self.destino / nome
        with self.lock:
            anterior = self.vistos.get(nome)
            if anterior is not None and anterior != params:
                print(f"  aviso: {rota} {params} e {anterior} caem no mesmo arquivo {nome}", file=sys.stderr)
            self.vistos[nome] = params
        if time.time() > self.prazo:
            return self._anterior(alvo)
        url = self.base + rota + ("?" + urlencode(params) if params else "")
        status, corpo = None, None
        for tentativa in range(TENTATIVAS):
            try:
                with urllib.request.urlopen(url, timeout=600) as r:
                    status, corpo = r.status, r.read()
            except urllib.error.HTTPError as e:
                status, corpo = e.code, e.read()
            except Exception:  # noqa: BLE001 - conexão caída: tenta de novo
                status, corpo = None, None
            if status is not None and status not in PASSAGEIRO:
                break
            time.sleep(10 if status == 202 else 3 * (tentativa + 1))
        if status is None or status in PASSAGEIRO:
            return self._anterior(alvo)
        dados = json.loads(corpo)
        if status != 200:
            # Erro que não muda (candidato sem registro, empresa sem dados): o navegador mostra a mesma mensagem.
            dados = {"_status": status, "erro": dados.get("erro")}
        alvo.parent.mkdir(parents=True, exist_ok=True)
        tmp = alvo.with_name(alvo.name + ".tmp")
        tmp.write_text(json.dumps(dados, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        tmp.replace(alvo)
        with self.lock:
            self.contagem["novos"] += 1
        return None if status != 200 else dados

    def _anterior(self, alvo):
        with self.lock:
            self.contagem["anteriores" if alvo.exists() else "faltando"] += 1
        if not alvo.exists():
            return None
        dados = json.loads(alvo.read_text(encoding="utf-8"))
        return None if "_status" in dados else dados

    def varios(self, pedidos, trabalhadores, rotulo):
        pedidos = list(pedidos)
        print(f"{rotulo}: {len(pedidos)} respostas", flush=True)
        inicio, feitos = time.time(), [0]

        def um(p):
            try:
                return self.pedir(*p)
            except Exception:  # noqa: BLE001 - uma resposta com problema não para as outras
                traceback.print_exc()
                return None
            finally:
                with self.lock:
                    feitos[0] += 1
                    if feitos[0] % 500 == 0:
                        print(f"  {feitos[0]}/{len(pedidos)} em {time.time() - inicio:.0f} s", flush=True)

        with ThreadPoolExecutor(max_workers=trabalhadores) as pool:
            return list(pool.map(um, pedidos))


def _esperar_bases(server, historico, ufs, limite):
    """Confere as bases a cada minuto (como o servidor faz de hora em hora) até todas ficarem prontas, ou até o
    limite. Uma base que falhou (ex.: o TSE refazendo o ZIP) é tentada de novo na conferência seguinte."""
    fim = time.time() + limite
    while True:
        server._conferir_bases()
        bases = server._status_bases()
        faltam = [b["descricao"] for b in bases if not b["pronto"] or b["atualizando"]]
        estados = [uf for uf in ufs if not historico.pronto(uf)]
        if not faltam and not estados:
            print("bases prontas", flush=True)
            return
        if time.time() > fim:
            print(f"seguindo sem esperar mais: {faltam} {estados}", flush=True)
            return
        print(f"esperando {len(faltam)} bases e {len(estados)} estados: {', '.join(faltam[:3])}", flush=True)
        time.sleep(60)


def _cnpjs(dados, achados):
    """Todo CNPJ que aparece numa resposta: é o que as telas oferecem para abrir a ficha da empresa."""
    if isinstance(dados, dict):
        for k, v in dados.items():
            if k in ("cnpj", "doc") and isinstance(v, str) and re.fullmatch(r"\d{14}", v):
                achados.add(v)
            else:
                _cnpjs(v, achados)
    elif isinstance(dados, list):
        for v in dados:
            _cnpjs(v, achados)


def gerar(args):
    sys.path.insert(0, str(RAIZ))
    import analise
    import empresas
    import historico
    import login
    import server
    import tse

    server.MODO["publico"] = True
    tse.configurar(Path(args.cache).expanduser())
    analise.configurar(PROJETO / "dados" / "config.json")
    login.configurar(PROJETO / "dados" / "login.json")
    empresas.BAIXAR_DA_RECEITA = False
    servidor = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    ufs = [uf for uf in server.ORDEM_ESTADOS if not args.ufs or uf in args.ufs]

    def preparar_estados():
        for uf in ufs:
            try:
                historico.base(uf)
                historico.municipal(uf)
            except Exception:  # noqa: BLE001 - a tela de deputados deste estado pede de novo (e espera)
                traceback.print_exc()

    threading.Thread(target=preparar_estados, daemon=True).start()
    _esperar_bases(server, historico, ufs, args.espera * 60)

    g = Gerador(servidor.server_address[1], Path(args.api), time.time() + args.prazo * 60)
    n = args.trabalhadores
    g.varios([("config",), ("status",)], n, "configuração")

    cargos = [("BR", 1)] + [(uf, c) for uf in ufs for c in (3, 5) + historico.cargos_proporcionais(uf)]
    listas = g.varios([("candidatos", {"uf": uf, "cargo": c}) for uf, c in cargos], n, "listas de candidatos")
    candidatos = [(uf, c, x["id"]) for (uf, c), l in zip(cargos, listas) for x in (l or {}).get("candidatos", [])]

    g.varios([("quiz", {"uf": uf}) for uf in ufs], n, "questionário")
    g.varios([("gastos/panorama", {"uf": uf}) for uf in ufs], n, "fornecedores")
    proporcionais = [(uf, c) for uf in ufs for c in historico.cargos_proporcionais(uf)]
    paineis = g.varios([("listas", {"uf": uf, "cargo": c}) for uf, c in proporcionais], n, "listas de deputados")
    g.varios([(rota, {"uf": uf, "cargo": c}) for uf, c in proporcionais for rota in ("indicadores", "perfis")], n,
             "indicadores e perfis")
    grupos = [(uf, c, gr["id"]) for (uf, c), p in zip(proporcionais, paineis) for gr in (p or {}).get("grupos", [])]
    g.varios([(rota, {"uf": uf, "cargo": c, "grupo": gr}) for uf, c, gr in grupos
              for rota in ("ranking", "grupo", "rede_lista")], n, "federações e partidos")

    # Senado, governo e presidência primeiro: são poucos e aparecem para todo mundo.
    candidatos.sort(key=lambda x: x[1] in tse.CARGOS_PROPORCIONAIS)
    fichas = g.varios([(rota, {"uf": uf, "cargo": c, "id": i}) for uf, c, i in candidatos for rota in ("ficha", "analise")],
                      n, "fichas e análises")

    achados = set()
    for d in fichas:
        _cnpjs(d, achados)
    for p in (g.destino / "gastos" / "panorama").glob("*.json"):
        _cnpjs(json.loads(p.read_text(encoding="utf-8")), achados)
    for p in (g.destino / "rede_lista").rglob("*.json"):
        _cnpjs(json.loads(p.read_text(encoding="utf-8")), achados)
    g.varios([("empresa", {"cnpj": c}) for c in sorted(achados)], n, "empresas")
    servidor.shutdown()
    print(f"respostas: {g.contagem['novos']} novas, {g.contagem['anteriores']} da versão anterior, "
          f"{g.contagem['faltando']} sem dados", flush=True)


def montar_site(api, saida):
    saida = Path(saida)
    if saida.exists():
        shutil.rmtree(saida)
    shutil.copytree(RAIZ / "static", saida, ignore=lambda pasta, nomes: [x for x in nomes if x in FORA_DO_SITE])
    if Path(api).exists():
        shutil.copytree(api, saida / "api", ignore=shutil.ignore_patterns("*.tmp"))
    (saida / ".nojekyll").touch()
    print(f"site montado em {saida}")


def main():
    ap = argparse.ArgumentParser(description="Gera a versão estática do Voto Informado 2026")
    ap.add_argument("--cache", default=str(Path.home() / ".meuvoto" / "cache"), help="cache dos dados públicos")
    ap.add_argument("--api", default=str(PROJETO / "build" / "api"), help="onde ficam as respostas geradas")
    ap.add_argument("--saida", default=str(PROJETO / "build" / "site"), help="pasta do site pronto")
    ap.add_argument("--ufs", type=lambda s: {x.strip().upper() for x in s.split(",") if x.strip()},
                    help="só estes estados, separados por vírgula (para testar)")
    ap.add_argument("--trabalhadores", type=int, default=8, help="pedidos ao mesmo tempo")
    ap.add_argument("--espera", type=int, default=60, help="minutos, no máximo, esperando as bases")
    ap.add_argument("--prazo", type=int, default=240,
                    help="minutos, no máximo, gerando respostas; depois disso fica a versão anterior")
    ap.add_argument("--so-interface", action="store_true", help="não gera respostas, só monta o site")
    args = ap.parse_args()
    if not args.so_interface:
        gerar(args)
    montar_site(args.api, args.saida)


if __name__ == "__main__":
    main()
