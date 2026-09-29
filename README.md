# Voto Informado 2026

Site para montar sua cédula das eleições de 2026, conhecer os candidatos e
comparar opções com dados públicos: TSE, Câmara dos Deputados, ALESP, Receita
Federal, Portal da Transparência, TCU, Ministério do Trabalho e Ibama.

Na versão pública, a cédula e as respostas do quiz ficam só no navegador de
cada pessoa. O servidor não tem login e não recebe nem guarda votos.

## Como rodar

Precisa do Python 3.11 ou mais novo.

```
pip install -r requirements.txt
python app/server.py --publico --sem-navegador
```

O site abre em http://127.0.0.1:8765. Os dados públicos baixados ficam em
`~/.meuvoto/cache` (centenas de MB na primeira vez).

Para colocar na internet a partir do próprio computador, sem servidor pago,
`python app/publicar.py` sobe o site e abre um túnel gratuito da Cloudflare
(precisa do `cloudflared` instalado). O endereço `https://....trycloudflare.com`
aparece na tela e muda cada vez que o túnel reinicia.

## Sócios de empresas (Receita Federal)

Montar o cruzamento de sócios baixa uns 10 GB da Receita e leva perto de uma
hora, por isso o servidor público não faz isso: ele usa o índice pronto que vai
junto com o site, em `app/dados_publicos/receita_socios.json.gz` (1,4 MB, sem
CPF). Uma vez por mês, quando a Receita publica dados novos, atualize no seu
computador e faça o commit do arquivo:

```
python app/empresas.py --atualizar
```

Se o app pessoal já tiver montado o índice do mês, `--empacotar` só empacota.

## O que o site mostra

- **Cédula**: os votos na ordem da urna, para imprimir ou levar anotado.
- **Ficha do candidato**: dados do TSE, gastos e doações de campanha e, para
  quem já tem mandato, a atuação na Câmara ou na ALESP.
- **Empresas e punições**: empresas em que o candidato é sócio e registros em
  listas públicas de sanções e punições.
- **Quiz de afinidade** e **notícias** sobre os candidatos.

CPF e título de eleitor dos candidatos nunca são mostrados.
