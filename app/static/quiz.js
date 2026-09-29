"use strict";

// Questionário de afinidade: uma votação por vez, com barra de progresso, e o resultado numa tela
// própria. Como as bancadas votaram só aparece depois da resposta, para não influenciar.

let quizDados = null;
const quizVisao = { modo: null, i: 0, uf: null }; // modo: "perguntas" ou "resultado"
let listasQuiz = null;

// Votações do questionário e como cada partido votou. Devolve null enquanto a Câmara ainda está sendo preparada.
async function carregarQuizDados() {
  if (quizDados && quizDados.uf === estado.uf) return quizDados;
  const d = await api(`/api/quiz?uf=${estado.uf}`);
  if (!d.pronto) return null;
  quizDados = { uf: estado.uf, ...d };
  // Respostas de votações que saíram do questionário não contam mais: são descartadas.
  const validas = new Set(d.perguntas.map((q) => q.id));
  const antigas = Object.keys(estado.quiz || {}).filter((id) => !validas.has(id));
  if (antigas.length) {
    antigas.forEach((id) => delete estado.quiz[id]);
    salvar();
  }
  return quizDados;
}

async function montarQuiz() {
  const corpo = $("#quiz-corpo");
  if (!estado.quiz) estado.quiz = {};
  ligarQuiz();
  if (!quizDados || quizDados.uf !== estado.uf) {
    if (!corpo.querySelector(".espera")) corpo.innerHTML = `<p class="carregando">Carregando as votações…</p>`;
    let d;
    try {
      d = await carregarQuizDados();
    } catch (e) {
      corpo.innerHTML = `<p class="carregando aviso">${esc(e.message)}</p>`;
      return;
    }
    if (!d) {
      corpo.innerHTML = htmlEspera("quiz", "Preparando as votações da Câmara",
        [["camara", "Baixando as votações do plenário desde 2023 e como cada deputado votou"]], "camara",
        "Isso só acontece na primeira vez depois que o site é atualizado e leva cerca de um minuto. A tela atualiza sozinha.");
      setTimeout(() => { if (!$("#aba-quiz").hidden) montarQuiz(); }, 4000);
      return;
    }
    fimEspera("quiz");
  }
  // Na primeira visita: quem já respondeu vê o resultado; quem não, continua de onde parou.
  if (!quizVisao.modo || quizVisao.uf !== estado.uf) {
    quizVisao.uf = estado.uf;
    quizVisao.modo = respostasQuiz() >= 3 ? "resultado" : "perguntas";
    quizVisao.i = primeiraSemResposta();
  }
  desenharQuiz();
}

function primeiraSemResposta() {
  const i = quizDados.perguntas.findIndex((q) => !(q.id in estado.quiz));
  return i < 0 ? 0 : i;
}

function desenharQuiz(rolar = false) {
  if (quizVisao.modo === "resultado" && respostasQuiz() >= 3) desenharResultado();
  else { quizVisao.modo = "perguntas"; desenharPergunta(); }
  if (rolar) $("#quiz-palco")?.scrollIntoView({ block: "start", behavior: "smooth" });
}

// ---------- uma votação por vez ----------

function desenharPergunta() {
  const perguntas = quizDados.perguntas;
  const i = Math.min(quizVisao.i, perguntas.length - 1);
  const q = perguntas[i];
  const r = estado.quiz[q.id];
  const respondeu = q.id in estado.quiz;
  const n = respostasQuiz();
  const ultima = i === perguntas.length - 1;
  const botao = (v, texto, classe) =>
    `<button type="button" class="resp ${classe}" data-quiz-resp="${v}" aria-pressed="${r === v}">${texto}</button>`;
  const segmentos = perguntas.map((p, j) => {
    const v = estado.quiz[p.id];
    const estadoSeg = v ? "resp" : p.id in estado.quiz ? "pulou" : "";
    const rotulo = v === 1 ? "concordou" : v === -1 ? "discordou" : p.id in estado.quiz ? "pulou" : "sem resposta";
    return `<button type="button" class="seg ${estadoSeg}${j === i ? " atual" : ""}" data-quiz-ir="${j}"
      aria-label="Votação ${j + 1}: ${rotulo}" title="${j + 1}. ${esc(p.tema)} (${rotulo})"></button>`;
  }).join("");
  const falta = Math.max(0, 3 - n);
  const topoDireita = n >= 3
    ? `<button type="button" class="link-btn quiz-parcial" data-quiz="resultado">Ver resultado com ${n} respostas →</button>`
    : `<span class="quiz-falta">${falta === 3 ? "Responda 3 para ver o resultado" : `Faltam ${falta} para ver o resultado`}</span>`;
  let seguir;
  if (!ultima) {
    seguir = `<button type="button" class="btn${respondeu ? " primario" : ""}" data-quiz="proxima">Próxima votação →</button>`;
  } else {
    seguir = `<button type="button" class="btn primario" data-quiz="resultado"${n < 3 ? " disabled" : ""}>Ver meu resultado →</button>`;
  }

  $("#quiz-corpo").innerHTML = `<div class="quiz-palco" id="quiz-palco">
    <div class="quiz-progresso">
      <div class="quiz-progresso-topo">
        <span>Votação <strong>${i + 1}</strong> de ${perguntas.length}</span>
        ${topoDireita}
      </div>
      <div class="quiz-segmentos">${segmentos}</div>
    </div>
    <article class="quiz-cartao">
      <p class="quiz-tema">${esc(q.tema)}</p>
      <h3 class="quiz-afirmacao">${esc(q.afirmacao)}</h3>
      <p class="quiz-contexto">${esc(q.contexto)} Placar na Câmara: ${q.sim} a ${q.nao}.</p>
      ${htmlEfeitos(q)}
      ${q.nota ? `<p class="quiz-nota"><strong>Para não confundir:</strong> ${esc(q.nota)}</p>` : ""}
      ${htmlMaisContexto(q)}
      <div class="quiz-respostas" role="group" aria-label="Sua resposta">
        ${botao(1, "Concordo", "concordo")}${botao(-1, "Discordo", "discordo")}${botao(0, "Não sei, prefiro pular", "pular")}
      </div>
      ${respondeu ? htmlComoVotaram(q) : ""}
      ${respondeu && [3, 8].includes(n) ? htmlJaDaParaVer(n, perguntas.length, ultima) : ""}
    </article>
    <div class="quiz-nav">
      ${i > 0 ? `<button type="button" class="btn" data-quiz="anterior">← Anterior</button>` : "<span></span>"}
      ${seguir}
    </div>
    ${ultima && n < 3 ? `<p class="nota-pequena quiz-nota-fim">Responda pelo menos 3 votações para ver o resultado. Toque nos traços acima para voltar a uma delas.</p>` : ""}
    <p class="quiz-pular"><button type="button" class="link-btn" data-ir-passo="dep_federal">Pular o questionário e ir para Deputado(a) federal</button></p>
    <details class="metodo quiz-metodo"><summary>Como as votações foram escolhidas</summary><p>${esc(quizDados.criterio)}${quizDados.atualizadoEm ? ` Os textos de contexto foram revisados em ${esc(quizDados.atualizadoEm)}.` : ""}</p></details>
  </div>`;
}

// Aparece logo depois da 3ª resposta (e de novo na 8ª): sem barreira, quem quiser já pode ver o resultado.
function htmlJaDaParaVer(n, total, ultima) {
  const texto = n === 3
    ? "Com 3 respostas já dá para ver com quais partidos e candidatos você se parece mais."
    : `Você já respondeu ${n} das ${total}. O resultado fica mais preciso a cada resposta, mas já dá para ver.`;
  return `<div class="quiz-ja" role="status">
    <p><strong>Pronto!</strong> ${texto}</p>
    <div class="quiz-ja-acoes">
      <button type="button" class="btn primario" data-quiz="resultado">Ver meu resultado</button>
      ${ultima ? "" : `<button type="button" class="btn" data-quiz="proxima">Continuar respondendo</button>`}
    </div>
  </div>`;
}

// "Grupo: efeito" vira o grupo em negrito seguido do efeito.
function itemEfeito(texto) {
  const i = texto.indexOf(": ");
  if (i < 0) return `<li>${esc(texto)}</li>`;
  return `<li><strong>${esc(texto.slice(0, i))}</strong> ${esc(texto.slice(i + 2))}</li>`;
}

// Logo abaixo da pergunta, o que mais ajuda a decidir: quem tende a ganhar e quem tende a perder.
function htmlEfeitos(q) {
  if (!q.ganha?.length && !q.perde?.length) return "";
  return `<section class="quiz-sec quiz-sec-efeitos"><h4>Quem tende a ganhar e a perder</h4>
    <div class="quiz-efeitos">
      <div class="quiz-efeito ganha"><p class="quiz-lado-tit">Quem tende a ganhar</p><ul>${(q.ganha || []).map(itemEfeito).join("")}</ul></div>
      <div class="quiz-efeito perde"><p class="quiz-lado-tit">Quem tende a perder</p><ul>${(q.perde || []).map(itemEfeito).join("")}</ul></div>
    </div></section>`;
}

// O resto fica recolhido em "Preciso de mais contexto", para a tela ter menos texto e a pessoa poder responder logo.
// Continua aberto ao responder (a tela é redesenhada) enquanto for a mesma pergunta.
function htmlMaisContexto(q) {
  const secao = (titulo, corpo) => corpo ? `<section class="quiz-sec"><h4>${titulo}</h4>${corpo}</section>` : "";
  // Partidos e governo ficam de fora até a resposta, para não influenciar: aqui só os argumentos e, quando há,
  // quem apoiava de fora do Congresso (sindicatos, organizações). Como cada bancada votou aparece depois.
  const ladoHtml = (classe, titulo, l) => l ? `<div class="quiz-lado ${classe}">
      <p class="quiz-lado-tit">${titulo}</p>
      ${l.quem ? `<p class="quiz-lado-quem">Fora do Congresso: ${esc(l.quem)}</p>` : ""}
      <ul>${l.argumentos.map((a) => `<li>${esc(a)}</li>`).join("")}</ul>
    </div>` : "";
  const lados = q.ladoSim || q.ladoNao
    ? `<div class="quiz-lados">${ladoHtml("sim", "Quem concordava <small>(votou Sim)</small>", q.ladoSim)}${ladoHtml("nao", "Quem discordava <small>(votou Não)</small>", q.ladoNao)}</div>` : "";
  const pratica = q.pratica
    ? `<p>${esc(q.pratica)}</p>${q.incerto ? `<p class="quiz-incerto"><strong>Ainda em aberto:</strong> ${esc(q.incerto)}</p>` : ""}` : "";
  const p = q.proposicao;
  const link = (url, nome) => `<a href="${esc(url)}" target="_blank" rel="noopener">${esc(nome)}</a>`;
  const fontes = [p ? link(p.link, `Ficha do ${p.nome} na Câmara`) : "", ...(q.fontes || []).map((f) => link(f.url, f.nome))]
    .filter(Boolean).join("");
  const situacao = p?.situacao
    ? `<p class="situacao">No sistema da Câmara, o último registro é "${esc(p.situacao)}"${p.dataSituacao ? `, de ${esc(dataBr(p.dataSituacao))}` : ""}. Esse registro às vezes não acompanha o que aconteceu depois no Senado ou na sanção, por isso vale o desfecho descrito acima.</p>` : "";
  const depois = `${q.depois ? `<p>${esc(q.depois)}</p>` : ""}${situacao}
    ${p?.ementa ? `<p class="ementa">Ementa oficial: “${esc(p.ementa)}”</p>` : ""}
    ${fontes ? `<div class="links">${fontes}</div>` : ""}`;
  return `<details class="quiz-mais" data-contexto="${esc(q.id)}"${quizVisao.contexto === q.id ? " open" : ""}>
    <summary>Preciso de mais contexto</summary>
    <div class="quiz-guia">
      ${secao("Como chegou a essa votação", q.historia ? `<p>${esc(q.historia)}</p>` : "")}
      ${secao("O que muda na prática", pratica)}
      ${secao("Os argumentos de cada lado", lados)}
      ${secao("O que aconteceu depois e fontes", depois)}
    </div>
  </details>`;
}

// Mostrado só depois da resposta. Concordar com a afirmação equivale a votar Sim.
function htmlComoVotaram(q) {
  const sim = [];
  const nao = [];
  for (const [s, pos] of Object.entries(q.partidos)) (pos.voto === "Sim" ? sim : nao).push(sigla(s));
  const r = estado.quiz[q.id];
  const lado = r === 1 ? "Sim" : r === -1 ? "Não" : null;
  const orientacao = { Sim: "Sim", "Não": "Não", "Obstrução": "Não (obstrução)" }[q.governo];
  const gov = orientacao ? `O governo federal pediu voto <strong>${orientacao}</strong>.` : "O governo federal não indicou como votar.";
  const coluna = (voto, lista) => `<div class="cv-col${lado === voto ? " seu-lado" : ""}">
    <div class="cv-tit">Votaram ${voto}${lado === voto ? `<span class="cv-voce">como você</span>` : ""}</div>
    <div class="chips">${lista.sort().map((s) => `<span class="chip">${esc(s)}</span>`).join("") || `<span class="cv-vazio">Nenhum partido</span>`}</div>
  </div>`;
  return `<div class="como-votaram" aria-live="polite">
    <p class="cv-cab"><strong>Como votaram as bancadas</strong>, pela maioria de cada partido. ${gov}</p>
    <div class="cv-colunas">${coluna("Sim", sim)}${coluna("Não", nao)}</div>
  </div>`;
}

// ---------- tela de resultado ----------

function linhaAfinidade(nome, sub, x, atributos = "") {
  const p = pctAfinidade(x);
  return `<div class="linha" title="${p}% de afinidade: votou como você em ${x.a} de ${x.n} votações do questionário">
    <span class="nome">${nome}${sub ? `<small>${sub}</small>` : ""}</span>
    <span class="linha-barra"><span class="trilho"><span class="cheio" style="width:${p}%"></span></span><b ${atributos}>${p}%</b></span>
  </div>`;
}

// O número grande dos cartões do pódio, sempre dizendo o que é.
function htmlPctCartao(x) {
  return `<div class="res-pc" title="Votou como você em ${x.a} de ${x.n} ${x.n === 1 ? "votação" : "votações"} do questionário"><strong>${pctAfinidade(x)}%</strong><span>de afinidade</span></div>`;
}

// Ordena com um pequeno ajuste para quem tem poucas votações em comum (regra de Laplace).
function notaQuiz(x) { return (x.a + 1) / (x.n + 2); }

function desenharResultado() {
  const perguntas = quizDados.perguntas;
  const respondidas = perguntas.filter((q) => estado.quiz[q.id]);
  const n = respondidas.length;
  const vistas = perguntas.filter((q) => q.id in estado.quiz).length;
  const concorda = (q, voto) => (estado.quiz[q.id] === 1) === (voto === "Sim");

  const partidos = {};
  for (const q of respondidas) {
    for (const [s, pos] of Object.entries(q.partidos)) {
      const x = partidos[s] || (partidos[s] = { a: 0, n: 0 });
      x.n++;
      if (concorda(q, pos.voto)) x.a++;
    }
  }
  const gov = { a: 0, n: 0 };
  for (const q of respondidas) {
    if (!q.governo) continue;
    gov.n++;
    if (concorda(q, q.governo === "Sim" ? "Sim" : "Não")) gov.a++;
  }
  const minimo = Math.min(3, n);
  const rankingPartidos = Object.entries(partidos).filter(([, x]) => x.n >= minimo)
    .sort((a, b) => notaQuiz(b[1]) - notaQuiz(a[1]));
  const nomeUf = esc(UFS[estado.uf] || estado.uf);

  const faltam = vistas < perguntas.length;
  $("#quiz-corpo").innerHTML = `<div class="quiz-res" id="quiz-palco">
    <header class="res-cab">
      <div class="res-cab-texto">
        <p class="passo-kicker">Seu resultado</p>
        <h3>Quem votou mais parecido com você</h3>
        <p>Com base nas suas ${n} respostas${faltam ? `, de ${perguntas.length} votações` : ""}. A porcentagem é a <strong>afinidade</strong>: em quantas dessas votações a maioria da bancada votou do mesmo jeito que você respondeu. 100% quer dizer que votou igual a você em todas; 50%, em metade.</p>
      </div>
      <div class="res-cab-lado">
        ${gov.n ? `<div class="res-gov" title="Votações em que você concordou com a orientação que o governo deu à base na Câmara">
          <span class="res-gov-rot">Com o governo federal</span>
          <strong>${gov.a} de ${gov.n}</strong>
        </div>` : ""}
        <button type="button" class="btn pequeno" data-quiz="revisar">${faltam ? `Continuar respondendo (${vistas} de ${perguntas.length})` : "Revisar respostas"}</button>
      </div>
    </header>

    <section class="res-secao">
      <div class="res-secao-cab">
        <h4>Federações e partidos, para deputado</h4>
        <p class="explica">O voto para deputado vai primeiro para a lista, que é a federação ou o partido. As listas são as mesmas para deputado federal e estadual em ${nomeUf}. Nas federações, os partidos votam como um bloco, então as bancadas são somadas.</p>
      </div>
      <p class="nota-pequena">As vagas de cada lista são uma estimativa com os votos de 2022, não uma previsão.</p>
      <div class="res-podio" id="res-podio"><p class="carregando">Comparando com as listas de ${nomeUf}…</p></div>
    </section>

    <section class="res-secao">
      <div class="res-secao-cab">
        <h4>Senado, governo e presidência</h4>
        <p class="explica">Os candidatos a esses cargos, na maioria, não têm voto registrado na Câmara. Por isso a afinidade de cada um é a do partido dele. Toque no nome para abrir a ficha.</p>
      </div>
      <div class="res-cargos" id="res-cargos"><p class="carregando">Comparando com os candidatos…</p></div>
    </section>

    ${rankingPartidos.length ? `<section class="res-secao">
      <div class="res-secao-cab">
        <h4>Partido por partido</h4>
        <p class="explica">Cada partido sozinho, pela maioria da própria bancada na Câmara. Partidos sem deputados federais não aparecem porque não têm votos para comparar.</p>
      </div>
      <div class="partidos-grade">${rankingPartidos.slice(0, 8).map(cartaoPartido).join("")}</div>
      ${rankingPartidos.length > 8 ? `<details class="res-mais"><summary>Ver os outros ${rankingPartidos.length - 8} partidos</summary>
        <div class="partidos-grade">${rankingPartidos.slice(8).map(cartaoPartido).join("")}</div></details>` : ""}
    </section>` : ""}

    <div class="callout res-seguir">
      <p>Essa afinidade acompanha você nos próximos passos: aparece em cada lista de deputados e ao lado de cada candidato a senador, governador e presidente.</p>
      <button type="button" class="btn primario" data-ir-passo="dep_federal">Seguir para Deputado(a) federal →</button>
    </div>
    <div class="res-rodape">
      <p class="nota-pequena">A comparação usa só estas ${perguntas.length} votações da Câmara. <button type="button" class="link-btn" data-abrir-sobre="metodologia">Como a afinidade é calculada</button>. <button type="button" class="link-btn quiz-refazer" data-quiz="refazer">Apagar as respostas e refazer o questionário</button></p>
    </div>
  </div>`;
  preencherListasResultado();
  preencherCargosResultado();
}

// Cartão pequeno de um partido: sigla, porcentagem e uma barra fina.
function cartaoPartido([s, x]) {
  const p = pctAfinidade(x);
  return `<div class="partido-card" title="${p}% de afinidade: votou como você em ${x.a} de ${x.n} votações do questionário">
    <span class="partido-sigla">${esc(sigla(s))}</span>
    <strong>${p}%</strong>
    <span class="partido-trilho"><span style="width:${p}%"></span></span>
  </div>`;
}

// Senado, Governo e Presidência: um cargo por vez, em abas, com os candidatos ordenados pela afinidade do partido.
const CARGOS_RESULTADO = [[5, "Senado"], [3, "Governo do estado"], [1, "Presidência"]];
const resCargos = { listas: null, uf: null, cargo: 5, todos: false };
const MOSTRAR_CANDIDATOS = 5;

async function preencherCargosResultado() {
  if (!resCargos.listas || resCargos.uf !== estado.uf) {
    let listas;
    try {
      listas = await Promise.all(CARGOS_RESULTADO.map(([c]) => api(`/api/candidatos?uf=${ufConsulta(c)}&cargo=${c}`)));
    } catch {
      $("#res-cargos")?.closest(".res-secao").remove();
      return;
    }
    resCargos.listas = Object.fromEntries(CARGOS_RESULTADO.map(([c], i) => [c, listas[i].candidatos]));
    resCargos.uf = estado.uf;
  }
  desenharCargosResultado();
}

function desenharCargosResultado() {
  const alvo = $("#res-cargos");
  if (!alvo || !resCargos.listas) return;
  const cargo = resCargos.cargo;
  const uf = ufConsulta(cargo);
  const vistos = new Set();
  const itens = resCargos.listas[cargo]
    .filter((c) => candidaturaValida(c) && !vistos.has(`${c.nomeUrna}|${c.numero}`) && vistos.add(`${c.nomeUrna}|${c.numero}`))
    .map((c) => ({ c, x: afinidadePartidos([c.partido]) }))
    .sort((a, b) => notaAfinidade(b.x) - notaAfinidade(a.x) || a.c.nomeUrna.localeCompare(b.c.nomeUrna, "pt-BR"));
  const abas = CARGOS_RESULTADO.map(([c, rot]) =>
    `<button type="button" role="tab" data-res-cargo="${c}" aria-selected="${c === cargo}">${rot}</button>`).join("");
  const nome = (c) => `<button type="button" class="link-btn" data-dep-ficha="${c.id}" data-cargo="${cargo}">${esc(nomeProprio(c.nomeUrna))}</button>`;
  // Os 3 primeiros em cartões, no mesmo formato do pódio das listas; o anel da foto é a nota geral.
  const cartao = ({ c, x }, k) => `<article class="res-top${k === 0 ? " primeiro" : ""}">
      <span class="res-pos">${k + 1}º lugar</span>
      <div class="res-pessoa">${fotoHtml(uf, c.id, c.nomeUrna, "foto res-foto")}<h4>${nome(c)}</h4></div>
      <div class="chips"><span class="chip">${esc(c.partido)}</span><span class="chip">Nº ${esc(c.numero)}</span></div>
      ${x ? `${htmlPctCartao(x)}<div class="trilho"><span class="cheio" style="width:${pctAfinidade(x)}%"></span></div>`
        : `<p class="res-vagas">O partido não tem bancada na Câmara, então não há afinidade para calcular.</p>`}
      <p class="res-vagas" data-nota-quiz="${c.id}">Nota geral: calculando…</p>
    </article>`;
  const linha = ({ c, x }, k) => `<li class="res-cand">
      <span class="res-cand-pos">${k + 4}º</span>
      ${fotoHtml(uf, c.id, c.nomeUrna, "foto res-cand-foto")}
      <span class="res-cand-nome">${nome(c)}<small>${esc(c.partido)}, número ${esc(c.numero)}</small></span>
      ${x ? `<span class="linha-barra" title="${pctAfinidade(x)}% de afinidade: o partido votou como você em ${x.a} de ${x.n} votações do questionário"><span class="trilho"><span class="cheio" style="width:${pctAfinidade(x)}%"></span></span><b>${pctAfinidade(x)}%</b></span>`
        : `<span class="res-cand-sem">Partido sem bancada na Câmara</span>`}
    </li>`;
  const resto = itens.slice(3);
  alvo.innerHTML = `<div class="res-abas" role="tablist" aria-label="Cargo">${abas}</div>
    <div class="res-podio">${itens.slice(0, 3).map(cartao).join("")}</div>
    ${resto.length ? `<button type="button" class="link-btn res-ver-todos" data-res-cargo-todos>${resCargos.todos ? "Mostrar só os 3 primeiros" : `Ver os outros ${resto.length} candidatos`}</button>` : ""}
    ${resCargos.todos && resto.length ? `<div class="cartao res-cargo-painel"><ol class="res-cands">${resto.map(linha).join("")}</ol></div>` : ""}`;
  pintarNotasQuiz(cargo, uf, resCargos.todos ? itens : itens.slice(0, 3));
}

// Anel da foto e nota geral de cada candidato mostrado, com a mesma análise da ficha (guardada em resumoMajoritario,
// que a tela do cargo também usa), de dois em dois para não pesar no servidor.
async function pintarNotasQuiz(cargo, uf, itens) {
  const fila = [...itens];
  const trabalhar = async () => {
    for (let it = fila.shift(); it; it = fila.shift()) {
      const { c } = it;
      const chave = `a-${uf}-${cargo}-${c.id}`;
      let a = resumoMajoritario.get(chave);
      if (!a) {
        try { a = await api(`/api/analise?uf=${uf}&cargo=${cargo}&id=${c.id}`); resumoMajoritario.set(chave, a); } catch { a = null; }
      }
      if (resCargos.cargo !== cargo) return;
      const nota = a?.pontuacao?.nota;
      const nivel = nivelNota(nota);
      document.querySelectorAll(`#res-cargos [data-dep-ficha="${c.id}"]`).forEach((b) => {
        const foto = b.closest(".res-top, .res-cand")?.querySelector(".foto");
        if (foto && nivel) foto.classList.add(`anel-${nivel}`);
      });
      const txt = $(`#res-cargos [data-nota-quiz="${c.id}"]`);
      if (txt) txt.innerHTML = nota == null ? "" : `Nota geral: <strong class="nota-${nivel}">${nota}</strong> de 100`;
    }
  };
  await Promise.all([trabalhar(), trabalhar()]);
}

// Pódio com as 3 listas (federação ou partido) de deputado federal do estado que mais votaram como você.
async function preencherListasResultado() {
  if (!listasQuiz || listasQuiz.uf !== estado.uf) {
    let p;
    try {
      p = await api(`/api/listas?uf=${estado.uf}&cargo=6`);
    } catch {
      const podio = $("#res-podio");
      if (podio) podio.innerHTML = `<p class="carregando aviso">Não foi possível montar as listas agora. Tente de novo em alguns minutos.</p>`;
      return;
    }
    if (p.preparando) {
      // Servidor novo: a base de 2022 do estado ainda está sendo montada.
      const podio = $("#res-podio");
      if (podio) podio.innerHTML = htmlEsperaListas(p);
      setTimeout(() => { if ($("#res-podio")) preencherListasResultado(); }, 4000);
      return;
    }
    fimEspera(`listas-${estado.uf}`);
    listasQuiz = { uf: estado.uf, p };
  }
  const podio = $("#res-podio");
  if (!podio) return;
  const todos = rankingListas(listasQuiz.p.grupos);
  const com = todos.filter((i) => i.x);
  const sem = todos.filter((i) => !i.x).map((i) => esc(agremiacao(i.g.id)));
  const nomeUf = esc(UFS[estado.uf] || estado.uf);

  const top = com.slice(0, 3);
  // Todos os cartões têm as mesmas partes, na mesma ordem, para ficarem alinhados lado a lado.
  podio.innerHTML = top.map(({ g, x }, k) => {
    const pcx = pctAfinidade(x);
    const partidos = g.partidos.length > 1
      ? g.partidos.map((s) => `<span class="chip">${esc(sigla(s))}</span>`).join("")
      : `<span class="chip">Sem federação</span>`;
    const vagas = g.vagas
      ? `${g.vagas} ${g.vagas === 1 ? "vaga estimada" : "vagas estimadas"} em ${nomeUf}`
      : `Nenhuma vaga estimada em ${nomeUf}`;
    return `<article class="res-top${k === 0 ? " primeiro" : ""}">
      <span class="res-pos">${k + 1}º lugar</span>
      <h4>${esc(agremiacao(g.id))}</h4>
      <div class="chips">${partidos}</div>
      ${htmlPctCartao(x)}
      <div class="trilho"><span class="cheio" style="width:${pcx}%"></span></div>
      <p class="res-vagas">${vagas}</p>
    </article>`;
  }).join("") + `<details class="res-todos cartao"><summary>Ver todas as listas (${com.length})</summary>
      <div class="afinidade">${htmlLinhasRanking(com, false)}</div>
      ${sem.length ? `<p class="nota-pequena">Sem bancada na Câmara para comparar: ${listaNatural(sem)}.</p>` : ""}
    </details>` + (top.length ? `<details class="res-todos cartao"><summary>Comparar votação por votação</summary>${htmlVotacaoPorVotacao(top.map((i) => i.g))}</details>` : "");
}

// Tabela: cada votação respondida numa linha, a sua resposta e como cada lista do pódio votou.
function htmlVotacaoPorVotacao(grupos) {
  const celula = (q, g) => {
    const voto = votoDoBloco(q, g.partidos);
    if (!voto) return `<td class="neutro" title="Sem maioria clara">–</td>`;
    const igual = (estado.quiz[q.id] === 1) === (voto === "Sim");
    return `<td class="${igual ? "igual" : "diferente"}"><span class="res-marca">${igual ? "✓" : "✕"}</span> ${voto}</td>`;
  };
  const linhas = quizDados.perguntas.filter((q) => estado.quiz[q.id]).map((q) => `<tr>
    <td class="res-afirm"><small>${esc(q.tema)}</small>${esc(q.afirmacao)}</td>
    <td class="res-voce">${estado.quiz[q.id] === 1 ? "Sim" : "Não"}</td>
    ${grupos.map((g) => celula(q, g)).join("")}
  </tr>`).join("");
  return `<p class="explica">Tudo aparece como voto na Câmara: responder Concordo equivale a votar Sim, e Discordo, a votar Não. O ✓ marca quando a maioria da lista votou igual a você.</p>
    <div class="tabela-rolagem"><table class="lista res-tabela">
      <thead><tr><th>Votação</th><th>Você</th>${grupos.map((g) => `<th>${esc(agremiacao(g.id))}</th>`).join("")}</tr></thead>
      <tbody>${linhas}</tbody></table></div>`;
}

// ---------- ações ----------

let quizLigado = false;

function ligarQuiz() {
  if (quizLigado) return;
  quizLigado = true;
  // Lembra se "Preciso de mais contexto" está aberto, para não fechar ao responder.
  $("#quiz-corpo").addEventListener("toggle", (e) => {
    const d = e.target.closest?.("[data-contexto]");
    if (d) quizVisao.contexto = d.open ? d.dataset.contexto : null;
  }, true);
  $("#quiz-corpo").addEventListener("click", (e) => {
    const resp = e.target.closest("[data-quiz-resp]");
    if (resp) {
      const q = quizDados.perguntas[quizVisao.i];
      const v = +resp.dataset.quizResp;
      if (estado.quiz[q.id] === v) delete estado.quiz[q.id];
      else estado.quiz[q.id] = v;
      salvar();
      desenharPergunta();
      ($(".quiz-ja") || $(".como-votaram"))?.scrollIntoView({ block: "nearest", behavior: "smooth" });
      return;
    }
    const ir = e.target.closest("[data-quiz-ir]");
    if (ir) {
      quizVisao.i = +ir.dataset.quizIr;
      quizVisao.modo = "perguntas";
      return desenharQuiz(true);
    }
    const aba = e.target.closest("[data-res-cargo]");
    if (aba) {
      resCargos.cargo = +aba.dataset.resCargo;
      resCargos.todos = false;
      return desenharCargosResultado();
    }
    if (e.target.closest("[data-res-cargo-todos]")) {
      resCargos.todos = !resCargos.todos;
      return desenharCargosResultado();
    }
    const ficha = e.target.closest("[data-dep-ficha]");
    if (ficha) return abrirFicha(+ficha.dataset.cargo, +ficha.dataset.depFicha);
    const acao = e.target.closest("[data-quiz]")?.dataset.quiz;
    if (!acao) return;
    if (acao === "anterior") quizVisao.i = Math.max(0, quizVisao.i - 1);
    if (acao === "proxima") quizVisao.i = Math.min(quizDados.perguntas.length - 1, quizVisao.i + 1);
    if (acao === "resultado") quizVisao.modo = "resultado";
    if (acao === "revisar") { quizVisao.modo = "perguntas"; quizVisao.i = primeiraSemResposta(); }
    if (acao === "refazer") {
      if (!confirm("Apagar todas as suas respostas do questionário e começar de novo?")) return;
      estado.quiz = {};
      salvar();
      quizVisao.modo = "perguntas";
      quizVisao.i = 0;
    }
    desenharQuiz(true);
  });
}
