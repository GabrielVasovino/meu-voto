"use strict";

// Tela de deputados: um cartão por lista (federação ou partido), com as vagas, quem as
// ocuparia e quem está na disputa. Clicar em "Ver os candidatos" abre a lista completa.

let listasAtual = null;
let perfisAtual = null;

// Como o usuário quer ver as vagas: por lista ou por pessoa, e em que ordem. Fica guardado neste navegador.
const visaoListas = (() => {
  try {
    return { modo: "grupo", ordem: "padrao", ...JSON.parse(localStorage.getItem("visaoListas") || "{}") };
  } catch {
    return { modo: "grupo", ordem: "padrao" };
  }
})();

function guardarVisao() {
  try { localStorage.setItem("visaoListas", JSON.stringify(visaoListas)); } catch { /* sem armazenamento, segue sem guardar */ }
}

function faixaDisputa(vagas) {
  return Math.max(2, Math.round(vagas * 0.25));
}

function margemLista(g) {
  const rel = (v) => (g.votos2022 ? v / g.votos2022 : 1);
  if (g.faltamParaMaisUma == null) return { texto: "", tag: "" };
  const perto = rel(g.faltamParaMaisUma) < 0.05;
  const ameacada = g.vagas && g.folgaDaUltima != null && rel(g.folgaDaUltima) < 0.05;
  let texto = `Com uns ${brlNumeroCurto(g.faltamParaMaisUma)} votos a mais, ganharia outra vaga.`;
  if (g.vagas && g.folgaDaUltima != null) texto += ` A última está garantida por uma folga de ${brlNumeroCurto(g.folgaDaUltima)}.`;
  let tag = "";
  if (ameacada) tag = `<span class="leitura-tag tom-atencao">Última vaga apertada</span>`;
  else if (perto) tag = `<span class="leitura-tag tom-info">Perto de ganhar uma vaga</span>`;
  return { texto, tag };
}

const numeroCurto = new Intl.NumberFormat("pt-BR", { notation: "compact", maximumFractionDigits: 1 });
function brlNumeroCurto(v) { return numeroCurto.format(v); }

function htmlComoFunciona(p, item) {
  return `<ol class="como-funciona">
    <li><span class="passo">1</span><div><strong>O voto vai para a lista</strong><span>A lista é a federação ou o partido do candidato. Votar só no número do partido também conta.</span></div></li>
    <li><span class="passo">2</span><div><strong>A lista ganha vagas</strong><span>Quanto mais votos, mais vagas. O estado tem ${p.vagas} vagas de ${esc(item.rotulo.toLowerCase())}.</span></div></li>
    <li><span class="passo">3</span><div><strong>Os mais votados entram</strong><span>Dentro de cada lista, as vagas ficam com quem teve mais votos.</span></div></li>
  </ol>`;
}

function rosto(c, meuId) {
  const x = afinidadePessoa(c.id);
  const afin = x ? ` ${textoAfinidadePessoa(c.id)}.` : "";
  return `<button type="button" class="rosto${c.id === meuId ? " meu" : ""}" data-ficha-lista="${c.id}" data-pessoa="${c.id}" title="${esc(nomeProprio(c.nomeUrna))}, em ${c.posicao}º lugar.${afin} Clique para abrir a ficha.">
    ${x ? `<span class="rosto-afin" aria-hidden="true">${pctAfinidade(x)}%</span>` : ""}
    ${fotoHtml(estado.uf, c.id, c.nomeUrna, "foto rosto-foto")}
    <span class="rosto-nome">${esc(nomeProprio(c.nomeUrna))}</span>
  </button>`;
}

// Afinidade da lista com o questionário, na mesma linha usada nos cartões de Senado, Governo e Presidência.
function linhaAfinidadeLista(g) {
  if (respostasQuiz() < 3 || !quizDados) return "";
  return `<div class="maj-afin"><span>Afinidade ${g.partidos.length > 1 ? "da federação" : "do partido"}</span>${celulaAfinidade(afinidadePartidos(g.partidos))}</div>`;
}

// Nota da lista: média de quem entraria, ajustada para lista pequena (uma pessoa só não decide a nota).
function rotuloNotaLista(g) {
  return `Nota geral ${g.partidos.length > 1 ? "da federação" : "do partido"}`;
}

function explicaNotaLista(ind) {
  return `Média da nota geral de quem entraria. Numa lista pequena, a média é puxada para a de todas as listas${indicadoresAtual?.mediaGeral != null ? ` (${indicadoresAtual.mediaGeral})` : ""}, para uma pessoa só não decidir a nota. ${EXPLICA_NOTA_GERAL}`;
}

function htmlListaCartao(g, item) {
  const voto = estado.votos[item.slot];
  const minha = voto && voto.coligacao === g.id;
  const partidos = g.partidos.length > 1 ? `<div class="lista-partidos">${g.partidos.map((s) => `<span class="chip">${esc(s)}</span>`).join("")}</div>` : "";
  const mostrar = 12;
  const rostos = g.eleitos.slice(0, mostrar).map((c) => rosto(c, voto?.id)).join("");
  const mais = g.eleitos.length > mostrar
    ? `<button type="button" class="rosto rosto-mais" data-abrir-lista="${esc(g.id)}">+${g.eleitos.length - mostrar}</button>` : "";
  const disputa = g.disputa.length ? `<p class="lista-rot">Na disputa pela última vaga</p>
    <div class="chips">${g.disputa.map((c) => `<button type="button" class="chip chip-botao${voto?.id === c.id ? " destaque" : ""}" data-ficha-lista="${c.id}">${c.posicao}º ${esc(nomeProprio(c.nomeUrna))}</button>`).join("")}</div>` : "";
  return `<article class="lista-card clicavel${minha ? " minha" : ""}" data-abrir-lista="${esc(g.id)}" tabindex="0" role="button"
      aria-label="Abrir a lista ${esc(agremiacao(g.id))}: todos os candidatos e a análise de quem ocuparia as vagas">
    <header class="lista-cab">
      <div class="lista-nome">
        <h3>${esc(agremiacao(g.id))}</h3>
        ${partidos}
        ${minha ? `<span class="badge ok">✓ Seu voto está nesta lista</span>` : ""}
      </div>
      <div class="lista-numeros">
        <div class="lista-num" title="Vagas que a lista teria se os votos de 2022 se repetissem"><strong>${g.vagas}</strong><span>${g.vagas === 1 ? "vaga" : "vagas"}</span></div>
      </div>
    </header>
    ${linhaAfinidadeLista(g)}
    <div class="maj-afin" data-nota-lista="${esc(g.id)}"><span>${rotuloNotaLista(g)}</span><small class="maj-carregando">calculando…</small></div>
    <p class="lista-rot">Quem ocuparia as vagas</p>
    <div class="rostos">${rostos}${mais}</div>
    ${disputa}
    <p class="lista-abrir">Toque para ver os ${g.aptos} candidatos e a análise de quem entraria <span aria-hidden="true">›</span></p>
  </article>`;
}

function htmlListaSemVaga(g, item) {
  const voto = estado.votos[item.slot];
  const minha = voto && voto.coligacao === g.id;
  const m = margemLista(g);
  return `<article class="lista-card compacta${minha ? " minha" : ""}">
    <header class="lista-cab"><div><h3>${esc(agremiacao(g.id))}</h3>
      <small>Teve ${pct.format(g.percentual)} dos votos em 2022 e precisaria de mais uns ${brlNumeroCurto(g.faltamParaMaisUma || 0)} para eleger alguém.</small></div>
      <button type="button" class="btn pequeno" data-abrir-lista="${esc(g.id)}">Ver os ${g.aptos}</button></header>
    ${minha ? `<p class="lista-minha">✓ Seu voto está nesta lista</p>` : ""}
    ${linhaAfinidadeLista(g)}
    ${g.maisFortes.length ? `<p class="lista-rot">Mais bem colocados: ${listaNatural(g.maisFortes.map((c) => esc(nomeProprio(c.nomeUrna))))}</p>` : ""}
    ${m.tag}
  </article>`;
}

async function carregarProporcional(item, manter = false) {
  const corpo = $("#ajuda-corpo");
  const voltar = manter && listasAtual ? guardarRolagem() : null;
  // Numa nova tentativa, a lista de passos continua na tela em vez de piscar.
  if (!voltar && !corpo.querySelector(".espera")) corpo.innerHTML = `<p class="carregando">Montando as listas com os votos de 2022…</p>`;
  let p;
  try {
    // A afinidade do questionário (se respondido) é carregada junto, para os cartões já nascerem com ela.
    [p] = await Promise.all([api(`/api/listas?uf=${estado.uf}&cargo=${item.cargo}`), afinidadePronta()]);
  } catch (e) {
    corpo.innerHTML = `<p class="carregando aviso">${esc(e.message)}</p>`;
    return;
  }
  if (ajuda.cargo !== item.cargo) return;
  if (p.preparando) {
    // Servidor novo: a base de 2022 deste estado ainda está sendo montada. Pergunta de novo em alguns segundos.
    corpo.innerHTML = htmlEsperaListas(p);
    setTimeout(() => { if (ajuda.cargo === item.cargo && !$("#aba-ajuda").hidden) carregarProporcional(item); }, 4000);
    return;
  }
  fimEspera(`listas-${estado.uf}`);
  listasAtual = { p, item };
  desenharListas();
  voltar?.();
}

// Balão de informação: um botão pequeno que abre a explicação por cima, sem empurrar a tela.
function balao(titulo, html) {
  return `<details class="info-balao"><summary>${titulo}</summary><div class="info-balao-corpo">${html}</div></details>`;
}

function desenharListas() {
  const { p, item } = listasAtual;
  const corpo = $("#ajuda-corpo");
  const semVaga = p.grupos.filter((g) => g.vagas === 0);
  const metodo = htmlMetodo(p).replace(/^\s*<details[^>]*>\s*<summary>[^<]*<\/summary>/, "").replace(/<\/details>\s*$/, "");
  const comQuiz = respostasQuiz() >= 3 && quizDados;
  corpo.innerHTML = `
    ${p.semDinheiro ? `<div class="callout"><p>Os valores arrecadados pelas campanhas ainda estão sendo carregados, então por enquanto a ordem dentro de cada lista usa só as votações de 2022 e 2024. Volte em alguns minutos para ver a estimativa completa.</p></div>` : ""}
    <div class="listas-barra">
      <div class="segmentado" role="group" aria-label="Como ver as vagas">
        <button type="button" data-visao="grupo" aria-pressed="${visaoListas.modo === "grupo"}">Por lista</button>
        <button type="button" data-visao="pessoa" aria-pressed="${visaoListas.modo === "pessoa"}">Por pessoa</button>
      </div>
      <label class="visao-ordem">Ordenar por
        <select id="visao-ordem">
          <option value="padrao"${visaoListas.ordem === "padrao" ? " selected" : ""}>${visaoListas.modo === "pessoa" ? "Posição na lista" : "Número de vagas"}</option>
          ${comQuiz ? `<option value="afinidade"${visaoListas.ordem === "afinidade" ? " selected" : ""}>Maior afinidade com você</option>` : ""}
          <option value="maior"${visaoListas.ordem === "maior" ? " selected" : ""}>Maior nota geral</option>
          <option value="menor"${visaoListas.ordem === "menor" ? " selected" : ""}>Menor nota geral</option>
        </select>
      </label>
      <div class="busca-listas">
        <input type="search" id="busca-lista" autocomplete="off" placeholder="Procurar candidato por nome ou número" aria-label="Procurar candidato">
        <div id="busca-lista-resultado" class="busca-resultado" aria-live="polite"></div>
      </div>
    </div>
    ${htmlAvisoEstimativa()}
    <div class="listas-info">
      ${balao("Como o voto vira vaga", `${htmlComoFunciona(p, item)}
        <p>Os cartões mostram como ficariam as ${p.vagas} vagas se os votos de 2022 se repetissem com as federações de 2026. Toque numa pessoa para abrir a ficha, ou em "Ver os candidatos" para a lista completa.</p>`)}
      ${balao("Como ler os números", `<ul>
        <li><strong>Vagas</strong> é quantas cadeiras a lista teria se os votos de 2022 se repetissem.</li>
        <li><strong>Nota geral da federação ou do partido</strong> é a média de quem entraria, ajustada: numa lista pequena, a média é puxada para a de todas as listas, porque ali uma só pessoa mudaria tudo. A <strong>nota geral</strong> de cada pessoa junta a <strong>integridade</strong>, que parte de 100 e perde pontos por indício que vale conferir ou alerta sério, e o <strong>desempenho</strong>, que só existe para quem já tem mandato e compara presença, projetos aprovados, relatorias, projetos simbólicos e gastos com os colegas. A posição política não entra, porque isso depende da sua opinião.</li>
        <li>O anel em volta da foto mostra a nota geral da pessoa: verde de 85 para cima, amarelo de 60 a 84 e vermelho abaixo de 60. A etiqueta azul no rosto é a afinidade de quem já é deputado federal com o seu questionário: a porcentagem das votações do questionário em que ele votou como você.</li>
      </ul>
      <p><button type="button" class="link-btn" data-abrir-sobre="metodologia">Ver a metodologia completa</button></p>`)}
      ${balao("Como a estimativa é feita", metodo)}
      ${comQuiz ? "" : `<button type="button" class="link-btn listas-quiz" data-ir-passo="afinidade">Faça o questionário para ordenar por afinidade</button>`}
    </div>
    <div id="listas-visao"></div>
    ${semVaga.length ? `<details class="mais listas-sem-vaga"><summary>Listas que não elegeriam ninguém pela estimativa (${semVaga.length})</summary>
      <div class="listas-grade compacta">${semVaga.map((g) => htmlListaSemVaga(g, item)).join("")}</div></details>` : ""}`;
  desenharVisao();
  carregarIndicadores(item);
  carregarPerfis(item);
  document.querySelectorAll(".listas-barra [data-visao]").forEach((b) => b.addEventListener("click", () => {
    visaoListas.modo = b.dataset.visao;
    guardarVisao();
    desenharListas();
  }));
  $("#visao-ordem").addEventListener("change", (e) => {
    visaoListas.ordem = e.target.value;
    guardarVisao();
    desenharVisao();
  });
  let timer;
  $("#busca-lista").addEventListener("input", (e) => {
    clearTimeout(timer);
    const q = e.target.value.trim();
    const alvo = $("#busca-lista-resultado");
    if (q.length < 2) { alvo.innerHTML = ""; return; }
    timer = setTimeout(async () => {
      const param = /^\d+$/.test(q) ? `numero=${q}` : `q=${encodeURIComponent(q)}`;
      try {
        const d = await api(`/api/buscar?uf=${estado.uf}&cargo=${item.cargo}&${param}`);
        const lista = d.candidatos.slice(0, 8);
        alvo.innerHTML = lista.length ? lista.map((c) => {
          const g = p.grupos.find((x) => x.id === c.coligacao);
          const pos = g && [...g.eleitos, ...g.disputa].find((x) => x.id === c.id);
          const onde = pos ? (pos.posicao <= g.vagas ? "Ocuparia uma vaga" : "Está na disputa") : "Fora das vagas estimadas";
          return `<button type="button" class="resultado-item" data-ficha-lista="${c.id}">
            <strong>${esc(nomeProprio(c.nomeUrna))}</strong> <span>Número ${esc(c.numero)}, ${esc(c.partido)}</span>
            <em>${onde}</em></button>`;
        }).join("") : `<p class="explica">Ninguém encontrado com "${esc(q)}".</p>`;
      } catch (err) {
        alvo.innerHTML = `<p class="erro">${esc(err.message)}</p>`;
      }
    }, 250);
  });
}

// ---------- indicadores de qualidade de cada lista ----------

let indicadoresAtual = null;

function htmlIndicadoresCarregando(progresso) {
  const texto = progresso?.total
    ? `Calculando os indicadores do grupo (${progresso.feitos} de ${progresso.total} pessoas)…`
    : "Calculando os indicadores do grupo…";
  return `<p class="ind-carregando"><span class="giro" aria-hidden="true"></span>${texto}</p>`;
}

function aplicarIndicadores() {
  if (!indicadoresAtual?.pronto) return;
  document.querySelectorAll("[data-nota-lista]").forEach((el) => {
    const ind = indicadoresAtual.grupos?.[el.dataset.notaLista];
    const g = listasAtual?.p.grupos.find((x) => x.id === el.dataset.notaLista);
    if (!g) return;
    el.innerHTML = `<span>${rotuloNotaLista(g)}</span>${ind?.indiceAjustado == null ? `<small class="sem-afinidade">Sem dados</small>` : celulaNota(ind.indiceAjustado, explicaNotaLista(ind))}`;
  });
  document.querySelectorAll(".lista-card[data-abrir-lista]").forEach((el) => {
    const g = indicadoresAtual.grupos?.[el.dataset.abrirLista];
    for (const [id, p] of Object.entries(g?.pessoas || {})) {
      const rosto = el.querySelector(`[data-pessoa="${id}"]`);
      if (!rosto) continue;
      if (p.nota != null) rosto.classList.add(`anel-${nivelNota(p.nota)}`);
      if (p.titulos.length) rosto.title += ` Pontos de atenção: ${p.titulos.join("; ")}.`;
    }
  });
}

function ordenarPorNota(itens, nota, desempate = () => null, afinidade = null) {
  if (visaoListas.ordem === "padrao") return itens;
  if (visaoListas.ordem === "afinidade") {
    // Sem questionário respondido, a opção some; se estava guardada, volta à ordem padrão.
    if (!afinidade || respostasQuiz() < 3 || !quizDados) return itens;
    return [...itens].sort((a, b) => notaAfinidade(afinidade(b)) - notaAfinidade(afinidade(a)));
  }
  const sinal = visaoListas.ordem === "maior" ? -1 : 1;
  // Quem não tem nota vai para o fim nas duas ordens.
  return [...itens].sort((a, b) => {
    const x = nota(a), y = nota(b);
    if (x == null && y == null) return 0;
    if (x == null) return 1;
    if (y == null) return -1;
    return sinal * (x - y) || sinal * ((desempate(a) ?? 50) - (desempate(b) ?? 50));
  });
}

function desenharVisao() {
  const alvo = $("#listas-visao");
  if (!alvo || !listasAtual) return;
  const { p, item } = listasAtual;
  const comVaga = p.grupos.filter((g) => g.vagas > 0);
  const semNotas = !["padrao", "afinidade"].includes(visaoListas.ordem) && !indicadoresAtual?.pronto
    ? `<p class="explica">As notas ainda estão sendo calculadas. A ordem se ajusta sozinha quando terminar.</p>` : "";
  if (visaoListas.modo === "pessoa") {
    alvo.innerHTML = semNotas + htmlVisaoPessoas(comVaga, item);
    return;
  }
  const grupos = ordenarPorNota(comVaga, (g) => indicadoresAtual?.pronto ? indicadoresAtual.grupos?.[g.id]?.indiceAjustado ?? null : null,
    (g) => indicadoresAtual?.grupos?.[g.id]?.integridade, (g) => afinidadePartidos(g.partidos));
  alvo.innerHTML = semNotas + `<div class="listas-grade">${grupos.map((g) => htmlListaCartao(g, item)).join("")}</div>`;
  aplicarIndicadores();
  aplicarPerfis();
}

function htmlVisaoPessoas(grupos, item) {
  const voto = estado.votos[item.slot];
  const pessoas = grupos.flatMap((g) => g.eleitos.map((c) => ({ ...c, grupo: g.id, ind: indicadoresAtual?.grupos?.[g.id]?.pessoas?.[String(c.id)] })));
  // Na visão por pessoa, vale o voto da própria pessoa quando ela já é deputada federal; senão, o do partido.
  const ordenadas = ordenarPorNota(pessoas, (c) => c.ind?.nota, (c) => c.ind?.integridade,
    (c) => afinidadePessoa(c.id) || afinidadePartidos(blocoDoPartido(c.partido)));
  const linhas = ordenadas.map((c) => {
    const i = c.ind;
    const anel = i?.nota == null ? "" : `anel-${nivelNota(i.nota)}`;
    const detalhe = !i ? "Calculando…"
      : `Integridade ${i.integridade ?? "—"}${i.desempenho != null ? `, desempenho ${i.desempenho} como deputado ${i.casa === "estadual" ? "estadual" : "federal"}` : ", sem mandato de deputado"}.${i.titulos.length ? ` ${esc(i.titulos.join("; "))}.` : ""}${textoAfinidadePessoa(c.id) ? ` ${textoAfinidadePessoa(c.id)}.` : ""}`;
    return `<li class="pessoa-linha${voto?.id === c.id ? " meu" : ""}">
      <button type="button" class="pessoa-botao" data-ficha-lista="${c.id}" title="Abrir a ficha">
        <span class="rosto ${anel}">${fotoHtml(estado.uf, c.id, c.nomeUrna, "foto rosto-foto")}</span>
        <span class="pessoa-info">
          <strong>${esc(nomeProprio(c.nomeUrna))}</strong>
          <small>${esc(c.partido)}, ${c.posicao}º na lista ${esc(agremiacao(c.grupo))}</small>
          <small class="pessoa-det">${detalhe}</small>
        </span>
        <span class="pessoa-nota${i?.nota == null ? " vazia" : ""}" title="${esc(EXPLICA_NOTA_GERAL)}">${i?.nota ?? "—"}<small>nota geral</small></span>
      </button>
    </li>`;
  }).join("");
  return `<p class="explica">São as ${pessoas.length} pessoas que ocupariam as vagas pela estimativa, que é o grupo para o qual a pontuação é calculada. Para ver os outros candidatos, use a busca acima ou abra a lista completa de cada partido.</p>
    <ol class="pessoas-lista">${linhas}</ol>`;
}

function aplicarPerfis() {
  if (!perfisAtual) return;
  document.querySelectorAll(".lista-perfil[data-perfil]").forEach((el) => {
    const p = perfisAtual[el.dataset.perfil];
    el.innerHTML = p ? textoPerfil(p) : "";
  });
}

function textoPerfil(p) {
  const quem = p.federacao ? "da federação" : "do partido";
  const casa = p.casa === "estadual" ? "estaduais" : "federais";
  if (p.indice == null || !p.membros) return `${p.federacao ? "A federação não tem" : "O partido não tem"} deputados ${casa} hoje, então não há histórico de bancada para mostrar.`;
  return `<strong>Histórico da bancada:</strong> ${p.membros === 1 ? `o único deputado ${casa.slice(0, -1)} atual ${quem} tem` : `os ${p.membros} deputados ${casa} atuais ${quem} têm`} desempenho médio de <strong>${p.indice}</strong>${p.referencia != null ? `, contra ${p.referencia} ${p.casa === "estadual" ? "na ALESP" : "na Câmara"} toda` : ""}.`;
}

async function carregarPerfis(item) {
  const cargo = item.cargo;
  let perfis;
  try {
    perfis = await api(`/api/perfis?uf=${estado.uf}&cargo=${cargo}`);
  } catch {
    return;
  }
  if (!listasAtual || listasAtual.item.cargo !== cargo) return;
  perfisAtual = perfis;
  aplicarPerfis();
}

async function carregarIndicadores(item) {
  const cargo = item.cargo;
  try {
    indicadoresAtual = await api(`/api/indicadores?uf=${estado.uf}&cargo=${cargo}`);
  } catch {
    document.querySelectorAll(".lista-ind").forEach((el) => { el.innerHTML = ""; });
    return;
  }
  if (!listasAtual || listasAtual.item.cargo !== cargo || ajuda.cargo !== cargo) return;
  if (indicadoresAtual.pronto) {
    // A ordem por pontuação e a visão por pessoa dependem das notas: redesenha.
    if (visaoListas.modo === "pessoa" || visaoListas.ordem !== "padrao") desenharVisao();
    else aplicarIndicadores();
  } else document.querySelectorAll(".lista-ind").forEach((el) => { el.innerHTML = htmlIndicadoresCarregando(indicadoresAtual.progresso); });
  if (!indicadoresAtual.pronto || indicadoresAtual.atualizando) {
    setTimeout(() => { if (listasAtual?.item.cargo === cargo && ajuda.cargo === cargo && !$("#aba-ajuda").hidden) carregarIndicadores(item); }, 4000);
  }
}

// ---------- lista completa (diálogo) ----------

// Com manter = true (depois de pôr ou tirar alguém da cédula), redesenha no mesmo ponto da rolagem.
async function abrirLista(idGrupo, manter = false) {
  const { p, item } = listasAtual;
  const g = p.grupos.find((x) => x.id === idGrupo);
  const dlg = $("#lista-dlg");
  const rolagem = manter ? $("#lista-dlg .lista-dlg-rolagem")?.scrollTop : null;
  // Faixas que a pessoa abriu ou fechou continuam assim depois de redesenhar.
  const abertos = manter ? [...dlg.querySelectorAll("details")].map((d) => d.open) : null;
  if (rolagem == null) $("#lista-dlg-corpo").innerHTML = `<p class="carregando">Carregando os candidatos…</p>`;
  if (!dlg.open) dlg.showModal();
  let r;
  try {
    r = await api(`/api/ranking?uf=${estado.uf}&cargo=${item.cargo}&grupo=${encodeURIComponent(idGrupo)}`);
  } catch (e) {
    $("#lista-dlg-corpo").innerHTML = `<p class="erro">${esc(e.message)}</p>`;
    return;
  }
  dlg.dataset.grupo = idGrupo;
  $("#lista-dlg-corpo").innerHTML = htmlListaCompleta(g, r, item);
  const novos = [...dlg.querySelectorAll("details")];
  if (abertos?.length === novos.length) novos.forEach((d, i) => { d.open = abertos[i]; });
  if (rolagem != null) $("#lista-dlg .lista-dlg-rolagem").scrollTop = rolagem;
  carregarRedeLista(idGrupo, item);
}

function linhaCandidato(c, g, item) {
  const voto = estado.votos[item.slot];
  const naCedula = voto && voto.id === c.id;
  const p = indicadoresAtual?.pronto ? indicadoresAtual.grupos?.[g.id]?.pessoas?.[String(c.id)] : null;
  const af = afinidadePessoa(c.id);
  const acao = !c.apto ? "" : naCedula
    ? `<button type="button" class="btn pequeno" data-lista-retirar="${c.id}">Retirar da cédula</button>`
    : `<button type="button" class="btn pequeno primario" data-lista-cedula="${c.id}">Pôr na cédula</button>`;
  // Três selos iguais, lado a lado: afinidade (só de quem já é deputado federal), nota geral (de quem entraria) e força.
  const selos = [
    af ? `<span class="selo" title="${esc(textoAfinidadePessoa(c.id))}">Afinidade <strong>${pctAfinidade(af)}%</strong></span>` : "",
    p?.nota != null ? `<span class="selo selo-${nivelNota(p.nota)}" title="${esc(`${EXPLICA_NOTA_GERAL}${p.titulos.length ? ` Pontos de atenção: ${p.titulos.join("; ")}.` : ""}`)}">Nota <strong>${p.nota}</strong></span>` : "",
    c.forca != null ? `<span class="selo" title="Junta a maior votação recente (deputado em 2022 ou vereador e prefeito em 2024) e o dinheiro arrecadado em 2026. É o que define a ordem da lista.">Força <strong>${Math.round(c.forca)}</strong></span>` : "",
  ].join("");
  return `<li class="cand-linha${naCedula ? " meu" : ""}">
    <span class="cand-pos">${c.posicao ?? "—"}</span>
    ${fotoHtml(estado.uf, c.id, c.nomeUrna, `foto cand-linha-foto${p?.nota != null ? ` anel-${nivelNota(p.nota)}` : ""}`)}
    <div class="cand-linha-info">
      <button type="button" class="link-btn" data-ficha-lista="${c.id}">${esc(nomeProprio(c.nomeUrna))}</button>
      <span class="cand-linha-meta">Número ${esc(c.numero)}, ${esc(c.partido)}${c.apto ? "" : `. ${esc(c.situacao)}`}</span>
      ${selos ? `<span class="selos">${selos}</span>` : ""}
    </div>
    <div class="cand-linha-acoes">${acao}</div>
  </li>`;
}

// Primeira coisa da janela: quem ocuparia as vagas e onde o voto pesa mais.
function htmlGuiaLista(g, aptos, vagas, faixa) {
  const nomes = (lista) => listaNatural(lista.map((c) =>
    `<button type="button" class="link-btn" data-ficha-lista="${c.id}">${esc(nomeProprio(c.nomeUrna))}</button>`));
  const m = margemLista(g);
  if (!vagas) {
    return `<section class="callout lista-guia">
      <h3>Como escolher nesta lista</h3>
      <p>Se os votos de 2022 se repetissem, esta lista não elegeria ninguém${g.faltamParaMaisUma ? `: faltariam uns ${brlNumeroCurto(g.faltamParaMaisUma)} votos para a primeira vaga` : ""}.</p>
      <p>O voto em qualquer candidato daqui soma para a lista tentar chegar lá. Se ela não chegar, o voto não elege ninguém desta lista.${aptos.length ? ` Os mais bem colocados são ${nomes(aptos.slice(0, 3))}.` : ""}</p>
    </section>`;
  }
  const entram = aptos.filter((c) => c.posicao <= vagas);
  const atras = aptos.filter((c) => c.posicao > vagas && c.posicao <= vagas + faixa);
  const primeiros = vagas >= 3 ? entram.slice(0, 3) : entram.slice(0, vagas - 1);
  const ultimo = entram[entram.length - 1];
  return `<section class="callout lista-guia">
    <h3>Como escolher nesta lista</h3>
    <p>Se os votos de 2022 se repetissem, esta lista elegeria ${vagas === 1 ? "uma pessoa" : `${vagas} pessoas`}. Dentro da lista, as vagas ficam com os mais votados, por isso os candidatos abaixo estão em ordem de força: quem teve mais votos em 2022 e 2024 e arrecadou mais em 2026 aparece na frente.</p>
    ${primeiros.length ? `<p>Os primeiros, como ${nomes(primeiros)}, devem entrar mesmo sem o seu voto.</p>` : ""}
    ${ultimo && atras.length ? `<p><strong>Onde o seu voto pesa mais é na disputa pela ${vagas === 1 ? "vaga" : "última vaga"}.</strong> Hoje ela ficaria com ${nomes([ultimo])}, e logo atrás vêm ${nomes(atras)}. Nessa faixa, poucos votos decidem quem entra.</p>` : ""}
    <p>Votar em alguém com chance baixa não é voto perdido: ele soma para a lista e ajuda a eleger quem está na frente dela, que pode não ser quem você escolheu.</p>
    ${m.texto ? `<p>${m.tag} Pensando na lista inteira: ${m.texto.charAt(0).toLowerCase()}${m.texto.slice(1)}</p>` : ""}
  </section>`;
}

// Cartão simples com a nota e os avisos de quem entraria. Os detalhes ficam para quem quiser abrir.
function htmlResumoLista(g, ind, perfil, entrariam) {
  const afinidade = linhaAfinidadeLista(g);
  if (!ind) {
    return `<section class="resumo-lista">${afinidade}<p class="explica">As notas de quem entraria ainda estão sendo calculadas.</p></section>`;
  }
  const com = entrariam.map((c) => ({ c, p: ind.pessoas?.[String(c.id)] }))
    .filter((x) => x.p && (x.p.alertas || x.p.atencoes))
    .sort((a, b) => (b.p.alertas - a.p.alertas) || (b.p.atencoes - a.p.atencoes));
  const serios = com.filter((x) => x.p.alertas).length;
  const cabeca = !entrariam.length ? ""
    : entrariam.length === 1
      ? (com.length ? `A pessoa que entraria tem ${serios ? "alerta sério" : "algo para conferir"}.` : "A pessoa que entraria não tem nada para conferir.")
    : com.length
      ? `${com.length} das ${entrariam.length} pessoas que entrariam ${com.length === 1 ? "tem" : "têm"} algo para conferir${serios ? `, ${serios === 1 ? "uma delas com alerta sério" : `${serios} delas com alerta sério`}` : ""}.`
      : `Ninguém entre as ${entrariam.length} pessoas que entrariam tem algo para conferir.`;
  const mandato = ind.comMandato
    ? `${ind.comMandato === 1 ? "Uma pessoa já tem mandato de deputado" : `${ind.comMandato} pessoas já têm mandato de deputado`}, e é daí que sai o desempenho.`
    : "Ninguém do grupo tem mandato de deputado hoje, então não há desempenho para comparar.";
  return `<section class="resumo-lista">
    <h3>Quem entraria, em resumo</h3>
    ${afinidade}
    ${linhaNota(rotuloNotaLista(g), ind.indiceAjustado, { titulo: explicaNotaLista(ind) })}
    ${cabeca ? `<p class="resumo-frase">${cabeca}</p>` : ""}
    <details class="mais resumo-detalhes"><summary>Ver os avisos de cada um</summary>
      <p class="analise-texto">${mandato}${perfil ? ` ${textoPerfil(perfil)}` : ""}</p>
      ${com.length ? `<ul class="quem-entraria">${com.map(({ c, p }) => `<li>
        <span class="badge ${nivelAnel(p.alertas, p.atencoes, p.integridade) === "serio" ? "bad" : "warn"}">${p.alertas ? "Alerta sério" : p.integridade < 50 ? "Vários pontos" : "Conferir"}</span>
        <button type="button" class="link-btn" data-ficha-lista="${c.id}">${esc(nomeProprio(c.nomeUrna))}</button>
        <small>${esc(p.titulos.join("; "))}</small></li>`).join("")}</ul>` : ""}
    </details>
  </section>`;
}

function htmlListaCompleta(g, r, item) {
  const vagas = r.vagasEstimadas;
  const faixa = faixaDisputa(vagas);
  const aptos = r.candidatos.filter((c) => c.posicao);
  const problema = r.candidatos.filter((c) => !c.posicao);
  const grupos = [
    ["Ocupariam as vagas", "Pela estimativa, são estes que entram. Em 2022, quem estava nesta posição se elegeu cerca de 7 em cada 10 vezes.", aptos.filter((c) => c.posicao <= vagas), true],
    ["Na disputa pela última vaga", "Estão perto da linha de corte, onde um voto a mais decide quem entra. Em 2022, uns 3 em cada 10 nesta faixa se elegeram.", aptos.filter((c) => vagas && c.posicao > vagas && c.posicao <= vagas + faixa), true],
    ["Chance baixa", "Precisariam de bem mais votos do que tiveram em 2022. Nesta faixa, cerca de 1 em cada 10 costuma se eleger.", aptos.filter((c) => c.posicao > vagas + faixa && c.chance === "Baixa"), true],
    ["Chance muito baixa", "Estão longe das vagas, e o voto neles ajuda principalmente a lista. Aqui, cerca de 1 em cada 100 se elege.", aptos.filter((c) => c.chance === "Muito baixa" && !(vagas && c.posicao <= vagas + faixa)), false],
    ["Candidatura com problema", "O registro foi negado ou cancelado, e o voto pode não valer.", problema, false],
  ].filter(([, , lista]) => lista.length);
  const ind = indicadoresAtual?.pronto ? indicadoresAtual.grupos?.[g.id] : null;
  return `<header class="lista-dlg-cab">
      <div><h2>${esc(agremiacao(g.id))}</h2>
        <p>${aptos.length} candidatos disputam ${g.vagas === 1 ? "a vaga estimada" : `as ${g.vagas} vagas estimadas`}. Em 2022, esta lista teve ${pct.format(g.percentual)} dos votos.</p></div>
      <button type="button" class="fechar" data-fechar-lista aria-label="Fechar">✕</button>
    </header>
    <div class="lista-dlg-rolagem">
      ${htmlGuiaLista(g, aptos, vagas, faixa)}
      ${htmlAvisoEstimativa()}
      ${htmlResumoLista(g, ind, perfisAtual?.[g.id], aptos.filter((c) => c.posicao <= vagas))}
      ${grupos.map(([titulo, expl, lista, aberto]) => `<details class="faixa-lista"${aberto ? " open" : ""}>
        <summary><strong>${titulo}</strong> <span class="contador">${lista.length}</span><small>${expl}</small></summary>
        <ul class="cand-linhas">${lista.map((c) => linhaCandidato(c, g, item)).join("")}</ul>
      </details>`).join("")}
      <p class="nota-pequena">A ordem segue a força de cada candidato, que junta a maior votação recente (para deputado em 2022 ou para vereador ou prefeito em 2024) e o dinheiro arrecadado em 2026. Clique no nome para abrir a ficha completa.</p>
      <details class="faixa-lista rede-lista-sec" id="rede-lista">
        <summary><strong>Dinheiro entre candidatos</strong><small>Cruzando o dinheiro entre os candidatos da lista…</small></summary>
      </details>
    </div>`;
}

// ---------- dinheiro entre candidatos da lista (diálogo) ----------

async function carregarRedeLista(idGrupo, item) {
  let r;
  try {
    r = await api(`/api/rede_lista?uf=${estado.uf}&cargo=${item.cargo}&grupo=${encodeURIComponent(idGrupo)}`);
  } catch {
    r = null;
  }
  const alvo = $("#rede-lista");
  if (!alvo || $("#lista-dlg").dataset.grupo !== idGrupo) return;
  if (!r?.pronto) { alvo.remove(); return; }
  const rp = r.repasses;
  const empresas = r.empresas.length ? `<ul class="rede-lista">${r.empresas.map((e) => `<li class="rede-item">
      <div class="rede-topo">
        <span><strong>${esc(nomeProprio(e.empresa || e.cnpj))}</strong>
          <small>Empresa de <button type="button" class="link-btn" data-ficha-lista="${e.dono.id}">${esc(nomeProprio(e.dono.nomeUrna))}</button> (${esc(e.dono.partido || "")})</small></span>
        <span class="rede-valor">${brlCompacto.format(e.total)}<small>de ${e.quantas} ${e.quantas === 1 ? "campanha" : "campanhas"}${e.daLista ? `, ${e.daLista} desta lista` : ""}</small></span>
      </div>
      <div class="chips">${e.porPartido.slice(0, 5).map(([p, n]) => `<span class="chip">${esc(p)}: ${n}</span>`).join("")}</div>
      <button type="button" class="link-acao link-inline" data-empresa="${esc(e.cnpj)}">Ver a ficha da empresa</button>
    </li>`).join("")}</ul>${r.totalEmpresas > r.empresas.length ? `<p class="nota-pequena">E mais ${r.totalEmpresas - r.empresas.length} com valores menores.</p>` : ""}`
    : `<p class="explica">Nenhuma empresa de candidatos desta lista recebeu de outras campanhas.</p>`;
  const repasses = rp.total ? `<p class="rede-texto">Os candidatos da lista receberam ${brlCompacto.format(rp.total)} de outros candidatos, e ${pct.format(rp.publico / rp.total)} disso é dinheiro do Fundo Eleitoral ou do Fundo Partidário${rp.daLista ? `; ${brlCompacto.format(rp.daLista)} veio de colegas da própria lista` : ""}. Quem mais repassou:</p>
      <ul class="lista-simples">${rp.doadores.map((d) => `<li>${esc(nomeProprio(d.nome || "candidato"))} (${esc(d.partido || "")}${d.cargo ? `, ${esc(d.cargo.toLowerCase())}` : ""}): ${brlCompacto.format(d.valor)}</li>`).join("")}</ul>`
    : `<p class="explica">Os candidatos desta lista não receberam repasses de outros candidatos.</p>`;
  const resumo = [
    r.totalEmpresas ? `${r.totalEmpresas} ${r.totalEmpresas === 1 ? "empresa de candidato da lista recebeu" : "empresas de candidatos da lista receberam"} de outras campanhas` : "",
    rp.total ? `${brlCompacto.format(rp.total)} em repasses de outros candidatos` : "",
  ].filter(Boolean).join(", e ");
  alvo.innerHTML = `<summary><strong>Dinheiro entre candidatos</strong>
      <small>${resumo ? `${resumo.charAt(0).toUpperCase()}${resumo.slice(1)}. Toque para ver.` : "Nada encontrado entre os candidatos desta lista."}</small></summary>
    <div class="rede-corpo">
    <h4 class="rede-sub">Empresas de candidatos da lista pagas por outras campanhas</h4>
    ${empresas}
    <h4 class="rede-sub">Repasses de outros candidatos</h4>
    ${repasses}
    <p class="nota-pequena">Repassar o Fundo Eleitoral entre candidatos do mesmo partido é permitido e comum: é assim que o partido divide o dinheiro. Já a empresa de um candidato que recebe de muitas campanhas vale uma olhada, porque também é um caminho para o dinheiro de campanha chegar a um aliado. Os sócios vêm da Receita Federal.</p>
    </div>`;
}

(function ligarListas() {
  // Cartão clicável também abre com Enter ou espaço (acessibilidade).
  document.addEventListener("keydown", (e) => {
    const card = e.target.closest?.(".lista-card.clicavel");
    if (card && e.target === card && (e.key === "Enter" || e.key === " ")) {
      e.preventDefault();
      abrirLista(card.dataset.abrirLista);
    }
  });
  document.addEventListener("click", (e) => {
    document.querySelectorAll("details.info-balao[open]").forEach((d) => { if (!d.contains(e.target)) d.open = false; });
  });
  document.addEventListener("click", async (e) => {
    const ficha = e.target.closest("[data-ficha-lista]");
    if (ficha && listasAtual) return abrirFicha(listasAtual.item.cargo, +ficha.dataset.fichaLista);
    const abrir = e.target.closest("[data-abrir-lista]");
    if (abrir) return abrirLista(abrir.dataset.abrirLista);
    const dlg = $("#lista-dlg");
    if (e.target === dlg || e.target.closest("[data-fechar-lista]")) return dlg.close();
    const por = e.target.closest("[data-lista-cedula],[data-lista-retirar]");
    if (por && listasAtual) {
      const { item } = listasAtual;
      const idGrupo = dlg.dataset.grupo;
      if (por.dataset.listaRetirar) retirarVoto(item.slot);
      else {
        const r = await api(`/api/ranking?uf=${estado.uf}&cargo=${item.cargo}&grupo=${encodeURIComponent(idGrupo)}`);
        const c = r.candidatos.find((x) => x.id === +por.dataset.listaCedula);
        escolher(slots.find((s) => s.key === item.slot), { ...c, coligacao: idGrupo });
      }
      abrirLista(idGrupo, true);
      const voltar = guardarRolagem();
      desenharListas();
      voltar();
    }
  });
})();
