FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=America/Sao_Paulo

WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# O cache de dados públicos (centenas de MB) fica num volume para sobreviver a reinícios.
RUN useradd --create-home --uid 1000 meuvoto \
    && mkdir -p /cache && chown meuvoto /cache
USER meuvoto
VOLUME /cache

EXPOSE 8765

CMD ["python", "app/server.py", "--publico", "--sem-navegador", "--host", "0.0.0.0", "--cache", "/cache"]
