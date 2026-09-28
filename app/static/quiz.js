"use strict";

// Quiz de afinidade: uma votação por vez, com barra de progresso, e o resultado numa tela
// própria. Como as bancadas votaram só aparece depois da resposta, para não influenciar.

let quizDados = null;
const quizVisao = { modo: null, i: 0, uf: null }; // modo: "perguntas" ou "resultado"
let listasQuiz = null;

// Votações do quiz e como cada partido votou. Devolve null enquanto a Câmara ainda está sendo preparada.
async function carregarQuizDados() {
  if (quizDados && quizDados.uf === estado.uf) return quizDados;
  const d = await api(`/api/quiz?uf=${estado.uf}`);
  if (!d.pronto) return null;
  quizDados = { uf: estado.uf, ...d };
  // Respostas de votações que saíram do quiz não contam mais: são descartadas.
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
    corpo.innerHTML = `<p class="carregando">Carregando as votações…</p>`;
    let d;
    try {
      d = await carregarQuizDados();
    } catch (e) {
      corpo.innerHTML = `<p class="carregando">${esc(e.message)}</p>`;
      return;
    }
    if (!d) {
      corpo.innerHTML = `<p class="carregando">Preparando os dados da Câmara. Na primeira vez isso leva cerca de um minuto…</p>`;
      setTimeout(() => { if (!$("#aba-quiz").hidden) montarQuiz(); }, 5000);
      return;
    }
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
      <div class="quiz-guia">${htmlGuiaPergunta(q)}</div>
      ${q.nota ? `<p class="quiz-nota"><strong>Para não confundir:</strong> ${esc(q.nota)}</p>` : ""}
      ${htmlEntenda(q)}
      <div class="quiz-respostas" role="group" aria-label="Sua resposta">
        ${botao(1, "Concordo", "concordo")}${botao(-1, "Discordo", "discordo")}${botao(0, "Não sei, prefiro pular", "pular")}
      </div>
      ${respondeu ? htmlComoVotaram(q) : ""}
    </article>
    <div class="quiz-nav">
      ${i > 0 ? `<button type="button" class="btn" data-quiz="anterior">← Anterior</button>` : "<span></span>"}
      ${seguir}
    </div>
    ${ultima && n < 3 ? `<p class="nota-pequena quiz-nota-fim">Responda pelo menos 3 votações para ver o resultado. Toque nos traços acima para voltar a uma delas.</p>` : ""}
    <p class="quiz-pular"><button type="button" class="link-btn" data-ir-passo="dep_federal">Pular o quiz e ir para Deputado(a) federal</button></p>
    <details class="metodo quiz-metodo"><summary>Como as votações foram escolhidas</summary><p>${esc(quizDados.criterio)}${quizDados.atualizadoEm ? ` Os textos de contexto foram revisados em ${esc(quizDados.atualizadoEm)}.` : ""}</p></details>
  </div>`;
}

// "Grupo: efeito" vira o grupo em negrito seguido do efeito.
function itemEfeito(texto) {
  const i = texto.indexOf(": ");
  if (i < 0) return `<li>${esc(texto)}</li>`;
  return `<li><strong>${esc(texto.slice(0, i))}</strong> ${esc(texto.slice(i + 2))}</li>`;
}

// As quatro partes, sempre na mesma ordem, que a pessoa lê antes de responder.
function htmlGuiaPergunta(q) {
  const secao = (n, titulo, corpo) => corpo
    ? `<section class="quiz-sec"><h4><span class="quiz-sec-n" aria-hidden="true">${n}</span>${titulo}</h4>${corpo}</section>` : "";
  const ladoHtml = (classe, titulo, l) => l ? `<div class="quiz-lado ${classe}">
      <p class="quiz-lado-tit">${titulo}</p>
      <p class="quiz-lado-quem">${esc(l.quem)}</p>
      <ul>${l.argumentos.map((a) => `<li>${esc(a)}</li>`).join("")}</ul>
    </div>` : "";
  // ladoSim/ladoNao: sim e nao já são o placar da votação.
  const lados = q.ladoSim || q.ladoNao
    ? `<div class="quiz-lados">${ladoHtml("sim", "Quem defendia o Sim <small>(concordar)</small>", q.ladoSim)}${ladoHtml("nao", "Quem defendia o Não <small>(discordar)</small>", q.ladoNao)}</div>` : "";
  const efeitos = q.ganha?.length || q.perde?.length ? `<div class="quiz-efeitos">
      <div class="quiz-efeito ganha"><p class="quiz-lado-tit">Quem tende a ganhar</p><ul>${(q.ganha || []).map(itemEfeito).join("")}</ul></div>
      <div class="quiz-efeito perde"><p class="quiz-lado-tit">Quem tende a perder</p><ul>${(q.perde || []).map(itemEfeito).join("")}</ul></div>
    </div>` : "";
  const pratica = q.pratica
    ? `<p>${esc(q.pratica)}</p>${q.incerto ? `<p class="quiz-incerto"><strong>Ainda em aberto:</strong> ${esc(q.incerto)}</p>` : ""}` : "";
  return secao(1, "Como chegou a essa votação", q.historia ? `<p>${esc(q.historia)}</p>` : "")
    + secao(2, "O que muda na prática", pratica)
    + secao(3, "Os dois lados", lados)
    + secao(4, "Quem tende a ganhar e a perder", efeitos);
}

// Desfecho, ementa oficial e fontes ficam recolhidos.
function htmlEntenda(q) {
  const p = q.proposicao;
  const link = (url, nome) => `<a href="${esc(url)}" target="_blank" rel="noopener">${esc(nome)}</a>`;
  const fontes = [p ? link(p.link, `Ficha do ${p.nome} na Câmara`) : "", ...(q.fontes || []).map((f) => link(f.url, f.nome))]
    .filter(Boolean).join("");
  const situacao = p?.situacao
    ? `<p class="situacao">No sistema da Câmara, o último registro é "${esc(p.situacao)}"${p.dataSituacao ? `, de ${esc(dataBr(p.dataSituacao))}` : ""}. Esse registro às vezes não acompanha o que aconteceu depois no Senado ou na sanção, por isso vale o desfecho descrito acima.</p>` : "";
  return `<details class="entenda">
    <summary>O que aconteceu depois e fontes</summary>
    <p>${esc(q.depois)}</p>
    ${situacao}
    ${p?.ementa ? `<p class="ementa">Ementa oficial: “${esc(p.ementa)}”</p>` : ""}
    ${fontes ? `<div class="links">${fontes}</div>` : ""}
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
  const p = x.a / x.n;
  return `<div class="linha" title="Concorda em ${x.a} de ${x.n} votações">
    <span class="nome">${nome}${sub ? `<small>${sub}</small>` : ""}</span>
    <span class="trilho"><span class="cheio" style="width:${Math.round(p * 100)}%"></span></span>
    <span class="pc" ${atributos}>${Math.round(p * 100)}%<small>${x.a} de ${x.n}</small></span>
  </div>`;
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
  const deps = quizDados.deputados.map((d) => {
    const x = { d, a: 0, n: 0 };
    for (const q of respondidas) {
      const v = q.deputados[d.id];
      if (!v) continue;
      x.n++;
      if (concorda(q, v)) x.a++;
    }
    return x;
  }).filter((x) => x.n >= minimo).sort((a, b) => notaQuiz(b) - notaQuiz(a));

  const listaPartidos = Object.entries(partidos).filter(([, x]) => x.n >= minimo)
    .sort((a, b) => notaQuiz(b[1]) - notaQuiz(a[1]))
    .map(([s, x]) => linhaAfinidade(esc(sigla(s)), "", x)).join("");
  const htmlDep = (x) => linhaAfinidade(
    `<button type="button" class="link-btn" data-dep-ficha="${x.d.candidatura.id}" data-cargo="${x.d.candidatura.cargo}">${esc(x.d.nome)}</button>`,
    `${esc(sigla(x.d.partido))}, disputa ${esc(x.d.candidatura.rotulo.toLowerCase())} com o ${esc(x.d.candidatura.numero)}`, x);
  const topDeps = deps.slice(0, 3);

  const faltam = vistas < perguntas.length;
  $("#quiz-corpo").innerHTML = `<div class="quiz-res" id="quiz-palco">
    <header class="res-cab">
      <div class="res-cab-texto">
        <p class="passo-kicker">Seu resultado</p>
        <h3>Quem votou mais parecido com você</h3>
        <p>Com base nas suas ${n} respostas${faltam ? `, de ${perguntas.length} votações` : ""}. A porcentagem mostra em quantas delas a maioria da bancada votou do jeito que você respondeu.</p>
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
        <h4>Federações e partidos</h4>
        <p class="explica">As listas que disputam deputado federal em ${esc(UFS[estado.uf] || estado.uf)}. Nas federações, os partidos votam como um bloco, então as bancadas são somadas.</p>
      </div>
      <div class="res-podio" id="res-podio"><p class="carregando">Comparando com as listas de ${esc(UFS[estado.uf] || estado.uf)}…</p></div>
    </section>

    ${topDeps.length ? `<section class="res-secao">
      <div class="res-secao-cab">
        <h4>Deputados federais</h4>
        <p class="explica">Quem já é deputado federal e disputa 2026 em ${esc(estado.uf)} tem o próprio voto registrado nessas votações. Toque no nome para abrir a ficha.</p>
      </div>
      <div class="res-podio">
        ${topDeps.map((x, k) => cartaoPessoa(x, k)).join("")}
        <details class="res-todos cartao"><summary>Ver todos os deputados (${deps.length})</summary>
          <div class="afinidade">${deps.map(htmlDep).join("")}</div>
        </details>
      </div>
    </section>` : ""}

    <div class="callout res-seguir">
      <p>Essa afinidade acompanha você nos próximos passos: aparece em cada lista de deputados, no rosto de quem já é deputado federal e ao lado de cada candidato a senador, governador e presidente.</p>
      <button type="button" class="btn primario" data-ir-passo="dep_federal">Seguir para Deputado(a) federal →</button>
    </div>
    <div class="res-rodape">
      <details class="metodo res-partidos"><summary>Ver partido por partido</summary><div class="afinidade" style="margin-top:8px">${listaPartidos}</div></details>
      <p class="nota-pequena">A comparação usa só estas ${perguntas.length} votações da Câmara. <button type="button" class="link-btn quiz-refazer" data-quiz="refazer">Apagar as respostas e refazer o quiz</button></p>
    </div>
  </div>`;
  preencherListasResultado();
}

// Pódio com as 3 listas (federação ou partido) de deputado federal do estado que mais votaram como você.
async function preencherListasResultado() {
  if (!listasQuiz || listasQuiz.uf !== estado.uf) {
    try {
      listasQuiz = { uf: estado.uf, p: await api(`/api/listas?uf=${estado.uf}&cargo=6`) };
    } catch {
      const podio = $("#res-podio");
      if (podio) podio.innerHTML = "";
      return;
    }
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
      <div class="res-pc"><strong>${pcx}%</strong><span>${x.a} de ${x.n} votações</span></div>
      <div class="trilho"><span class="cheio" style="width:${pcx}%"></span></div>
      <p class="res-vagas">${vagas}</p>
    </article>`;
  }).join("") + `<details class="res-todos cartao"><summary>Ver todas as listas (${com.length})</summary>
      <div class="afinidade">${htmlLinhasRanking(com, false)}</div>
      ${sem.length ? `<p class="nota-pequena">Sem bancada na Câmara para comparar: ${listaNatural(sem)}.</p>` : ""}
    </details>` + (top.length ? `<details class="res-todos cartao"><summary>Comparar votação por votação</summary>${htmlVotacaoPorVotacao(top.map((i) => i.g))}</details>` : "");
}

// Cartão de deputado com as mesmas 6 partes do cartão de lista, para as duas seções ficarem iguais.
function cartaoPessoa(x, k) {
  const pcx = pctAfinidade(x);
  const c = x.d.candidatura;
  return `<article class="res-top${k === 0 ? " primeiro" : ""}">
    <span class="res-pos">${k + 1}º lugar</span>
    <div class="res-pessoa">
      ${fotoHtml(estado.uf, c.id, x.d.nome, "foto res-foto")}
      <h4><button type="button" class="link-btn" data-dep-ficha="${c.id}" data-cargo="${c.cargo}">${esc(nomeProprio(x.d.nome))}</button></h4>
    </div>
    <div class="chips"><span class="chip">${esc(sigla(x.d.partido))}</span><span class="chip">Nº ${esc(c.numero)}</span></div>
    <div class="res-pc"><strong>${pcx}%</strong><span>${x.a} de ${x.n} votações</span></div>
    <div class="trilho"><span class="cheio" style="width:${pcx}%"></span></div>
    <p class="res-vagas">Disputa ${esc(c.rotulo.toLowerCase())} em 2026</p>
  </article>`;
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
  $("#quiz-corpo").addEventListener("click", (e) => {
    const resp = e.target.closest("[data-quiz-resp]");
    if (resp) {
      const q = quizDados.perguntas[quizVisao.i];
      const v = +resp.dataset.quizResp;
      if (estado.quiz[q.id] === v) delete estado.quiz[q.id];
      else estado.quiz[q.id] = v;
      salvar();
      desenharPergunta();
      $(".como-votaram")?.scrollIntoView({ block: "nearest", behavior: "smooth" });
      return;
    }
    const ir = e.target.closest("[data-quiz-ir]");
    if (ir) {
      quizVisao.i = +ir.dataset.quizIr;
      quizVisao.modo = "perguntas";
      return desenharQuiz(true);
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
      if (!confirm("Apagar todas as suas respostas do quiz e começar de novo?")) return;
      estado.quiz = {};
      salvar();
      quizVisao.modo = "perguntas";
      quizVisao.i = 0;
    }
    desenharQuiz(true);
  });
}
