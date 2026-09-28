# Meu Voto 2026

App local para montar sua cédula das eleições de 2026, conhecer os candidatos
e comparar opções com dados públicos (TSE, Câmara dos Deputados, Receita
Federal e, se você ativar, Portal da Transparência).

## Como abrir

Dê dois cliques em **`Abrir Meu Voto.bat`**. Ele instala a dependência (só na
primeira vez), sobe o servidor e abre o navegador em http://127.0.0.1:8765.
Para encerrar, feche a janela preta ou tecle Ctrl+C nela.

Pelo terminal:

```
pip install -r requirements.txt
python app/server.py
```

## Login
No primeiro acesso o app pede para criar um usuário e uma senha (mínimo 8
caracteres). O login fica em `dados/login.json`, que guarda só o hash da senha,
e vale por 30 dias em cada aparelho. O botão **Sair** fica no topo. Se
esquecer a senha, apague `dados/login.json` e crie outra (a cédula continua).

## No tablet (Android, pelo cabo USB)
1. No tablet, ative a **depuração USB** (Opções do desenvolvedor) e ligue o cabo.
2. Dê dois cliques em **`Abrir no tablet.bat`**. Ele sobe o servidor, se ainda
   não estiver rodando, liga a porta 8765 do tablet a este computador
   (`adb reverse`) e abre http://localhost:8765 no navegador do tablet.
3. No Chrome do tablet, use o menu **⋮ > Instalar app** (ou "Adicionar à tela
   inicial") para ter o ícone do Meu Voto.

O app continua rodando no computador: os dados não saem dele, e o tablet só
funciona com o cabo ligado e a janela do servidor aberta.

## No tablet, sem cabo (Tailscale)
Com o Tailscale ligado no computador e no tablet (mesma conta), dê dois
cliques em **`Abrir para o tablet (Tailscale).bat`** e abra
no tablet o endereço que aparece na janela (http://nome-do-computador:8765), de qualquer lugar com internet. O
servidor só atende este computador e os aparelhos da sua rede Tailscale;
outros aparelhos do Wi-Fi ou da internet são recusados. O computador precisa
ficar ligado com a janela aberta.

## Guia e trilha de passos
No primeiro acesso abre um **guia de boas-vindas**: explica o caminho, pede o
estado, oferece a chave do Portal da Transparência (com o passo a passo, e dá
para pular) e pergunta por onde começar. Quem já sabe em quem votar vai direto
para a cédula; quem tem dúvida começa pelo quiz. O botão **Guia**, no topo,
abre o guia de novo.

Depois do guia, o app vira uma **trilha na ordem da urna**: Afinidade (quiz,
opcional), Deputado federal, Deputado estadual, Senado, Governo, Presidência e
Sua cédula. Cada passo começa com um texto curto sobre o que aquele voto faz,
traz o campo para escolher o candidato e o conteúdo de ajuda do cargo, e
termina com o botão para o próximo passo. O ✓ na trilha marca o que já foi
escolhido. O código fica em `app/static/jornada.js`.

**Afinidade nos passos seguintes**: com pelo menos 3 respostas no quiz, as
telas de deputado mostram as listas que mais votaram como você (as bancadas
de uma federação são somadas, porque na eleição ela funciona como um partido
só), cada cartão de lista traz a sua concordância, e as tabelas de senador,
governador e presidente ganham a coluna Afinidade, pelo partido de cada
candidato. Para deputado estadual, a comparação usa como os mesmos partidos
votam na Câmara dos Deputados.

### Sua cédula
Todos os votos na ordem da urna, a chave do Portal, o botão de imprimir a
cola e o acesso aos fornecedores de campanha. Com 2 dígitos em deputado, é
voto de legenda.

### Passos de cada cargo (antes: Ajuda para decidir)
- **Vagas estimadas por federação ou partido** (deputados): os votos de 2022,
  reagrupados nas federações de 2026, distribuídos pelas regras do sistema
  proporcional. Testado com a eleição de 2022: acertou 1.536 de 1.572 vagas
  (97,7%) no país.
- **Lista de candidatos por força estimada** (0 a 100): metade vem da maior
  votação recente da pessoa (deputado em 2022 ou vereador e prefeito em 2024,
  pelo título de eleitor; só o CSV do estado é baixado dos arquivos do TSE, em
  `~/.meuvoto/cache/historico/municipal2024_UF.json`), metade da arrecadação de
  2026. Testado com 2022 em SP e MG: a ordem acertou 211 dos 294 eleitos
  (71,8%), contra 204 (69,4%) sem a votação municipal. A posição comparada às
  vagas estimadas vira uma faixa de chance (Alta, Disputada, Baixa, Muito baixa).
- **Para onde seu voto tende a ir**: quem o seu voto ajuda a eleger na lista.
- Presidente, governador e senador: comparação pela ficha (sem estimativa de
  chance, que dependeria de pesquisas).

### Ficha do candidato
Abre com um **Resumo** em cartões clicáveis e se divide em abas: **Seu voto
elege** (só deputados: quem a lista elegeria junto, retrato do grupo e onde o
voto pesa mais), **Quem é**, **Atuação política**, **Dinheiro** e
**Alertas**. Cada parte tem ao lado um quadro **"Como ler isto"** com um
veredito curto (Dentro do esperado, Fora da média, Vale conferir, Merece
atenção ou Só informativo) e uma explicação do que o número significa.
O código da ficha fica em `app/static/ficha.js`.

Conteúdo: chance de se eleger, orientação política e pautas (para deputados federais:
% de votos com o governo, com o partido, participação e temas dos projetos;
para os demais, a bancada do partido), sinais de atenção, dinheiro da
campanha, patrimônio e candidaturas anteriores.

Para deputados estaduais de SP em exercício, a aba **Atuação política** usa os
dados abertos da ALESP: o que defende (temas das palavras-chave dos projetos),
que tipo de projeto apresenta (que muda regras, benefício local como município
turístico, ou homenagem e data), leis aprovadas desde 2023, presença nas
comissões, indicações ao governador e pedidos de informação, e verba de
gabinete com os principais fornecedores. Quem não tem mandato vê a bancada do
partido na Câmara, com um aviso de que os números não são da pessoa.

A aba **Quem é** traz a **trajetória**: todas as candidaturas desde 2004, tempo
em mandato, cargos, cidades, partidos (PMDB e MDB contam como o mesmo) e
profissões declaradas, com o resultado explicado ("Média" é a eleição pela
sobra de vagas). O patrimônio de cada eleição aparece corrigido pelo IPCA do
Banco Central; o sinal aparece quando o patrimônio cresceu, acima da
inflação, pelo menos 50%, mais de R$ 1 milhão e mais de R$ 250 mil por ano,
no total ou entre duas eleições quaisquer, desde que a pessoa ainda tenha a
maior parte do que ganhou (um salto seguido de queda não conta). Só tira
pontos se o crescimento aconteceu enquanto a pessoa tinha cargo eletivo; para
quem não tinha, aparece como informação. Ser político de carreira aparece só
como contexto, sem tirar pontos.

**Emendas** (deputados federais): o arquivo completo do Portal da Transparência
(`~/.meuvoto/cache/emendas/`, refeito por semana) mostra para quem o dinheiro
foi (prefeituras, estados, associações e ONGs, empresas), os municípios e os
maiores recebedores com CNPJ. O alerta aparece quando uma entidade sem fins
lucrativos (associação, instituto, ONG) recebeu pelo menos R$ 2 milhões de uma pessoa e quase nenhum outro parlamentar
manda emendas para ela, ou quando quem recebeu emenda também trabalhou ou doou
para a campanha. O Transferegov mostra se cada emenda Pix tem relatório de
gestão publicado.

**Pontuação**: integridade (100 menos 20 por ponto que vale conferir e 50 por
alerta sério) mais um ajuste de até 20 pontos pelo desempenho no mandato. Na
Câmara, o desempenho compara presença, projetos aprovados que mudam regras,
relatorias, parte simbólica (peso dobrado), cota e parte das emendas por Pix.
Na ALESP, presença nas comissões, leis que mudam regras, parte simbólica
(peso dobrado) e verba de gabinete. Na aba **Seu voto elege**, o bloco "O
partido por dentro" mostra o histórico da bancada atual na Câmara e na ALESP,
e, nas federações, o quanto os partidos votam juntos.

Para deputados federais em exercício, a seção **Trabalho no mandato** mostra
projetos apresentados e o que aconteceu com eles (viraram lei, passaram na
Câmara, anexados, arquivados), se os aprovados passaram com o texto do autor,
com emendas ou reescritos por substitutivo (lido do histórico de tramitação),
a parte simbólica (homenagens, datas, nomes de obras) e relatorias. Tudo
comparado à mediana da Câmara; mede produção e resultado, não qualidade.

A **Análise dos gastos** usa todas as despesas declaradas ao TSE por todas as
campanhas do país (e as de 2022, como histórico), cruzadas com o cadastro da
Receita Federal (via BrasilAPI):
- em que a campanha gasta, comparada a campanhas de tamanho parecido para o
  mesmo cargo no estado; concentração no maior fornecedor; pagamentos a
  pessoas; quanto foi pago com dinheiro público;
- para cada empresa contratada: quantas campanhas e partidos atende no país,
  se já atuava em 2022, idade da empresa, MEI, capital social, sócios;
- sinais: empresa aberta pouco antes da campanha, CNPJ inativo, MEI acima do
  limite anual, atividade registrada que não combina com o serviço, sócio que
  é o próprio candidato, doador da campanha, outro candidato do estado ou tem
  sobrenome pouco comum igual ao do candidato, fornecedor exclusivo e
  estreante, gasto concentrado;
- fornecedores em comum com outras campanhas do partido (sem contar grandes
  plataformas) e dinheiro trocado entre campanhas.

Na aba "Ajuda para decidir", **Fornecedores de campanha** lista as 200
empresas que mais receberam no estado, com busca e detalhes de cada uma.

Os dados do TSE ficam num banco local (`~/.meuvoto/cache/gastos/`, cerca de
260 MB), refeito uma vez por dia em segundo plano (cerca de 2 minutos).

Os **sinais de atenção** são fatos públicos que valem uma conferida, nunca
acusações: candidatura em julgamento, motivos de indeferimento, crescimento do
patrimônio, financiamento próprio ou público, fornecedor com CNPJ inativo ou
aberto pouco antes da campanha, cota parlamentar e participação comparadas à
Câmara, troca de partido e sanções no CEIS, CNEP e CEAF.

Calibragem (revisada em 27/09/2026 com uma auditoria de 255 candidatos de SP):
- Problema de fornecedor só tira pontos se a campanha pagou pelo menos
  R$ 10 mil ou 10% do que gastou; abaixo disso aparece como informação. A
  exceção é empresa do próprio candidato.
- MEI acima do limite anual é problema do fornecedor: vira alerta sério só se
  esta campanha, sozinha, pagou acima do limite.
- Empresa aberta até 180 dias antes da campanha tem três níveis. Sozinha, é só
  informação (negócios abrem o tempo todo; se atende várias campanhas, é um
  negócio novo do ramo). Vale conferir se atende no máximo três campanhas e
  há mais um indício: aberta menos de 60 dias antes, 10% ou mais dos gastos,
  ou outro ponto sobre ela. Vira alerta sério se foi aberta menos de 60 dias
  antes e recebeu 20% ou mais dos gastos da campanha e pelo menos R$ 10 mil
  (proporção, para tratar igual campanhas grandes e pequenas, com um piso para
  que campanhas minúsculas não levem alerta sério por valores de troco). O aviso mostra os
  sócios e compara o valor com o capital declarado; sócio que também foi pago
  pela campanha como pessoa física gera aviso próprio.
- Gasto concentrado não conta plataformas que atendem mais de 100 campanhas
  (anúncios na internet, meios de pagamento) e só vale acima de R$ 100 mil.
- Gastos perto do limite legal e o padrão de "candidatura de fachada" (gastos
  iguais aos de outra campanha do partido) são só informativos antes da
  apuração; o segundo não se aplica a mandatos coletivos nem quando o partido
  usa a mesma agência para muitas campanhas.
- Fornecedor em cadastro de sanções pesa como atenção, e só se o valor pago for
  relevante; candidato em cadastro de sanções continua alerta sério.

### Quiz de afinidade (passo Afinidade)
15 votações reais do plenário da Câmara (2023 a 2026), escolhidas por critério
objetivo e escritas de forma neutra em `app/quiz.json`. Aparece uma votação
por vez, com barra de progresso (toque num traço para voltar a uma votação).
Antes dos botões, cada votação mostra quatro partes, sempre na mesma ordem: 1. como
chegou a essa votação (quem apresentou, o que mudou no caminho, como o governo
orientou); 2. o que muda na prática; 3. os dois lados, com quem defendia o Sim e
o Não e os argumentos de cada um; 4. quem tende a ganhar e a perder. Quando há
armadilha (votar Sim é derrubar uma regra do governo, por exemplo), aparece
"Para não confundir". Desfecho e fontes ficam recolhidos. Campos do quiz.json:
`historia`, `pratica`, `incerto`, `ladoSim`, `ladoNao` (não use `sim`/`nao`,
que o servidor preenche com o placar), `ganha`, `perde`, `nota`, `depois` e `fontes`.
Depois de cada resposta, o app mostra como as bancadas votaram, com o lado da
sua resposta destacado. Com 3 respostas já dá para ver o resultado, que fica
numa tela própria, com duas seções no mesmo formato: federações e partidos, e
deputados federais que disputam 2026 no estado (só quem já tem mandato tem
voto próprio). Cada seção mostra os 3 mais próximos em cartões e a lista
inteira; as listas têm também a tabela "votação por votação". O código fica em `app/static/quiz.js`.

## Checagem de sanções (sem chave)
A ficha confere o candidato e os principais fornecedores da campanha nos
cadastros nacionais de punidos: CEIS, CNEP e CEAF. Os arquivos abertos da CGU
são baixados do Portal da Transparência uma vez por dia (`app/sancoes.py`,
cerca de 4 MB, em `~/.meuvoto/cache/sancoes/`), sem precisar de chave. No CEAF
o CPF vem mascarado, e o casamento usa os 6 dígitos do meio junto com o nome
completo. A chave antiga do Portal só é usada se esses arquivos ainda não
tiverem sido baixados.

## Empresas dos candidatos (sócios, pela Receita)
A aba "Quem é" da ficha lista as empresas de que o candidato é sócio. A fonte
é a base aberta do CNPJ da Receita Federal (arquivos Socios e Empresas,
cerca de 2 GB, em `arquivos.receitafederal.gov.br`). O app baixa uma parte por
vez, guarda só as linhas que casam com algum candidato de 2026 e apaga o resto
(`app/empresas.py`, índice em `~/.meuvoto/cache/empresas/indice.json`, refeito
a cada 30 dias em segundo plano, o que leva uns 20 minutos). Como o CPF do
sócio vem mascarado, o casamento usa os 6 dígitos do meio e o nome completo.

Cada empresa é cruzada com os gastos de campanha de 2026 (desta e de outras
campanhas), com as emendas parlamentares e com os cadastros de punidos. Isso
gera avisos na análise: "Campanha pagou empresa do próprio candidato",
"Empresa do candidato recebeu de outras campanhas", "…recebeu dinheiro de
emendas" (alerta sério se a emenda é do próprio candidato) e "…tem sanção".
Abaixo de R$ 10 mil, os de dinheiro viram só informação. O outro lado também
aparece: a campanha que pagou a empresa de outro candidato recebe o aviso
"Fornecedor é empresa de outro candidato". Ter empresa, sem
nenhum desses cruzamentos, não gera aviso.

## Punições em listas públicas (TCU, trabalho escravo, Ibama)
`app/punicoes.py` junta, num índice só por CPF/CNPJ completos (em
`~/.meuvoto/cache/punicoes/indice.json`, refeito a cada 3 dias, menos de
1 minuto):
- **TCU** (API aberta de certidoes.apps.tcu.gov.br): contas julgadas
  irregulares para fins eleitorais (a lista enviada à Justiça Eleitoral),
  todas as contas irregulares, inabilitados para cargo público e licitantes
  inidôneos;
- **Ministério do Trabalho**: a "lista suja" do trabalho análogo à escravidão
  (PDF oficial, lido tabela por tabela);
- **Ibama**: termos de embargo ambiental (CSV de ~200 MB, lido aos poucos).

Avisos: lista eleitoral do TCU, inabilitação e lista suja são alerta sério;
contas irregulares antigas, embargo do Ibama em vigor e empresa do candidato
condenada no TCU ou embargada são "vale conferir"; embargo já suspenso é só
informação. Fornecedor de campanha na lista suja ou proibido de licitar gera
aviso (só informação abaixo de R$ 10 mil). O índice de empresas também guarda a
situação na Receita (ativa, baixada, inapta, suspensa), a abertura, a atividade
e a cidade de cada empresa; empresa inapta ou suspensa que recebeu dinheiro de
campanha ou de emendas gera aviso.

## Notícias
A aba "Quem é" mostra as manchetes dos últimos 6 meses que citam o nome de
urna (`app/noticias.py`, RSS de busca do Google Notícias; a GDELT não conecta
desta rede). Guarda só título, veículo, data e link, em cache por 12 horas, uma
busca a cada 2 segundos. A busca junta o nome com o cargo ou o partido e
descarta páginas-perfil de candidatura. Mostra os assuntos mais citados e
marca as manchetes que falam de investigação ou processo. Notícia não é prova:
não entra na nota.

Ainda não integrados: CNJ (improbidade; consulta só por formulário, uma pessoa
por vez), votações e presença no Senado, extratos bancários de campanha.

## Versão pública (para outras pessoas)
`python app/server.py --publico` sobe o app sem login. A cédula e as
respostas do quiz ficam só no navegador de cada pessoa (localStorage) e nunca
são enviadas ao servidor: o servidor recusa gravar cédula, criar login ou
guardar chave. O modo pessoal (sem `--publico`) continua igual, com login e a
cédula em `dados/cedula.json`.

### Colocar a versão pública na internet (grátis, deste computador)
Dê dois cliques em **`Publicar na internet.bat`**. Ele sobe o app em modo
público na porta 8780 (só para este computador) e abre um túnel gratuito da
Cloudflare (`cloudflared`, instalado pelo winget) que cria um endereço
`https://....trycloudflare.com`. O endereço aparece na janela e fica salvo em
`endereco-publico.txt`; ele muda cada vez que o túnel reinicia. O computador
precisa ficar ligado, sem entrar em suspensão, com a janela aberta. O túnel só
expõe a versão pública; o servidor pessoal (porta 8765) continua fora da
internet. A versão pública usa uma cópia própria do cache
(`~/.meuvoto/cache-publico`) e limita cada visitante a 120 consultas por minuto.

## Onde ficam os dados
- `dados/cedula.json`: sua cédula e suas respostas do quiz.
- `dados/config.json`: a chave antiga do Portal, se você tiver configurado (não é mais necessária).
- `C:\Users\<você>\.meuvoto\cache\`: cópias dos dados públicos, fora do
  OneDrive para não sincronizar centenas de MB. Pode apagar à vontade; o app
  baixa de novo. O resumo da Câmara é refeito uma vez por semana, em cerca de
  1 minuto, em segundo plano.

## Como funciona
- `app/tse.py`: API pública do DivulgaCandContas. O site do TSE bloqueia
  clientes HTTP comuns, por isso usamos `curl_cffi`, que se apresenta como o
  Chrome. CPF e título de eleitor dos candidatos nunca vão para a tela.
- `app/historico.py`: base de 2022 (resultados, votos por partido, cadastro)
  e projeção de vagas.
- `app/camara.py`: arquivos em lote da Câmara (votações, orientações,
  projetos, temas, cota parlamentar).
- `app/alesp.py`: dados abertos da ALESP (projetos, autores, palavras-chave,
  leis, comissões, verba de gabinete), resumidos uma vez por semana.
- `app/emendas.py`: emendas individuais do Portal da Transparência e prestação
  de contas das emendas Pix no Transferegov.
- `app/partidos.py`: perfil de partido ou federação pelas bancadas atuais.
- `app/analise.py`: junta tudo por candidato e calcula os sinais.
- `app/server.py`: servidor local (só em 127.0.0.1).
- `app/static/`: a interface (HTML, CSS e JavaScript puros).

Métodos inspirados em projetos abertos: pasimplicio/eleicoes (regras de
distribuição de vagas), augusto-dmh/mandato-aberto (alinhamento e presença),
guipfranco/contas2026 (sinais sobre fornecedores) e didifive/legisvisao
(quiz com ajuste para poucas respostas). Nenhum código deles foi copiado.

## Limites conhecidos
- Estimativa de chance não usa pesquisas; candidatos vindos de eleição
  municipal aparecem só pela arrecadação, que é parcial durante a campanha.
- Orientação política cobre a Câmara e a ALESP; o Senado e as outras
  assembleias ainda não.
- As emendas dos deputados estaduais de SP não entram: o site do governo que as
  publica bloqueia acesso automatizado, e o app não contorna esse bloqueio.
- As emendas que vão para prefeituras deixam de aparecer nos dados federais
  depois que chegam lá; quem mostra o gasto é a prefeitura.

## Próximas fases
1. **Apuração (a partir de 4/out)**: se seus candidatos foram eleitos e quem o
   seu voto de fato ajudou a eleger.
2. **Mandato (fev/2027 em diante)**: votações, presença, gastos, emendas e
   notícias dos eleitos.
