"use strict";

// Fornecedores de campanha: fica fora da trilha dos cargos, num painel próprio aberto pelo topo.
// Cada empresa é uma linha com os números rotulados, em vez de uma tabela de colunas apertadas.

const fornecedores = { dados: null, uf: null, ordem: "valor", semPlataformas: false, busca: "" };

// Mesmo corte do servidor (gastos.MIN_CLIENTES_PLATAFORMA): quem atende mais campanhas que isso no país são redes
// sociais, meios de pagamento e gráficas gigantes, que aparecem no topo em qualquer estado.
const CLIENTES_PLATAFORMA = 100;

// Os passos que o servidor segue para montar o banco de gastos (gastos._montar).
const PASSOS_GASTOS = [
  ["despesas de 2026", "Baixando as despesas de todas as campanhas do país"],
  ["pagamentos de 2026", "Baixando os pagamentos já feitos"],
  ["receitas de 2026", "Baixando as doações e demais receitas"],
  ["histórico de fornecedores (2022)", "Comparando com os fornecedores de 2022"],
  ["índices", "Organizando tudo para as buscas ficarem rápidas"],
];

const ORDENS_FORNECEDORES = {
  valor: ["Mais dinheiro recebido", (a, b) => b.total - a.total],
  campanhas: ["Mais campanhas atendidas no estado", (a, b) => b.candidatos - a.candidatos || b.total - a.total],
  partido: ["Mais concentrado em um partido", (a, b) => (b.concentracaoPartido ?? 0) - (a.concentracaoPartido ?? 0) || b.total - a.total],
};

function abrirFornecedores() {
  const dlg = $("#fornecedores-dlg");
  if (!dlg.open) dlg.showModal();
  if (!estado.uf) {
    $("#fornecedores-corpo").innerHTML = `${cabFornecedores("")}
      <div class="lista-dlg-rolagem"><p class="carregando aviso">Escolha o seu estado no topo da página para ver os fornecedores das campanhas de lá.</p></div>`;
    return;
  }
  carregarFornecedores();
}

function cabFornecedores(uf) {
  return `<header class="lista-dlg-cab">
      <div><h2 id="fornecedores-titulo">Fornecedores de campanha${uf ? ` em ${esc(UFS[uf] || uf)}` : ""}</h2>
        <p>As empresas que mais receberam das campanhas de 2026, de todos os cargos. Serve para ver quem abastece as campanhas e onde vale olhar com mais atenção.</p></div>
      <button type="button" class="fechar" data-fechar-fornecedores aria-label="Fechar">✕</button>
    </header>`;
}

async function carregarFornecedores() {
  const uf = estado.uf;
  const corpo = $("#fornecedores-corpo");
  if (fornecedores.dados && fornecedores.uf === uf) return desenharFornecedores();
  if (!corpo.querySelector(".espera")) corpo.innerHTML = `${cabFornecedores(uf)}<div class="lista-dlg-rolagem"><p class="carregando">Montando o panorama de fornecedores de ${esc(uf)}…</p></div>`;
  let p;
  try {
    p = await api(`/api/gastos/panorama?uf=${uf}`);
  } catch (e) {
    corpo.innerHTML = `${cabFornecedores(uf)}<div class="lista-dlg-rolagem"><p class="carregando aviso">${esc(e.message)}</p></div>`;
    return;
  }
  if (!$("#fornecedores-dlg").open || estado.uf !== uf) return;
  if (!p.pronto) {
    corpo.innerHTML = `${cabFornecedores(uf)}<div class="lista-dlg-rolagem">${htmlEspera("fornecedores", "Preparando as contas de campanha",
      PASSOS_GASTOS, p.status?.etapa, "Isso só acontece na primeira vez depois que o site é atualizado e leva alguns minutos. A tela atualiza sozinha.")}</div>`;
    setTimeout(() => { if ($("#fornecedores-dlg").open) carregarFornecedores(); }, 4000);
    return;
  }
  fimEspera("fornecedores");
  fornecedores.dados = p;
  fornecedores.uf = uf;
  desenharFornecedores();
}

function linhaFornecedor(f, max, uf) {
  const nacional = f.candidatosPais > f.candidatos
    ? `<small>${numero.format(f.candidatosPais)} no país${f.ufs > 1 ? `, em ${f.ufs} estados` : ""}</small>` : "";
  const partido = f.partidos === 1
    ? `<small>Todas as campanhas são do ${esc(f.partidoPrincipal)}</small>`
    : `<small>Campanhas do ${esc(f.partidoPrincipal)} pagaram ${pct.format(f.concentracaoPartido)} do total</small>`;
  return `<li class="forn-item">
    <div class="forn-topo">
      <div class="forn-nome">
        <h3>${esc(nomeProprio(f.nome))}</h3>
        <small>${esc(f.atividade ? f.atividade.charAt(0) + f.atividade.slice(1).toLowerCase() : "Atividade não informada")}</small>
      </div>
      <div class="forn-valor">
        <strong>${brlCompacto.format(f.total)}</strong>
        <small>recebido de campanhas em ${esc(uf)}</small>
      </div>
    </div>
    <div class="forn-barra" aria-hidden="true"><span style="width:${Math.max((f.total / max) * 100, 1)}%"></span></div>
    <dl class="forn-dados">
      <div><dt>Campanhas atendidas</dt><dd>${numero.format(f.candidatos)} em ${esc(uf)}${nacional}</dd></div>
      <div><dt>Partidos</dt><dd>${f.partidos} ${f.partidos === 1 ? "partido" : "partidos"}${partido}</dd></div>
      <div><dt>Em 2022</dt><dd>${f.em2022 ? `${numero.format(f.em2022)} ${f.em2022 === 1 ? "campanha" : "campanhas"}` : `<span class="badge">Não trabalhou em 2022</span>`}</dd></div>
    </dl>
    <div class="forn-acoes"><button type="button" class="btn pequeno" data-empresa="${esc(f.cnpj)}">Ver a empresa</button></div>
  </li>`;
}

function desenharFornecedores() {
  const p = fornecedores.dados;
  const uf = p.uf;
  const q = fornecedores.busca.trim().toLowerCase();
  let lista = p.fornecedores.filter((f) => !fornecedores.semPlataformas || f.candidatosPais <= CLIENTES_PLATAFORMA);
  if (q) lista = lista.filter((f) => `${f.nome} ${f.cnpj} ${f.atividade || ""}`.toLowerCase().includes(q));
  lista = [...lista].sort(ORDENS_FORNECEDORES[fornecedores.ordem][1]);
  const max = Math.max(...p.fornecedores.map((f) => f.total), 1);
  const plataformas = p.fornecedores.filter((f) => f.candidatosPais > CLIENTES_PLATAFORMA).length;
  const somaTop = p.fornecedores.reduce((s, f) => s + f.total, 0);
  const opcoes = Object.entries(ORDENS_FORNECEDORES).map(([k, [rot]]) =>
    `<option value="${k}"${fornecedores.ordem === k ? " selected" : ""}>${rot}</option>`).join("");

  $("#fornecedores-corpo").innerHTML = `${cabFornecedores(uf)}
    <div class="lista-dlg-rolagem">
      <div class="forn-resumo">
        <div><strong>${brlCompacto.format(p.totalUf || 0)}</strong><span>em despesas contratadas pelas campanhas de ${esc(uf)} até agora</span></div>
        <div><strong>${p.fornecedores.length}</strong><span>empresas que mais receberam, listadas abaixo</span></div>
        <div><strong>${pct.format(p.totalUf ? somaTop / p.totalUf : 0)}</strong><span>do dinheiro foi para essas ${p.fornecedores.length} empresas</span></div>
      </div>
      <div class="forn-filtros">
        <input type="search" id="busca-fornecedor" value="${esc(fornecedores.busca)}" placeholder="Buscar por nome, CNPJ ou atividade" aria-label="Buscar fornecedor">
        <label>Ordenar por <select id="ordem-fornecedor">${opcoes}</select></label>
        <label class="forn-check"><input type="checkbox" id="sem-plataformas"${fornecedores.semPlataformas ? " checked" : ""}>
          Esconder as ${plataformas} plataformas que atendem mais de ${CLIENTES_PLATAFORMA} campanhas no país</label>
      </div>
      ${lista.length ? `<ol class="forn-lista">${lista.map((f) => linhaFornecedor(f, max, uf)).join("")}</ol>`
        : `<p class="carregando aviso">Nenhuma empresa encontrada com "${esc(fornecedores.busca)}".</p>`}
      <p class="nota-pequena">Redes sociais, meios de pagamento e grandes gráficas aparecem no topo porque atendem quase todas as campanhas; o filtro acima tira essas empresas da lista. Em "Ver a empresa" estão o cadastro na Receita, os sócios, todas as campanhas atendidas e o que chama atenção. Dados das prestações de contas de 2026 e 2022 entregues ao TSE, atualizados em ${esc(p.geradoEm)}.</p>
    </div>`;
}

(function ligarFornecedores() {
  const dlg = $("#fornecedores-dlg");
  $("#abrir-fornecedores").addEventListener("click", abrirFornecedores);
  dlg.addEventListener("click", (e) => {
    if (e.target === dlg || e.target.closest("[data-fechar-fornecedores]")) dlg.close();
  });
  dlg.addEventListener("change", (e) => {
    if (e.target.id === "ordem-fornecedor") fornecedores.ordem = e.target.value;
    else if (e.target.id === "sem-plataformas") fornecedores.semPlataformas = e.target.checked;
    else return;
    desenharFornecedores();
  });
  let timer;
  dlg.addEventListener("input", (e) => {
    if (e.target.id !== "busca-fornecedor") return;
    clearTimeout(timer);
    timer = setTimeout(() => {
      fornecedores.busca = e.target.value;
      desenharFornecedores();
      const campo = $("#busca-fornecedor");
      campo.focus();
      campo.setSelectionRange(campo.value.length, campo.value.length);
    }, 200);
  });
})();
