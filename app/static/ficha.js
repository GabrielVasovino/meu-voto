"use strict";

// Ficha do candidato: um resumo em cartões clicáveis, abas por assunto e, ao lado
// de cada parte, um quadro "Como ler isto" que interpreta os números.
// Usa as funções e formatadores definidos em app.js (esc, brl, pct, api...).

const ICONES = {
  resumo: '<path d="M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z"/>',
  pessoa: '<circle cx="12" cy="8" r="4"/><path d="M4 21c0-4 3.6-6 8-6s8 2 8 6"/>',
  politica: '<path d="M3 21h18M5 21V10M9.7 21V10M14.3 21V10M19 21V10M2 10l10-6 10 6z"/>',
  dinheiro: '<rect x="2.5" y="6" width="19" height="13" rx="2"/><circle cx="12" cy="12.5" r="2.8"/><path d="M6 10v5M18 10v5"/>',
  alerta: '<path d="M12 3.5 2.5 20h19z"/><path d="M12 10v4.2M12 17.2v.3"/>',
  chance: '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1.4"/>',
  trabalho: '<path d="M6 3h9l4 4v14H6z"/><path d="M9 12h7M9 16h7M9 8h3"/>',
  casa: '<path d="M3 11.5 12 4l9 7.5V20H3z"/><path d="M9.5 20v-5.5h5V20"/>',
  seta: '<path d="M5 12h14M13 6l6 6-6 6"/>',
  grupo: '<circle cx="9" cy="8" r="3.2"/><path d="M3 20c0-3.3 2.7-5.2 6-5.2s6 1.9 6 5.2"/><circle cx="17" cy="9" r="2.6"/><path d="M16 14.9c2.9.2 5 1.9 5 4.6"/>',
};

function icone(nome, classe = "ic-svg") {
  return `<svg class="${classe}" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor"
    stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${ICONES[nome]}</svg>`;
}

// Vereditos do quadro "Como ler isto". Nunca é "bom" ou "ruim" para temas políticos.
const TONS = {
  ok: "Dentro do esperado",
  info: "Fora da média",
  atencao: "Vale conferir",
  alerta: "Merece atenção",
  neutro: "Para contexto",
};
const PESO_TOM = { alerta: 3, atencao: 2, info: 1, neutro: 0, ok: 0 };

function leitura(tom, texto, dica) {
  return `<aside class="leitura tom-${tom}">
    <div class="leitura-cab"><span class="leitura-tag">${TONS[tom]}</span><span class="leitura-rot">Como ler isto</span></div>
    <p>${texto}</p>${dica ? `<p class="leitura-dica">${dica}</p>` : ""}
  </aside>`;
}

// `largo`: para tabelas, o quadro de leitura vai para cima e o conteúdo usa a largura toda.
function secao(titulo, conteudo, aside = "", id = "", largo = false) {
  const grade = !aside ? " sem-aside" : largo ? " largo" : "";
  return `<section class="fsecao"${id ? ` id="${id}"` : ""}>
    <h3>${titulo}</h3>
    <div class="fsecao-grade${grade}">${largo ? aside : ""}<div class="fsecao-corpo">${conteudo}</div>${largo ? "" : aside}</div>
  </section>`;
}

function esqueleto(texto = "Montando a análise com dados da Câmara, do TSE e da Receita…") {
  return `<div class="esqueleto"><span class="giro" aria-hidden="true"></span>${esc(texto)}</div>`;
}

const ficha = { id: 0, cargo: 0, f: null, a: null, erroAnalise: null, g: null, aba: "resumo", sub: {}, filtro: "todos" };
let fichaPedido = 0;

function slotParaCargo(cargo) {
  if (cargo === 6) return "dep_federal";
  if (cargo === 7 || cargo === 8) return "dep_estadual";
  if (cargo === 5) return estado.votos.senador_1 ? "senador_2" : "senador_1";
  if (cargo === 3) return "governador";
  if (cargo === 1) return "presidente";
  return null;
}

async function abrirFicha(cargo, id) {
  const minha = ++fichaPedido;
  Object.assign(ficha, {
    id, cargo, f: null, a: null, n: null, erroAnalise: null, g: null, aba: "resumo",
    sub: { politica: "posicoes", dinheiro: "geral" }, filtro: "todos",
  });
  const dlg = $("#ficha");
  $("#ficha-cab").innerHTML = `<div class="ficha-id"><p class="carregando">Carregando dados do TSE…</p></div>
    <div class="ficha-acoes"><button type="button" class="fechar" data-fechar aria-label="Fechar">✕</button></div>`;
  $("#ficha-nav").innerHTML = "";
  $("#ficha-painel").innerHTML = "";
  if (!dlg.open) dlg.showModal();
  const pedidoAnalise = api(`/api/analise?uf=${ufConsulta(cargo)}&cargo=${cargo}&id=${id}`);
  // Notícias chegam por conta própria; só redesenham se a pessoa estiver na aba "Quem é".
  api(`/api/noticias?uf=${ufConsulta(cargo)}&cargo=${cargo}&id=${id}`)
    .then((n) => n, () => ({ erro: true }))
    .then((n) => {
      if (minha !== fichaPedido) return;
      ficha.n = n;
      if (ficha.f && ficha.aba === "quem") desenharFicha(true);
    });
  try {
    ficha.f = await api(`/api/ficha?uf=${ufConsulta(cargo)}&cargo=${cargo}&id=${id}`);
  } catch (e) {
    $("#ficha-cab .ficha-id").innerHTML = `<p class="carregando">${esc(e.message)}</p>`;
    return;
  }
  if (minha !== fichaPedido) return;
  desenharFicha();
  try {
    ficha.a = await pedidoAnalise;
  } catch (e) {
    ficha.erroAnalise = e.message;
  }
  if (minha === fichaPedido) desenharFicha(true);
}

function desenharFicha(manterRolagem = false) {
  const rolagem = $("#ficha-rolagem");
  const topo = rolagem.scrollTop;
  $("#ficha-cab").innerHTML = htmlCabecalho(ficha.f);
  $("#ficha-nav").innerHTML = htmlNavegacao();
  desenharPainel();
  rolagem.scrollTop = manterRolagem ? topo : 0;
}

function desenharPainel() {
  const painel = $("#ficha-painel");
  const aba = ficha.aba;
  painel.setAttribute("aria-labelledby", `ficha-aba-${aba}`);
  painel.innerHTML = {
    resumo: painelResumo, grupo: painelGrupo, quem: painelQuem, politica: painelPolitica, dinheiro: painelDinheiro,
    alertas: painelAlertas,
  }[aba]();
}

// ---------- cabeçalho e navegação ----------

function htmlCabecalho(f) {
  const chave = chaveDoVoto(f.id);
  const agrem = f.coligacao && f.coligacao !== f.partido.sigla ? agremiacao(f.coligacao) : "";
  let acao = "";
  if (chave) {
    acao = `<span class="badge ok">✓ Na sua cédula</span>
      <button type="button" class="btn pequeno" data-cedula-acao="retirar">Retirar</button>`;
  } else if (slotParaCargo(f.codCargo) && candidaturaValida({ situacao: f.situacao })) {
    acao = `<button type="button" class="btn pequeno primario" data-cedula-acao="por">Pôr na cédula</button>`;
  }
  return `${fotoHtml(f.uf, f.id, f.nomeUrna, "foto ficha-foto")}
    <div class="ficha-id">
      <h2 id="ficha-nome">${esc(nomeProprio(f.nomeUrna))} <span class="ficha-num">${esc(f.numero)}</span></h2>
      <div class="ficha-sub">Candidato a ${esc(f.cargo.toLowerCase())} ${f.uf === "BR" ? "" : `por ${esc(f.uf)} `}pelo ${esc(f.partido.sigla)}${agrem ? `, na ${esc(agrem)}` : ""}</div>
      <div class="cand-badges">${badgeSituacao(f.situacao)}${f.reeleicao ? `<span class="badge info">Tenta a reeleição</span>` : ""}</div>
    </div>
    <div class="ficha-acoes">${acao}<button type="button" class="fechar" data-fechar aria-label="Fechar">✕</button></div>`;
}

function abasFicha() {
  const proporcional = [6, 7, 8].includes(ficha.f?.codCargo);
  return [
    ["resumo", "Resumo", "resumo"],
    ...(proporcional ? [["grupo", "Seu voto elege", "grupo"]] : []),
    ["quem", "Quem é", "pessoa"],
    ["politica", "Atuação política", "politica"],
    ["dinheiro", "Dinheiro", "dinheiro"],
    ["alertas", "Alertas", "alerta"],
  ];
}

function sinaisFortes() {
  return (ficha.a?.sinais || []).filter((s) => s.nivel === "alerta" || s.nivel === "atencao");
}

function htmlNavegacao() {
  return abasFicha().map(([id, rotulo, ic]) => {
    let extra = "";
    if (id === "alertas") {
      if (!ficha.a && !ficha.erroAnalise) extra = `<span class="contador">…</span>`;
      else if (sinaisFortes().length) extra = `<span class="contador forte">${sinaisFortes().length}</span>`;
    }
    const ativa = ficha.aba === id;
    return `<button type="button" role="tab" id="ficha-aba-${id}" class="ficha-aba" data-aba="${id}"
      aria-selected="${ativa}" tabindex="${ativa ? 0 : -1}">${icone(ic)}<span>${rotulo}</span>${extra}</button>`;
  }).join("");
}

function subnav(aba, opcoes) {
  const atual = ficha.sub[aba];
  return `<div class="subnav" role="group" aria-label="Assuntos">${opcoes.map(([id, rotulo]) =>
    `<button type="button" data-sub="${id}" aria-pressed="${atual === id}">${rotulo}</button>`).join("")}</div>`;
}

// ---------- Resumo ----------

function htmlCartao(c) {
  const tom = c.tom || "neutro";
  const destino = c.link
    ? `href="${esc(c.link)}" target="_blank" rel="noopener"`
    : `data-ir="${c.ir}"${c.sub ? ` data-sub-destino="${c.sub}"` : ""}`;
  const tag = c.link ? "a" : "button";
  return `<${tag} ${c.link ? "" : 'type="button"'} class="rcard tom-${tom}" ${destino}>
    <span class="rcard-topo"><span class="rcard-ic">${icone(c.icone)}</span><span class="rcard-rot">${c.rot}</span></span>
    <span class="rcard-val">${c.val}</span>
    <span class="rcard-ctx">${c.ctx || ""}</span>
    <span class="rcard-rodape">${tom !== "neutro" ? `<span class="rcard-tag">${TONS[tom]}</span>` : ""}
      <span class="rcard-ir">${c.link ? "Abrir" : "Ver detalhes"} ${icone("seta", "ic-svg ic-peq")}</span></span>
  </${tag}>`;
}

function textoContagemAlertas(alertas, conferir) {
  const partes = [];
  if (alertas) partes.push(`${alertas === 1 ? "um merece" : `${alertas} merecem`} atenção`);
  if (conferir) partes.push(`${conferir === 1 ? "um vale" : `${conferir} valem`} uma conferida`);
  const frase = partes.join(" e ");
  return frase.charAt(0).toUpperCase() + frase.slice(1) + ".";
}

function painelResumo() {
  const f = ficha.f;
  const a = ficha.a;
  const cartoes = [];

  if (a?.pontuacao?.nota != null) {
    const p = a.pontuacao;
    cartoes.push({
      icone: "resumo", rot: "Pontuação", ir: "#bloco-pontuacao",
      val: `${p.nota}<small class="de100"> de 100</small>`,
      ctx: p.desempenho != null
        ? `Integridade ${p.integridade} e desempenho ${p.desempenho} como deputado ${p.casa === "estadual" ? "estadual" : "federal"}.`
        : `Vem só da integridade, porque não tem mandato de deputado para avaliar.`,
      tom: p.nota >= 80 ? "ok" : p.nota >= 60 ? "atencao" : "alerta",
    });
  }

  if (a?.chance?.candidato) {
    const c = a.chance;
    const x = c.candidato;
    cartoes.push(x.posicao ? {
      icone: "chance", rot: "Chance de se eleger", ir: "#bloco-chance",
      val: `<span class="chance ${classeChance(x.chance)}">${esc(x.chance)}</span>`,
      ctx: `Está em ${x.posicao}º lugar entre ${c.total} candidatos de uma lista que teria ${c.vagasEstimadas} ${c.vagasEstimadas === 1 ? "vaga" : "vagas"}.`,
    } : { icone: "chance", rot: "Chance de se eleger", ir: "alertas", val: "Fora da estimativa", ctx: esc(x.situacao), tom: "atencao" });
  } else if ([1, 3, 5].includes(f.codCargo)) {
    cartoes.push({
      icone: "chance", rot: "Chance de se eleger", link: "https://pesqele-divulgacao.tse.jus.br/", val: "Veja as pesquisas",
      ctx: "Para este cargo, quem mostra a chance são as pesquisas registradas no TSE.",
    });
  }

  const o = a?.orientacao;
  if (o?.deputado?.governismo != null) {
    const p = o.partido;
    cartoes.push({
      icone: "politica", rot: "Votou com o governo", ir: "politica", sub: "posicoes",
      val: pct.format(o.deputado.governismo),
      ctx: `Nas votações da Câmara desde 2023.${p?.governismo != null ? ` A bancada do ${esc(sigla(p.sigla))} votou com o governo em ${pct.format(p.governismo)}.` : ""}`,
    });
  } else if (o?.partido?.governismo != null) {
    cartoes.push({
      icone: "politica", rot: "Partido na Câmara", ir: "politica", sub: "posicoes",
      val: pct.format(o.partido.governismo),
      ctx: `É quanto a bancada do ${esc(sigla(o.partido.sigla))} votou com o governo desde 2023.`,
    });
  }

  if (a?.trabalho) {
    const t = a.trabalho;
    const avancaram = (t.etapas.lei || 0) + (t.etapas.aprovada || 0);
    cartoes.push({
      icone: "trabalho", rot: "Trabalho no mandato", ir: "politica", sub: "projetos",
      val: `${numero.format(t.projetos)} projetos`,
      ctx: `Apresentados desde 2023. ${avancaram === 0 ? "Nenhum passou" : avancaram === 1 ? "Um passou" : `${avancaram} passaram`} pela Câmara, e um deputado típico apresentou ${t.medianas?.projetos ?? "—"}.`,
      tom: tomProjetos(t),
    });
  }

  if (a?.estadual) {
    const e = a.estadual;
    cartoes.push({
      icone: "trabalho", rot: "Trabalho na ALESP", ir: "politica", sub: "alesp",
      val: `${numero.format(e.projetos)} projetos`,
      ctx: `${e.simbolicos === 1 ? "Um é homenagem" : `${numero.format(e.simbolicos)} são homenagens`} ou datas, e ${e.leisSubstantivas === 1 ? "uma lei aprovada muda" : `${e.leisSubstantivas} leis aprovadas mudam`} regras para o estado.`,
      tom: e.projetos >= 10 && e.simbolicos / e.projetos >= 0.15 && e.simbolicos / e.projetos >= 2 * (e.medianas.simbolicos || 0) ? "info" : "neutro",
    });
  }

  const tr = a?.trajetoria?.resumo;
  if (tr?.candidaturas) {
    cartoes.push({
      icone: "pessoa", rot: "Carreira política", ir: "quem",
      val: tr.anosEmMandato ? `${tr.anosEmMandato} anos em mandato` : `${tr.candidaturas} ${tr.candidaturas === 1 ? "eleição" : "eleições"}`,
      ctx: tr.anosEmMandato
        ? `Desde ${tr.primeiraEleicao}, como ${listaNatural(tr.cargosOcupados.map((c) => esc(c.toLowerCase())))}.`
        : `Disputou desde ${tr.primeiraEleicao} e não se elegeu.`,
    });
  }

  if (f.contas) {
    const c = f.contas;
    const publico = c.fundoEleitoral + c.fundoPartidario;
    cartoes.push({
      icone: "dinheiro", rot: "Arrecadou", ir: "dinheiro", sub: "geral",
      val: brlCompacto.format(c.totalRecebido),
      ctx: c.totalRecebido ? `${pct.format(publico / c.totalRecebido)} desse valor veio de dinheiro público.` : "Ainda não declarou arrecadação.",
    });
  }

  const sinalBens = (a?.sinais || []).find((s) => /patrimônio/i.test(s.titulo) && s.fonte.includes("IPCA"));
  const primeiraDecl = (a?.trajetoria?.linhas || []).find((l) => l.bensHoje && !l.atual);
  cartoes.push({
    icone: "casa", rot: "Patrimônio declarado", ir: "quem",
    val: brlCompacto.format(f.totalBens || 0),
    ctx: primeiraDecl
      ? `Em ${primeiraDecl.ano}, declarou o equivalente a ${brlCompacto.format(primeiraDecl.bensHoje)} em valores de hoje.`
      : `Soma de ${f.bens.length} ${f.bens.length === 1 ? "bem declarado" : "bens declarados"}.`,
    tom: sinalBens?.nivel === "atencao" ? "atencao" : primeiraDecl ? "ok" : "neutro",
  });

  if (a) {
    const fortes = sinaisFortes();
    const alertas = fortes.filter((s) => s.nivel === "alerta").length;
    cartoes.push({
      icone: "alerta", rot: "Alertas", ir: "alertas",
      val: fortes.length ? `${fortes.length} ${fortes.length === 1 ? "ponto" : "pontos"}` : "Nenhum",
      ctx: fortes.length ? textoContagemAlertas(alertas, fortes.length - alertas)
        : "Nada fora do comum apareceu nas fontes consultadas.",
      tom: alertas ? "alerta" : fortes.length ? "atencao" : "ok",
    });
  }

  const destaques = sinaisFortes().slice(0, 3);
  const blocoDestaques = !a ? esqueleto() : destaques.length ? `<section class="fsecao">
      <h3>O que mais chama atenção</h3>
      <ul class="sinais">${destaques.map(htmlSinal).join("")}</ul>
      <button type="button" class="link-acao" data-ir="alertas">Ver todos os alertas ${icone("seta", "ic-svg ic-peq")}</button>
    </section>` : "";

  return `<p class="painel-intro">O essencial sobre esta candidatura. Clique em qualquer cartão para ver os detalhes.</p>
    <div class="resumo-grid">${cartoes.map(htmlCartao).join("")}${!a && !ficha.erroAnalise ? `<div class="rcard rcard-carregando">${esqueleto("Calculando chance, posições e alertas…")}</div>` : ""}</div>
    ${ficha.erroAnalise ? `<p class="erro">Não foi possível montar a análise: ${esc(ficha.erroAnalise)}</p>` : ""}
    ${a?.pontuacao?.nota != null ? htmlBlocoPontuacao(a.pontuacao) : ""}
    ${blocoDestaques}
    ${a?.chance?.candidato?.posicao ? htmlBlocoChance(a.chance) : ""}
    <details class="como-ler"><summary>Como ler esta ficha</summary>
      <p>Ao lado de cada parte há um quadro chamado <strong>Como ler isto</strong>, que resume o que o número quer dizer. Ele vem com uma etiqueta:</p>
      <ul>
        <li><span class="leitura-tag tom-ok">Dentro do esperado</span> quando o número é parecido com o de outros candidatos ou deputados.</li>
        <li><span class="leitura-tag tom-info">Fora da média</span> quando ele foge do comum, o que não é necessariamente um problema.</li>
        <li><span class="leitura-tag tom-atencao">Vale conferir</span> quando há um indício que merece uma olhada com calma.</li>
        <li><span class="leitura-tag tom-alerta">Merece atenção</span> quando os dados públicos mostram algo mais sério.</li>
        <li><span class="leitura-tag tom-neutro">Para contexto</span> quando o dado depende da sua opinião, como o alinhamento com o governo.</li>
      </ul>
    </details>`;
}

function barraNota(rotulo, valor, extra = "") {
  return `<div class="nota-barra"><span class="nota-rot">${rotulo}</span>
    <span class="trilho"><span class="cheio" style="width:${valor}%"></span><span class="marca-meio" title="Deputado típico"></span></span>
    <b>${valor}</b>${extra}</div>`;
}

function htmlBlocoPontuacao(p) {
  const descontos = p.descontos.length
    ? `<ul class="descontos">${p.descontos.map((d) => `<li><span class="leitura-tag tom-${d.nivel}">−${d.pontos}</span> ${esc(d.titulo)}</li>`).join("")}</ul>`
    : `<p class="explica">Nenhum desconto: os dados públicos não mostram alertas de integridade.</p>`;
  const casa = p.casa === "estadual" ? "deputados estaduais de São Paulo" : "deputados federais";
  const criterios = p.criterios ? `<p class="nota-sub">Desempenho no mandato, comparado aos outros ${casa}. O traço no meio de cada barra marca o deputado típico.</p>
      <div class="nota-barras">${p.criterios.map((c) => barraNota(c.rotulo + (c.peso > 1 ? " <small>(vale em dobro)</small>" : ""), Math.round(100 * c.valor))).join("")}</div>` : "";
  const ajuste = p.desempenho != null ? Math.round(0.4 * (p.desempenho - 50)) : 0;
  let texto = `A nota é ${p.nota}. A integridade ficou em ${p.integridade}`;
  texto += p.descontos.length
    ? ` e perdeu ${100 - p.integridade} pontos por ${p.descontos.length === 1 ? "um indício encontrado" : `${p.descontos.length} indícios encontrados`} nos dados públicos.`
    : ", sem nenhum desconto.";
  if (p.desempenho != null) {
    texto += ` O desempenho no mandato ficou em ${p.desempenho}, ${ajuste === 0 ? "igual ao de um deputado típico, e não mudou a nota" : ajuste > 0 ? `acima de um deputado típico, e somou ${ajuste} pontos` : `abaixo de um deputado típico, e tirou ${-ajuste} pontos`}.`;
  }
  return secao("Pontuação", `
      <div class="nota-topo">
        <div class="nota-grande"><strong>${p.nota}</strong><span>de 100</span></div>
        <div class="nota-barras">
          ${barraNota("Integridade", p.integridade)}
          ${p.desempenho != null ? barraNota("Desempenho", p.desempenho) : `<p class="explica">Sem desempenho no mandato para avaliar, porque não tem mandato de deputado federal nem de deputado estadual em São Paulo.</p>`}
        </div>
      </div>
      <p class="nota-sub">O que tirou pontos da integridade:</p>
      ${descontos}
      ${criterios}`,
  leitura("neutro", texto,
    "A integridade começa em 100 e perde 20 pontos por indício que vale conferir e 50 por alerta sério. Para quem tem mandato, o desempenho soma ou tira até 20 pontos. Projeto simbólico, como homenagem ou nome de viaduto, pesa em dobro no desempenho. A posição política não entra na conta."),
  "bloco-pontuacao");
}

function htmlBlocoChance(c) {
  const x = c.candidato;
  const vagas = c.vagasEstimadas;
  const mostrar = Math.min(c.total, Math.max(vagas * 2 + 4, x.posicao + 3, 12));
  const nomes = new Map(c.eleitosProvaveis.map((e) => [e.posicao, e.nomeUrna]));
  nomes.set(x.posicao, x.nomeUrna);
  const quadrados = Array.from({ length: mostrar }, (_, i) => {
    const pos = i + 1;
    const classes = ["q", pos <= vagas ? "dentro" : "", pos === x.posicao ? "voce" : ""].join(" ");
    const nome = nomes.get(pos);
    return `<span class="${classes}" title="${pos}º lugar${nome ? `: ${esc(nomeProprio(nome))}` : ""}">${pos === x.posicao ? pos : ""}</span>`;
  }).join("");
  const outros = c.eleitosProvaveis.filter((e) => e.id !== x.id).slice(0, 6).map((e) => esc(nomeProprio(e.nomeUrna)));
  const dentro = x.posicao <= vagas;
  const texto = vagas === 0
    ? `Pela estimativa, a lista <strong>${esc(agremiacao(c.grupo))}</strong> não chegaria ao número mínimo de votos para eleger alguém. Se isso se repetir, os votos nela não elegem ninguém.`
    : dentro
      ? `Está entre os que ocupariam as ${vagas} vagas da lista. A ordem ainda pode mudar na urna.`
      : `Está abaixo das ${vagas} vagas da lista. O voto nele continua valendo para a lista <strong>${esc(agremiacao(c.grupo))}</strong> e ajuda a eleger quem está na frente${outros.length ? `, que hoje seriam ${outros.join(", ")}` : ""}.`;
  const hist = [
    x.votos2022 ? `${numero.format(x.votos2022)} votos para deputado em 2022` : "nenhum voto para deputado em 2022",
    x.votosMunicipais ? `${numero.format(x.votosMunicipais)} votos para ${x.cargoMunicipal.toLowerCase()} em 2024` : "",
  ].filter(Boolean).join(" e ");
  return secao("Onde está na fila da lista", `
      <div class="fila" role="img" aria-label="Posição ${x.posicao} de ${c.total}; ${vagas} vagas estimadas">${quadrados}${c.total > mostrar ? `<span class="q-mais">+${c.total - mostrar}</span>` : ""}</div>
      <div class="fila-legenda"><span><i class="q dentro"></i> as ${vagas} vagas da lista</span><span><i class="q voce"></i> este candidato, em ${x.posicao}º</span><span><i class="q"></i> os demais</span></div>
      <p class="fila-texto">A ordem vem da força de cada candidato, que junta a maior votação recente (deputado em 2022 ou vereador e prefeito em 2024) e o dinheiro arrecadado em 2026. Este teve ${hist} e arrecadou ${brlCompacto.format(x.arrecadado)}, o que dá força ${Math.round(x.forca)} de 100. Passe o mouse sobre um quadrado para ver o nome.</p>`,
  leitura("neutro", texto, `Na eleição de 2022, quem estava na faixa "${esc(x.chance)}" se elegeu ${CHANCE_EM_2022[x.chance] || "em poucos casos"} vezes. A conta usa os votos anteriores e o dinheiro arrecadado, sem pesquisas.`),
  "bloco-chance");
}

// ---------- Seu voto elege (deputados) ----------

async function carregarGrupo() {
  const pedido = fichaPedido;
  ficha.g = { carregando: true };
  try {
    ficha.g = await api(`/api/grupo?uf=${ufConsulta(ficha.cargo)}&cargo=${ficha.cargo}&grupo=${encodeURIComponent(ficha.a.chance.grupo)}`);
  } catch (e) {
    ficha.g = { erro: e.message };
  }
  if (pedido === fichaPedido && ficha.aba === "grupo") desenharPainel();
}

function faixaDoCandidato(g, pos) {
  const faixa = Math.max(2, Math.round(g.vagas * 0.25));
  if (!pos) return "fora";
  if (pos <= g.vagas - faixa) return "certo";
  if (pos <= g.vagas + faixa) return "disputa";
  return "longe";
}

function miniMembro(m, destaque) {
  return `<button type="button" class="membro${destaque ? " eu" : ""}" data-abrir="${m.id}" title="Abrir a ficha">
    ${fotoHtml(ufConsulta(ficha.cargo), m.id, m.nomeUrna, "foto membro-foto")}
    <span class="membro-nome">${esc(nomeProprio(m.nomeUrna))}</span>
    <span class="membro-meta">${m.posicao}º lugar, ${esc(m.partido)}</span>
    <span class="membro-tags">${m.deputado ? `<span class="badge info">já é deputado(a)</span>` : ""}<span class="chance ${classeChance(m.chance)}">${esc(m.chance)}</span></span>
  </button>`;
}

function listaNatural(itens) {
  if (itens.length <= 1) return itens.join("");
  return `${itens.slice(0, -1).join(", ")} e ${itens[itens.length - 1]}`;
}

function painelGrupo() {
  const a = ficha.a;
  if (!a) return ficha.erroAnalise ? `<p class="erro">${esc(ficha.erroAnalise)}</p>` : esqueleto();
  if (!a.chance?.grupo) return `<p class="painel-intro">Não foi possível identificar a lista desta candidatura.</p>`;
  if (!ficha.g) carregarGrupo();
  if (!ficha.g || ficha.g.carregando) return esqueleto("Montando o retrato do grupo que a lista elegeria…");
  const g = ficha.g;
  if (g.erro) return `<p class="erro">${esc(g.erro)}</p>`;
  const f = ficha.f;
  const eu = a.chance.candidato;
  const nome = esc(nomeProprio(f.nomeUrna));
  const lista = esc(agremiacao(g.grupo));
  const dentro = eu?.posicao && eu.posicao <= g.vagas;
  const intro = `<p class="painel-intro">Para deputado, o voto conta primeiro para a lista, que aqui é a ${lista}, e só depois para a pessoa. Por isso, votar em ${nome} também ajuda a eleger os mais bem colocados dessa lista.</p>`;

  if (!g.vagas) {
    return intro + secao("Quem a lista elegeria", `<p>Pela estimativa, a lista ${lista} não chegaria ao número mínimo de votos para eleger alguém.</p>`,
      leitura("atencao", "Se isso se repetir em 2026, os votos nesta lista não elegem ninguém. Mais abaixo você vê quantos votos faltariam.")) + htmlOndePesa(g, eu, nome);
  }

  const membros = g.membros.map((m) => miniMembro(m, m.id === f.id)).join("");
  const grupoTexto = dentro
    ? `${nome} está entre os ${g.vagas} que a lista elegeria, e o seu voto reforça esse grupo.`
    : `${nome} está ${eu?.posicao ? `em ${eu.posicao}º lugar` : "fora da estimativa"}, abaixo das ${g.vagas} vagas. Na prática, o voto em ${nome} ajuda principalmente a eleger ${g.vagas === 1 ? "esta pessoa" : `estas ${g.vagas} pessoas`}.`;
  const blocoGrupo = secao("Quem você ajuda a eleger",
    `<div class="membros">${membros}</div><p class="nota-pequena">Clique em uma pessoa para abrir a ficha dela.</p>`,
    leitura("neutro", grupoTexto, "Numa federação, as vagas podem ir para qualquer partido que faz parte dela, não só para o partido de quem você escolheu."));

  const r = g.retrato;
  const n = g.membros.length;
  const partidos = r.partidos.map((p) => `<span class="chip">${esc(p.partido)}: ${p.quantidade}</span>`).join("");
  const gov = r.governismoMedio != null
    ? `<div class="tile"><div class="rot">Votaram com o governo</div><div class="val">${pct.format(r.governismoMedio)}</div>
        <div class="det">${r.deputadosAtuais === 1 ? "Considera quem já é deputado." : `Média dos ${r.deputadosAtuais} que já são deputados${r.governismoMin !== r.governismoMax ? `, que vai de ${pct.format(r.governismoMin)} a ${pct.format(r.governismoMax)}` : ""}.`}</div></div>` : "";
  const partes = [
    `${r.deputadosAtuais} já ${r.deputadosAtuais === 1 ? "é deputado federal" : "são deputados federais"}`,
    `${r.mulheres} ${r.mulheres === 1 ? "é mulher" : "são mulheres"}`,
    r.idadeMediana ? `a idade típica é de ${r.idadeMediana} anos` : "",
  ].filter(Boolean);
  const blocoRetrato = secao("Retrato do grupo", `
      <div class="tiles">
        <div class="tile"><div class="rot">Já são deputados</div><div class="val">${r.deputadosAtuais} de ${n}</div><div class="det">${r.jaEleitos2022 === 1 ? "Um foi eleito" : `${r.jaEleitos2022} foram eleitos`} em 2022.</div></div>
        <div class="tile"><div class="rot">Mulheres</div><div class="val">${r.mulheres} de ${n}</div><div class="det">${r.idadeMediana ? `A idade típica do grupo é ${r.idadeMediana} anos.` : ""}</div></div>
        <div class="tile"><div class="rot">Patrimônio típico</div><div class="val">${r.patrimonioMediano != null ? brlCompacto.format(r.patrimonioMediano) : "—"}</div><div class="det">Valor do meio do grupo, declarado ao TSE.</div></div>
        ${gov}
      </div>
      <p style="margin-top:14px">Quantos são de cada partido:</p><div class="chips">${partidos}</div>
      ${r.ocupacoes.length ? `<p style="margin-top:12px">As profissões que mais aparecem são ${listaNatural(r.ocupacoes.map(([o]) => esc(nomeProprio(o).toLowerCase())))}.</p>` : ""}`,
  leitura("neutro", `São ${n} pessoas: ${listaNatural(partes)}.${r.governismoMedio != null ? ` Quem já está na Câmara votou com o governo, em média, em ${pct.format(r.governismoMedio)} das vezes.` : " Ninguém do grupo está na Câmara hoje, então não há votações para comparar."}`,
    "Para ver alertas, dinheiro e trajetória de cada pessoa, abra a ficha dela."));
  return intro + blocoGrupo + blocoRetrato + htmlPerfilPartido(g.perfil) + htmlOndePesa(g, eu, nome);
}

function comparaTexto(valor, ref, maiorEhMais = true) {
  if (valor == null || ref == null) return "";
  const dif = valor - ref;
  if (Math.abs(dif) < 0.03) return "parecido com a média";
  return (dif > 0) === maiorEhMais ? "acima da média" : "abaixo da média";
}

function htmlPerfilPartido(p) {
  if (!p || (!p.federal && !p.estadual)) return "";
  const nomeGrupo = p.federacao ? "A federação" : "O partido";
  const f = p.federal;
  const rf = p.referenciaFederal || {};
  const e = p.estadual;
  const re = p.referenciaEstadual || {};
  const tiles = [];
  if (p.indice != null) {
    tiles.push(`<div class="tile destaque"><div class="rot">Desempenho da bancada</div><div class="val">${p.indice}<small class="de100"> de 100</small></div>
      <div class="det">Média de quem já é deputado ${p.casaDoIndice === "estadual" ? "estadual em SP" : "federal"} pelo ${p.federacao ? "grupo" : "partido"}. O deputado típico fica em 50.</div></div>`);
  }
  if (f) {
    tiles.push(`<div class="tile"><div class="rot">Na Câmara</div><div class="val">${f.membros} ${f.membros === 1 ? "deputado" : "deputados"}</div>
      <div class="det">${f.governismo != null ? `Votaram com o governo em ${pct.format(f.governismo)} das vezes.` : ""}</div></div>`);
    if (f.partePix != null) tiles.push(`<div class="tile"><div class="rot">Emendas Pix</div><div class="val">${pct.format(f.partePix)}</div>
      <div class="det">Do valor das emendas da bancada. Na Câmara toda, ${pct.format(rf.partePix || 0)}.</div></div>`);
  }
  if (e) {
    tiles.push(`<div class="tile"><div class="rot">Na ALESP</div><div class="val">${e.membros} ${e.membros === 1 ? "deputado" : "deputados"}</div>
      <div class="det">${pct.format(e.parteSimbolica || 0)} dos projetos são homenagens ou datas, contra ${pct.format(re.parteSimbolica || 0)} na Assembleia toda.</div></div>`);
  }
  const frases = [];
  if (f) {
    frases.push(`Na Câmara, a bancada tem desempenho médio de ${f.desempenho ?? "—"}${rf.desempenho != null ? `, ${f.desempenho > rf.desempenho + 3 ? "acima" : f.desempenho < rf.desempenho - 3 ? "abaixo" : "perto"} da média de ${rf.desempenho}` : ""}.`);
    if (f.parteSimbolica != null) frases.push(`${pct.format(f.parteSimbolica)} dos projetos dela são simbólicos, ${comparaTexto(f.parteSimbolica, rf.parteSimbolica)} da Câmara, que é ${pct.format(rf.parteSimbolica || 0)}.`);
    if (f.comEntidadeDependente) frases.push(`${f.comEntidadeDependente === 1 ? "Um deputado da bancada tem" : `${f.comEntidadeDependente} deputados da bancada têm`} alguma entidade privada que depende das suas emendas.`);
    if (f.coesao != null) frases.push(`Os deputados acompanham a maioria da bancada em ${pct.format(f.coesao)} das votações.`);
  }
  if (e) frases.push(`Na ALESP, o desempenho médio da bancada é ${e.desempenho ?? "—"}${re.desempenho != null ? `, e o da Assembleia toda é ${re.desempenho}` : ""}.`);
  const dinamica = p.dinamica?.length ? `<p class="nota-sub">Como os partidos da federação votam entre si na Câmara:</p>
    <ul class="dinamica">${p.dinamica.map((x) => `<li><strong>${esc(x.a)} e ${esc(x.b)}</strong> votaram do mesmo jeito em ${pct.format(x.taxa)} das ${numero.format(x.votacoes)} votações em que os dois tinham posição.</li>`).join("")}</ul>` : "";
  const composicao = f?.porPartido?.length > 1 ? `<p style="margin-top:12px">Na Câmara, a bancada se divide assim: ${listaNatural(f.porPartido.map(([s, n]) => `${esc(s)} com ${n}`))}.</p>` : "";
  const temas = f?.temasDestaque?.length ? `<p style="margin-top:12px">Temas em que a bancada mais se concentra: ${listaNatural(f.temasDestaque.map((t) => esc(t[0].toLowerCase())))}.</p>` : "";
  return secao(`${nomeGrupo} por dentro`, `<div class="tiles">${tiles.join("")}</div>${composicao}${dinamica}${temas}`,
    leitura("neutro", frases.join(" "),
      `Quem a lista elegeria muitas vezes ainda não tem mandato, então este bloco mostra como ${p.federacao ? "os partidos da federação" : "o partido"} se comporta${p.federacao ? "m" : ""} com quem já tem. A posição política não entra no desempenho.`));
}

function htmlOndePesa(g, eu, nome) {
  const faixaEu = faixaDoCandidato(g, eu?.posicao);
  const textos = {
    certo: `${nome} está bem colocado e deve se eleger mesmo sem o seu voto. Aqui, o voto pesa mais para a lista ganhar ou manter vagas do que para decidir se ${nome} entra.`,
    disputa: `${nome} está perto da linha de corte, que é exatamente onde um voto a mais decide quem entra e quem fica de fora.`,
    longe: `${nome} está longe da linha de corte e dificilmente entra. O voto soma para a lista e, na prática, ajuda os primeiros colocados.`,
    fora: `A candidatura de ${nome} está com problema na Justiça Eleitoral. Se o registro for negado, o voto pode não contar nem para a lista.`,
  };
  const disputa = g.disputa.map((d) => `<button type="button" class="chip chip-botao${eu && d.id === eu.id ? " destaque" : ""}" data-abrir="${d.id}">${d.posicao}º ${esc(nomeProprio(d.nomeUrna))}, ${esc(d.partido)}</button>`).join("");
  const m = g.margem;
  const rel = (v) => (m.votos2022 ? v / m.votos2022 : 1);
  let margemTexto = "A estimativa de margens não está disponível para esta lista.";
  let tom = "neutro";
  if (m.faltamParaMaisUma != null) {
    const perto = rel(m.faltamParaMaisUma) < 0.05;
    const ameacada = m.folgaDaUltima != null && rel(m.folgaDaUltima) < 0.05;
    margemTexto = `Com cerca de <strong>${numero.format(m.faltamParaMaisUma)} votos</strong> a mais, a lista ganharia outra vaga.${m.folgaDaUltima != null ? ` A última vaga que ela tem está garantida por uma folga de uns <strong>${numero.format(m.folgaDaUltima)} votos</strong>.` : ""} `;
    if (perto) margemTexto += "Como falta pouco, votos nesta lista podem render mais uma cadeira.";
    else if (ameacada) margemTexto += "Como a folga é pequena, votos nesta lista ajudam a segurar essa vaga.";
    else margemTexto += "O número de vagas parece estável, então o voto pesa mais na disputa interna, entre quem está perto do corte.";
    tom = perto || ameacada ? "info" : "neutro";
  }
  return secao("Onde seu voto pesa mais", `
      <div class="faixas">
        <div class="faixa-item${faixaEu === "certo" ? " atual" : ""}"><strong>Quase certos</strong><span>Estão bem acima do corte e tendem a entrar de qualquer jeito.</span></div>
        <div class="faixa-item${faixaEu === "disputa" ? " atual" : ""}"><strong>Na disputa</strong><span>Estão perto do corte, onde o voto decide quem entra.</span></div>
        <div class="faixa-item${faixaEu === "longe" ? " atual" : ""}"><strong>Longe do corte</strong><span>O voto neles ajuda a lista e os primeiros colocados.</span></div>
      </div>
      <p style="margin-top:14px">${textos[faixaEu]}</p>
      ${disputa ? `<p style="margin-top:12px">Quem está perto do corte nesta lista:</p><div class="chips">${disputa}</div>` : ""}
      <p style="margin-top:14px">${margemTexto}</p>`,
  leitura(tom, "O voto tem mais efeito onde a disputa está apertada, seja entre candidatos perto da linha de corte, seja em listas perto de ganhar ou perder uma vaga.",
    "As margens foram calculadas com os votos de 2022 e são aproximadas."));
}

// ---------- Quem é ----------

function painelQuem() {
  const f = ficha.f;
  const anos = idade(f.nascimento);
  const perfil = [
    ["Idade", anos != null ? `${anos} anos` : null], ["Ocupação", f.ocupacao], ["Escolaridade", f.instrucao],
    ["Naturalidade", naturalidade(f.naturalidade)], ["Estado civil", f.estadoCivil],
    ["Cor/raça (autodeclarada)", f.corRaca && nomeProprio(f.corRaca)], ["Gênero", GENEROS[f.sexo] || f.sexo],
  ].filter(([, v]) => v);

  const chapa = f.vices.length ? secao("Chapa", f.vices.map((v) => `<div class="vice">${fotoHtml(v.uf, v.id, v.nomeUrna)}
      <div><div class="cand-nome">${esc(nomeProprio(v.nomeUrna))}</div><div class="cand-meta">${esc(v.cargo)}, ${esc(v.partido)}</div></div></div>`).join(""),
  leitura("neutro", f.codCargo === 5
    ? "Os suplentes assumem a vaga quando o senador se afasta, por exemplo para virar ministro. Isso acontece com frequência, então vale saber quem são."
    : "O vice assume se o titular deixar o cargo, por isso também vale conhecer quem vem na chapa.")) : "";

  const traj = ficha.a?.trajetoria;
  const blocoTraj = traj ? htmlTrajetoria(traj, f) : htmlTrajetoriaSimples(f);
  const blocoBens = htmlPatrimonio(f, traj);
  const blocoEmpresas = htmlEmpresasSocio(ficha.a?.empresas);
  const blocoNoticias = htmlNoticias(ficha.n, f);

  const links = [
    ...f.sites.map((s) => {
      const url = /^https?:\/\//i.test(s) ? s : `https://${s}`;
      let rotulo = s;
      try { rotulo = new URL(url.toLowerCase()).hostname.replace(/^www\./, ""); } catch { /* mantém o texto */ }
      return `<a href="${esc(url.toLowerCase())}" target="_blank" rel="noopener">${esc(rotulo)}</a>`;
    }),
    `<a href="${esc(f.linkTse)}" target="_blank" rel="noopener">Página oficial no TSE</a>`,
  ];

  return `<p class="painel-intro">Quem é a pessoa por trás do número: o perfil, a chapa, a trajetória nas eleições, o que declarou ter e as empresas de que é sócia.</p>
    ${secao("Perfil", `<dl class="grade">${perfil.map(([k, val]) => `<div><dt>${esc(k)}</dt><dd>${esc(val)}</dd></div>`).join("")}</dl>`)}
    ${chapa}
    ${blocoTraj}
    ${blocoBens}
    ${blocoEmpresas}
    ${blocoNoticias}
    ${secao("Links", `<div class="links">${links.join("")}</div>`)}
    <p class="fonte">Fonte: TSE, DivulgaCandContas. Registro atualizado em ${esc(dataBr(f.atualizadoEm))}.</p>`;
}

// Manchetes recentes (Google Notícias): só título, veículo, data e link. Contexto, não prova; não entra na nota.
function htmlNoticias(n, f) {
  if (!n) return secao("Nas notícias", `<p class="explica">Buscando notícias dos últimos 6 meses…</p>`);
  if (n.erro) return secao("Nas notícias", `<p class="explica">A busca de notícias não respondeu agora. Tente abrir a ficha de novo mais tarde.</p>`);
  if (!n.noticias?.length) {
    return secao("Nas notícias", `<p class="explica">Nenhuma manchete dos últimos 6 meses cita ${esc(nomeProprio(f.nomeUrna))} pelo nome de urna.</p>`);
  }
  const mostrar = 6;
  const item = (x) => `<li class="noticia${x.risco ? " risco" : ""}">
      <a href="${esc(x.link)}" target="_blank" rel="noopener">${esc(x.titulo)}</a>
      <small>${esc(x.veiculo || x.site)}${x.data ? ` · ${dataBr(x.data)}` : ""}${x.risco ? ` · <span class="badge warn">fala de investigação ou processo</span>` : ""}</small>
    </li>`;
  // As que falam de investigação vêm primeiro; o resto por data.
  const ordem = [...n.noticias].sort((a, b) => (b.risco - a.risco) || (b.data || "").localeCompare(a.data || ""));
  const assuntos = n.assuntos?.length
    ? `<div class="noticias-assuntos"><span>Assuntos mais citados</span><div class="chips">${n.assuntos.map((a) => `<span class="chip">${esc(a.termo)} <small>${a.vezes}</small></span>`).join("")}</div></div>` : "";
  const lista = `<ul class="noticias">${ordem.slice(0, mostrar).map(item).join("")}</ul>
    ${ordem.length > mostrar ? `<details class="mais"><summary>Ver as ${ordem.length} manchetes</summary><ul class="noticias">${ordem.slice(mostrar).map(item).join("")}</ul></details>` : ""}`;
  const texto = n.comRisco
    ? `${n.comRisco === 1 ? "Uma manchete fala" : `${n.comRisco} manchetes falam`} de investigação, processo ou acusação. Notícia não é condenação: leia a matéria e veja se há decisão da Justiça.`
    : "Nenhuma manchete recente fala de investigação ou processo. Os assuntos mostram do que a imprensa mais tem falado sobre a pessoa.";
  return secao(`Nas notícias <span class="emp-conta">${n.total}</span>`,
    assuntos + lista + `<p class="fonte">Fonte: Google Notícias, manchetes dos últimos 6 meses que citam o nome de urna (busca de ${esc(n.geradoEm)}). O app guarda só título, veículo e link.</p>`,
    leitura(n.comRisco ? "atencao" : "neutro", texto));
}

// Empresas em que a pessoa é sócia (base de sócios da Receita), com o que o dinheiro público e de campanha diz de cada uma.
function htmlEmpresasSocio(emp) {
  if (!emp) return "";
  const st = emp.status || {};
  if (!emp.lista) {
    return st.etapa === "erro" ? "" : secao("Empresas e entidades", `<p class="explica">Os dados de sócios da Receita ainda estão sendo baixados${st.progresso ? ` (${esc(st.etapa)}, ${esc(st.progresso)})` : ""}. Volte daqui a pouco.</p>`);
  }
  const fonte = `<p class="fonte">Fonte: Receita Federal, dados abertos do CNPJ (${esc(st.mes || "")}); punições: TCU, Ministério do Trabalho, Ibama e CGU. O CPF dos sócios vem parcialmente escondido, então o app confere os 6 dígitos visíveis e o nome completo.</p>`;
  if (!emp.lista.length) {
    return secao("Empresas e entidades", `<p class="explica">Não aparece como sócio(a) de nenhuma empresa na base da Receita.</p>${fonte}`);
  }
  const itens = emp.lista.map((e) => {
    const marcas = [];
    if (e.campanhaPropria) marcas.push(`<span class="badge warn">Recebeu ${brlCompacto.format(e.campanhaPropria)} desta campanha</span>`);
    if (e.outrasCampanhas?.quantas) marcas.push(`<span class="badge ${e.outrasCampanhas.total >= 10000 ? "warn" : "neutro"}">Recebeu ${brlCompacto.format(e.outrasCampanhas.total)} de ${e.outrasCampanhas.quantas} ${e.outrasCampanhas.quantas === 1 ? "outra campanha" : "outras campanhas"}</span>`);
    if (e.emendas?.total) marcas.push(`<span class="badge warn">Recebeu ${brlCompacto.format(e.emendas.total)} em emendas</span>`);
    if (e.sancoes?.length) marcas.push(`<span class="badge bad">Punida (${esc([...new Set(e.sancoes.map((s) => s.sigla))].join(", "))})</span>`);
    const fontes = new Set((e.punicoes || []).filter((p) => p.vigente || p.fonte === "tcu_irregular" || p.fonte === "tcu_eleitoral").map((p) => p.fonte));
    if (fontes.has("escravo")) marcas.push(`<span class="badge bad">Lista suja do trabalho escravo</span>`);
    if (fontes.has("tcu_eleitoral") || fontes.has("tcu_irregular")) marcas.push(`<span class="badge warn">Contas irregulares no TCU</span>`);
    if (fontes.has("tcu_inidoneo")) marcas.push(`<span class="badge warn">Proibida de licitar (TCU)</span>`);
    if (fontes.has("ibama")) marcas.push(`<span class="badge warn">Embargo do Ibama</span>`);
    if (e.situacao && e.situacao !== "Ativa") {
      marcas.push(`<span class="badge ${e.situacao === "Baixada" ? "neutro" : "warn"}" title="Situação na Receita Federal${e.dataSituacao ? ` desde ${dataBr(e.dataSituacao)}` : ""}">${esc(e.situacao)} na Receita</span>`);
    }
    const detalhes = [e.qualificacao, e.entrada ? `sócio(a) desde ${dataBr(e.entrada)}` : null,
      e.atividade ? nomeProprio(e.atividade) : null, e.cidade || null, e.abertura ? `aberta em ${dataBr(e.abertura)}` : null,
      e.porte !== "Demais" ? e.porte : null, e.capital ? `capital de ${brlCompacto.format(e.capital)}` : null].filter(Boolean).join(" · ");
    return `<li class="emp-socio">
      <div class="emp-socio-cab"><strong>${esc(nomeProprio(e.razao || `CNPJ ${e.basico}`))}</strong>
        <button type="button" class="link-acao link-inline" data-empresa="${esc(e.cnpj)}">Ver a ficha</button></div>
      <small>${esc(detalhes)}</small>
      ${marcas.length ? `<div class="chips">${marcas.join("")}</div>` : ""}
    </li>`;
  });
  const punida = (e) => e.sancoes?.length || (e.punicoes || []).some((p) => p.fonte.startsWith("tcu") || p.fonte === "escravo" || (p.fonte === "ibama" && p.vigente));
  const comDinheiro = emp.lista.filter((e) => e.campanhaPropria || e.outrasCampanhas?.quantas || e.emendas?.total || punida(e)).length;
  const texto = comDinheiro
    ? `${comDinheiro === 1 ? "Uma das empresas recebeu" : `${comDinheiro} das empresas receberam`} dinheiro de campanha ou de emendas, ou tem punição. Isso não é ilegal por si só, mas mostra onde interesses privados e públicos se encontram.`
    : "Ter empresa é comum e não indica problema. O app só avisa quando a empresa recebe dinheiro de campanha ou de emendas, ou tem punição (TCU, trabalho escravo, Ibama ou cadastros de punidos).";
  const mostrar = 5;
  const lista = `<ul class="emp-socios">${itens.slice(0, mostrar).join("")}</ul>
    ${itens.length > mostrar ? `<details class="mais"><summary>Ver todas as ${itens.length} empresas</summary><ul class="emp-socios">${itens.slice(mostrar).join("")}</ul></details>` : ""}`;
  return secao(`Empresas e entidades <span class="emp-conta">${emp.lista.length}</span>`, lista + fonte,
    leitura(comDinheiro ? "atencao" : "neutro", texto));
}

const RESULTADOS = {
  "Eleito por QP": ["Eleito pelos próprios votos", "Teve votos suficientes para ficar entre as vagas que a lista conquistou (QP é o quociente partidário)."],
  "Eleito por média": ["Eleito pela sobra de vagas", "Entrou na distribuição das vagas que sobram depois da primeira divisão, pelo cálculo da média."],
  "Média": ["Eleito pela sobra de vagas", "Entrou na distribuição das vagas que sobram depois da primeira divisão, pelo cálculo da média. É uma eleição válida como qualquer outra."],
  "Eleito": ["Eleito", ""],
  "Suplente": ["Ficou como suplente", "Não entrou, mas pode assumir se alguém da lista deixar o cargo."],
};

function textoResultado(r) {
  return RESULTADOS[r] || [r || "", ""];
}

function htmlTrajetoriaSimples(f) {
  const hist = [...f.historico].sort((x, y) => y.ano - x.ano);
  if (!hist.length) {
    return secao("Trajetória eleitoral", `<p class="explica">Primeira candidatura registrada no TSE.</p>`,
      leitura("neutro", "É a primeira eleição que disputa, pelos registros do TSE, que começam em 2004."));
  }
  return secao("Trajetória eleitoral", `<ol class="linha-tempo">${hist.map((h) => `<li>
      <span class="lt-ano">${esc(h.ano)}</span>
      <span class="lt-desc"><strong>${esc(h.cargo)}</strong> em ${esc(nomeProprio(h.local))}, pelo ${esc(h.partido)}</span>
      <span class="lt-res">${esc(h.resultado)}</span></li>`).join("")}</ol>`, ficha.a ? "" : leitura("neutro", "Carregando a análise da trajetória…"));
}

function htmlTrajetoria(t, f) {
  const r = t.resumo;
  const links = new Map(f.historico.map((h) => [`${h.ano}`, h.link]));
  const linhas = [...t.linhas].reverse();
  if (!r.candidaturas) {
    return secao("Trajetória eleitoral", `<p class="explica">É a primeira candidatura registrada no TSE.</p>`,
      leitura("neutro", "Os registros do TSE começam em 2004. Não há votos nem mandatos anteriores para comparar."));
  }
  const mudouNome = r.siglas.length > r.partidos.length;
  const itens = linhas.map((l) => {
    const [res, explica] = l.atual ? ["Concorre agora", ""] : textoResultado(l.resultado);
    const sigla = l.partido && l.partidoAtual && l.partido.toUpperCase() !== l.partidoAtual ? `${esc(l.partido)}, hoje ${esc(l.partidoAtual)}` : esc(l.partido);
    const link = links.get(`${l.ano}`);
    return `<li class="${l.eleito ? "venceu" : ""}${l.atual ? " atual" : ""}">
      <span class="lt-ano">${l.ano}</span>
      <span class="lt-desc"><strong>${esc(l.cargo)}</strong> ${l.municipal ? `em ${esc(l.local)}` : l.local ? `por ${esc(l.local)}` : ""}, pelo ${sigla}
        ${l.ocupacao || l.bens != null ? `<small>${l.ocupacao ? `Profissão declarada: ${esc(l.ocupacao.toLowerCase())}.` : ""}${l.bens != null ? ` ${l.bens ? `Bens: ${brlCompacto.format(l.bens)}.` : "Não declarou bens."}` : ""}</small>` : ""}</span>
      <span class="lt-res" ${explica ? `title="${esc(explica)}"` : ""}>${link && !l.atual ? `<a href="${esc(link)}" target="_blank" rel="noopener">${esc(res)}</a>` : esc(res)}</span>
    </li>`;
  }).join("");
  const tiles = `<div class="tiles">
      <div class="tile"><div class="rot">Tempo em mandato</div><div class="val">${r.anosEmMandato} ${r.anosEmMandato === 1 ? "ano" : "anos"}</div>
        <div class="det">Dos ${r.anosDesdePrimeira} anos desde a primeira eleição, em ${r.primeiraEleicao}.</div></div>
      <div class="tile"><div class="rot">Eleições</div><div class="val">${r.vitorias} de ${r.candidaturas}</div>
        <div class="det">Venceu ${r.vitorias === 1 ? "uma" : r.vitorias} das ${r.candidaturas} que disputou.</div></div>
      <div class="tile"><div class="rot">Partidos</div><div class="val">${r.partidos.length}</div>
        <div class="det">${listaNatural(r.siglas.map(esc))}${mudouNome ? ", contando nomes antigos do mesmo partido" : ""}.</div></div>
    </div>`;
  const partes = [];
  if (r.anosEmMandato) partes.push(`Esteve em mandato ${r.anosEmMandato} dos últimos ${r.anosDesdePrimeira} anos, como ${listaNatural(r.cargosOcupados.map((c) => esc(c.toLowerCase())))}.`);
  else partes.push(`Disputou ${r.candidaturas === 1 ? "uma eleição" : `${r.candidaturas} eleições`} e não se elegeu em nenhuma.`);
  if (r.municipios.length) partes.push(`Concorreu a cargos municipais em ${listaNatural(r.municipios.map(esc))}.`);
  if (mudouNome) partes.push(`${listaNatural(r.siglas.filter((x) => !r.partidos.includes(x.toUpperCase())).map(esc))} ${r.siglas.length - r.partidos.length === 1 ? "é o nome antigo" : "são nomes antigos"} de um partido que ainda existe, então não é troca de partido.`);
  if (r.ocupacoes.length > 1) partes.push(`A profissão declarada mudou com o tempo: a primeira foi "${esc(r.ocupacoes[0].toLowerCase())}" e a atual é "${esc(r.ocupacoes[r.ocupacoes.length - 1].toLowerCase())}".`);
  const carreira = r.anosEmMandato >= 12;
  const temMedia = t.linhas.some((l) => l.resultado === "Média" || l.resultado === "Eleito por média");
  return secao("Trajetória eleitoral", tiles + `<ol class="linha-tempo">${itens}</ol>`,
    leitura(carreira ? "info" : "neutro", partes.join(" "),
      (carreira ? "Passar muitos anos em mandato não é problema em si. Vale olhar como a pessoa trabalha, na aba Atuação política. " : "") +
      (temMedia ? "<strong>Eleito pela sobra de vagas</strong> (o TSE escreve \"Média\") quer dizer que a pessoa entrou numa das vagas que sobram depois da primeira divisão. É uma vitória tão válida quanto as outras. " : "") +
      "Passe o mouse sobre o resultado para ver a explicação."));
}

function htmlPatrimonio(f, t) {
  const topo = f.bens.slice(0, 3);
  const lista = f.bens.length ? `
    <ul class="bens-topo">${topo.map((b) => `<li><span>${esc(b.tipo)}<small>${esc(b.descricao)}</small></span><strong>${esc(brlCompacto.format(b.valor))}</strong></li>`).join("")}</ul>
    ${f.bens.length > 3 ? `<details class="mais"><summary>Ver todos os ${f.bens.length} bens</summary>
      <div class="tabela-rolagem"><table class="lista"><thead><tr><th>Tipo</th><th>Descrição</th><th class="num">Valor</th></tr></thead>
      <tbody>${f.bens.map((b) => `<tr><td>${esc(b.tipo)}</td><td>${esc(b.descricao)}</td><td class="num">${esc(brl.format(b.valor))}</td></tr>`).join("")}</tbody></table></div></details>` : ""}`
    : `<p class="explica">Não declarou bens nesta eleição.</p>`;
  const declarados = (t?.linhas || []).filter((l) => l.bens != null);
  const grafico = declarados.length >= 2 ? `<p class="nota-sub">Patrimônio declarado em cada eleição, em valores de hoje (corrigido pelo IPCA):</p>
    ${barras(declarados.map((l) => ({ nome: `${l.ano}`, valor: l.bensHoje || 0 })), 0, (v) => brlCompacto.format(v))}` : "";
  const sinal = (ficha.a?.sinais || []).find((s) => /patrimônio/i.test(s.titulo) && s.fonte.includes("IPCA"));
  const aside = !ficha.a ? "" : sinal
    ? leitura(sinal.nivel === "atencao" ? "atencao" : "ok", esc(sinal.detalhe),
      "Os valores são os que a própria pessoa informou ao TSE, muitas vezes pelo preço de compra e não pelo de mercado. Corrigir pela inflação mostra se o patrimônio cresceu de verdade ou só acompanhou os preços.")
    : leitura("neutro", "Não há declaração anterior para comparar. Os valores são os que o próprio candidato informou ao TSE, muitas vezes pelo preço de compra e não pelo de mercado.");
  return secao("Patrimônio declarado", `
    <div class="tiles"><div class="tile"><div class="rot">Total declarado agora</div><div class="val">${brl.format(f.totalBens)}</div>
      <div class="det">Soma de ${f.bens.length} ${f.bens.length === 1 ? "bem" : "bens"}.</div></div></div>
    ${grafico}${lista}`, aside);
}

// ---------- Atuação política ----------

function tomProjetos(t) {
  const m = t.medianas || {};
  const avancaram = (t.etapas.lei || 0) + (t.etapas.aprovada || 0);
  const taxa = t.projetos ? avancaram / t.projetos : 0;
  if (avancaram >= 2 && m.avancaram != null && taxa > 3 * Math.max(m.avancaram, 0.005)) return "info";
  return "ok";
}

function medidorComparado(valor, marcas) {
  return `<div class="medidor2">
    <div class="trilho"><div class="cheio" style="width:${Math.round(valor * 100)}%"></div>
      ${marcas.map((m, i) => `<span class="marca m${i}" style="left:${m.valor * 100}%" title="${esc(m.rotulo)}: ${pct.format(m.valor)}"></span>`).join("")}</div>
    <div class="escala"><span>0%</span><span>50%</span><span>100%</span></div>
    <div class="legenda2"><span><i class="marca-leg cheio-leg"></i>Este candidato: ${pct.format(valor)}</span>${marcas.map((m, i) => `<span><i class="marca-leg m${i}"></i>${esc(m.rotulo)}: ${pct.format(m.valor)}</span>`).join("")}</div>
  </div>`;
}

function painelPolitica() {
  const a = ficha.a;
  if (!a) return ficha.erroAnalise ? `<p class="erro">${esc(ficha.erroAnalise)}</p>` : esqueleto();
  const o = a.orientacao;
  if (!o.pronto) {
    return `<p class="painel-intro">Os dados da Câmara ainda estão sendo preparados (${esc(o.status?.etapa || "…")}). Feche e abra a ficha de novo em um ou dois minutos.</p>`;
  }
  const d = o.deputado;
  const est = a.estadual;
  if (!d && est) {
    const sub = ["alesp", "partido"].includes(ficha.sub.politica) ? ficha.sub.politica : "alesp";
    ficha.sub.politica = sub;
    const introEst = `<p class="painel-intro">O trabalho de ${esc(nomeProprio(ficha.f.nomeUrna))} como deputado estadual, com os dados abertos da Assembleia Legislativa de São Paulo desde março de 2023.</p>`;
    return introEst + subnav("politica", [["alesp", "Trabalho na ALESP"], ["partido", "Bancada do partido na Câmara"]]) +
      (sub === "alesp" ? painelAlesp(est) : avisoBancada(o) + posicoesPartido(o));
  }
  const intro = `<p class="painel-intro">${d ? "Como vota e o que produziu no mandato de deputado federal" : "Como o partido desta candidatura se posiciona na Câmara"}, com dados da Câmara dos Deputados desde fevereiro de 2023.</p>`;
  const plano = o.planoDeGoverno
    ? secao("Plano de governo", `<p>A candidatura registrou um plano de governo no TSE. Ele está na <a href="${esc(ficha.f.linkTse)}" target="_blank" rel="noopener">página oficial</a>, junto dos outros arquivos.</p>`,
      leitura("neutro", "É o documento com as propostas oficiais da candidatura e a melhor fonte para saber o que ela promete fazer."))
    : "";
  if (!d) return intro + avisoBancada(o) + posicoesPartido(o) + plano;

  const opcoes = [["posicoes", "Posições"], ["projetos", "Projetos"], ["emendas", "Emendas ao Orçamento"]];
  const sub = ficha.sub.politica;
  const conteudo = sub === "projetos" ? painelProjetos(a.trabalho) : sub === "emendas" ? painelEmendas(a.trabalho) : posicoesDeputado(o);
  return intro + subnav("politica", opcoes) + conteudo + (sub === "posicoes" ? plano : "");
}

function posicoesDeputado(o) {
  const d = o.deputado;
  const p = o.partido;
  const m = o.medianas || {};
  let governo = "";
  if (d.governismo != null) {
    const marcas = [];
    if (p?.governismo != null) marcas.push({ rotulo: `Bancada do ${sigla(p.sigla)}`, valor: p.governismo });
    if (m.governismo != null) marcas.push({ rotulo: "Mediana da Câmara", valor: m.governismo });
    const dif = p?.governismo != null ? d.governismo - p.governismo : null;
    const comparacao = dif == null ? "" : Math.abs(dif) < 0.05
      ? ` Vota de forma parecida com a bancada do ${esc(sigla(p.sigla))}.`
      : ` É ${dif > 0 ? "mais" : "menos"} alinhado ao governo que a própria bancada do ${esc(sigla(p.sigla))}, que ficou em ${pct.format(p.governismo)}.`;
    governo = secao("Votou com o governo federal", `
        <div class="numero-grande">${pct.format(d.governismo)}<small>das ${numero.format(d.votacoesComGoverno)} votações em que o governo indicou como votar</small></div>
        ${medidorComparado(d.governismo, marcas)}`,
    leitura("neutro", `Votou como o governo pediu em ${pct.format(d.governismo)} das vezes.${comparacao}`,
      "O número mostra o grau de apoio ou de oposição ao governo Lula. Ele diz mais sobre a relação com o governo atual do que sobre ser de esquerda ou de direita."));
  }
  let partido = "";
  if (d.fidelidade != null) {
    const baixa = m.fidelidade != null && d.fidelidade < m.fidelidade - 0.1;
    partido = secao("Votou com o próprio partido", `
        <div class="numero-grande">${pct.format(d.fidelidade)}<small>das votações em que acompanhou a maioria da bancada do ${esc(d.partido)}</small></div>
        ${m.fidelidade != null ? medidorComparado(d.fidelidade, [{ rotulo: "Mediana da Câmara", valor: m.fidelidade }]) : ""}`,
    leitura(baixa ? "info" : "neutro",
      baixa ? `Diverge do próprio partido com mais frequência que a maioria dos deputados, que acompanha a bancada em ${pct.format(m.fidelidade)} das vezes.`
        : `Costuma votar junto com o partido, como a maioria dos deputados${m.fidelidade != null ? `, que acompanha a bancada em ${pct.format(m.fidelidade)} das vezes` : ""}.`,
      "Votar sempre com o partido mostra disciplina. Divergir com frequência pode indicar independência ou atrito com a bancada."));
  }
  let presenca = "";
  if (d.participacao != null) {
    const todas = m.participacao;
    const tom = todas == null ? "neutro" : d.participacao >= todas - 0.05 ? "ok" : d.participacao < todas - 0.25 ? "atencao" : "info";
    presenca = secao("Presença nas votações", `
        <div class="numero-grande">${pct.format(d.participacao)}<small>das votações do plenário, contando só o período em que exerceu o mandato</small></div>
        ${todas != null ? medidorComparado(d.participacao, [{ rotulo: "Mediana da Câmara", valor: todas }]) : ""}`,
    leitura(tom, tom === "ok" ? "Participou tanto quanto a maioria dos deputados, ou mais."
      : tom === "atencao" ? `Participou bem menos que a maioria, que votou em ${pct.format(todas)} das sessões.` : `Participou um pouco menos que a maioria, que votou em ${pct.format(todas)} das sessões.`,
    "As faltas podem ter motivo, como licença médica, missão oficial ou um período como secretário ou ministro."));
  }
  const temas = d.temas?.length ? secao("Temas que mais defende", htmlTemas(d.temas, d.temasDestaque),
    leitura("neutro", d.temasDestaque?.length
      ? `Os temas em azul, ${listaNatural(d.temasDestaque.map((t) => esc(t[0].toLowerCase())))}, são os que mais caracterizam a atuação, porque recebem mais projetos do que na média da Câmara.`
      : "Os projetos se espalham pelos temas de forma parecida com a média da Câmara, sem um foco que se destaque.",
    "O número ao lado de cada tema é a quantidade de projetos. O tema Direitos Humanos e Minorias aparece para quase todos porque a Câmara o usa de forma bem ampla.")) : "";
  return governo + partido + presenca + temas +
    `<p class="fonte">Dados abertos da Câmara dos Deputados. Veja também o <a href="https://www.camara.leg.br/deputados/${esc(d.id)}" target="_blank" rel="noopener">perfil na Câmara</a>.</p>`;
}

function avisoBancada(o) {
  if (!o.partido) return "";
  return `<p class="aviso-bancada">Os números abaixo são da <strong>bancada do ${esc(sigla(o.partido.sigla))} na Câmara dos Deputados</strong>, e não desta pessoa, que não tem mandato de deputado federal. Servem para mostrar como o partido costuma agir.</p>`;
}

const CLASSES_PROJETO = [
  ["geral", "Mudam alguma regra", "Criam, alteram ou revogam regras que valem para o estado."],
  ["local", "Benefício local", "Classificam um município como turístico ou estância, o que dá acesso a um fundo estadual."],
  ["simbolica", "Homenagens e datas", "Dão nome a estradas e viadutos, declaram utilidade pública, criam datas e títulos."],
];

function painelAlesp(e) {
  const m = e.medianas || {};
  const nome = esc(nomeProprio(ficha.f.nomeUrna));
  const geral = e.projetos - e.simbolicos - e.locais;
  const parteSimb = e.projetos ? e.simbolicos / e.projetos : 0;
  const simbAlto = e.projetos >= 10 && parteSimb >= 0.15 && parteSimb >= 2 * (m.simbolicos || 0);
  const comparaSimb = parteSimb >= 2 * (m.simbolicos || 0) ? `${parteSimb >= 3 * (m.simbolicos || 0) ? "mais que o triplo" : "o dobro ou mais"} dos ${pct.format(m.simbolicos || 0)} de um deputado estadual típico`
    : parteSimb >= 1.3 * (m.simbolicos || 0) ? `acima dos ${pct.format(m.simbolicos || 0)} de um deputado estadual típico`
      : `perto dos ${pct.format(m.simbolicos || 0)} de um deputado estadual típico, ou abaixo`;

  const temas = e.temas.filter(([, n]) => n >= 2);
  const principais = temas.slice(0, 3).map(([t]) => esc(t.toLowerCase()));
  const defende = secao("O que defende", `
      ${temas.length ? `<div class="chips">${temas.map(([t, n]) => `<span class="chip">${esc(t)}: ${n}</span>`).join("")}</div>` : `<p class="explica">Os projetos que mudam regras são poucos para apontar um tema principal.</p>`}
      ${e.areas?.length ? `<p style="margin-top:12px">Áreas que o próprio gabinete diz priorizar: ${listaNatural(e.areas.map((x) => esc(x.toLowerCase())))}.</p>` : ""}
      ${e.exemplos?.length ? `<p class="nota-sub">Alguns projetos que mudam regras:</p><ul class="projetos">${e.exemplos.slice(0, 4).map((x) => `<li class="projeto"><div class="tit">${esc(x.nome)}</div><div class="det">${esc(x.ementa)}</div></li>`).join("")}</ul>` : ""}`,
    leitura("neutro", principais.length
      ? `Entre os projetos que mudam regras, os temas que mais aparecem são ${listaNatural(principais)}. O número ao lado de cada tema é a quantidade de projetos.`
      : "Não há projetos suficientes para apontar um tema principal.",
    "Os temas saem das palavras-chave que a própria ALESP dá a cada projeto. Homenagens e benefícios locais ficam de fora dessa conta, para não esconder o que a pessoa realmente propõe."));

  const pilha = CLASSES_PROJETO.map(([k, rot]) => {
    const n = k === "geral" ? geral : k === "local" ? e.locais : e.simbolicos;
    return { k, rot, n };
  });
  const tipos = secao("Que tipo de projeto apresenta", `
      <div class="pilha" role="img" aria-label="${pilha.map((x) => `${x.rot}: ${x.n}`).join(", ")}">${pilha.map((x) => x.n ? `<span class="pilha-${x.k}" style="flex:${x.n}" title="${x.rot}: ${x.n}"></span>` : "").join("")}</div>
      <ul class="pilha-legenda">${CLASSES_PROJETO.map(([k, rot, expl]) => {
        const n = pilha.find((x) => x.k === k).n;
        return `<li><i class="pilha-${k}"></i><strong>${rot}: ${numero.format(n)}</strong><span>${expl}</span></li>`;
      }).join("")}</ul>`,
    leitura(simbAlto ? "info" : "ok",
      `De ${numero.format(e.projetos)} projetos desde 2023, ${pct.format(parteSimb)} são homenagens ou datas, ${comparaSimb}.`,
      "Homenagens custam pouco esforço e raramente mudam a vida das pessoas. Quando são muitas, costumam indicar um mandato voltado à visibilidade."));

  const gerais = e.leis.filter((l) => l.classe === "geral");
  const leis = secao("Leis aprovadas desde 2023", `
      <div class="tiles">
        <div class="tile"><div class="rot">Mudam regras</div><div class="val">${numero.format(e.leisSubstantivas)}</div><div class="det">Um deputado estadual típico tem ${m.leisSubstantivas ?? "—"}.</div></div>
        <div class="tile"><div class="rot">Benefício local</div><div class="val">${numero.format(e.leisLocais)}</div><div class="det">Municípios turísticos e estâncias.</div></div>
        <div class="tile"><div class="rot">Homenagens e datas</div><div class="val">${numero.format(e.leisSimbolicas)}</div><div class="det">Um deputado estadual típico tem ${m.leisSimbolicas ?? "—"}.</div></div>
      </div>
      ${gerais.length ? `<ul class="projetos">${gerais.slice(0, 5).map((l) => `<li class="projeto"><div class="tit">${l.link ? `<a href="${esc(l.link)}" target="_blank" rel="noopener">Lei ${esc(l.numero)}</a>` : `Lei ${esc(l.numero)}`}<span class="fnt">${esc(dataBr(l.data))}</span></div><div class="det">${esc(l.ementa)}</div></li>`).join("")}</ul>` : ""}`,
    leitura("neutro", e.leisSubstantivas
      ? `${e.leisSubstantivas === 1 ? "Uma lei que muda regras tem" : `${e.leisSubstantivas} leis que mudam regras têm`} ${nome} entre os autores.`
      : `Nenhuma lei que muda regras tem ${nome} entre os autores desde 2023, o que não é raro: a maioria das leis estaduais vem do governador.`,
    "Conta a lei quando a pessoa é autora ou coautora do projeto. Muitas leis têm vários autores."));

  const pr = e.presenca;
  const presenca = pr ? secao("Presença nas comissões", `
      <div class="numero-grande">${pct.format(pr.taxa)}<small>das ${pr.reunioes} reuniões das comissões de que é titular, com presença em ${pr.presente}</small></div>
      ${m.presenca != null ? medidorComparado(pr.taxa, [{ rotulo: "Deputado estadual típico", valor: m.presenca }]) : ""}`,
    leitura(pr.taxa < (m.presenca || 0) / 2 ? "atencao" : pr.taxa < (m.presenca || 0) - 0.1 ? "info" : "ok",
      pr.taxa < (m.presenca || 0) / 2 ? `Foi a bem menos reuniões que a maioria, que vai a ${pct.format(m.presenca)}.`
        : `Um deputado estadual típico vai a ${pct.format(m.presenca || 0)} das reuniões.`,
      "É nas comissões que os projetos são discutidos e votados antes do plenário. A ALESP publica a lista de presença das reuniões realizadas.")) : "";

  const pedidos = secao("Pedidos e fiscalização", `
      <div class="tiles">
        <div class="tile"><div class="rot">Indicações ao governador</div><div class="val">${numero.format(e.indicacoes)}</div><div class="det">Pedidos de obra, verba ou serviço. Um deputado típico faz ${numero.format(Math.round(m.indicacoes || 0))}.</div></div>
        <div class="tile"><div class="rot">Pedidos de informação</div><div class="val">${numero.format(e.requerimentosInformacao)}</div><div class="det">Perguntas formais ao governo. Um deputado típico faz ${numero.format(Math.round(m.requerimentosInformacao || 0))}.</div></div>
      </div>
      ${e.municipiosIndicacoes?.length ? `<p style="margin-top:12px">Os municípios que mais aparecem nas indicações são ${listaNatural(e.municipiosIndicacoes.slice(0, 5).map(([x]) => esc(x)))}.</p>` : ""}`,
    leitura("neutro", "As indicações mostram para onde a pessoa tenta levar obras e verbas, o que costuma coincidir com a base eleitoral. Os pedidos de informação são a principal ferramenta de fiscalização do governo.",
      "Nenhum dos dois é bom ou ruim por si: dependem do que você espera de um deputado."));

  const v = e.verba;
  const verba = v ? secao("Verba de gabinete", `
      <div class="numero-grande">${brlCompacto.format(v.mediaMensal)}<small>por mês, em média, desde 2023. Um deputado estadual típico gasta ${brlCompacto.format(m.verbaMensal || 0)}.</small></div>
      ${barras(v.categorias.map(([nome, valor]) => ({ nome, valor })), v.total, (x) => brlCompacto.format(x))}
      <p class="nota-sub">Quem mais recebeu:</p>
      <ul class="bens-topo">${v.fornecedores.slice(0, 6).map((x) => `<li><span>${esc(nomeProprio(x.nome || ""))}${x.cnpj.length === 14 ? `<small><button type="button" class="link-acao link-inline" data-empresa="${esc(x.cnpj)}">Ver a ficha da empresa</button></small>` : "<small>Pessoa física</small>"}</span><strong>${brlCompacto.format(x.valor)}</strong></li>`).join("")}</ul>`,
    leitura(v.mediaMensal > 1.3 * (m.verbaMensal || Infinity) ? "info" : "ok",
      v.mediaMensal > 1.3 * (m.verbaMensal || Infinity) ? "Gasta bem mais que um deputado estadual típico." : "O gasto está perto do de um deputado estadual típico, ou abaixo.",
      "A verba paga escritório, carro, combustível e divulgação do mandato. Vale olhar se os fornecedores são empresas comuns do ramo.")) : "";

  return defende + tipos + leis + presenca + pedidos + verba +
    `<p class="fonte">Dados abertos da ALESP, atualizados em ${esc(dataBr(e.geradoEm.slice(0, 10)))}.</p>`;
}

function posicoesPartido(o) {
  const p = o.partido;
  if (!p) {
    return secao("Posições", `<p>O partido não tem bancada na Câmara nesta legislatura, então não há votações para comparar.</p>`,
      leitura("neutro", "Sem votações para comparar, as melhores fontes são o plano de governo e as propostas divulgadas pela campanha."));
  }
  const m = o.medianas || {};
  return secao(`Bancada do ${esc(sigla(p.sigla))} na Câmara`, `
      ${p.governismo != null ? `<div class="numero-grande">${pct.format(p.governismo)}<small>das vezes a bancada votou como o governo federal pediu</small></div>
      ${medidorComparado(p.governismo, m.governismo != null ? [{ rotulo: "Mediana da Câmara", valor: m.governismo }] : [])}` : ""}
      ${p.temas?.length ? `<p style="margin-top:16px">Os temas em que a bancada mais apresenta projetos:</p>${htmlTemas(p.temas, p.temasDestaque)}` : ""}`,
  leitura("neutro", "Como esta pessoa não foi deputada federal nesta legislatura, a referência é a bancada do partido.",
    "Cada candidato pode pensar diferente do partido. Para governador e presidente, o plano de governo diz mais."));
}

function painelProjetos(t) {
  if (!t) return `<p class="explica">Sem dados de projetos para este mandato.</p>`;
  const m = t.medianas || {};
  const avancaram = (t.etapas.lei || 0) + (t.etapas.aprovada || 0);
  const taxa = t.projetos ? avancaram / t.projetos : 0;
  const tom = tomProjetos(t);
  const etapas = barras(ETAPAS.filter(([k]) => t.etapas[k]).map(([k, nome]) => ({ nome, valor: t.etapas[k] })), t.projetos, (v) => numero.format(v));
  const leituraProd = leitura(tom,
    avancaram === 0
      ? `Nenhum dos projetos passou pela Câmara até agora, o que é a situação mais comum: um deputado típico aprova só ${pct.format(m.avancaram || 0)} do que apresenta.`
      : `Passaram pela Câmara ${pct.format(taxa)} dos projetos, enquanto um deputado típico aprova ${pct.format(m.avancaram || 0)}. ${tom === "info" ? "É um resultado bem acima do comum." : "É um resultado dentro do comum."}`,
    "Aprovar projetos depende muito de estar na base do governo, presidir comissões e fazer acordos entre líderes. Ser anexado a outro projeto é comum e significa que o tema segue junto com uma proposta parecida.");

  const pctSimb = t.projetos ? t.simbolicos / t.projetos : 0;
  const simbolicoAlto = t.simbolicos >= 3 && m.simbolicos != null && pctSimb > 2 * m.simbolicos;
  const avancados = t.destaques.map((x) => {
    const [rot, expl] = ALTERACOES[x.alteracao] || ["Não identificado", "Não foi possível identificar no histórico como o texto foi aprovado."];
    return `<li class="projeto"><div class="tit"><a href="https://www.camara.leg.br/proposicoesWeb/fichadetramitacao?idProposicao=${esc(x.id)}" target="_blank" rel="noopener">${esc(x.nome)}</a>
      <span class="chip" title="${esc(expl)}">${esc(rot)}</span>${x.etapa === "lei" ? `<span class="badge ok">virou lei</span>` : ""}</div>
      <div class="det">${esc(x.ementa)}</div><div class="fnt">${esc(x.situacao)}${x.data ? `, desde ${esc(dataBr(x.data))}` : ""}.</div></li>`;
  });
  const listaAvancados = avancados.length
    ? `<ul class="projetos">${avancados.slice(0, 3).join("")}</ul>${avancados.length > 3
      ? `<details class="mais"><summary>Ver mais ${avancados.length - 3}</summary><ul class="projetos">${avancados.slice(3).join("")}</ul></details>` : ""}`
    : `<p class="explica">Nenhum projeto apresentado desde 2023 passou pela Câmara ainda.</p>`;

  return secao("O que aconteceu com os projetos", `
      <div class="tiles">
        <div class="tile"><div class="rot">Apresentou</div><div class="val">${numero.format(t.projetos)}</div><div class="det">Um deputado típico apresentou ${m.projetos ?? "—"}.</div></div>
        <div class="tile"><div class="rot">Passaram pela Câmara</div><div class="val">${numero.format(avancaram)}</div><div class="det">${t.etapas.lei ? `${t.etapas.lei === 1 ? "Um já virou lei" : `${t.etapas.lei} já viraram lei`}.` : "Nenhum virou lei ainda."}</div></div>
      </div>
      <div style="margin-top:14px">${etapas}</div>`, leituraProd) +
    secao("Projetos que avançaram", listaAvancados,
      leitura("neutro", "A etiqueta mostra como o texto foi aprovado. <strong>Texto do autor</strong> quer dizer que passou como foi escrito, <strong>com ajustes</strong> que recebeu emendas pontuais e <strong>reescrito</strong> que o relator refez o texto, muitas vezes juntando projetos parecidos.",
        "Ser reescrito é o caminho mais comum para um projeto avançar.")) +
    secao("Projetos simbólicos", `<div class="numero-grande">${numero.format(t.simbolicos)}<small>dos ${numero.format(t.projetos)} projetos são homenagens, datas comemorativas ou nomes de obras, o que dá ${pct.format(pctSimb)}.</small></div>`,
      leitura(simbolicoAlto ? "info" : "ok",
        simbolicoAlto ? `A parte simbólica é bem maior que a de um deputado típico, que fica em ${pct.format(m.simbolicos)}.` : `A proporção é parecida com a de um deputado típico${m.simbolicos != null ? `, que fica em ${pct.format(m.simbolicos)}` : ""}.`,
        "Projetos simbólicos custam pouco esforço e raramente mudam a vida das pessoas. Quando são muitos, costumam indicar uma atuação voltada à visibilidade.")) +
    secao("Relatorias", `<div class="numero-grande">${numero.format(t.relatorias)}<small>propostas das quais é o relator mais recente. Dessas, ${t.relatoriasLei === 1 ? "uma virou lei" : `${t.relatoriasLei} viraram lei`}.</small></div>`,
      leitura(t.relatorias > 2 * (m.relatorias || 0) ? "info" : "ok",
        `Um deputado típico relata ${m.relatorias ?? "—"} propostas.${t.relatorias > 2 * (m.relatorias || 0) ? " Este relata bem mais que a maioria." : ""}`,
        "O relator escreve o parecer e, muitas vezes, o texto final de uma proposta. Muitas relatorias costumam indicar influência e a confiança dos líderes."));
}

const GRUPOS_EMENDA = [
  ["prefeituras", "Prefeituras e fundos municipais"],
  ["estados", "Governos estaduais"],
  ["semFins", "Associações, fundações e ONGs"],
  ["empresas", "Empresas"],
  ["outrosPublicos", "Bancos públicos, estatais e órgãos federais"],
];

function painelEmendas(t) {
  if (!t) return "";
  if (!t.emendas) {
    return secao("Emendas ao Orçamento", t.emendasAtivo
      ? `<p class="explica">Os dados de emendas ainda estão sendo preparados. Feche e abra a ficha de novo em um minuto.</p>`
      : `<p>Os dados de emendas ainda não foram baixados.</p>`);
  }
  const e = t.emendas;
  if (!e.quantidade) return secao("Emendas ao Orçamento", `<p class="explica">Não encontramos emendas individuais com o nome parlamentar desta pessoa.</p>`);
  const pago = e.empenhado ? e.pago / e.empenhado : 0;
  const pix = e.partePix ?? (e.empenhado ? e.transferenciasEspeciais / e.empenhado : 0);
  const grupos = e.grupos ? GRUPOS_EMENDA.filter(([k]) => e.grupos[k]).map(([k, nome]) => ({ nome, valor: e.grupos[k] })) : [];
  const semFinsAlto = e.parteSemFins != null && e.parteSemFins > Math.max(0.2, 3 * (e.medianaSemFins || 0));
  const dependentes = (e.favorecidos || []).filter((f) => f.dependente);

  const visao = secao(`Emendas ao Orçamento desde ${e.desde || 2023}`, `
      <div class="tiles">
        <div class="tile"><div class="rot">Indicou</div><div class="val">${brlCompacto.format(e.empenhado)}</div><div class="det">Em ${e.quantidade} emendas individuais, das quais ${pct.format(pago)} já foi pago.</div></div>
        <div class="tile"><div class="rot">Emendas Pix</div><div class="val">${pct.format(pix)}</div><div class="det">Um deputado típico manda ${pct.format(e.medianaPix || 0)} por Pix.</div></div>
        ${e.rastro ? `<div class="tile"><div class="rot">Pix com prestação de contas</div><div class="val">${e.rastro.emendasPix ? pct.format(e.rastro.pixComRelatorio / e.rastro.emendasPix) : "—"}</div><div class="det">${e.rastro.emendasPix ? `${e.rastro.pixComRelatorio} de ${e.rastro.emendasPix} emendas Pix até ${e.rastro.ateAno} têm relatório de gestão publicado.` : `Nenhuma emenda Pix até ${e.rastro.ateAno}.`}</div></div>` : ""}
      </div>
      <p style="margin-top:14px">As áreas que receberam o dinheiro:</p>${barras(e.areas.map((x) => ({ nome: x.area === "Encargos especiais" ? "Emendas Pix e outros encargos" : x.area, valor: x.valor })), e.empenhado, (v) => brlCompacto.format(v))}`,
    leitura(pix > Math.max(0.45, 1.3 * (e.medianaPix || 0)) ? "info" : "neutro",
      `${pct.format(pix)} do valor foi por emenda Pix, que cai direto no caixa da prefeitura ou do estado sem finalidade definida. ${pix > (e.medianaPix || 0) ? "É mais do que um deputado típico." : "É menos do que um deputado típico."}`,
      "Em 2026, a maior auditoria do TCU sobre emendas Pix achou problemas em 82% das que examinou, de superfaturamento a obras sem comprovação. Por isso, mandar muito por Pix tira alguns pontos no desempenho. Todo deputado tem o mesmo valor de emendas por ano; o que muda é para onde e como manda."));

  const destino = grupos.length ? secao("Quem recebeu o dinheiro", `
      ${barras(grupos, e.recebido, (v) => brlCompacto.format(v))}
      ${e.lugares?.length ? `<p class="nota-sub">Municípios que mais receberam:</p><div class="chips">${e.lugares.slice(0, 8).map((l) => `<span class="chip">${esc(nomeProprio(l.municipio))} (${esc(l.uf)}): ${brlCompacto.format(l.valor)}</span>`).join("")}</div>` : ""}`,
    leitura(semFinsAlto ? "info" : "neutro",
      semFinsAlto
        ? `${pct.format(e.parteSemFins)} foi para associações, fundações e ONGs, bem acima dos ${pct.format(e.medianaSemFins || 0)} de um deputado típico. Muitas fazem trabalho sério, como hospitais filantrópicos, mas é onde a CGU mais encontra problemas.`
        : `A maior parte foi para prefeituras e órgãos públicos, como é comum. Associações, fundações e ONGs ficaram com ${pct.format(e.parteSemFins || 0)}.`,
      "O dinheiro que vai para a prefeitura some dos dados federais depois que chega lá: quem mostra como foi gasto é a própria prefeitura. Já o que vai direto para uma entidade aparece com nome e CNPJ.")) : "";

  const favorecidos = (e.favorecidos || []).slice(0, 12).map((f) => `<li>
      <span>${esc(nomeProprio(f.nome))}<small>${esc(f.natureza)}, ${esc(nomeProprio(f.municipio || ""))}${f.uf ? ` (${esc(f.uf)})` : ""}. ${f.autores === 1 ? "Só esta pessoa manda emendas para ela." : `Recebe emendas de ${numero.format(f.autores)} parlamentares.`}
        ${f.dependente ? `<span class="badge atencao">depende desta pessoa</span>` : ""}${f.campanha ? `<span class="badge alerta">trabalhou na campanha</span>` : ""}
        ${f.privado && f.doc.length === 14 ? `<button type="button" class="link-acao link-inline" data-empresa="${esc(f.doc)}">Ver a ficha</button>` : ""}</small></span>
      <strong>${brlCompacto.format(f.valor)}</strong></li>`).join("");
  const lista = favorecidos ? secao("Os maiores recebedores", `<ul class="bens-topo">${favorecidos}</ul>`,
    leitura(dependentes.length ? "atencao" : "ok",
      dependentes.length
        ? `${dependentes.length === 1 ? "Uma entidade privada depende" : `${dependentes.length} entidades privadas dependem`} das emendas desta pessoa: receberam pelo menos R$ 2 milhões e quase ninguém mais manda emendas para elas. Pode ser um projeto legítimo, mas vale abrir a ficha e ver quem está por trás.`
        : "Nenhuma entidade privada depende só das emendas desta pessoa, e nenhum recebedor aparece como fornecedor ou doador da campanha.",
      "Uma entidade que recebe de muitos parlamentares, como um hospital de referência, é um destino comum. A que recebe muito de uma só pessoa é o padrão que os órgãos de controle mais investigam."), "", true) : "";

  return visao + destino + lista + `<p class="fonte">Fontes: <a href="${esc(e.link)}" target="_blank" rel="noopener">Portal da Transparência</a>, com o arquivo completo de emendas, e Transferegov, para a prestação de contas das emendas Pix.</p>`;
}

// ---------- Dinheiro ----------

function painelDinheiro() {
  const f = ficha.f;
  const c = f.contas;
  const g = ficha.a?.gastos;
  if (!c && (!g || g.semDados)) {
    return `<p class="painel-intro">Ainda não há prestação de contas publicada pelo TSE para esta candidatura.</p>`;
  }
  const opcoes = [["geral", "Visão geral"], ["origem", "De onde vem"], ["destino", "Para onde vai"], ["fornecedores", "Fornecedores"], ["outras", "Outras campanhas"]];
  const sub = ficha.sub.dinheiro;
  const intro = `<p class="painel-intro">Quanto a campanha arrecadou, de onde veio o dinheiro, com o que foi gasto e quem recebeu. São os valores declarados ao TSE, que ainda mudam até o fim da campanha.</p>`;
  const corpo = { geral: dinheiroGeral, origem: dinheiroOrigem, destino: dinheiroDestino, fornecedores: dinheiroFornecedores, outras: dinheiroOutras }[sub](c, g);
  return intro + subnav("dinheiro", opcoes) + corpo;
}

function precisaGastos(g) {
  if (!ficha.a) return esqueleto("Cruzando as despesas de todas as campanhas do país…");
  if (!g) return `<p class="explica">A análise de gastos não está disponível agora.</p>`;
  if (!g.pronto) return `<p class="explica">Os dados de despesas de todas as campanhas ainda estão sendo preparados, o que leva uns 2 minutos na primeira vez. Depois disso, abra a ficha de novo.</p>`;
  if (g.semDados) return `<p class="explica">Ainda não há despesas desta campanha nos dados abertos do TSE.</p>`;
  return null;
}

function dinheiroGeral(c, g) {
  if (!c) return precisaGastos(g) || "";
  const publico = c.fundoEleitoral + c.fundoPartidario;
  const partePublica = c.totalRecebido ? publico / c.totalRecebido : 0;
  const usoLimite = c.limiteGastos ? c.despesasContratadas / c.limiteGastos : 0;
  const medianaTotal = g?.pronto && !g.semDados ? g.pares.medianaTotal : null;
  const grande = medianaTotal && c.despesasContratadas > 3 * medianaTotal;
  let tom = "neutro";
  if (usoLimite > 0.9) tom = "atencao";
  else if (grande) tom = "info";
  const texto = [
    c.totalRecebido ? `De cada R$ 100 arrecadados, R$ ${Math.round(partePublica * 100)} vieram do Fundo Eleitoral ou do Fundo Partidário, que são dinheiro público.` : "",
    medianaTotal ? `A campanha contratou ${brlCompacto.format(c.despesasContratadas)} em despesas, enquanto uma campanha típica para o mesmo cargo no estado contrata ${brlCompacto.format(medianaTotal)}.` : "",
    usoLimite > 0.9 ? `Já usou ${pct.format(usoLimite)} do limite legal de gastos.` : "",
  ].filter(Boolean).join(" ");
  return secao("Visão geral", `
      <div class="tiles">
        <div class="tile"><div class="rot">Arrecadou</div><div class="val">${brlCompacto.format(c.totalRecebido)}</div>${c.estimaveis ? `<div class="det">Recebeu também ${brlCompacto.format(c.estimaveis)} em bens e serviços.</div>` : ""}</div>
        <div class="tile"><div class="rot">Contratou em despesas</div><div class="val">${brlCompacto.format(c.despesasContratadas)}</div><div class="det">Já pagou ${brlCompacto.format(c.despesasPagas)}.</div></div>
        <div class="tile"><div class="rot">Dinheiro público</div><div class="val">${pct.format(partePublica)}</div><div class="det">Equivale a ${brlCompacto.format(publico)}.</div></div>
      </div>
      ${c.limiteGastos ? `<div class="medidor" title="${esc(pct.format(usoLimite))} do limite legal">
        <div class="trilho"><div class="cheio" style="width:${Math.min(usoLimite, 1) * 100}%"></div></div>
        <div class="legenda"><span>Já usou ${pct.format(usoLimite)} do limite legal de gastos</span><span>O limite é ${brlCompacto.format(c.limiteGastos)}</span></div></div>` : ""}`,
  leitura(tom, texto || "A campanha ainda declarou pouca informação financeira.",
    "Desde 2018, o dinheiro público é a principal fonte da maioria das campanhas. Quem decide quanto cada candidato recebe é a direção do partido."));
}

function dinheiroOrigem(c) {
  if (!c) return `<p class="explica">Sem receitas declaradas ainda.</p>`;
  const origens = [...c.origens].sort((x, y) => y.valor - x.valor).map((o) => ({ nome: o.origem, valor: o.valor }));
  const total = c.totalRecebido || 0;
  const proprios = c.origens.find((o) => o.origem === "Recursos próprios")?.valor || 0;
  const pf = c.origens.find((o) => o.origem === "Pessoas físicas")?.valor || 0;
  const partidos = c.origens.find((o) => o.origem === "Partidos")?.valor || 0;
  let tom = "neutro";
  let texto;
  if (total && proprios / total > 0.5) {
    tom = "info";
    texto = `${pct.format(proprios / total)} do dinheiro saiu do bolso do próprio candidato. É permitido até um limite, mas favorece quem tem patrimônio.`;
  } else if (total && partidos / total > 0.7) {
    texto = `${pct.format(partidos / total)} veio do partido, quase sempre do Fundo Eleitoral, o que mostra que a direção partidária apostou nesta candidatura.`;
  } else if (total && pf / total > 0.5) {
    tom = "ok";
    texto = `A maior parte do dinheiro, ${pct.format(pf / total)}, veio de doações de pessoas, sinal de apoio de eleitores e aliados.`;
  } else {
    texto = "O dinheiro vem de várias fontes, sem uma que domine.";
  }
  const doadores = c.doadores.length ? `<p style="margin-top:16px">Quem mais doou:</p>
    <ul class="bens-topo">${c.doadores.slice(0, 5).map((p) => `<li><span>${esc(p.nome)}<small>${p.qtd === 1 ? "Uma doação" : `${p.qtd} doações`}</small></span><strong>${esc(brlCompacto.format(p.valor))}</strong></li>`).join("")}</ul>` : "";
  return secao("De onde vem o dinheiro", `${origens.length ? barras(origens, total) : `<p class="explica">Ainda não há receitas declaradas.</p>`}${doadores}`,
    leitura(tom, texto, "Empresas não podem doar para campanhas desde 2015, e cada pessoa pode doar até 10% da própria renda."));
}

function dinheiroDestino(c, g) {
  const falta = precisaGastos(g);
  if (falta) {
    if (!c?.categorias?.length) return falta;
    const cats = [...c.categorias].sort((x, y) => y.valor - x.valor).slice(0, 8).map((x) => ({ nome: x.categoria, valor: x.valor }));
    return secao("Com o que gasta", barras(cats, c.despesasContratadas)) + falta;
  }
  const acima = g.composicao.filter((i) => i.parte > 0.3 && i.parte > 2.5 * Math.max(i.medianaPares, 0.02));
  const concentrado = g.concentracao.parte > 0.5 && g.total > 50_000;
  const tom = concentrado ? "atencao" : acima.length ? "info" : "ok";
  const texto = [
    acima.length ? `Gasta bem mais que o comum com ${listaNatural(acima.map((i) => `${esc(i.categoria.toLowerCase())}, que leva ${pct.format(i.parte)} do dinheiro, contra ${pct.format(i.medianaPares)} numa campanha típica`))}.`
      : "A divisão dos gastos é parecida com a de campanhas do mesmo porte.",
    concentrado ? `Além disso, ${pct.format(g.concentracao.parte)} do gasto foi para um único fornecedor, ${esc(g.concentracao.maiorFornecedor)}.` : "",
  ].filter(Boolean).join(" ");
  return secao("Para onde vai o dinheiro", `
      <p class="legenda-comp">A barra mostra esta campanha, e o traço mostra uma campanha típica entre ${numero.format(g.pares.quantidade)} de tamanho parecido para ${esc(g.pares.cargo?.toLowerCase() || "o mesmo cargo")} em ${esc(g.pares.uf)}.</p>
      <div class="comparacoes">${g.composicao.map(linhaComparacao).join("")}</div>
      <div class="tiles" style="margin-top:16px">
        <div class="tile"><div class="rot">Pagamentos a pessoas</div><div class="val">${brlCompacto.format(g.pessoasFisicas.total)}</div><div class="det">Para ${numero.format(g.pessoasFisicas.pessoas)} pessoas da militância e da equipe.</div></div>
        <div class="tile"><div class="rot">Maior fornecedor</div><div class="val">${pct.format(g.concentracao.parte)}</div><div class="det">Do gasto foi para ${esc(g.concentracao.maiorFornecedor || "—")}.</div></div>
      </div>`,
  leitura(tom, texto, "Cada campanha tem sua estratégia: uma aposta na internet, outra em material impresso. O que merece uma olhada é quando quase tudo vai para um único fornecedor."));
}

function piorTom(sinais) {
  return (sinais || []).reduce((pior, s) => (PESO_TOM[s.nivel] > PESO_TOM[pior] ? s.nivel : pior), "ok");
}

function dinheiroFornecedores(c, g) {
  const falta = precisaGastos(g);
  if (falta) return falta;
  const linhas = g.fornecedores.map((f) => {
    const tom = piorTom(f.sinais);
    return `<tr>
      <td class="quem">${esc(f.nome)}<small>${esc(listaNatural(f.categorias.map((x) => x.toLowerCase())))}</small></td>
      <td class="num">${brlCompacto.format(f.valor)}<small>${pct.format(f.parte)} do gasto</small></td>
      <td>Atende ${esc(textoRede(f.rede))}.<small>${f.rede.em2022 ? `Em 2022, atendeu ${esc(textoHistorico(f.rede))}.` : "Não trabalhou em campanhas em 2022."}</small></td>
      <td><span class="leitura-tag tom-${tom}">${tom === "ok" ? "Nada fora do comum" : TONS[tom]}</span>${f.sinais.length ? `<small>${esc(listaNatural(f.sinais.map((s) => s.titulo)))}.</small>` : ""}</td>
      <td><button type="button" class="btn pequeno" data-empresa="${esc(f.cnpj)}">Ver a empresa</button></td>
    </tr>`;
  }).join("");
  const pior = piorTom(g.fornecedores.flatMap((f) => f.sinais));
  const com = g.fornecedores.filter((f) => PESO_TOM[piorTom(f.sinais)] >= 2).length;
  return secao(`Quem recebeu (${numero.format(g.totalFornecedores)} empresas)`, `
      <div class="tabela-rolagem"><table class="lista tabela-fornecedores">
        <thead><tr><th>Fornecedor</th><th class="num">Recebeu</th><th>Experiência</th><th>Leitura</th><th></th></tr></thead>
        <tbody>${linhas}</tbody></table></div>
      <p class="nota-pequena">Em Ver a empresa você encontra o cadastro na Receita, os sócios, todas as campanhas que ela atende e um resumo do que chama atenção.</p>`,
  leitura(pior === "ok" ? "ok" : pior,
    com ? `${com === 1 ? "Um fornecedor tem" : `${com} fornecedores têm`} algo que vale conferir. O motivo aparece na coluna Leitura.` : "Nenhum dos maiores fornecedores tem sinal forte.",
    "Um fornecedor estabelecido costuma atender várias campanhas, de partidos diferentes, e já trabalhava em 2022. Os casos que merecem atenção são MEI recebendo acima do limite, empresa aberta dias antes da campanha, CNPJ inativo e sócio ligado ao candidato."),
  "", true);
}

function dinheiroOutras(c, g) {
  const falta = precisaGastos(g);
  if (falta) return falta;
  const comp = g.compartilhados.filter((x) => x.parteDoGasto >= 0.05).slice(0, 6);
  const suspeito = (x) => x.parteDoGasto > 0.5 && (x.totalOutro || 0) > g.total;
  const listaComp = comp.length ? `<ul class="compartilhados">${comp.map((x) => `<li>
      <span><strong>${esc(nomeProprio(x.nome))}</strong><small>Candidato a ${esc((x.cargo || "").toLowerCase())}${x.numero ? `, número ${esc(x.numero)}` : ""}. ${x.fornecedoresEmComum === 1 ? "Um fornecedor em comum" : `${x.fornecedoresEmComum} fornecedores em comum`}.</small></span>
      <span class="num">${pct.format(x.parteDoGasto)}<small>do gasto com empresas</small></span>
      <span class="leitura-tag tom-${suspeito(x) ? "atencao" : "ok"}">${suspeito(x) ? "Vale conferir" : "Comum"}</span></li>`).join("")}</ul>`
    : `<p class="explica">A campanha não divide fornecedores relevantes com outras do mesmo partido no estado.</p>`;
  const algum = comp.some(suspeito);
  const enviados = g.repasses.enviados;
  const recebidos = g.repasses.recebidos;
  const repasses = enviados.length || recebidos.length ? `<ul class="lista-simples">
      ${enviados.map((x) => `<li>Enviou ${brl.format(x.valor)} para ${esc(nomeProprio(x.nome))}${x.cargo && x.cargo !== "#NULO" ? ` (${esc(x.cargo.toLowerCase())})` : ""}</li>`).join("")}
      ${recebidos.map((x) => `<li>Recebeu ${brl.format(x.valor)} de ${esc(nomeProprio(x.nome || "?"))}${x.partido ? ` (${esc(x.partido)})` : ""}</li>`).join("")}</ul>`
    : `<p class="explica">A campanha não trocou dinheiro com outras.</p>`;
  return secao("Fornecedores em comum com o partido", listaComp,
    leitura(algum ? "atencao" : "ok",
      algum ? "Esta campanha gasta a maior parte do dinheiro com fornecedores que também atendem uma candidatura maior do mesmo partido. Esse padrão já apareceu em casos de candidaturas laranja, usadas só para repassar dinheiro."
        : "Dividir fornecedores com colegas de partido é normal, porque o partido costuma contratar a mesma gráfica ou agência para vários candidatos.",
      algum ? "Também acontece quando o partido contrata uma agência para todos. A votação e as contas finais ajudam a tirar a dúvida." : "Só chama atenção quando uma campanha pequena gasta quase tudo com o fornecedor de outra campanha maior.")) +
    secao("Dinheiro trocado com outras campanhas", repasses,
      leitura("neutro", "Repassar dinheiro entre campanhas é permitido e comum, principalmente de candidatos a governador ou senador para deputados do mesmo partido."));
}

// ---------- Alertas ----------

const NIVEIS = [["alerta", "Merecem atenção"], ["atencao", "Vale conferir"], ["info", "Informativos"], ["ok", "Tudo certo"]];

function htmlSinal(s) {
  const icones = { alerta: "✕", atencao: "!", info: "i", ok: "✓" };
  const rotulo = { alerta: "Merece atenção", atencao: "Vale conferir", info: "Informativo", ok: "Tudo certo" }[s.nivel];
  return `<li class="sinal ${s.nivel}">
    <span class="ic" aria-hidden="true">${icones[s.nivel]}</span>
    <div><div class="tit">${esc(s.titulo)} <span class="sinal-nivel">${rotulo}</span></div><div class="det">${esc(s.detalhe)}</div>
    <div class="fnt">Fonte: ${esc(s.fonte)}.${s.link ? ` <a href="${esc(s.link)}" target="_blank" rel="noopener">Ver na fonte</a>` : ""}${botoesEmpresa(s)}</div></div></li>`;
}

function botoesEmpresa(s) {
  const lista = s.empresas?.length ? s.empresas : s.cnpj ? [{ cnpj: s.cnpj }] : [];
  if (lista.length === 1) return ` <button type="button" class="link-acao link-inline" data-empresa="${esc(lista[0].cnpj)}">Ver a ficha da empresa</button>`;
  return lista.map((e) => ` <button type="button" class="link-acao link-inline" data-empresa="${esc(e.cnpj)}">Ficha de ${esc(nomeProprio(e.nome || e.cnpj))}</button>`).join("");
}

function painelAlertas() {
  const a = ficha.a;
  if (!a) return ficha.erroAnalise ? `<p class="erro">${esc(ficha.erroAnalise)}</p>` : esqueleto();
  const contagem = Object.fromEntries(NIVEIS.map(([n]) => [n, a.sinais.filter((s) => s.nivel === n).length]));
  const filtro = ficha.filtro;
  const lista = a.sinais.filter((s) => filtro === "todos" || s.nivel === filtro);
  const botoes = [["todos", "Todos", a.sinais.length], ...NIVEIS.map(([n, r]) => [n, r, contagem[n]])]
    .filter(([n, , q]) => n === "todos" || q)
    .map(([n, r, q]) => `<button type="button" data-filtro="${n}" class="filtro filtro-${n}" aria-pressed="${filtro === n}">${r} <span>${q}</span></button>`).join("");
  return `<p class="painel-intro">Tudo o que chamou atenção nas outras partes da ficha, reunido num só lugar. Cada ponto traz o detalhe e a fonte.</p>
    <div class="filtros" role="group" aria-label="Filtrar por nível">${botoes}</div>
    ${secao("Lista", lista.length ? `<ul class="sinais">${lista.map(htmlSinal).join("")}</ul>` : `<p class="explica">Nada neste filtro.</p>`,
    leitura(contagem.alerta ? "alerta" : contagem.atencao ? "atencao" : "ok",
      contagem.alerta ? `${contagem.alerta === 1 ? "Há um ponto mais sério" : `Há ${contagem.alerta} pontos mais sérios`} nos dados públicos. Vale ler o detalhe e a fonte de cada um.`
        : contagem.atencao ? `${contagem.atencao === 1 ? "Há um indício" : `Há ${contagem.atencao} indícios`} para conferir, mas nada mais grave.`
          : "Nada fora do comum apareceu nas fontes consultadas.",
      "<strong>Merece atenção</strong> marca fatos mais sérios, como uma candidatura indeferida. <strong>Vale conferir</strong> marca indícios que podem ter uma explicação comum. <strong>Informativo</strong> traz contexto útil, sem problema aparente."))}
    ${a.portalAtivo ? "" : `<p class="nota-pequena">A checagem nos cadastros de sanções da CGU ainda está sendo preparada. Os arquivos são baixados uma vez por dia; abra a ficha de novo em alguns instantes.</p>`}`;
}

// ---------- eventos ----------

function irPara(destino, sub) {
  if (destino.startsWith("#")) {
    $(destino)?.scrollIntoView({ behavior: "smooth", block: "start" });
    return;
  }
  ficha.aba = destino;
  if (sub) ficha.sub[destino] = sub;
  $("#ficha-nav").innerHTML = htmlNavegacao();
  desenharPainel();
  $("#ficha-rolagem").scrollTop = 0;
  $(`#ficha-aba-${destino}`)?.focus({ preventScroll: true });
}

(function ligarFicha() {
  const dlg = $("#ficha");
  dlg.addEventListener("click", (e) => {
    if (e.target === dlg) return dlg.close();
    const alvo = e.target.closest("[data-fechar],[data-aba],[data-ir],[data-sub],[data-filtro],[data-cedula-acao],[data-abrir]");
    if (!alvo || !dlg.contains(alvo)) return;
    if (alvo.hasAttribute("data-fechar")) return dlg.close();
    if (alvo.dataset.abrir) return abrirFicha(ficha.cargo, +alvo.dataset.abrir);
    if (alvo.dataset.aba) return irPara(alvo.dataset.aba);
    if (alvo.dataset.ir) return irPara(alvo.dataset.ir, alvo.dataset.subDestino);
    if (alvo.dataset.sub) {
      ficha.sub[ficha.aba] = alvo.dataset.sub;
      desenharPainel();
      return;
    }
    if (alvo.dataset.filtro) {
      ficha.filtro = alvo.dataset.filtro;
      desenharPainel();
      return;
    }
    if (alvo.dataset.cedulaAcao) {
      const f = ficha.f;
      if (alvo.dataset.cedulaAcao === "retirar") retirarVoto(chaveDoVoto(f.id));
      else {
        escolher(slots.find((s) => s.key === slotParaCargo(f.codCargo)), {
          id: f.id, numero: f.numero, nomeUrna: f.nomeUrna, partido: f.partido.sigla, coligacao: f.coligacao, situacao: f.situacao,
        });
      }
      $("#ficha-cab").innerHTML = htmlCabecalho(f);
      if (!$("#aba-ajuda").hidden) montarAjuda();
    }
  });
  // Setas do teclado trocam de aba, como em qualquer lista de abas.
  $("#ficha-nav").addEventListener("keydown", (e) => {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(e.key)) return;
    const ids = abasFicha().map(([id]) => id);
    let i = ids.indexOf(ficha.aba);
    if (e.key === "ArrowRight") i = (i + 1) % ids.length;
    else if (e.key === "ArrowLeft") i = (i - 1 + ids.length) % ids.length;
    else if (e.key === "Home") i = 0;
    else i = ids.length - 1;
    e.preventDefault();
    irPara(ids[i]);
  });
})();
