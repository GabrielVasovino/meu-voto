"""Indicadores de qualidade de quem ocuparia as vagas de cada lista (deputados).

Para cada pessoa que, pela estimativa, ocuparia uma vaga:
- integridade (0 a 100): começa em 100; cada ponto "vale conferir" tira 20 (gasto concentrado e empresa nova, 10) e cada
  alerta sério tira 50. Usa só dados locais (TSE, trajetória, gastos de campanha e
  emendas), sem consultar a Receita, para caber no cálculo do estado inteiro;
- desempenho (0 a 100), para quem já tem mandato de deputado: na Câmara, a posição em
  relação aos colegas em presença, projetos aprovados, relatorias, projetos simbólicos,
  cota e emendas Pix; na ALESP, presença nas comissões, leis aprovadas, projetos
  simbólicos e verba de gabinete. Projeto simbólico pesa em dobro.
A nota de cada pessoa é a integridade; para quem tem mandato, o desempenho soma ou tira
até 20 pontos conforme esteja acima ou abaixo do deputado típico (quem está na média não
ganha nem perde). Assim, ter mandato não pesa contra ninguém. O índice do grupo é a média
dessas notas. Posição política não entra: isso é opinião, não qualidade.

O cálculo roda em segundo plano e fica guardado por 12 horas.
"""
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import alesp
import analise
import camara
import empresas
import gastos
import historico
import punicoes
import sancoes
import tse

TTL = 12 * tse.HORA
# Muda quando a regra da nota muda, para o cálculo guardado ser refeito na hora.
CALCULO = 7

_estado = {}  # (uf, cargo) -> {"etapa", "feitos", "total"}
_rodando = set()
_lock = threading.Lock()


def _arquivo(uf, cargo):
    p = tse._cache_dir / "indicadores"
    p.mkdir(parents=True, exist_ok=True)
    return p / f"{uf}_{cargo}.json"


# ---------- desempenho no mandato ----------

# ---------- alertas de uma pessoa ----------

def _alertas(uf, cargo, id_candidato):
    """Mesma análise completa da ficha, para que o anel da foto, a média da lista e a ficha nunca discordem."""
    a = analise.analisar(uf, cargo, id_candidato)
    if not a:
        return {"integridade": None, "alertas": 0, "atencoes": 0, "titulos": []}
    fortes = [s for s in a["sinais"] if s["nivel"] in analise.PENALIDADE and s.get("categoria") != "mandato"]
    return {
        "integridade": a["pontuacao"]["integridade"],
        "alertas": sum(1 for s in fortes if s["nivel"] == "alerta"),
        "atencoes": sum(1 for s in fortes if s["nivel"] == "atencao"),
        "titulos": list(dict.fromkeys(s["titulo"].split(":")[0] for s in fortes))[:4],
    }


def _media(valores):
    v = [x for x in valores if x is not None]
    return round(sum(v) / len(v)) if v else None


def _calcular(uf, cargo):
    chave = (uf, cargo)
    listas = historico.panorama_listas(uf, cargo)
    brutos = {c["id"]: c for c in tse.listar_bruto(uf, cargo)}
    pessoas = [(g["id"], c) for g in listas["grupos"] for c in g["eleitos"]]
    _estado[chave] = {"etapa": "calculando", "feitos": 0, "total": len(pessoas)}

    def uma(item):
        grupo, c = item
        nome = (brutos.get(c["id"]) or {}).get("nomeCompleto")
        dep = camara.deputado(nome, uf, c["nomeUrna"]) if camara.resumo() else None
        try:
            bruto = tse.ficha_bruta(uf, cargo, c["id"])
            dep_est = alesp.deputado_da_ficha(bruto) if uf == "SP" else None
            r = _alertas(uf, cargo, c["id"])
        except Exception:  # noqa: BLE001 - uma pessoa com dado faltando não derruba o cálculo
            dep_est = None
            r = {"integridade": None, "alertas": 0, "atencoes": 0, "titulos": []}
        d, casa, _ = analise.desempenho_de(dep, dep_est)
        r["desempenho"] = d["nota"] if d else None
        r["casa"] = casa
        r["nota"] = analise.nota_pessoa(r["integridade"], r["desempenho"])
        _estado[chave]["feitos"] += 1
        return grupo, c["id"], r

    with ThreadPoolExecutor(max_workers=4) as pool:
        resultados = list(pool.map(uma, pessoas))

    grupos = {}
    for grupo, id_c, r in resultados:
        grupos.setdefault(grupo, {"pessoas": {}})["pessoas"][str(id_c)] = r
    for g in grupos.values():
        ps = list(g["pessoas"].values())
        integridade = _media(p["integridade"] for p in ps)
        desemp = _media(p["desempenho"] for p in ps)
        g.update(
            membros=len(ps),
            integridade=integridade,
            desempenho=desemp,
            comMandato=sum(1 for p in ps if p["desempenho"] is not None),
            comMandatoFederal=sum(1 for p in ps if p.get("casa") == "federal"),
            comMandatoEstadual=sum(1 for p in ps if p.get("casa") == "estadual"),
            semAlertaForte=sum(1 for p in ps if not p["alertas"] and not p["atencoes"]),
            comAlertaSerio=sum(1 for p in ps if p["alertas"]),
            indice=_media(p["nota"] for p in ps),
        )
    return {"geradoEm": time.strftime("%Y-%m-%d %H:%M"), "calculo": CALCULO, "grupos": grupos}


# Nota da lista: média de quem entraria, puxada para a média de todas as listas como se cada lista tivesse mais
# PESO_MEDIA pessoas "médias". Numa lista grande quase não muda; numa lista de 1 ou 2 vagas, uma pessoa só não
# decide a nota sozinha.
PESO_MEDIA = 5


def _ajustar(dados):
    notas = [p["nota"] for g in dados.get("grupos", {}).values() for p in g["pessoas"].values() if p.get("nota") is not None]
    if not notas:
        return dados
    media = sum(notas) / len(notas)
    for g in dados["grupos"].values():
        ns = [p["nota"] for p in g["pessoas"].values() if p.get("nota") is not None]
        g["indiceAjustado"] = round((sum(ns) + PESO_MEDIA * media) / (len(ns) + PESO_MEDIA)) if ns else None
    dados["mediaGeral"] = round(media)
    return dados


def _rodar(uf, cargo):
    chave = (uf, cargo)
    try:
        dados = _calcular(uf, cargo)
        _arquivo(uf, cargo).write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")
        _estado[chave] = {"etapa": "pronto"}
    except Exception as e:  # noqa: BLE001 - mostramos o erro na interface
        _estado[chave] = {"etapa": "erro", "erro": str(e)}
    finally:
        with _lock:
            _rodando.discard(chave)


def obter(uf, cargo):
    """Devolve os indicadores prontos; se não houver (ou estiverem velhos), dispara o cálculo em segundo plano."""
    arq = _arquivo(uf, cargo)
    dados = _ajustar(json.loads(arq.read_text(encoding="utf-8"))) if arq.exists() else None
    # Também refaz quando uma base usada nos alertas ficou pronta ou foi atualizada depois do último cálculo
    # (ex.: o índice de sócios da Receita, que no primeiro dia do servidor só fica pronto horas depois).
    bases = [gastos._banco(), empresas._arquivo(), sancoes._arquivo(), punicoes._arquivo()]
    base_mais_nova = max((b.stat().st_mtime for b in bases if b.exists()), default=0)
    velho = (not arq.exists() or time.time() - arq.stat().st_mtime > TTL or arq.stat().st_mtime < base_mais_nova
             or (dados or {}).get("calculo") != CALCULO)
    chave = (uf, cargo)
    if velho and gastos._banco().exists():
        with _lock:
            if chave not in _rodando:
                _rodando.add(chave)
                threading.Thread(target=_rodar, args=(uf, cargo), daemon=True).start()
    estado = _estado.get(chave, {})
    return {"pronto": dados is not None, "atualizando": chave in _rodando, "progresso": estado, **(dados or {})}
