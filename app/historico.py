"""Base histórica (eleição de 2022) e projeção de vagas para deputado em 2026.

É uma estimativa, não uma previsão. O método:
1. Soma os votos de 2022 de cada partido no estado (nominais + legenda),
   levando em conta as fusões (ex.: PTB e Patriota viraram PRD).
2. Agrupa os partidos nas federações de 2026 e distribui as vagas pelas regras
   do sistema proporcional (Código Eleitoral, arts. 106 a 109): quociente
   eleitoral, quociente partidário e sobras pela maior média entre quem
   atingiu 80% do quociente. Se ainda sobrar vaga, todos participam (STF, 2024).
3. Dentro de cada federação ou partido, ordena os candidatos por uma "força"
   de 0 a 100: metade vem da maior votação recente da pessoa, a de deputado em
   2022 ou a de vereador ou prefeito em 2024 (comparada à maior da lista), e
   metade da arrecadação de 2026 (comparada à maior da lista).
   Testado com 2022 em SP e MG (votos de 2018 e de 2020 + dinheiro de 2022): a
   ordem acertou 211 dos 294 eleitos (71,8%), contra 204 (69,4%) usando só os
   votos de deputado. O ganho vem de quem chega da política municipal.
"""
import csv
import io
import json
import math
import threading
import traceback
import zipfile

import gastos
import tse
import zipremoto

URL_CAND_2022 = "https://cdn.tse.jus.br/estatistica/sead/odsele/consulta_cand/consulta_cand_2022.zip"
URL_VOTOS_PARTIDO_2022 = (
    "https://cdn.tse.jus.br/estatistica/sead/odsele/votacao_partido_munzona/votacao_partido_munzona_2022.zip"
)
# O site de resultados (resultados.tse.jus.br) saiu do ar para 2022; os dados abertos do TSE ficam para sempre.
URL_VOTOS_CAND_2022 = "https://cdn.tse.jus.br/estatistica/sead/odsele/votacao_candidato_munzona/votacao_candidato_munzona_2022.zip"
URL_VAGAS_2022 = "https://cdn.tse.jus.br/estatistica/sead/odsele/consulta_vagas/consulta_vagas_2022.zip"
# Como o TSE escreve o resultado nos dados abertos -> como a interface mostra.
SITUACOES_2022 = {"ELEITO POR QP": "Eleito por QP", "ELEITO POR MÉDIA": "Eleito por média", "SUPLENTE": "Suplente",
                  "NÃO ELEITO": "Não eleito"}
TTL_HISTORICO = 90 * 24 * tse.HORA  # resultado de 2022 não muda mais
URL_CAND_2024 = "https://cdn.tse.jus.br/estatistica/sead/odsele/consulta_cand/consulta_cand_2024.zip"
URL_VOTOS_CAND_2024 = "https://cdn.tse.jus.br/estatistica/sead/odsele/votacao_candidato_munzona/votacao_candidato_munzona_2024.zip"
CARGOS_MUNICIPAIS = {"11": "Prefeito", "13": "Vereador"}

# Partidos de 2022 que deixaram de existir: sigla em 2022 -> número do sucessor em 2026.
# Não dá para casar só pelo número: o 14 era do PTB e hoje é do Missão.
FUSOES = {"PTB": 25, "PATRIOTA": 25, "PODE": 20, "PSC": 20, "PROS": 77}

_lock = threading.Lock()
_bases = {}
_municipais = {}


def _titulo(t):
    d = "".join(ch for ch in str(t or "") if ch.isdigit())
    return d.zfill(12) if d else ""


def _montar_municipal(uf):
    """Votos de cada pessoa na eleição municipal de 2024 (1º turno), pelo título de eleitor. Só o CSV do
    estado é baixado de dentro dos ZIPs nacionais do TSE."""
    pessoas = {}
    _etapas[uf] = "municipal"
    for r in zipremoto.linhas_csv(URL_CAND_2024, f"consulta_cand_2024_{uf}.csv"):
        if r["CD_CARGO"] not in CARGOS_MUNICIPAIS:
            continue
        p = pessoas.setdefault(r["SQ_CANDIDATO"], {
            "titulo": _titulo(r["NR_TITULO_ELEITORAL_CANDIDATO"]), "cargo": CARGOS_MUNICIPAIS[r["CD_CARGO"]],
            "municipio": r["NM_UE"].title(), "eleito": False, "votos": 0})
        if r["DS_SIT_TOT_TURNO"].upper().startswith("ELEITO"):
            p["eleito"] = True
    for r in zipremoto.linhas_csv(URL_VOTOS_CAND_2024, f"votacao_candidato_munzona_2024_{uf}.csv"):
        p = pessoas.get(r["SQ_CANDIDATO"])
        if p and r["NR_TURNO"] == "1":
            p["votos"] += int(r["QT_VOTOS_NOMINAIS"] or 0)
    por_titulo = {}
    for p in pessoas.values():
        if p["titulo"] and p["votos"] > por_titulo.get(p["titulo"], {}).get("votos", -1):
            por_titulo[p["titulo"]] = {k: p[k] for k in ("votos", "cargo", "municipio", "eleito")}
    return por_titulo


def municipal(uf):
    """Resultado de 2024 por título de eleitor (vazio no DF, que não tem eleição municipal, ou se o TSE falhar)."""
    if uf == "DF":
        return {}
    with _lock:
        if uf in _municipais:
            return _municipais[uf]
    try:
        m = _guardado(f"municipal2024_{uf}.json", lambda: _montar_municipal(uf))
    except Exception:  # sem a eleição municipal, a força usa só 2022, como antes (tenta de novo ao reiniciar)
        m = {}
    with _lock:
        _municipais[uf] = m
    return m


_preparando = set()
# Em que passo está a montagem de cada estado, para a tela mostrar o que está acontecendo enquanto espera.
_etapas = {}
PASSOS = ("vagas", "votos", "partidos", "candidatos", "municipal")


def etapa(uf):
    """Passo atual da montagem do estado (um de PASSOS), ou None se ainda não começou."""
    return _etapas.get(uf)


def pronto(uf):
    """True se a base de 2022 e os votos de 2024 do estado já estão montados, e as telas de deputado respondem na hora."""
    pasta = tse._cache_dir / "historico"
    with _lock:
        tem_base = uf in _bases or (pasta / f"base2022_{uf}.json").exists()
        tem_municipal = uf == "DF" or uf in _municipais or (pasta / f"municipal2024_{uf}.json").exists()
    return tem_base and tem_municipal


def preparar(uf):
    """Monta a base do estado em segundo plano (na primeira vez leva de segundos a 2 minutos, conforme o estado)."""
    with _lock:
        if uf in _preparando:
            return
        _preparando.add(uf)

    def rodar():
        try:
            base(uf)
            municipal(uf)
        except Exception:  # noqa: BLE001 - a próxima visita tenta de novo
            traceback.print_exc()
        finally:
            with _lock:
                _preparando.discard(uf)

    threading.Thread(target=rodar, daemon=True).start()


_locks_arquivo = {}


def _guardado(nome, montar):
    """Lê o arquivo da pasta historico do cache ou, se ele não existir, monta e grava. Um estado é montado uma
    vez só, mesmo quando a preparação em segundo plano e um visitante pedem o mesmo estado ao mesmo tempo."""
    arq = tse._cache_dir / "historico" / nome
    with _lock:
        lock = _locks_arquivo.setdefault(nome, threading.Lock())
    with lock:
        if arq.exists():
            return json.loads(arq.read_text(encoding="utf-8"))
        dados = montar()
        arq.parent.mkdir(parents=True, exist_ok=True)
        tmp = arq.with_suffix(".tmp")
        tmp.write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")
        tmp.replace(arq)
        return dados


def cargos_proporcionais(uf):
    return (6, 8) if uf == "DF" else (6, 7)


def _csv_do_zip(conteudo, sufixo):
    z = zipfile.ZipFile(io.BytesIO(conteudo))
    nome = next(n for n in z.namelist() if n.endswith(sufixo))
    return csv.DictReader(io.TextIOWrapper(z.open(nome), encoding="latin-1"), delimiter=";")


def _montar_base(uf):
    cargos = cargos_proporcionais(uf)
    base = {"cargos": {}, "candidatos": {}}

    _etapas[uf] = "vagas"
    for r in zipremoto.linhas_csv(URL_VAGAS_2022, f"consulta_vagas_2022_{uf}.csv"):
        if int(r["CD_CARGO"]) in cargos:
            base["cargos"][r["CD_CARGO"]] = {
                "vagas": int(r["QT_VAGA"]), "votos": {}, "siglas": {}, "grupo2022": {}, "nomeGrupo2022": {}, "eleitos": {},
            }
    if len(base["cargos"]) != len(cargos):
        raise IOError(f"o TSE não informou as vagas de deputado de {uf} em 2022")

    # Votos nominais de cada candidato no 1º turno (inclusive os anulados depois, como o site de resultados contava), somando as zonas eleitorais.
    votos_cand = {}
    _etapas[uf] = "votos"
    for r in zipremoto.linhas_csv(URL_VOTOS_CAND_2022, f"votacao_candidato_munzona_2022_{uf}.csv"):
        if r["CD_CARGO"] in base["cargos"] and r["NR_TURNO"] == "1":
            sq = r["SQ_CANDIDATO"]
            votos_cand[sq] = votos_cand.get(sq, 0) + int(r["QT_VOTOS_NOMINAIS"] or 0)

    _etapas[uf] = "partidos"
    zip_votos = tse.arquivo(URL_VOTOS_PARTIDO_2022, "historico/votacao_partido_munzona_2022.zip", TTL_HISTORICO)
    for row in _csv_do_zip(zip_votos, f"_{uf}.csv"):
        c = base["cargos"].get(row["CD_CARGO"])
        if c is None:
            continue
        nr = row["NR_PARTIDO"]
        c["votos"][nr] = c["votos"].get(nr, 0) + int(row["QT_TOTAL_VOTOS_LEG_VALIDOS"]) + int(row["QT_VOTOS_NOMINAIS_VALIDOS"])
        c["siglas"][nr] = row["SG_PARTIDO"]
        fed = row["NR_FEDERACAO"]
        c["grupo2022"][nr] = f"F{fed}" if fed not in ("-1", "") else nr
        c["nomeGrupo2022"][c["grupo2022"][nr]] = row["SG_FEDERACAO"] if fed not in ("-1", "") else row["SG_PARTIDO"]

    _etapas[uf] = "candidatos"
    zip_cand = tse.arquivo(URL_CAND_2022, "historico/consulta_cand_2022.zip", TTL_HISTORICO)
    for row in _csv_do_zip(zip_cand, f"_{uf}.csv"):
        c = base["cargos"].get(row["CD_CARGO"])
        if c is None or row["NR_TURNO"] != "1":
            continue
        nr = row["NR_PARTIDO"]
        if row["DS_SIT_TOT_TURNO"].startswith("ELEITO"):
            c["eleitos"][nr] = c["eleitos"].get(nr, 0) + 1
        votos = votos_cand.get(row["SQ_CANDIDATO"], 0)
        situacao = SITUACOES_2022.get(row["DS_SIT_TOT_TURNO"])
        titulo = row["NR_TITULO_ELEITORAL_CANDIDATO"]
        if titulo and situacao:
            base["candidatos"].setdefault(titulo, []).append({
                "cargo": int(row["CD_CARGO"]), "votos": votos, "situacao": situacao,
                "partido": row["SG_PARTIDO"], "urna": row["NM_URNA_CANDIDATO"],
            })
    return base


def base(uf):
    with _lock:
        if uf in _bases:
            return _bases[uf]
    b = _guardado(f"base2022_{uf}.json", lambda: _montar_base(uf))
    with _lock:
        _bases[uf] = b
    return b


def distribuir(votos, vagas):
    """Distribui as vagas entre grupos (partidos ou federações). Retorna (vagas por grupo, quociente)."""
    total = sum(votos.values())
    cadeiras = {g: 0 for g in votos}
    if not total or not vagas:
        return cadeiras, 0
    bruto = total / vagas
    qe = math.floor(bruto) if bruto - math.floor(bruto) <= 0.5 else math.ceil(bruto)
    for g, v in votos.items():
        cadeiras[g] = int(v // qe)
    restantes = vagas - sum(cadeiras.values())
    aptos = [g for g, v in votos.items() if v >= 0.8 * qe]
    for participantes in (aptos, list(votos)):
        while restantes > 0 and participantes:
            g = max(participantes, key=lambda g: votos[g] / (cadeiras[g] + 1))
            cadeiras[g] += 1
            restantes -= 1
    return cadeiras, qe


def margens(votos, cadeiras, qe):
    """Quantos votos, aproximadamente, faltam para cada grupo ganhar mais uma vaga e
    quantos ele pode perder antes de ficar sem a última.

    Usa a lógica da maior média: a última vaga distribuída vai para quem tem o maior
    "votos / (vagas + 1)". É uma aproximação da regra completa.
    """
    com_vaga = [g for g in votos if cadeiras[g] > 0]
    if not com_vaga or not qe:
        return {g: (None, None) for g in votos}
    ultima_media = min(votos[g] / cadeiras[g] for g in com_vaga)
    aptos = [g for g in votos if votos[g] >= 0.8 * qe]
    proxima_media = max((votos[g] / (cadeiras[g] + 1) for g in aptos), default=0)
    saida = {}
    for g, v in votos.items():
        faltam = max(ultima_media * (cadeiras[g] + 1) - v, 0.8 * qe - v, 0)
        folga = v - proxima_media * cadeiras[g] if cadeiras[g] else None
        saida[g] = (round(faltam), round(folga) if folga is not None else None)
    return saida


def validar_2022(uf, cargo):
    """Aplica o método aos votos de 2022 e compara com quem de fato foi eleito."""
    c = base(uf)["cargos"][str(cargo)]
    votos, reais = {}, {}
    for nr, v in c["votos"].items():
        g = c["grupo2022"][nr]
        votos[g] = votos.get(g, 0) + v
        reais[g] = reais.get(g, 0) + c["eleitos"].get(nr, 0)
    estimadas, _ = distribuir(votos, c["vagas"])
    erro = sum(abs(estimadas[g] - reais.get(g, 0)) for g in votos) // 2
    return {"vagas": c["vagas"], "vagasDiferentes": erro}


def _numero_2026(nr, sigla):
    return str(FUSOES.get(sigla, nr))


def _grupos_2026(uf, cargo):
    grupos = {}
    for c in tse.listar_bruto(uf, cargo):
        g = grupos.setdefault(c["nomeColigacao"], {"partidos": {}, "candidatos": []})
        g["partidos"][str(c["numero"])[:2]] = (c.get("partido") or {}).get("sigla")
        g["candidatos"].append(c)
    return grupos


def projecao(uf, cargo):
    c = base(uf)["cargos"][str(cargo)]
    votos_2026 = {}
    for nr, v in c["votos"].items():
        n = _numero_2026(nr, c["siglas"][nr])
        votos_2026[n] = votos_2026.get(n, 0) + v

    grupos = _grupos_2026(uf, cargo)
    votos_grupo = {g: sum(votos_2026.get(p, 0) for p in d["partidos"]) for g, d in grupos.items()}
    usados = {p for d in grupos.values() for p in d["partidos"]}
    sem_par = sorted(
        ({"partido": c["siglas"][nr], "votos": v} for nr, v in c["votos"].items()
         if _numero_2026(nr, c["siglas"][nr]) not in usados and v),
        key=lambda x: -x["votos"],
    )
    cadeiras, qe = distribuir(votos_grupo, c["vagas"])
    folgas = margens(votos_grupo, cadeiras, qe)
    total = sum(votos_grupo.values()) or 1
    lista = [
        {
            "id": g,
            "partidos": sorted(s for s in d["partidos"].values() if s),
            "votos2022": votos_grupo[g],
            "percentual": votos_grupo[g] / total,
            "vagas": cadeiras[g],
            "candidatos": len(d["candidatos"]),
            "faltamParaMaisUma": folgas[g][0],
            "folgaDaUltima": folgas[g][1],
        }
        for g, d in grupos.items()
    ]
    lista.sort(key=lambda x: (-x["vagas"], -x["votos2022"]))
    return {
        "cargo": cargo,
        "vagas": c["vagas"],
        "quociente": qe,
        "grupos": lista,
        "semCorrespondente": sem_par,
        "validacao2022": validar_2022(uf, cargo),
    }


def _faixa(posicao, vagas):
    if vagas == 0:
        return "Muito baixa"
    if posicao <= math.ceil(vagas * 0.75):
        return "Alta"
    if posicao <= vagas + max(1, round(vagas * 0.25)):
        return "Disputada"
    if posicao <= 2 * vagas + 2:
        return "Baixa"
    return "Muito baixa"


def _historico_candidato(b, titulo, cargo):
    """Melhor referência de 2022: o mesmo cargo, senão o outro cargo de deputado."""
    entradas = b["candidatos"].get(titulo or "", [])
    if not entradas:
        return None
    return max(entradas, key=lambda e: (e["cargo"] == cargo, e["votos"]))


def _financas(candidatos):
    """Dinheiro de cada candidato, pelo banco local de gastos. Enquanto o banco é montado (só nos primeiros minutos
    de um servidor novo), vale zero para todos e a ordem sai só pelos votos; a tela avisa que é provisória.
    Pedir as contas ao TSE candidato a candidato levava minutos por estado e estourava o tempo do nginx."""
    locais = gastos.financas([c["id"] for c in candidatos])
    if locais is not None:
        return [locais[c["id"]] for c in candidatos]
    return [{"arrecadado": 0, "publico": 0, "gastos": 0} for _ in candidatos]


def ranking(uf, cargo, grupo, proj=None, grupos=None):
    grupos = grupos or _grupos_2026(uf, cargo)
    if grupo not in grupos:
        return None
    proj = proj or projecao(uf, cargo)
    vagas = next(g["vagas"] for g in proj["grupos"] if g["id"] == grupo)
    b = base(uf)
    mun = municipal(uf)
    candidatos = grupos[grupo]["candidatos"]
    financas = _financas(candidatos)

    linhas = []
    for c, ct in zip(candidatos, financas):
        h = _historico_candidato(b, c.get("tituloEleitor"), cargo)
        m = mun.get(_titulo(c.get("tituloEleitor")))
        situacao = c.get("descricaoSituacao")
        linhas.append({
            "id": c["id"],
            "numero": c["numero"],
            "nomeUrna": c.get("nomeUrna"),
            "partido": (c.get("partido") or {}).get("sigla"),
            "situacao": situacao,
            "apto": tse._prioridade({"situacao": situacao}) < 2,
            "votos2022": h["votos"] if h else 0,
            "cargo2022": tse.CARGOS.get(h["cargo"]) if h else None,
            "situacao2022": h["situacao"] if h else None,
            "votosMunicipais": m["votos"] if m else 0,
            "cargoMunicipal": m["cargo"] if m else None,
            "municipio": m["municipio"] if m else None,
            "eleitoMunicipal": m["eleito"] if m else None,
            "arrecadado": ct["arrecadado"],
            "fundoPublico": ct["publico"],
            "gastos": ct["gastos"],
        })

    aptos = [l for l in linhas if l["apto"]]
    # Votos de referência: a maior votação recente, de deputado (2022) ou municipal (2024).
    for l in aptos:
        l["votosReferencia"] = max(l["votos2022"], l["votosMunicipais"])
    max_votos = max((l["votosReferencia"] for l in aptos), default=0) or 1
    max_dinheiro = max((l["arrecadado"] for l in aptos), default=0) or 1
    for l in aptos:
        l["forca"] = round(50 * l["votosReferencia"] / max_votos + 50 * l["arrecadado"] / max_dinheiro, 1)
    aptos.sort(key=lambda l: (-l["forca"], -l["votosReferencia"], -l["arrecadado"]))
    for i, l in enumerate(aptos, 1):
        l["posicao"] = i
        l["chance"] = _faixa(i, vagas)
    inaptos = [l for l in linhas if not l["apto"]]
    for l in inaptos:
        l["posicao"] = l["forca"] = None
        l["chance"] = "Candidatura com problema"
    return {"grupo": grupo, "vagasEstimadas": vagas, "candidatos": aptos + inaptos}


def faixa_disputa(vagas):
    return max(2, round(vagas * 0.25))


def panorama_listas(uf, cargo):
    """Todas as listas do estado de uma vez: vagas, margens, quem ocuparia as vagas e quem está na disputa."""
    proj = projecao(uf, cargo)
    grupos = _grupos_2026(uf, cargo)
    resumo = lambda c: {k: c[k] for k in ("id", "numero", "nomeUrna", "partido", "posicao", "chance")}
    for g in proj["grupos"]:
        r = ranking(uf, cargo, g["id"], proj, grupos)
        aptos = [c for c in r["candidatos"] if c["posicao"]]
        vagas = g["vagas"]
        faixa = faixa_disputa(vagas) if vagas else 0
        g["eleitos"] = [resumo(c) for c in aptos[:vagas]]
        g["disputa"] = [resumo(c) for c in aptos if vagas and vagas < c["posicao"] <= vagas + faixa]
        g["maisFortes"] = [resumo(c) for c in aptos[:3]] if not vagas else []
        g["aptos"] = len(aptos)
    proj["semDinheiro"] = not gastos._banco().exists()
    return proj
