# Voto Informado 2026

Site para montar sua cédula das eleições de 2026, conhecer os candidatos e
comparar opções com dados públicos: TSE, Câmara dos Deputados, ALESP, Receita
Federal, Portal da Transparência, TCU, Ministério do Trabalho e Ibama.

A cédula e as respostas do quiz ficam só no navegador de cada pessoa. O site
não tem login e não recebe nem guarda votos.

## Como funciona

O site é estático e fica no GitHub Pages. O workflow
`.github/workflows/main.yml` roda `app/gerar_estatico.py`, que sobe o servidor
(`app/server.py`) dentro do próprio GitHub Actions, espera as bases de dados
públicos ficarem prontas e grava cada resposta que as telas usam (fichas,
análises, listas de deputados, questionário, fornecedores e empresas) como um
arquivo JSON em `api/`. A interface (`app/static`) lê esses arquivos em vez de
chamar um servidor. As fotos vêm direto do TSE, e as notícias abrem uma busca
no Google Notícias.

O site é publicado a cada commit na `main` e refeito a cada 6 horas com os
dados mais novos. Se o commit só muda a interface (`app/static`), a publicação
reaproveita os dados da última execução e leva um ou dois minutos; se muda a
análise (`app/*.py`), refaz tudo. Os dados baixados e as respostas ficam no
cache do GitHub Actions entre uma execução e outra; se uma fonte estiver fora
do ar, o site segue com a resposta anterior.

Para publicar pela primeira vez: em Settings > Pages do repositório, escolha
"GitHub Actions" como fonte. A primeira execução baixa tudo e leva algumas
horas.

## Como rodar no seu computador

Precisa do Python 3.11 ou mais novo.

```
pip install -r requirements.txt
python app/gerar_estatico.py --ufs RR
python -m http.server -d build/site
```

O site abre em http://localhost:8000. `--ufs` limita a geração a alguns
estados (separados por vírgula), porque o país inteiro leva horas. Os dados
públicos baixados ficam em `~/.meuvoto/cache` (centenas de MB na primeira vez).
Para ver uma mudança só na interface, sem gerar de novo:
`python app/gerar_estatico.py --so-interface`.

## Sócios de empresas (Receita Federal)

Montar o cruzamento de sócios baixa uns 10 GB da Receita e leva perto de uma
hora, por isso a geração do site não faz isso: ela usa o índice pronto que vai
junto com o código, em `app/dados_publicos/receita_socios.json.gz` (1,4 MB, sem
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
