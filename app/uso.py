"""Contadores de uso do servidor público, só em memória e só agregados.

Guarda, minuto a minuto (última hora), quantos pedidos chegaram, quantos deram erro e quanto tempo levaram.
Visitantes são contados por um resumo embaralhado do IP que nunca sai daqui nem vai para disco.
Serve para acompanhar a carga em /monitor.html; tudo zera quando o servidor reinicia.
"""
import hashlib
import os
import secrets
import threading
import time

_SAL = secrets.token_bytes(16)
_lock = threading.Lock()
_inicio = time.time()
_minutos = {}  # minuto -> contadores
_visitantes = {}  # resumo do IP -> último acesso
_sem_ip_real = [0]


def _novo():
    return {"api": 0, "paginas": 0, "limite": 0, "erros": 0, "tempo": 0.0, "lento": 0, "maior": 0.0}


def registrar(caminho, status, segundos, ip, ip_real):
    agora = time.time()
    minuto = int(agora // 60)
    chave = hashlib.blake2b(ip.encode(), key=_SAL, digest_size=8).hexdigest()
    with _lock:
        m = _minutos.setdefault(minuto, _novo())
        if caminho.startswith("/api/"):
            m["api"] += 1
            m["tempo"] += segundos
            m["maior"] = max(m["maior"], segundos)
            if segundos > 3:
                m["lento"] += 1
        else:
            m["paginas"] += 1
        if status == 429:
            m["limite"] += 1
        elif status >= 500:
            m["erros"] += 1
        _visitantes[chave] = agora
        if not ip_real:
            _sem_ip_real[0] += 1
        if len(_minutos) > 70:
            for velho in [k for k in _minutos if k < minuto - 60]:
                del _minutos[velho]
        if len(_visitantes) > 50000:
            for velho in [k for k, v in _visitantes.items() if agora - v > 3600]:
                del _visitantes[velho]


def _memoria_mb():
    try:
        with open("/proc/self/status") as f:
            for linha in f:
                if linha.startswith("VmRSS:"):
                    return round(int(linha.split()[1]) / 1024)
    except OSError:
        return None


def resumo():
    agora = time.time()
    minuto = int(agora // 60)
    with _lock:
        serie = []
        for k in range(minuto - 59, minuto + 1):
            m = _minutos.get(k, _novo())
            serie.append({"hora": time.strftime("%H:%M", time.localtime(k * 60)), "api": m["api"],
                          "paginas": m["paginas"], "limite": m["limite"], "erros": m["erros"], "lento": m["lento"],
                          "mediaMs": round(1000 * m["tempo"] / m["api"]) if m["api"] else None,
                          "maiorMs": round(1000 * m["maior"]) if m["api"] else None})
        online = sum(1 for v in _visitantes.values() if agora - v < 300)
        hora = sum(1 for v in _visitantes.values() if agora - v < 3600)
        sem_ip = _sem_ip_real[0]
    try:
        carga = [round(x, 2) for x in os.getloadavg()]
    except (AttributeError, OSError):
        carga = None
    return {
        "agora": time.strftime("%d/%m %H:%M:%S"),
        "ligadoHa": round(agora - _inicio),
        "visitantes5min": online,
        "visitantes1h": hora,
        "minutos": serie,
        "servidor": {"processadores": os.cpu_count(), "carga": carga, "memoriaMb": _memoria_mb(),
                     "linhas": threading.active_count()},
        "pedidosSemIpReal": sem_ip,
    }
