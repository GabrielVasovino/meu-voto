"use strict";

// Jornada guiada: em vez de abas soltas, o app segue a ordem da urna, um cargo por vez, com
// uma explicação curta em cada passo. O guia de boas-vindas abre no primeiro acesso e pelo
// botão "Guia" do topo. A afinidade do quiz acompanha a pessoa pelos passos seguintes.

const jornada = { passo: null };

function passosJornada() {
  const distrital = estado.uf === "DF";
  return [
    { id: "afinidade", curto: "Afinidade", titulo: "Quiz de afinidade", conteudo: "quiz" },
    { id: "dep_federal", curto: "Dep. federal", titulo: "Deputado(a) federal", cargo: 6, slots: ["dep_federal"], conteudo: "ajuda" },
    {
      id: "dep_estadual", curto: distrital ? "Dep. distrital" : "Dep. estadual",
      titulo: distrital ? "Deputado(a) distrital" : "Deputado(a) estadual",
      cargo: distrital ? 8 : 7, slots: ["dep_estadual"], conteudo: "ajuda",
    },
    { id: "senado", curto: "Senado", titulo: "Senado", cargo: 5, slots: ["senador_1", "senador_2"], conteudo: "ajuda" },
    { id: "governo", curto: "Governo", titulo: "Governo do estado", cargo: 3, slots: ["governador"], conteudo: "ajuda" },
    { id: "presidencia", curto: "Presidência", titulo: "Presidência", cargo: 1, slots: ["presidente"], conteudo: "ajuda" },
    { id: "cedula", curto: "Sua cédula", titulo: "Sua cédula", conteudo: "cedula" },
  ];
}

// Fica fora da trilha: abre a partir de "Sua cédula".
const PASSO_FORNECEDORES = { id: "fornecedores", titulo: "Fornecedores de campanha", cargo: "fornecedores", conteudo: "ajuda" };

function nomeCasa() {
  if (estado.uf === "DF") return "Câmara Legislativa do Distrito Federal";
  if (estado.uf === "SP") return "Assembleia Legislativa de São Paulo, a ALESP";
  return `Assembleia Legislativa de ${UFS[estado.uf] || "seu estado"}`;
}

// Texto de abertura de cada passo: o que este voto faz e o que dá para fazer na tela.
function introPasso(p) {
  const fezQuiz = respostasQuiz() >= 3;
  const textos = {
    afinidade: {
      kicker: "Opcional, para quem ainda tem dúvida",
      texto: `<p>São votações reais da Câmara dos Deputados, de 2023 a 2026, uma por vez. Diga se concorda ou discorda; como cada partido votou só aparece depois da sua resposta. No fim, você vê quais federações e partidos votaram mais parecido com você.</p>`,
    },
    dep_federal: {
      kicker: "1º voto na urna, com 4 dígitos",
      texto: `<p>O voto vai primeiro para a lista (federação ou partido) e depois para a pessoa. Escolha pelos cartões ou digite o número.</p>`,
    },
    dep_estadual: {
      kicker: "2º voto na urna, com 5 dígitos",
      texto: `<p>Funciona igual ao de deputado federal. Os eleitos vão para a ${esc(nomeCasa())}, que faz as leis do estado e fiscaliza o governador.</p>`,
    },
    senado: {
      kicker: "3º e 4º votos na urna, com 3 dígitos cada",
      texto: `<p>São duas vagas: você vota em duas pessoas diferentes, e ganham as duas mais votadas do estado, para 8 anos de mandato.</p>`,
    },
    governo: {
      kicker: "5º voto na urna, com 2 dígitos",
      texto: `<p>${estado.uf === "DF" ? "Governa o Distrito Federal" : "Governa o estado"} por 4 anos. Se ninguém passar da metade dos votos válidos, há 2º turno em 25 de outubro.</p>`,
    },
    presidencia: {
      kicker: "6º e último voto na urna, com 2 dígitos",
      texto: `<p>Governa o país por 4 anos. Se ninguém passar da metade dos votos válidos, há 2º turno em 25 de outubro.</p>`,
    },
    cedula: {
      kicker: "Revisão final",
      texto: `<p>Aqui estão os seus votos na ordem da urna. Se já sabe em quem votar, é só digitar o número ou o nome em cada cargo; para conferir alguém, toque em "Ver ficha". Quando terminar, imprima a cola: o celular não pode entrar na cabine, mas o papel pode.</p>`,
    },
    fornecedores: {
      kicker: "Para ir além",
      texto: `<p>As empresas que mais receberam das campanhas do seu estado em 2026. Em "Ver a empresa" aparecem o cadastro na Receita, os sócios, as campanhas que ela atende e o que chama atenção.</p>`,
    },
  };
  return textos[p.id];
}

function passoPorId(id) {
  if (id === PASSO_FORNECEDORES.id) return PASSO_FORNECEDORES;
  const lista = passosJornada();
  return lista.find((p) => p.id === id) || lista[lista.length - 1];
}

// ---------- trilha ----------

function respostasQuiz() {
  return Object.values(estado.quiz || {}).filter((v) => v).length;
}

function passoFeito(p) {
  if (p.id === "afinidade") return respostasQuiz() >= 3;
  if (p.slots) return p.slots.every((k) => estado.votos[k]);
  if (p.id === "cedula") return slots.length > 0 && slots.every((s) => estado.votos[s.key]);
  return false;
}

function desenharTrilha() {
  $("#jornada-passos").innerHTML = passosJornada().map((p, i) => `<li>
    <button type="button" class="jornada-passo" data-ir-passo="${p.id}">
      <span class="jornada-num" aria-hidden="true">${i + 1}</span><span>${esc(p.curto)}</span>
    </button></li>`).join("");
  marcarPassos();
}

// Atualiza os ✓ e o passo atual sem redesenhar (a trilha pode estar rolada no tablet).
function marcarPassos() {
  const lista = passosJornada();
  const atual = jornada.passo === PASSO_FORNECEDORES.id ? "cedula" : jornada.passo;
  document.querySelectorAll(".jornada-passo").forEach((b, i) => {
    const p = lista[i];
    if (!p) return;
    const feito = passoFeito(p);
    b.classList.toggle("feito", feito);
    b.querySelector(".jornada-num").textContent = feito ? "✓" : String(i + 1);
    if (p.id === atual) b.setAttribute("aria-current", "step");
    else b.removeAttribute("aria-current");
    b.title = feito ? `${p.titulo}: concluído` : p.titulo;
  });
}

function irParaPasso(id, rolar = true) {
  const p = passoPorId(id);
  jornada.passo = p.id;
  try { localStorage.setItem("passo", p.id); } catch { /* sem armazenamento: começa da cédula na próxima vez */ }
  document.querySelectorAll("[data-conteudo]").forEach((s) => { s.hidden = s.dataset.conteudo !== p.conteudo; });
  marcarPassos();
  desenharIntro(p);
  posicionarSlots(p);
  desenharNavPasso(p);
  if (p.conteudo === "ajuda") { ajuda.cargo = p.cargo; ajuda.grupo = null; montarAjuda(); }
  else if (p.conteudo === "quiz") montarQuiz();
  else montarPortal();
  if (rolar) window.scrollTo({ top: 0, behavior: "smooth" });
  $('.jornada-passo[aria-current="step"]')?.scrollIntoView({ block: "nearest", inline: "nearest" });
}

function desenharIntro(p) {
  const t = introPasso(p);
  $("#passo-intro").innerHTML = `<section class="passo-intro">
    <p class="passo-kicker">${t.kicker}</p>
    <h2>${esc(p.titulo)}</h2>
    ${t.texto}
  </section>`;
}

// Os campos da cédula são criados uma vez (montarCedula) e só mudam de lugar: no passo de um
// cargo ficam no topo dele; em "Sua cédula" voltam todos, na ordem da urna.
function posicionarSlots(p) {
  const noPasso = $("#passo-slots");
  for (const s of slots) {
    if (p.slots?.includes(s.key)) noPasso.appendChild(s.el);
    else $("#slots").appendChild(s.el);
  }
  noPasso.hidden = !p.slots;
}

function desenharNavPasso(p) {
  // O quiz tem navegação própria (votação anterior, próxima e o botão de seguir no resultado).
  if (p.id === "afinidade") { $("#passo-nav").innerHTML = ""; return; }
  const lista = passosJornada();
  const i = lista.findIndex((x) => x.id === p.id);
  const anterior = p.id === PASSO_FORNECEDORES.id ? lista[lista.length - 1] : lista[i - 1];
  const proximo = i >= 0 ? lista[i + 1] : null;
  $("#passo-nav").innerHTML = `
    ${anterior ? `<button type="button" class="btn" data-ir-passo="${anterior.id}">← ${esc(anterior.titulo)}</button>` : "<span></span>"}
    ${proximo ? `<button type="button" class="btn primario" data-ir-passo="${proximo.id}">Próximo: ${esc(proximo.titulo)} →</button>` : ""}`;
}

// Chamado por montarCedula (início e troca de estado).
function aoMontarCedula() {
  let salvo = null;
  try { salvo = localStorage.getItem("passo"); } catch { /* segue sem */ }
  if (!$("#jornada-passos").children.length || jornada.uf !== estado.uf) desenharTrilha();
  jornada.uf = estado.uf;
  irParaPasso(jornada.passo || salvo || "cedula", false);
}

// ---------- afinidade do quiz aplicada às listas e aos candidatos ----------

// A Câmara escreve as siglas sem acento (UNIAO); o TSE, com acento e às vezes com espaço (PC do B).
function normSigla(s) {
  return String(s || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toUpperCase().replace(/\s+/g, "");
}

// true quando a pessoa respondeu o quiz e as votações já estão carregadas.
async function afinidadePronta() {
  if (respostasQuiz() < 3) return false;
  try { return !!(await carregarQuizDados()); } catch { return false; }
}

// Como a maioria destes partidos, somados como um bloco, votou numa votação do quiz:
// "Sim", "Não" ou null quando não há bancada suficiente ou deu empate.
// Uma federação funciona como um só partido na eleição, então as bancadas são somadas.
function votoDoBloco(q, siglas) {
  const alvo = new Set(siglas.map(normSigla));
  let sim = 0;
  let nao = 0;
  for (const [s, pos] of Object.entries(q.partidos)) {
    if (alvo.has(normSigla(s))) { sim += pos.sim; nao += pos.nao; }
  }
  if (sim + nao < 3 || sim === nao) return null;
  return sim > nao ? "Sim" : "Não";
}

// Em quantas votações do quiz respondidas o bloco votou como você.
function afinidadePartidos(siglas) {
  if (!quizDados || quizDados.uf !== estado.uf) return null;
  const x = { a: 0, n: 0 };
  for (const q of quizDados.perguntas) {
    const r = estado.quiz?.[q.id];
    if (!r) continue;
    const voto = votoDoBloco(q, siglas);
    if (!voto) continue;
    x.n++;
    if ((r === 1) === (voto === "Sim")) x.a++;
  }
  return x.n >= 3 ? x : null;
}

// Afinidade individual: só existe para quem já é deputado federal, porque é quem tem voto
// registrado nessas votações. idTse é o id da candidatura no TSE.
function afinidadePessoa(idTse) {
  if (respostasQuiz() < 3 || !quizDados || quizDados.uf !== estado.uf) return null;
  const d = quizDados.deputados.find((x) => x.candidatura.id === +idTse);
  if (!d) return null;
  const x = { a: 0, n: 0 };
  for (const q of quizDados.perguntas) {
    const r = estado.quiz?.[q.id];
    const v = q.deputados[d.id];
    if (!r || !v) continue;
    x.n++;
    if ((r === 1) === (v === "Sim")) x.a++;
  }
  return x.n >= 3 ? x : null;
}

function textoAfinidadePessoa(idTse) {
  const x = afinidadePessoa(idTse);
  return x ? `No seu quiz, votou como você em ${x.a} de ${x.n} (${pctAfinidade(x)}%)` : "";
}

// Mesmo ajuste da tela do quiz para quem tem poucas votações em comum (regra de Laplace).
function notaAfinidade(x) { return x ? (x.a + 1) / (x.n + 2) : -1; }
function pctAfinidade(x) { return Math.round((x.a / x.n) * 100); }

function celulaAfinidade(x) {
  if (!x) return `<small class="sem-afinidade">Sem bancada na Câmara para comparar</small>`;
  return `<span class="afin-mini" title="A bancada votou como você em ${x.a} de ${x.n} votações do quiz">
    <span class="trilho"><span class="cheio" style="width:${pctAfinidade(x)}%"></span></span><b>${pctAfinidade(x)}%</b></span>`;
}

function rankingListas(grupos) {
  return grupos.map((g) => ({ g, x: afinidadePartidos(g.partidos) }))
    .sort((a, b) => notaAfinidade(b.x) - notaAfinidade(a.x));
}

function htmlLinhasRanking(itens, botao) {
  return itens.map(({ g, x }) => linhaAfinidade(
    botao ? `<button type="button" class="link-btn" data-abrir-lista="${esc(g.id)}">${esc(agremiacao(g.id))}</button>` : esc(agremiacao(g.id)),
    g.vagas ? `${g.vagas} ${g.vagas === 1 ? "vaga estimada" : "vagas estimadas"}` : "nenhuma vaga estimada", x)).join("");
}

// ---------- guia de boas-vindas ----------

const guia = { etapa: 0 };
const ETAPAS_GUIA = 3;

function abrirGuia(etapa = 0) {
  guia.etapa = etapa;
  const dlg = $("#guia");
  if (!dlg.open) dlg.showModal();
  desenharGuia();
}

function marcarGuiaVisto() {
  if (estado.guiaVisto || !estado.uf) return;
  estado.guiaVisto = true;
  salvar();
}

function topoGuia() {
  const pontos = Array.from({ length: ETAPAS_GUIA }, (_, i) => `<i class="${i <= guia.etapa ? "on" : ""}"></i>`).join("");
  return `<div class="guia-topo">
    <div class="guia-pontos" aria-label="Etapa ${guia.etapa + 1} de ${ETAPAS_GUIA}">${pontos}</div>
    <button type="button" class="fechar" data-guia="fechar" aria-label="Fechar o guia">✕</button>
  </div>`;
}

async function desenharGuia() {
  const corpo = $("#guia-corpo");
  const etapa = guia.etapa;
  let html = "";
  if (etapa === 0) {
    html = `<h2 id="guia-titulo">Boas-vindas ao Meu Voto</h2>
      <p>Em poucos minutos você monta a sua cédula para 4 de outubro e entende o que cada voto faz. O caminho é este:</p>
      <ol class="guia-roteiro">
        <li>Você diz em que estado vota.</li>
        <li>Se ainda tiver dúvida, responde um quiz com votações reais da Câmara e descobre com quais federações e partidos tem mais afinidade.</li>
        <li>Passa pelos cargos na mesma ordem da urna, com uma explicação curta em cada um e a ficha de cada candidato, montada com dados públicos.</li>
        <li>No fim, imprime a cola para levar no dia da eleição.</li>
      </ol>
      <p class="nota-pequena">Suas escolhas ficam guardadas só ${modoApp.publico ? "neste aparelho" : "no seu computador"}. O app mostra dados e comparações, mas não recomenda em quem votar.</p>
      <div class="guia-acoes"><span></span><button type="button" class="btn primario" data-guia="avancar">Começar →</button></div>`;
  } else if (etapa === 1) {
    const opcoes = Object.entries(UFS).map(([s, n]) => `<option value="${s}"${s === estado.uf ? " selected" : ""}>${esc(n)} (${s})</option>`).join("");
    html = `<h2 id="guia-titulo">Onde você vota?</h2>
      <p>É o estado do seu título de eleitor. Ele define quem aparece para você em deputado, senador e governador.</p>
      <label class="guia-rotulo" for="guia-uf">Estado</label>
      <select id="guia-uf"><option value="">Escolha…</option>${opcoes}</select>
      <div class="guia-acoes">
        <button type="button" class="btn" data-guia="voltar">← Voltar</button>
        <button type="button" class="btn primario" data-guia="uf"${estado.uf ? "" : " disabled"}>Continuar →</button>
      </div>`;
  } else {
    html = `<h2 id="guia-titulo">Por onde você quer começar?</h2>
      <div class="guia-escolhas">
        <button type="button" class="guia-escolha" data-guia-ir="cedula">
          <strong>Já sei em quem votar</strong>
          <span>Vá direto para a cédula e digite os números. Dá para abrir a ficha de cada candidato antes de confirmar.</span>
        </button>
        <button type="button" class="guia-escolha principal" data-guia-ir="afinidade">
          <strong>Ainda tenho dúvidas</strong>
          <span>Responda o quiz de afinidade e depois siga os cargos na ordem da urna, vendo quais listas e candidatos votaram mais parecido com você.</span>
        </button>
      </div>
      <div class="guia-acoes">
        <button type="button" class="btn" data-guia="voltar">← Voltar</button>
        <button type="button" class="link-btn" data-guia-ir="dep_federal">Prefiro ver os cargos um por um, sem o quiz</button>
      </div>`;
  }
  corpo.innerHTML = topoGuia() + html;
  $("#guia-uf")?.addEventListener("change", (e) => {
    $('[data-guia="uf"]').disabled = !e.target.value;
  });
  corpo.querySelector("h2")?.focus?.();
}

async function acaoGuia(acao) {
  if (acao === "fechar") return $("#guia").close();
  if (acao === "voltar") { guia.etapa = Math.max(0, guia.etapa - 1); return desenharGuia(); }
  if (acao === "avancar") { guia.etapa++; return desenharGuia(); }
  if (acao === "uf") {
    const uf = $("#guia-uf").value;
    if (!uf || !trocarUf(uf)) return;
    guia.etapa++;
    return desenharGuia();
  }
}

function iniciarJornada() {
  document.addEventListener("click", (e) => {
    const ir = e.target.closest("[data-ir-passo],[data-guia-ir]");
    if (ir) {
      if ($("#guia").open) $("#guia").close();
      irParaPasso(ir.dataset.irPasso || ir.dataset.guiaIr);
      return;
    }
    const acao = e.target.closest("[data-guia]");
    if (acao) acaoGuia(acao.dataset.guia);
  });
  $("#guia").addEventListener("close", marcarGuiaVisto);
  $("#abrir-guia").addEventListener("click", () => abrirGuia(0));
  $("#ver-fornecedores").addEventListener("click", () => irParaPasso("fornecedores"));
  if (!estado.uf || !estado.guiaVisto) abrirGuia(0);
}
