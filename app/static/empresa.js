"use strict";

// Ficha de empresa: um checklist do que costuma separar uma empresa comum de uma estranha,
// os dados da Receita, os sócios e o dinheiro público ou de campanha que ela recebeu
// (campanhas de 2026, emendas parlamentares e verba de gabinete da ALESP).

const INICIO_CAMPANHA = new Date("2026-08-16T00:00:00");

function cnpjFormatado(c) {
  return String(c).replace(/^(\d{2})(\d{3})(\d{3})(\d{4})(\d{2})$/, "$1.$2.$3/$4-$5");
}

// contexto (opcional): { candidato, valor, sinais } quando a ficha é aberta a partir de uma campanha.
async function abrirEmpresa(cnpj, contexto = null) {
  const dlg = $("#empresa-dlg");
  const corpo = $("#empresa-dlg-corpo");
  corpo.innerHTML = `<div class="empresa-cab"><p class="carregando">Buscando a empresa na Receita, nas campanhas e nas emendas…</p>
    <button type="button" class="fechar" data-fechar-empresa aria-label="Fechar">✕</button></div>`;
  if (!dlg.open) dlg.showModal();
  let f;
  try {
    f = await api(`/api/empresa?cnpj=${cnpj}`);
  } catch (e) {
    corpo.querySelector(".carregando").textContent = e.message;
    return;
  }
  corpo.innerHTML = htmlEmpresa(f, contexto);
}

function descreverPorte(r) {
  if (r.mei) return "um MEI";
  const p = (r.porte || "").toUpperCase();
  if (p.includes("MICRO")) return "uma microempresa";
  if (p.includes("PEQUENO")) return "uma empresa de pequeno porte";
  if (p.includes("DEMAIS")) return "uma empresa de médio ou grande porte";
  return `uma empresa de porte ${esc(p.toLowerCase())}`;
}

function itemChecklist(tom, titulo, texto) {
  const icones = { ok: "✓", info: "i", atencao: "!", alerta: "✕", neutro: "–" };
  return `<li class="check tom-${tom}"><span class="check-ic" aria-hidden="true">${icones[tom]}</span>
    <div><strong>${titulo}</strong><span>${texto}</span></div></li>`;
}

function htmlEmpresa(dados, ctx) {
  const r = dados.receita || {};
  const f = { ...(dados.campanha || {}), cnpj: dados.cnpj, nome: dados.nome, sancoes: dados.sancoes, clientes: dados.campanha?.clientes || [] };
  const rede = dados.campanha?.rede;
  const emendas = dados.emendas;
  const gabinete = dados.gabinete || [];
  const sinais = [...(f.sinais || []), ...((ctx?.sinais || []).filter((s) => !(f.sinais || []).some((x) => x.titulo === s.titulo)))];
  const tem = (inicio) => sinais.find((s) => s.titulo.startsWith(inicio));
  const itens = [];

  // 1. Idade da empresa
  if (r.abertura) {
    const abertura = new Date(r.abertura + "T00:00:00");
    const dias = Math.round((INICIO_CAMPANHA - abertura) / 86400000);
    const anos = Math.floor((new Date() - abertura) / (365.25 * 86400000));
    const quando = anos >= 1 ? `há ${anos} ${anos === 1 ? "ano" : "anos"}` : "há menos de um ano";
    const antesDaEmenda = emendas ? emendas.desde - abertura.getFullYear() : null;
    if (!rede) {
      if (antesDaEmenda != null && antesDaEmenda <= 1) itens.push(itemChecklist("atencao", "Aberta pouco antes de receber emendas", `Foi registrada em ${dataBr(r.abertura)} e começou a receber emendas em ${emendas.desde}. Entidades criadas às vésperas de receber dinheiro público são um padrão que a CGU observa.`));
      else itens.push(itemChecklist("ok", "Entidade com histórico", `Existe desde ${dataBr(r.abertura)}, ${quando}.`));
    } else if (dias < 0) itens.push(itemChecklist("atencao", "Aberta depois que a campanha começou", `Foi registrada em ${dataBr(r.abertura)}.`));
    else if (dias < 180) itens.push(itemChecklist("atencao", "Aberta pouco antes da campanha", `Foi registrada em ${dataBr(r.abertura)}, ${dias} dias antes de a campanha começar. Às vezes a empresa é criada justamente para a campanha.`));
    else itens.push(itemChecklist("ok", "Empresa com histórico", `Existe desde ${dataBr(r.abertura)}, ${quando}.`));
  } else {
    itens.push(itemChecklist("neutro", "Data de abertura indisponível", "Não foi possível consultar o cadastro na Receita agora."));
  }

  // 2. Situação cadastral
  if (r.situacao) {
    itens.push(r.situacao.toUpperCase() === "ATIVA"
      ? itemChecklist("ok", "CNPJ ativo", "A empresa está regular no cadastro da Receita Federal.")
      : itemChecklist("alerta", "CNPJ não está ativo", `Na Receita, a situação é ${esc(r.situacao.toLowerCase())}. Uma empresa nessa situação não deveria emitir notas.`));
  }

  // 3. Emendas: de quantos parlamentares depende
  if (emendas) {
    const privado = ["semFins", "empresas"].includes(emendas.grupo);
    if (privado && emendas.totalParlamentares <= 2 && emendas.total >= 2_000_000) {
      itens.push(itemChecklist("atencao", "Depende de poucos parlamentares", `Recebeu ${brlCompacto.format(emendas.total)} em emendas de ${emendas.totalParlamentares === 1 ? "um só parlamentar" : "só dois parlamentares"}. Repasses grandes para entidades ligadas a uma pessoa são o que a CGU e o TCU mais investigam.`));
    } else {
      itens.push(itemChecklist("ok", "Emendas de várias origens", `Recebeu emendas de ${emendas.totalParlamentares === 1 ? "um parlamentar" : `${emendas.totalParlamentares} parlamentares`}, num total de ${brlCompacto.format(emendas.total)}.`));
    }
  }

  // 4. Porte e limite do MEI
  const mei = tem("MEI recebendo");
  if (mei) itens.push(itemChecklist(mei.nivel, "MEI recebendo acima do limite", esc(mei.detalhe)));
  else if (rede && (r.porte || r.mei)) itens.push(itemChecklist("ok", "Porte compatível", `É ${descreverPorte(r)}, e o volume recebido cabe nesse porte.`));

  // 4. Atividade x serviço
  const atividade = tem("Atividade registrada");
  if (atividade) itens.push(itemChecklist("atencao", "Atividade não combina com o serviço", esc(atividade.detalhe)));
  else if (r.cnaeDescricao) itens.push(rede
    ? itemChecklist("ok", "Atividade combina com o serviço", `A atividade principal é ${esc(r.cnaeDescricao.toLowerCase())}.`)
    : itemChecklist("neutro", "Atividade registrada", `A atividade principal é ${esc(r.cnaeDescricao.toLowerCase())}.`));

  // 5. Experiência em campanhas
  if (!rede) {
    // não é fornecedora de campanha
  } else if (rede.em2022) {
    itens.push(itemChecklist("ok", "Já trabalhava com campanhas", `Em 2022 atendeu ${numero.format(rede.em2022.candidatos)} ${rede.em2022.candidatos === 1 ? "campanha" : "campanhas"}.`));
  } else {
    const exclusivo = tem("Fornecedor exclusivo");
    itens.push(itemChecklist(exclusivo ? "info" : "neutro", "Estreante em campanhas", exclusivo ? esc(exclusivo.detalhe) : "Não trabalhou em campanhas em 2022, o que é comum para empresas novas no ramo."));
  }

  // 6. Variedade de clientes
  if (!rede) {
    // idem
  } else if (rede.candidatos > 1) {
    const concentrada = tem("Atende quase só");
    itens.push(concentrada
      ? itemChecklist("info", "Clientes de um só partido", esc(concentrada.detalhe))
      : itemChecklist("ok", "Clientes variados", `Atende ${esc(textoRede(rede))}.`));
  } else {
    itens.push(itemChecklist("info", "Um único cliente", "A empresa atende só uma campanha em 2026."));
  }

  // 7. Sócios
  const socio = sinais.find((s) => /^(Empresa do próprio|Sócio)/.test(s.titulo));
  if (socio) itens.push(itemChecklist(socio.nivel, socio.titulo, esc(socio.detalhe)));
  else if (ctx) itens.push(itemChecklist("ok", "Sócios sem ligação aparente", "Nenhum sócio é o próprio candidato, um doador desta campanha ou outro candidato do estado."));

  // 8. Sanções do governo federal
  if (f.sancoes == null) {
    itens.push(itemChecklist("neutro", "Sanções não verificadas", "Cadastre a chave do Portal da Transparência na aba Ajuda para decidir para conferir se a empresa foi punida pelo governo federal."));
  } else if (f.sancoes.length) {
    itens.push(itemChecklist("alerta", "Empresa punida pelo governo federal", f.sancoes.map((s) =>
      `${esc(s.cadastro)}${s.sancao ? `: ${esc(s.sancao.toLowerCase())}` : ""}${s.orgao ? `, aplicada por ${esc(s.orgao)}` : ""}${s.inicio ? ` em ${esc(s.inicio)}` : ""}.`).join(" ")));
  } else {
    itens.push(itemChecklist("ok", "Sem sanções", "A empresa não aparece nos cadastros de punidos do governo federal."));
  }

  const peso = { alerta: 3, atencao: 2, info: 1, ok: 0, neutro: 0 };
  const pior = itens.reduce((acc, html) => {
    const t = /tom-(\w+)/.exec(html)[1];
    return peso[t] > peso[acc] ? t : acc;
  }, "ok");
  const veredito = {
    ok: ["Nada estranho", "Os dados públicos não mostram nada fora do comum para esta empresa."],
    info: ["Algumas particularidades", "Há pontos fora do comum, mas nenhum que indique problema."],
    atencao: ["Há pontos para conferir", "Alguns sinais merecem uma olhada. Eles podem ter explicação comum, então vale ler o detalhe de cada um."],
    alerta: ["Há sinais sérios", "Os dados públicos mostram pelo menos um problema mais sério. Leia o detalhe abaixo."],
  }[pior];

  const socios = r.socios?.length
    ? `<ul class="socios">${r.socios.map((s) => `<li><strong>${esc(nomeProprio(s.nome))}</strong><span>${esc(s.qualificacao || "")}</span></li>`).join("")}</ul>`
    : `<p class="explica">${r.mei ? "Como MEI, a empresa tem um único dono, que não aparece na lista pública de sócios." : "A Receita não informou sócios."}</p>`;
  const blocoEmendas = emendas ? `<h3 class="empresa-titulo">Emendas parlamentares recebidas</h3>
      <p class="explica">${esc(emendas.natureza)}. Recebeu ${brlCompacto.format(emendas.total)} desde ${emendas.desde}, de ${emendas.totalParlamentares === 1 ? "um parlamentar" : `${emendas.totalParlamentares} parlamentares`}.</p>
      <ul class="bens-topo">${emendas.parlamentares.slice(0, 8).map((x) => `<li><span>${esc(nomeProprio(x.nome))}<small>${x.primeiro === x.ultimo ? `Em ${x.primeiro}` : `De ${x.primeiro} a ${x.ultimo}`}</small></span><strong>${brlCompacto.format(x.valor)}</strong></li>`).join("")}</ul>` : "";
  const blocoGabinete = gabinete.length ? `<h3 class="empresa-titulo">Verba de gabinete na ALESP</h3>
      <ul class="bens-topo">${gabinete.map((x) => `<li><span>${esc(x.deputado)}<small>${esc(x.partido)}, desde 2023</small></span><strong>${brlCompacto.format(x.valor)}</strong></li>`).join("")}</ul>` : "";
  const clientes = f.clientes.map((x) => `<li><span>${esc(nomeProprio(x.nome || "?"))}<small>${esc(x.cargo || "")}, ${esc(x.partido)} de ${esc(x.uf)}</small></span><strong>${brlCompacto.format(x.valor)}</strong></li>`);

  return `<header class="empresa-cab">
      <div>
        <p class="empresa-rot">Ficha da empresa</p>
        <h2>${esc(r.nomeFantasia || r.razaoSocial || f.nome)}</h2>
        <p class="empresa-sub">${r.nomeFantasia && r.razaoSocial ? `${esc(r.razaoSocial)}. ` : ""}CNPJ ${cnpjFormatado(f.cnpj)}${r.municipio ? `, de ${esc(nomeProprio(r.municipio))}${r.uf ? ` (${esc(r.uf)})` : ""}` : ""}.</p>
      </div>
      <button type="button" class="fechar" data-fechar-empresa aria-label="Fechar">✕</button>
    </header>
    <div class="empresa-rolagem">
      <div class="empresa-veredito tom-${pior}"><strong>${veredito[0]}</strong><span>${veredito[1]}</span></div>
      ${ctx ? `<p class="empresa-contexto">Esta empresa recebeu ${brl.format(ctx.valor)} da campanha de ${esc(ctx.candidato)}.</p>` : ""}
      ${rede ? `<div class="tiles empresa-numeros">
        <div class="tile"><div class="rot">Recebeu de campanhas em 2026</div><div class="val">${brlCompacto.format(rede.total)}</div>
          <div class="det">${rede.publico != null ? `${pct.format(rede.publico)} do que já foi pago veio de dinheiro público.` : ""}</div></div>
        <div class="tile"><div class="rot">Campanhas atendidas</div><div class="val">${numero.format(rede.candidatos)}</div>
          <div class="det">${rede.partidos === 1 ? "De um só partido" : `De ${rede.partidos} partidos`}${rede.ufs > 1 ? `, em ${rede.ufs} estados` : ""}.</div></div>
        <div class="tile"><div class="rot">Capital social</div><div class="val">${r.capitalSocial != null ? brlCompacto.format(r.capitalSocial) : "—"}</div>
          <div class="det">É o valor que os sócios declararam investir na empresa.</div></div>
      </div>` : ""}
      <h3 class="empresa-titulo">O que os dados mostram</h3>
      <ul class="checklist">${itens.join("")}</ul>
      <h3 class="empresa-titulo">Sócios</h3>
      ${socios}
      ${blocoEmendas}
      ${blocoGabinete}
      ${rede ? `<h3 class="empresa-titulo">Campanhas que a empresa atende</h3>
      <ul class="bens-topo">${clientes.slice(0, 6).join("")}</ul>
      ${clientes.length > 6 ? `<details class="mais"><summary>Ver as outras ${clientes.length - 6}</summary><ul class="bens-topo">${clientes.slice(6).join("")}</ul></details>` : ""}
      ${rede.candidatos > f.clientes.length ? `<p class="nota-pequena">Aparecem as ${f.clientes.length} campanhas que mais pagaram, de um total de ${numero.format(rede.candidatos)}.</p>` : ""}` : ""}
      <p class="fonte">Os dados vêm da Receita Federal${rede ? ", das prestações de contas entregues ao TSE" : ""}${emendas ? ", do arquivo de emendas do Portal da Transparência" : ""}${gabinete.length ? ", da ALESP" : ""}${f.sancoes != null ? " e dos cadastros de sanções da CGU" : ""}. Nenhum desses pontos prova irregularidade sozinho, mas juntos ajudam a entender quem é a entidade.</p>
    </div>`;
}

(function ligarEmpresa() {
  document.addEventListener("click", (e) => {
    const dlg = $("#empresa-dlg");
    if (e.target === dlg || e.target.closest("[data-fechar-empresa]")) return dlg.close();
    const botao = e.target.closest("[data-empresa]");
    if (!botao) return;
    const cnpj = botao.dataset.empresa;
    let contexto = null;
    const fornecedor = typeof ficha !== "undefined" && ficha?.a?.gastos?.fornecedores?.find((x) => x.cnpj === cnpj);
    if (fornecedor && $("#ficha").open) {
      contexto = { candidato: nomeProprio(ficha.f.nomeUrna), valor: fornecedor.valor, sinais: fornecedor.sinais };
    }
    abrirEmpresa(cnpj, contexto);
  });
})();
