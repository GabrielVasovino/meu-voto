"use strict";

const UFS = {
  AC: "Acre", AL: "Alagoas", AP: "Amapá", AM: "Amazonas", BA: "Bahia", CE: "Ceará",
  DF: "Distrito Federal", ES: "Espírito Santo", GO: "Goiás", MA: "Maranhão", MT: "Mato Grosso",
  MS: "Mato Grosso do Sul", MG: "Minas Gerais", PA: "Pará", PB: "Paraíba", PR: "Paraná",
  PE: "Pernambuco", PI: "Piauí", RJ: "Rio de Janeiro", RN: "Rio Grande do Norte",
  RS: "Rio Grande do Sul", RO: "Rondônia", RR: "Roraima", SC: "Santa Catarina",
  SP: "São Paulo", SE: "Sergipe", TO: "Tocantins",
};

// Mesma ordem da urna em 2026.
function slotsPara(uf) {
  const distrital = uf === "DF";
  return [
    { key: "dep_federal", cargo: 6, rotulo: "Deputado(a) Federal", digitos: 4, legenda: true },
    {
      key: "dep_estadual", cargo: distrital ? 8 : 7, digitos: 5, legenda: true,
      rotulo: distrital ? "Deputado(a) Distrital" : "Deputado(a) Estadual",
    },
    { key: "senador_1", cargo: 5, rotulo: "Senador(a), 1ª vaga", digitos: 3 },
    { key: "senador_2", cargo: 5, rotulo: "Senador(a), 2ª vaga", digitos: 3 },
    { key: "governador", cargo: 3, rotulo: "Governador(a)", digitos: 2 },
    { key: "presidente", cargo: 1, rotulo: "Presidente", digitos: 2 },
  ];
}

const estado = { uf: "", votos: {} };
let slots = [];

const $ = (sel, raiz = document) => raiz.querySelector(sel);
const brl = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" });
const pct = new Intl.NumberFormat("pt-BR", { style: "percent", maximumFractionDigits: 1 });

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

const MINUSCULAS = new Set(["de", "da", "do", "das", "dos", "e", "di", "du"]);
function nomeProprio(s) {
  return String(s ?? "").toLowerCase().split(/(\s+|-)/).map((p, i) =>
    i > 0 && MINUSCULAS.has(p) ? p : p.charAt(0).toUpperCase() + p.slice(1)
  ).join("");
}

// "FEDERAÇÃO PSDB CIDADANIA(45-PSDB/23-CIDADANIA)" -> "FEDERAÇÃO PSDB CIDADANIA"
function agremiacao(nome) {
  return String(nome ?? "").replace(/\s*\(.*\)\s*$/, "");
}

function dataBr(s) {
  const m = /^(\d{4})-(\d{2})-(\d{2})(.*)$/.exec(s || "");
  return m ? `${m[3]}/${m[2]}/${m[1]}${m[4]}` : s || "—";
}

function naturalidade(s) {
  const m = /^([A-Z]{2})-(.+)$/.exec(s || "");
  return m ? `${nomeProprio(m[2])} (${m[1]})` : s;
}

const GENEROS = { "MASC.": "Masculino", "FEM.": "Feminino" };

// Os dados da Câmara vêm com siglas sem acento; aqui voltamos à grafia oficial.
const SIGLAS = { UNIAO: "UNIÃO", PCDOB: "PCdoB", MISSAO: "MISSÃO" };
function sigla(s) { return SIGLAS[s] || s; }

// Logos dos partidos (Wikipédia / Wikimedia Commons), em static/logos/SIGLA.png, sigla sem acento nem espaço.
const LOGOS = new Set(("AGIR AVANTE CIDADANIA DC DEMOCRATA MDB MISSAO NOVO PCB PCDOB PCO PDT PL PODE PP PRD PRTB PSB PSD PSDB "
  + "PSOL PSTU PT PV REDE REPUBLICANOS SOLIDARIEDADE UNIAO").split(" "));
function logoPartido(s, classe = "logo-partido") {
  const chave = String(s || "").normalize("NFD").replace(/[̀-ͯ\s]/g, "").toUpperCase();
  return LOGOS.has(chave) ? `<img class="${classe}" src="logos/${chave}.png" alt="${esc(sigla(s))}" loading="lazy">` : "";
}

function iniciais(nome) {
  return String(nome ?? "?").split(/\s+/).filter(Boolean).slice(0, 2).map((p) => p[0]).join("").toUpperCase();
}

function idade(nascimento) {
  if (!nascimento) return null;
  const n = new Date(nascimento + "T12:00:00");
  const hoje = new Date();
  let a = hoje.getFullYear() - n.getFullYear();
  if (hoje.getMonth() < n.getMonth() || (hoje.getMonth() === n.getMonth() && hoje.getDate() < n.getDate())) a--;
  return a;
}

async function api(caminho, opcoes) {
  const r = await fetch(caminho, opcoes);
  let dados = null;
  try { dados = await r.json(); } catch { /* resposta sem JSON */ }
  if (r.status === 401) location.reload(); // sessão expirou: o servidor mostra a tela de login
  if (!r.ok) throw new Error(dados?.erro || `Erro ${r.status}`);
  return dados;
}

// ---------- esperas longas ----------

// Quando o servidor ainda está montando uma base (só na primeira vez), a tela mostra a lista de passos, com o
// passo atual girando, e há quanto tempo está esperando, para ninguém achar que travou.
const inicioEspera = new Map();

// passos: [[id, texto], ...]; atual: id do passo em andamento (null = o primeiro).
function htmlEspera(chave, titulo, passos, atual, nota) {
  if (!inicioEspera.has(chave)) inicioEspera.set(chave, Date.now());
  const seg = Math.round((Date.now() - inicioEspera.get(chave)) / 1000);
  const i = Math.max(0, passos.findIndex(([id]) => id === atual));
  const itens = passos.map(([, texto], k) => {
    const st = k < i ? "feito" : k === i ? "agora" : "depois";
    const marca = st === "feito" ? "✓" : st === "agora" ? "" : String(k + 1);
    return `<li class="espera-passo ${st}"><span class="espera-marca" aria-hidden="true">${marca}</span>${esc(texto)}</li>`;
  }).join("");
  return `<div class="espera" role="status" aria-live="polite">
    <div class="espera-anim" aria-hidden="true"><span></span><span></span><span></span></div>
    <h3>${esc(titulo)}</h3>
    <ol class="espera-passos">${itens}</ol>
    <p class="espera-nota">${esc(nota)}${seg >= 5 ? ` Esperando há ${seg < 60 ? `${seg} s` : `${Math.floor(seg / 60)} min ${seg % 60} s`}.` : ""}</p>
  </div>`;
}

function fimEspera(chave) { inicioEspera.delete(chave); }

// Os passos que o servidor segue para montar a base de deputados de um estado (historico.PASSOS).
const PASSOS_LISTAS = [
  ["vagas", "Conferindo quantas vagas de deputado o estado tem"],
  ["votos", "Somando os votos de cada candidato em 2022"],
  ["partidos", "Somando os votos de cada partido em 2022"],
  ["candidatos", "Vendo quem se elegeu em 2022"],
  ["municipal", "Buscando os votos de vereador e prefeito em 2024"],
  ["montar", "Montando as listas de 2026"],
];

function htmlEsperaListas(p) {
  const nome = UFS[estado.uf] || estado.uf;
  return htmlEspera(`listas-${estado.uf}`, `Preparando os dados de ${nome}`, PASSOS_LISTAS, p.etapa,
    "Isso só acontece na primeira vez que alguém abre este estado e leva até 2 minutos. A tela atualiza sozinha.");
}

// Assim que o estado é conhecido (no guia de boas-vindas ou ao reabrir o site), pede em segundo plano o que as
// próximas telas vão usar. Na primeira vez o servidor começa a montar os dados deste estado enquanto a pessoa
// ainda lê o guia ou responde o questionário; nas outras, as respostas já ficam prontas no navegador e no servidor.
const aquecidos = new Set();
function aquecerEstado(uf) {
  if (!uf || aquecidos.has(uf)) return;
  aquecidos.add(uf);
  const segundo = uf === "DF" ? 8 : 7;
  const pedidos = [`/api/quiz?uf=${uf}`, `/api/listas?uf=${uf}&cargo=6`, `/api/listas?uf=${uf}&cargo=${segundo}`,
    `/api/candidatos?uf=${uf}&cargo=5`, `/api/candidatos?uf=${uf}&cargo=3`, "/api/candidatos?uf=BR&cargo=1"];
  for (const url of pedidos) fetch(url).catch(() => { /* só adianta o trabalho; a tela pede de novo quando abrir */ });
}

function ufConsulta(cargo) { return cargo === 1 ? "BR" : estado.uf; }

function fotoHtml(uf, id, nome, classe = "foto") {
  if (!id) return `<div class="${classe}" aria-hidden="true">${esc(iniciais(nome))}</div>`;
  return `<img class="${classe}" alt="" loading="lazy" src="/api/foto?uf=${esc(uf)}&id=${esc(id)}"
    data-iniciais="${esc(iniciais(nome))}" onerror="trocarFoto(this)">`;
}

window.trocarFoto = (img) => {
  const div = document.createElement("div");
  div.className = img.className;
  div.setAttribute("aria-hidden", "true");
  div.textContent = img.dataset.iniciais;
  img.replaceWith(div);
};

function badgeSituacao(situacao) {
  const s = (situacao || "").toLowerCase();
  if (!s) return "";
  let tipo = "";
  let texto = situacao;
  if (s === "deferido") { tipo = "ok"; texto = "Candidatura deferida"; }
  else if (s.includes("indeferido") || s.includes("cancel") || s.includes("renúncia") || s.includes("falec")) tipo = "bad";
  else if (s.includes("pendente") || s.includes("recurso")) tipo = "warn";
  const icone = { ok: "✓", bad: "✕", warn: "!" }[tipo] || "";
  return `<span class="badge ${tipo}">${icone ? `<span aria-hidden="true">${icone}</span>` : ""}${esc(texto)}</span>`;
}

// ---------- contagem ----------

function atualizarContagem() {
  const hoje = new Date();
  hoje.setHours(0, 0, 0, 0);
  const dias = (d) => Math.round((new Date(d + "T00:00:00") - hoje) / 86400000);
  const p = dias("2026-10-04");
  const s = dias("2026-10-25");
  let txt;
  if (p > 1) txt = `Faltam <strong>${p} dias</strong> para o 1º turno (4/out)`;
  else if (p === 1) txt = `<strong>Amanhã</strong> é o 1º turno`;
  else if (p === 0) txt = `<strong>Hoje</strong> é dia de votar`;
  else if (s > 0) txt = `2º turno em <strong>${s} ${s === 1 ? "dia" : "dias"}</strong> (25/out)`;
  else if (s === 0) txt = `<strong>Hoje</strong> é o 2º turno`;
  else txt = "Eleições 2026 encerradas";
  $("#contagem").innerHTML = txt;
}

// ---------- salvar ----------

// No modo público (servidor com --publico) a cédula e o questionário ficam só neste navegador.
const modoApp = { publico: false };
const CHAVE_LOCAL = "meuvoto:cedula";

function lerCedulaLocal() {
  try { return JSON.parse(localStorage.getItem(CHAVE_LOCAL) || "{}"); } catch { return {}; }
}

let timerSalvar;
function salvar() {
  marcarPassos();
  clearTimeout(timerSalvar);
  timerSalvar = setTimeout(async () => {
    if (modoApp.publico) {
      try {
        localStorage.setItem(CHAVE_LOCAL, JSON.stringify(estado));
        const hora = new Date().toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
        $("#salvo").textContent = `Salvo neste aparelho às ${hora}`;
      } catch {
        $("#salvo").textContent = "Este navegador não deixou salvar. Suas escolhas somem ao fechar a página.";
      }
      return;
    }
    try {
      const r = await api("/api/cedula", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(estado),
      });
      const hora = new Date(r.salvoEm).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
      $("#salvo").textContent = `Salvo às ${hora}`;
    } catch (e) {
      $("#salvo").textContent = `Não foi possível salvar: ${e.message}`;
    }
  }, 400);
}

// ---------- cédula ----------

function montarCedula() {
  slots = slotsPara(estado.uf);
  const raiz = $("#slots");
  raiz.innerHTML = "";
  for (const slot of slots) {
    const el = document.createElement("article");
    el.className = "slot";
    const dicaLegenda = slot.legenda ? ", ou 2 para votar só no partido" : "";
    el.innerHTML = `
      <div class="slot-cab">
        <h3>${esc(slot.rotulo)}</h3>
        <div class="dica">${slot.digitos} dígitos${dicaLegenda}</div>
        <input type="text" autocomplete="off" spellcheck="false" maxlength="60"
          aria-label="${esc(slot.rotulo)}: número ou nome" placeholder="Número ou nome">
      </div>
      <div class="resultado" aria-live="polite"></div>`;
    raiz.appendChild(el);
    slot.el = el;
    slot.input = $("input", el);
    slot.res = $(".resultado", el);
    slot.req = 0;
    ligarEntrada(slot);

    const voto = estado.votos[slot.key];
    if (voto) {
      slot.input.value = voto.numero;
      mostrarVoto(slot);
      if (voto.tipo === "candidato") atualizarEmSegundoPlano(slot, voto);
    } else {
      mostrar(slot, "vazio", "Ainda não escolhido.");
    }
  }
  $("#cedula").hidden = false;
  $("#futuro").hidden = false;
  $("#jornada").hidden = false;
  aoMontarCedula();
}

function mostrar(slot, tipo, msg) {
  slot.res.innerHTML = `<p class="${tipo}">${esc(msg)}</p>`;
}

function ligarEntrada(slot) {
  let timer;
  slot.input.addEventListener("input", () => {
    const v = slot.input.value.trim();
    clearTimeout(timer);
    slot.req++;
    slot.input.classList.toggle("texto", /\D/.test(v));
    if (estado.votos[slot.key] && estado.votos[slot.key].numero !== v) {
      delete estado.votos[slot.key];
      salvar();
    }
    if (!v) return mostrar(slot, "vazio", "Ainda não escolhido.");
    if (/^\d+$/.test(v)) {
      if (v.length === slot.digitos) return buscarNumero(slot, v);
      if (v.length > slot.digitos) return mostrar(slot, "aviso", `Para este cargo o número tem ${slot.digitos} dígitos.`);
      if (slot.legenda && v.length === 2) {
        return mostrar(slot, "vazio", "Continue digitando. Se quiser votar só no partido, que é o voto de legenda, tecle Enter.");
      }
      return mostrar(slot, "vazio", "Continue digitando…");
    }
    if (v.length >= 2) timer = setTimeout(() => buscarNome(slot, v), 300);
  });
  slot.input.addEventListener("keydown", (e) => {
    const v = slot.input.value.trim();
    if (e.key === "Enter" && slot.legenda && /^\d{2}$/.test(v)) buscarNumero(slot, v);
  });
}

async function buscarNumero(slot, numero) {
  const req = ++slot.req;
  mostrar(slot, "vazio", "Buscando no TSE…");
  try {
    const d = await api(`/api/buscar?uf=${ufConsulta(slot.cargo)}&cargo=${slot.cargo}&numero=${numero}`);
    if (req !== slot.req) return;
    if (d.legenda) return escolherLegenda(slot, d.legenda);
    if (!d.candidatos.length) {
      const oque = numero.length === 2 && slot.legenda ? "partido" : "candidato";
      return mostrar(slot, "aviso", `Nenhum ${oque} com o número ${numero} para este cargo. Na urna, seria voto nulo.`);
    }
    if (d.candidatos.length === 1) return escolher(slot, d.candidatos[0]);
    mostrarOpcoes(slot, d.candidatos, "Há mais de um registro com este número, o que acontece quando um candidato é substituído. Qual é o seu?");
  } catch (e) {
    if (req === slot.req) mostrar(slot, "erro", e.message);
  }
}

async function buscarNome(slot, q) {
  const req = ++slot.req;
  mostrar(slot, "vazio", "Buscando…");
  try {
    const d = await api(`/api/buscar?uf=${ufConsulta(slot.cargo)}&cargo=${slot.cargo}&q=${encodeURIComponent(q)}`);
    if (req !== slot.req) return;
    if (!d.candidatos.length) return mostrar(slot, "aviso", `Ninguém com "${q}" no nome para este cargo.`);
    mostrarOpcoes(slot, d.candidatos, "Escolha:");
  } catch (e) {
    if (req === slot.req) mostrar(slot, "erro", e.message);
  }
}

function mostrarOpcoes(slot, candidatos, rotulo) {
  slot.res.innerHTML = `<ul class="opcoes"><li class="rotulo">${esc(rotulo)}</li>${candidatos.map((c, i) => `
    <li><button type="button" class="opcao" data-i="${i}">
      <span><strong>${esc(nomeProprio(c.nomeUrna))}</strong> · ${esc(c.partido)}
        <span class="sit">${esc(c.situacao || "")}</span></span>
      <span class="num">${esc(c.numero)}</span>
    </button></li>`).join("")}</ul>`;
  slot.res.querySelectorAll(".opcao").forEach((b) =>
    b.addEventListener("click", () => escolher(slot, candidatos[+b.dataset.i]))
  );
}

function escolher(slot, c) {
  if (slot.key.startsWith("senador_")) {
    const outro = estado.votos[slot.key === "senador_1" ? "senador_2" : "senador_1"];
    if (outro && outro.id === c.id) {
      slot.input.value = String(c.numero);
      return mostrar(slot, "aviso", "Você já escolheu esta pessoa na outra vaga de senador. Escolha outro nome.");
    }
  }
  estado.votos[slot.key] = {
    tipo: "candidato", cargo: slot.cargo, numero: String(c.numero), id: c.id,
    nomeUrna: c.nomeUrna, partido: c.partido, coligacao: c.coligacao, situacao: c.situacao,
  };
  slot.input.value = String(c.numero);
  slot.input.classList.remove("texto");
  mostrarVoto(slot);
  salvar();
}

function escolherLegenda(slot, l) {
  estado.votos[slot.key] = {
    tipo: "legenda", cargo: slot.cargo, numero: l.numero, partido: l.partido, coligacao: l.coligacao,
  };
  mostrarVoto(slot);
  salvar();
}

function mostrarVoto(slot) {
  const v = estado.votos[slot.key];
  if (v.tipo === "legenda") {
    const fed = v.coligacao && v.coligacao !== v.partido ? `, que está na <strong>${esc(agremiacao(v.coligacao))}</strong>` : "";
    slot.res.innerHTML = `
      <div class="legenda-box">
        <span class="legenda-num">${esc(v.numero)}</span>
        <div>
          <div class="cand-nome">Voto de legenda: ${esc(v.partido)}</div>
          <div class="cand-meta">O voto vai para o partido${fed}, e não para uma pessoa. Ele ajuda a definir quantas vagas o partido ganha.</div>
        </div>
        <div class="cand-acoes"><button type="button" class="btn fantasma" data-acao="retirar">Retirar</button></div>
      </div>`;
    $('[data-acao="retirar"]', slot.res).addEventListener("click", () => retirarVoto(slot.key));
    return;
  }
  const uf = ufConsulta(slot.cargo);
  const fed = v.coligacao && v.coligacao !== v.partido ? `<br>${esc(agremiacao(v.coligacao))}` : "";
  slot.res.innerHTML = `
    <div class="cand">
      ${fotoHtml(uf, v.id, v.nomeUrna)}
      <div class="cand-info">
        <div class="cand-nome">${esc(nomeProprio(v.nomeUrna))}</div>
        <div class="cand-meta">${esc(v.numero)} · ${esc(v.partido)}${fed}</div>
        <div class="cand-badges">${badgeSituacao(v.situacao)}</div>
      </div>
      <div class="cand-acoes">
        <button type="button" class="btn primario" data-acao="ficha">Ver ficha</button>
        <button type="button" class="btn fantasma" data-acao="retirar">Retirar</button>
      </div>
    </div>`;
  $('[data-acao="ficha"]', slot.res).addEventListener("click", () => abrirFicha(slot.cargo, v.id));
  $('[data-acao="retirar"]', slot.res).addEventListener("click", () => retirarVoto(slot.key));
}

function chaveDoVoto(id) {
  return Object.keys(estado.votos).find((k) => estado.votos[k].id === id);
}

function retirarVoto(chave) {
  delete estado.votos[chave];
  const slot = slots.find((s) => s.key === chave);
  if (slot) {
    slot.req++;
    slot.input.value = "";
    slot.input.classList.remove("texto");
    mostrar(slot, "vazio", "Ainda não escolhido.");
  }
  salvar();
}

// Atualiza a situação da candidatura (ex.: um recurso julgado) sem atrapalhar a tela.
async function atualizarEmSegundoPlano(slot, voto) {
  try {
    const d = await api(`/api/buscar?uf=${ufConsulta(slot.cargo)}&cargo=${slot.cargo}&numero=${voto.numero}`);
    const c = d.candidatos.find((x) => x.id === voto.id);
    if (c && estado.votos[slot.key] === voto && c.situacao !== voto.situacao) {
      voto.situacao = c.situacao;
      mostrarVoto(slot);
      salvar();
    }
  } catch { /* sem internet: fica com o que já estava salvo */ }
}

// ---------- peças usadas pela ficha (ficha.js) e pela ficha da empresa (empresa.js) ----------

function htmlTemas(temas, destaques) {
  const d = new Set((destaques || []).map((t) => t[0]));
  const chips = (temas || []).map(([t, n]) => `<span class="chip${d.has(t) ? " destaque" : ""}">${esc(t)}: ${n}</span>`).join("");
  const extras = (destaques || []).filter(([t]) => !(temas || []).some(([x]) => x === t))
    .map(([t, n]) => `<span class="chip destaque">${esc(t)}: ${n}</span>`).join("");
  return `<div class="chips">${chips}${extras}</div>`;
}

const ETAPAS = [
  ["lei", "Viraram lei"],
  ["aprovada", "Aprovados na Câmara e enviados ao Senado ou à sanção"],
  ["pronta", "Prontos para votação no plenário"],
  ["analise", "Em análise nas comissões"],
  ["anexada", "Anexados a outro projeto parecido"],
  ["arquivada", "Arquivados, retirados ou devolvidos"],
];

const ALTERACOES = {
  original: ["Texto do autor", "Aprovado com o texto apresentado pelo autor."],
  emendas: ["Com ajustes", "Aprovado com emendas pontuais ao texto."],
  substitutivo: ["Reescrito", "Aprovado num texto reescrito pelo relator, que muitas vezes junta projetos parecidos."],
};

// ---------- análise dos gastos ----------

const NIVEL_CHIP = { alerta: "bad", atencao: "warn", info: "", ok: "ok" };

function chipsSinais(sinais) {
  return (sinais || []).map((x) =>
    `<span class="badge ${NIVEL_CHIP[x.nivel] || ""}" title="${esc(x.detalhe)}">${esc(x.titulo)}</span>`).join(" ");
}

function textoRede(r) {
  let texto = `${numero.format(r.candidatos)} ${r.candidatos === 1 ? "campanha" : "campanhas"}`;
  if (r.partidos > 1) texto += ` de ${r.partidos} partidos`;
  if (r.ufs > 1) texto += ` em ${r.ufs} estados`;
  return texto;
}

function textoHistorico(r) {
  return r.em2022 ? `${numero.format(r.em2022.candidatos)} ${r.em2022.candidatos === 1 ? "campanha" : "campanhas"}` : "estreante";
}

function linhaComparacao(item) {
  const pc = (v) => `${Math.min(v, 1) * 100}%`;
  return `<div class="comparacao" title="${esc(item.categoria)}: ${pct.format(item.parte)} nesta campanha e ${pct.format(item.medianaPares)} numa campanha típica">
    <span class="nome">${esc(item.categoria)}</span>
    <span class="trilho"><span class="cheio" style="width:${pc(item.parte)}"></span><span class="marca" style="left:${pc(item.medianaPares)}"></span></span>
    <span class="valor">${pct.format(item.parte)} <small>típico: ${pct.format(item.medianaPares)}</small></span>
  </div>`;
}

function barras(itens, total, formato = (v) => brl.format(v)) {
  const max = Math.max(...itens.map((i) => i.valor), 1);
  return `<div class="barras">${itens.map((i) => {
    const parte = total ? ` (${pct.format(i.valor / total)})` : "";
    return `<div class="barra" title="${esc(i.nome)}: ${esc(formato(i.valor))}${esc(parte)}">
      <span class="nome">${esc(i.nome)}</span>
      <span class="trilho"><span class="cheio" style="display:block;width:${(i.valor / max) * 100}%"></span></span>
      <span class="valor">${esc(formato(i.valor))}</span>
    </div>`;
  }).join("")}</div>`;
}

// ---------- ajuda para decidir (o conteúdo de cada passo de cargo da jornada) ----------

const brlCompacto = new Intl.NumberFormat("pt-BR", {
  style: "currency", currency: "BRL", notation: "compact", maximumFractionDigits: 1,
});
const numero = new Intl.NumberFormat("pt-BR");

const ajuda = { cargo: 6, grupo: null };

function cargosAjuda() {
  const distrital = estado.uf === "DF";
  return [
    { cargo: 6, rotulo: "Deputado(a) Federal", slot: "dep_federal", proporcional: true },
    {
      cargo: distrital ? 8 : 7, slot: "dep_estadual", proporcional: true,
      rotulo: distrital ? "Deputado(a) Distrital" : "Deputado(a) Estadual",
    },
    { cargo: 5, rotulo: "Senado", slot: "senador_1" },
    { cargo: 3, rotulo: "Governo do estado", slot: "governador" },
    { cargo: 1, rotulo: "Presidência", slot: "presidente" },
  ];
}

// Teste com a eleição de 2022 em SP e MG: quantos de cada faixa de fato se elegeram.
const CHANCE_EM_2022 = {
  Alta: "cerca de 7 em cada 10",
  Disputada: "cerca de 3 em cada 10",
  Baixa: "cerca de 1 em cada 10",
  "Muito baixa": "cerca de 1 em cada 100",
};

function classeChance(chance) {
  return {
    Alta: "alta", Disputada: "disputada", Baixa: "baixa", "Muito baixa": "muito-baixa",
  }[chance] || "problema";
}

// Desenha o conteúdo do cargo em ajuda.cargo (quem escolhe o cargo é a jornada).
// Com manter = true (ex.: depois de pôr alguém na cédula), redesenha sem apagar a tela nem voltar ao topo.
function montarAjuda(manter = false) {
  const itens = cargosAjuda();
  if (!itens.some((i) => i.cargo === ajuda.cargo)) ajuda.cargo = 6;
  const item = itens.find((i) => i.cargo === ajuda.cargo);
  if (item.proporcional) carregarProporcional(item, manter);
  else carregarMajoritario(item, false, manter);
}

// Guarda onde a pessoa estava na página; a função devolvida volta para lá depois de redesenhar.
function guardarRolagem() {
  const y = window.scrollY;
  return () => window.scrollTo({ top: y, behavior: "instant" });
}

function htmlMetodo(p) {
  const v = p.validacao2022;
  const acertos = v.vagas - v.vagasDiferentes;
  const semPar = p.semCorrespondente.length
    ? `<p>Alguns partidos que disputaram em 2022 não concorrem agora e ficaram de fora da conta: ${p.semCorrespondente.map((x) =>
      `${esc(x.partido)}, com ${numero.format(x.votos)} votos`).join("; ")}.</p>` : "";
  return `<details class="metodo"><summary>Como a estimativa é feita</summary>
    <p>Primeiro, somamos os votos que cada partido teve para este cargo no estado em 2022, contando os votos nos candidatos e na legenda, e juntamos esses partidos nas federações de 2026. Também levamos em conta as fusões: PTB e Patriota viraram PRD, PSC e Podemos se uniram no Podemos, e o PROS entrou no Solidariedade.</p>
    <p>Depois, distribuímos as vagas pelas regras do sistema proporcional. Aqui, cada vaga custa cerca de ${numero.format(p.quociente)} votos, e as vagas que sobram vão para as listas com a maior média de votos.</p>
    <p>Por fim, ordenamos os candidatos de cada lista por uma força de 0 a 100. Metade dela vem da maior votação recente da pessoa, a de deputado em 2022 ou a de vereador ou prefeito em 2024, e metade do dinheiro arrecadado em 2026, sempre em comparação com o melhor da mesma lista. Incluir a votação municipal foi testado com a eleição de 2022 em SP e MG: a ordem passou a acertar 211 dos 294 eleitos, contra 204 usando só os votos de deputado, porque quem vem de câmara municipal ou prefeitura deixa de aparecer só pelo dinheiro.</p>
    <p>Quando aplicamos o cálculo das vagas à eleição de 2022, ele acertou <strong>${acertos} das ${v.vagas}</strong> vagas deste cargo no estado. Já a ordem dentro de cada lista é bem mais incerta: testando com 2022 em São Paulo e Minas, cerca de 7 em cada 10 eleitos estavam entre os primeiros da estimativa. Entre quem ficou na faixa "Alta", uns 7 em cada 10 se elegeram. Na faixa "Disputada", só uns 3 em cada 10, o que mostra que perto da linha de corte a disputa é praticamente aberta.</p>
    <p>A conta não usa pesquisas, e quem vem de eleição municipal ou de fora da política aparece só pelo dinheiro arrecadado. Como esse dinheiro ainda muda até o fim da campanha, a estimativa de 2026 tende a ser um pouco menos precisa que a do teste, que usou os valores finais de 2022.</p>
    ${semPar}
  </details>`;
}

// Senado, Governo e Presidência: poucos candidatos, então cada um ganha um cartão com foto e resumo.
// O resumo (ficha do TSE) e os pontos para conferir (análise completa) chegam depois, cartão a cartão.
const resumoMajoritario = new Map();
// Ordem e filtro dos cartões (ficam guardados neste navegador).
const filtroMaj = (() => {
  try { return { ordem: "nome", minimo: 0, ...JSON.parse(localStorage.getItem("filtroMaj") || "{}") }; }
  catch { return { ordem: "nome", minimo: 0 }; }
})();

async function carregarMajoritario(item, reordenado = false, manter = false) {
  const corpo = $("#ajuda-corpo");
  const voltar = manter ? guardarRolagem() : null;
  if (!manter) corpo.innerHTML = `<p class="carregando">Buscando candidatos…</p>`;
  let lista;
  try {
    lista = (await api(`/api/candidatos?uf=${ufConsulta(item.cargo)}&cargo=${item.cargo}`)).candidatos;
  } catch (e) {
    corpo.innerHTML = `<p class="carregando aviso">${esc(e.message)}</p>`;
    return;
  }
  const comAfinidade = await afinidadePronta();
  if (ajuda.cargo !== item.cargo) return;
  const escolhidos = new Set(Object.values(estado.votos).map((v) => v.id));
  // A mesma pessoa pode ter mais de um registro (um deles com pedido não conhecido): fica o válido.
  const porPessoa = new Map();
  for (const c of lista) {
    const chave = `${c.nomeCompleto || c.nomeUrna}|${c.numero}`;
    const atual = porPessoa.get(chave);
    if (!atual || (!candidaturaValida(atual) && candidaturaValida(c))) porPessoa.set(chave, c);
  }
  lista = [...porPessoa.values()].sort((a, b) => a.nomeUrna.localeCompare(b.nomeUrna, "pt-BR"));
  let validos = lista.filter((c) => candidaturaValida(c) || escolhidos.has(c.id));
  const comProblema = lista.filter((c) => !validos.includes(c));
  const total = validos.length;
  const uf = ufConsulta(item.cargo);
  if (comAfinidade) {
    const af = (c) => afinidadePartidos(blocoDoPartido(c.partido));
    if (filtroMaj.minimo) validos = validos.filter((c) => escolhidos.has(c.id) || (af(c) && pctAfinidade(af(c)) >= filtroMaj.minimo));
    if (filtroMaj.ordem === "afinidade") validos.sort((a, b) => notaAfinidade(af(b)) - notaAfinidade(af(a)));
  }
  // Ordem pela nota geral: usa as análises já carregadas; quem ainda não tem nota vai para o fim e,
  // quando todas chegam, a tela é redesenhada na ordem certa (ver preencherResumos).
  const integ = (c) => resumoMajoritario.get(`a-${uf}-${item.cargo}-${c.id}`)?.pontuacao?.nota;
  let faltaNota = false;
  if (filtroMaj.ordem === "integridade") {
    faltaNota = validos.some((c) => integ(c) == null);
    validos.sort((a, b) => (integ(b) ?? -1) - (integ(a) ?? -1));
  }
  const vice = { 1: "Vice", 3: "Vice", 5: "Suplentes" }[item.cargo] || "Vice";

  const cartao = (c) => {
    const valida = candidaturaValida(c);
    const meu = escolhidos.has(c.id);
    const af = comAfinidade ? afinidadePartidos(blocoDoPartido(c.partido)) : null;
    const acao = meu
      ? `<button type="button" class="btn" data-retirar="${c.id}">Retirar da cédula</button>`
      : valida ? `<button type="button" class="btn primario" data-cedula="${c.id}">Pôr na cédula</button>` : "";
    return `<article class="maj-card${meu ? " escolhido" : ""}${valida ? "" : " invalido"}" data-maj="${c.id}">
      <header class="maj-cab">
        ${fotoHtml(uf, c.id, c.nomeUrna, "foto maj-foto")}
        <div class="maj-id">
          <h4><button type="button" class="link-btn" data-ficha="${c.id}">${esc(nomeProprio(c.nomeUrna))}</button></h4>
          <p class="maj-partido">${esc(c.partido)}${c.coligacao && c.coligacao !== c.partido ? `, ${esc(agremiacao(c.coligacao))}` : ""}</p>
          <div class="cand-badges">${(c.situacao || "").toLowerCase() === "deferido" ? "" : badgeSituacao(c.situacao)}${meu ? `<span class="badge ok">✓ Na sua cédula</span>` : ""}</div>
        </div>
        <span class="maj-num" title="Número na urna">${esc(c.numero)}</span>
      </header>
      ${comAfinidade ? `<div class="maj-afin"><span>Afinidade do partido</span>${celulaAfinidade(af)}</div>` : ""}
      <div class="maj-afin maj-integ" data-integ="${c.id}"><span>Nota geral</span><small class="maj-carregando">calculando…</small></div>
      <dl class="maj-resumo" data-resumo="${c.id}"><div class="maj-carregando">Carregando o resumo…</div></dl>
      <p class="maj-sinais" data-sinais="${c.id}"></p>
      <footer class="maj-rodape">
        <button type="button" class="btn" data-ficha="${c.id}">Ver ficha completa</button>
        ${acao}
      </footer>
    </article>`;
  };

  corpo.innerHTML = `
    <div class="maj-filtros" role="group" aria-label="Ordem e filtro">
      <label>Ordenar por
        <select id="maj-ordem">
          <option value="nome"${filtroMaj.ordem === "nome" ? " selected" : ""}>Nome (A a Z)</option>
          ${comAfinidade ? `<option value="afinidade"${filtroMaj.ordem === "afinidade" ? " selected" : ""}>Maior afinidade com você</option>` : ""}
          <option value="integridade"${filtroMaj.ordem === "integridade" ? " selected" : ""}>Maior nota geral</option>
        </select>
      </label>
      ${faltaNota ? `<span class="maj-filtro-aviso">Calculando as notas; a ordem se ajusta quando terminar.</span>` : ""}
      ${comAfinidade ? `<label>Mostrar
        <select id="maj-minimo">
          <option value="0"${!filtroMaj.minimo ? " selected" : ""}>Todos</option>
          <option value="50"${filtroMaj.minimo === 50 ? " selected" : ""}>Afinidade de 50% ou mais</option>
          <option value="70"${filtroMaj.minimo === 70 ? " selected" : ""}>Afinidade de 70% ou mais</option>
        </select>
      </label>
      ${validos.length < total ? `<span class="maj-filtro-aviso">Partidos sem bancada na Câmara não têm afinidade calculada e ficam de fora deste filtro.</span>` : ""}` : ""}
    </div>
    ${comAfinidade ? "" : `<div class="callout convite-quiz maj-convite"><div><p>Faça o questionário de afinidade para ordenar e filtrar os candidatos pelo quanto o partido de cada um votou como você.</p></div>
      <button type="button" class="btn pequeno primario" data-ir-passo="afinidade">Fazer o questionário</button></div>`}
    <p class="explica maj-intro">${validos.length === total ? `${total} candidatos` : `${validos.length} dos ${total} candidatos`}. A chance de cada um está nas <a href="https://pesqele-divulgacao.tse.jus.br/" target="_blank" rel="noopener">pesquisas registradas no TSE</a>.</p>
    <div class="maj-grade">${validos.map(cartao).join("")}</div>
    ${comProblema.length ? `<details class="metodo maj-problema">
      <summary>${comProblema.length === 1 ? "1 candidatura" : `${comProblema.length} candidaturas`} com o registro negado, cancelado ou não analisado</summary>
      <p class="explica">Algumas ainda podem aparecer na urna enquanto há recurso, mas o voto nelas pode ser anulado.</p>
      <div class="maj-grade">${comProblema.map(cartao).join("")}</div>
    </details>` : ""}`;

  const mudarFiltro = (campo, valor) => {
    filtroMaj[campo] = valor;
    try { localStorage.setItem("filtroMaj", JSON.stringify(filtroMaj)); } catch { /* segue sem guardar */ }
    carregarMajoritario(item);
  };
  $("#maj-ordem")?.addEventListener("change", (e) => mudarFiltro("ordem", e.target.value));
  $("#maj-minimo")?.addEventListener("change", (e) => mudarFiltro("minimo", +e.target.value));
  corpo.querySelectorAll("[data-ficha]").forEach((b) =>
    b.addEventListener("click", () => abrirFicha(item.cargo, +b.dataset.ficha)));
  corpo.querySelectorAll("[data-cedula]").forEach((b) => b.addEventListener("click", () => {
    const c = lista.find((x) => x.id === +b.dataset.cedula);
    let chave = item.slot;
    if (item.cargo === 5 && estado.votos.senador_1) chave = "senador_2";
    escolher(slots.find((s) => s.key === chave), c);
    carregarMajoritario(item, false, true);
  }));
  corpo.querySelectorAll("[data-retirar]").forEach((b) => b.addEventListener("click", () => {
    retirarVoto(chaveDoVoto(+b.dataset.retirar));
    carregarMajoritario(item, false, true);
  }));
  voltar?.();
  preencherResumos(item, uf, validos.concat(comProblema), vice).then(() => {
    if (faltaNota && !reordenado && filtroMaj.ordem === "integridade" && ajuda.cargo === item.cargo) carregarMajoritario(item, true, true);
  });
}

// ---------- aviso sobre as estimativas ----------

// Vai em toda tela que mostra vagas, ordem ou chance de deputados: é estimativa, não pesquisa nem previsão.
function htmlAvisoEstimativa(extra = "") {
  return `<p class="aviso-estimativa"><strong>Estimativa, não previsão.</strong> As vagas de cada lista, a ordem dos candidatos e as faixas de chance são calculadas com os votos de 2022 e 2024 e o dinheiro declarado em 2026. Não são pesquisa eleitoral nem resultado, e o resultado real pode ser bem diferente.${extra} <button type="button" class="link-btn" data-abrir-sobre="metodologia">Como é calculado</button></p>`;
}

// ---------- notas: o mesmo formato em todo o site ----------

// "Nota geral" é a nota que aparece nos cartões: a integridade e, para quem tem mandato de deputado, o desempenho.
// Ao abrir a ficha ou a lista, aparecem as três (geral, integridade e desempenho), sempre nesta mesma linha.
const EXPLICA_NOTA_GERAL = "Nota geral, de 0 a 100: junta a integridade (começa em 100 e perde pontos por indício encontrado nos dados públicos) e, para quem já é deputado, o desempenho no mandato.";

// Cor da nota geral, igual em todo o site (barra e anel em volta da foto): verde sem nada relevante, amarelo com
// algo para conferir (um aviso tira 20 pontos) e vermelho com alerta sério ou vários avisos somados.
function nivelNota(nota) {
  if (nota == null) return null;
  return nota >= 85 ? "ok" : nota >= 60 ? "conferir" : "serio";
}

function celulaNota(valor, titulo = "") {
  const n = Math.round(valor);
  const nivel = nivelNota(n);
  return `<span class="afin-mini integ-${nivel}" title="${esc(titulo)}">
    <span class="trilho"><span class="cheio" style="width:${Math.max(n, 2)}%"></span></span><b>${n}<small>/100</small></b></span>`;
}

function linhaNota(rotulo, valor, { titulo = "", vazio = "Sem dados", attrs = "" } = {}) {
  return `<div class="maj-afin" ${attrs}><span>${rotulo}</span>${valor == null
    ? `<small class="sem-afinidade">${esc(vazio)}</small>` : celulaNota(valor, titulo)}</div>`;
}

// Cor do anel da foto e da barra de integridade, igual em todas as telas: vermelho com alerta sério ou integridade
// abaixo de 50 (vários pontos para conferir somam tanto quanto um alerta); amarelo com algo para conferir; verde sem nada.
function nivelAnel(alertas, atencoes, integridade) {
  if (alertas || (integridade != null && integridade < 50)) return "serio";
  return atencoes ? "conferir" : "ok";
}

function nivelIntegridade(a) {
  const fortes = (a?.sinais || []).filter((s) => ["alerta", "atencao"].includes(s.nivel) && s.categoria !== "mandato");
  return nivelAnel(fortes.filter((s) => s.nivel === "alerta").length, fortes.length, a?.pontuacao?.integridade);
}

function pintarIntegridade(card, a) {
  if (!card) return;
  const cel = card.querySelector("[data-integ]");
  const nota = a?.pontuacao?.nota;
  if (nota == null) {
    cel?.remove();
    return;
  }
  card.querySelector(".maj-foto")?.classList.add(`anel-${nivelNota(nota)}`);
  if (cel) cel.innerHTML = `<span>Nota geral</span>${celulaNota(nota, `${EXPLICA_NOTA_GERAL} A ficha mostra as duas partes.`)}`;
}

async function preencherResumos(item, uf, lista, rotuloVice) {
  const alvo = (sel) => $(`#ajuda-corpo ${sel}`);
  const htmlResumo = (f) => {
    const anos = idade(f.nascimento);
    const ct = f.contas;
    const publico = ct && ct.totalRecebido ? (ct.fundoEleitoral + ct.fundoPartidario) / ct.totalRecebido : null;
    const vistos = new Set([f.nomeUrna]);
    const vices = (f.vices || []).filter((v) => !vistos.has(v.nomeUrna) && vistos.add(v.nomeUrna))
      .map((v) => `${esc(nomeProprio(v.nomeUrna))} <small>(${esc(v.partido)})</small>`).join("<br>");
    const itens = [
      ["Idade", anos != null ? `${anos} anos` : "—"],
      ["Profissão", esc(f.ocupacao || "—")],
      ["Escolaridade", esc(f.instrucao || "—")],
      ["Patrimônio declarado", f.totalBens != null ? brlCompacto.format(+f.totalBens) : "—"],
      ["Campanha arrecadou", ct ? `${brlCompacto.format(ct.totalRecebido || 0)}${publico != null ? ` <small>(${pct.format(publico)} público)</small>` : ""}` : "Sem prestação de contas ainda"],
      [rotuloVice, vices || "—"],
    ];
    return itens.map(([k, v]) => `<div><dt>${k}</dt><dd>${v}</dd></div>`).join("");
  };
  const htmlSinais = (a) => {
    const fortes = (a.sinais || []).filter((s) => ["alerta", "atencao"].includes(s.nivel) && s.categoria !== "mandato");
    const serios = fortes.filter((s) => s.nivel === "alerta").length;
    if (!fortes.length) return `<span class="badge ok">✓ Nada para conferir</span>`;
    const rotulo = serios
      ? `${serios} ${serios === 1 ? "alerta sério" : "alertas sérios"}`
      : `${fortes.length} ${fortes.length === 1 ? "ponto" : "pontos"} para conferir`;
    return `<span class="badge ${serios ? "bad" : "warn"}">${rotulo}</span>
      <small>${esc([...new Set(fortes.map((s) => s.titulo.split(":")[0]))].slice(0, 2).join("; "))}</small>`;
  };
  // Resumos primeiro (rápidos); depois a análise completa, de dois em dois, para não pesar no servidor.
  await Promise.all(lista.map(async (c) => {
    const chave = `${uf}-${item.cargo}-${c.id}`;
    let r = resumoMajoritario.get(chave);
    if (!r) {
      try { r = await api(`/api/ficha?uf=${uf}&cargo=${item.cargo}&id=${c.id}`); resumoMajoritario.set(chave, r); } catch { r = null; }
    }
    const el = alvo(`[data-resumo="${c.id}"]`);
    if (el) el.innerHTML = r ? htmlResumo(r) : `<div class="maj-carregando">Resumo indisponível agora.</div>`;
  }));
  const fila = [...lista];
  const trabalhar = async () => {
    for (let c = fila.shift(); c; c = fila.shift()) {
      if (ajuda.cargo !== item.cargo) return;
      const chave = `a-${uf}-${item.cargo}-${c.id}`;
      const el = alvo(`[data-sinais="${c.id}"]`);
      if (!el) return;
      let a = resumoMajoritario.get(chave);
      if (!a) {
        el.innerHTML = `<small class="maj-carregando">Conferindo alertas…</small>`;
        try { a = await api(`/api/analise?uf=${uf}&cargo=${item.cargo}&id=${c.id}`); resumoMajoritario.set(chave, a); } catch { a = null; }
      }
      const agora = alvo(`[data-sinais="${c.id}"]`);
      if (agora) agora.innerHTML = a ? htmlSinais(a) : "";
      pintarIntegridade(alvo(`[data-maj="${c.id}"]`), a);
    }
  };
  await Promise.all([trabalhar(), trabalhar()]);
}

function candidaturaValida(c) {
  const s = (c.situacao || "").toLowerCase();
  return !(s.includes("indeferido") || s.includes("cancel") || s.includes("renúncia") || s.includes("falec")
    || s.includes("não conhecido"));
}

// ---------- checagem de sanções ----------

// Os cadastros de punidos vêm dos arquivos abertos da CGU, baixados pelo servidor uma vez por dia (sancoes.py);
// não precisa de chave.
async function montarPortal() {
  const alvo = $("#ajuda-portal");
  let cfg;
  try { cfg = await api("/api/config"); } catch { return; }
  const s = cfg.sancoes || {};
  alvo.innerHTML = `<div class="cartao">
    <h3>Checagem de sanções</h3>
    <p class="explica">A ficha de cada candidato confere se ele ou as empresas que trabalharam na campanha aparecem nos cadastros nacionais de punidos: empresas e pessoas proibidas de contratar com o governo (CEIS), empresas punidas pela Lei Anticorrupção (CNEP) e servidores expulsos da administração federal (CEAF).</p>
    <p>${s.pronto
      ? `<span class="badge ok">✓ Ligada</span> Cadastros da CGU atualizados em ${esc(s.geradoEm)}.`
      : `<span class="badge">Preparando</span> Os cadastros da CGU estão sendo baixados; em alguns instantes a checagem liga sozinha.`}</p>
  </div>`;
}

// O questionário de afinidade fica em quiz.js.

// ---------- cola para imprimir ----------

function imprimirCola() {
  const linhas = slots.map((s) => {
    const v = estado.votos[s.key];
    const quem = !v ? "" : v.tipo === "legenda" ? `Legenda ${v.partido}` : `${nomeProprio(v.nomeUrna)} (${v.partido})`;
    return `<tr><td>${esc(s.rotulo)}</td><td class="numero">${esc(v?.numero || "")}</td><td>${esc(quem)}</td></tr>`;
  }).join("");
  $("#cola").innerHTML = `<h1>Minha cola para o 1º turno, 4 de outubro de 2026 (${esc(UFS[estado.uf] || estado.uf)})</h1>
    <table>${linhas}</table>
    <p>A ordem acima é a mesma da urna. Leve um documento com foto ou o e-Título, e lembre que o celular não pode entrar na cabine.</p>`;
  window.print();
}

// ---------- início ----------

async function iniciar() {
  atualizarContagem();
  const sel = $("#uf");
  for (const [sigla, nome] of Object.entries(UFS)) sel.add(new Option(`${nome} (${sigla})`, sigla));

  try {
    const m = await api("/api/login");
    modoApp.publico = !!m.publico;
  } catch { /* segue no modo pessoal */ }
  if (modoApp.publico) {
    $("#sair").hidden = true;
    $("#aviso-dados").textContent = "Sua cédula e suas respostas ficam guardadas só neste aparelho. Nada disso é enviado ao servidor.";
  }

  try {
    const salvo = modoApp.publico ? lerCedulaLocal() : await api("/api/cedula");
    if (salvo && salvo.uf) {
      estado.uf = salvo.uf;
      estado.votos = salvo.votos || {};
      estado.quiz = salvo.quiz || {};
      estado.guiaVisto = !!salvo.guiaVisto;
      sel.value = estado.uf;
      aquecerEstado(estado.uf);
      montarCedula();
    }
  } catch { /* primeira vez */ }

  sel.addEventListener("change", () => {
    if (!trocarUf(sel.value)) sel.value = estado.uf;
  });

  $("#imprimir").addEventListener("click", imprimirCola);
  $("#sair").addEventListener("click", async () => {
    await fetch("/api/sair", { method: "POST" }).catch(() => {});
    location.reload();
  });
  iniciarJornada();
}

// Troca o estado da cédula. Devolve false se a pessoa desistir para não perder os votos.
function trocarUf(uf) {
  if (uf === estado.uf) return true;
  const tinhaVotos = Object.keys(estado.votos).length > 0;
  if (tinhaVotos && !confirm("Trocar de estado apaga a cédula atual. Continuar?")) return false;
  estado.uf = uf;
  estado.votos = {};
  ajuda.grupo = null;
  aquecerEstado(uf);
  $("#uf").value = uf;
  if (estado.uf) montarCedula();
  else { $("#cedula").hidden = true; $("#futuro").hidden = true; $("#jornada").hidden = true; }
  salvar();
  return true;
}

// Espera todos os scripts (jornada.js, ficha.js...) carregarem antes de começar.
document.addEventListener("DOMContentLoaded", iniciar);
