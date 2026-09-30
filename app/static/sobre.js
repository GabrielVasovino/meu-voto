"use strict";

// "Sobre e metodologia": por que o site existe, como cada número é calculado e de onde vêm os dados,
// com o link do código aberto. Fica fora da trilha dos cargos, num painel aberto pelo topo.

const REPOSITORIO = "https://github.com/GabrielVasovino/meu-voto";
const sobre = { aba: "projeto" };

const ABAS_SOBRE = {
  projeto: "O projeto",
  metodologia: "Metodologia",
  dados: "Dados e código aberto",
};

function abrirSobre(aba = sobre.aba) {
  sobre.aba = aba;
  const dlg = $("#sobre");
  if (!dlg.open) dlg.showModal();
  desenharSobre();
}

function desenharSobre() {
  const abas = Object.entries(ABAS_SOBRE).map(([id, rot]) =>
    `<button type="button" role="tab" data-sobre-aba="${id}" aria-selected="${sobre.aba === id}">${rot}</button>`).join("");
  $("#sobre-corpo").innerHTML = `<header class="lista-dlg-cab">
      <div><h2 id="sobre-titulo">Sobre o Voto Informado</h2>
        <p>O que o site faz, como cada número é calculado e de onde vêm os dados.</p></div>
      <button type="button" class="fechar" data-fechar-sobre aria-label="Fechar">✕</button>
    </header>
    <nav class="sobre-abas" role="tablist" aria-label="Partes da página">${abas}</nav>
    <div class="lista-dlg-rolagem" id="sobre-rolagem" role="tabpanel">
      <div class="sobre-texto">${{ projeto: htmlSobreProjeto, metodologia: htmlSobreMetodologia, dados: htmlSobreDados }[sobre.aba]()}</div>
    </div>`;
  if (sobre.aba === "dados") preencherBases();
}

function htmlSobreProjeto() {
  return `<h3>Por que este site existe</h3>
    <p>Em 4 de outubro cada eleitor digita seis votos na urna. Juntos, eles decidem quem faz as leis, quem aprova o orçamento e os impostos e quem governa o estado e o país pelos próximos quatro anos, ou oito, no caso do Senado. Mesmo assim, a escolha costuma ser feita com pouca informação, principalmente para deputado: só em São Paulo são mais de 2.500 candidatos a deputado federal e estadual.</p>
    <p>O que se sabe sobre cada candidato é público, mas está espalhado por dezenas de sites e arquivos do TSE, da Câmara, da Receita Federal, da CGU, do TCU e de outros órgãos, em formatos que quase ninguém consegue ler. O Voto Informado junta esses dados num lugar só e traduz em linguagem simples: quem é a pessoa, de onde vem e para onde vai o dinheiro da campanha, como votou quem já tem mandato e o que vale conferir antes de confiar o voto a alguém.</p>
    <h3>Por que o voto para deputado merece mais atenção</h3>
    <p>É o voto que costuma receber menos atenção, mesmo sendo a Câmara e as Assembleias que aprovam as leis, o orçamento e os impostos. Ele vai primeiro para a lista, que é o partido ou a federação, e ajuda a eleger outras pessoas dessa lista, não só quem recebeu o voto. Por isso o site mostra quantas vagas cada lista deve ganhar e quem as ocuparia: o seu voto pode ajudar a eleger alguém que você nem conhece.</p>
    <h3>O que o site faz e o que não faz</h3>
    <p>O site mostra dados e comparações com os mesmos critérios para todos os candidatos, de todos os partidos. Ele não recomenda em quem votar, não usa pesquisas de intenção de voto e não leva em conta a posição política de ninguém nas notas: se alguém é mais à esquerda ou à direita é uma decisão sua, e o questionário de afinidade existe justamente para você comparar com a sua opinião.</p>
    <p>Os avisos são fatos que dá para conferir na fonte, nunca acusações. "Vale conferir" quer dizer que algo foge do padrão e merece um olhar, não que houve irregularidade. Cada aviso da ficha traz a fonte e, quando possível, o link para o registro original.</p>
    <h3>Avisos importantes</h3>
    <ul>
      <li><strong>Estimativas não são previsão.</strong> As vagas de cada lista, a ordem dos candidatos dentro dela, quem está "na disputa" e as faixas de chance são calculadas com os votos de 2022 e 2024 e o dinheiro declarado em 2026. Servem para entender como o voto funciona, não para dizer quem vai ganhar, e o resultado real pode ser muito diferente.</li>
      <li><strong>Não é pesquisa eleitoral.</strong> O site não entrevista eleitores nem mede intenção de voto. As pesquisas eleitorais registradas estão no <a href="https://pesqele-divulgacao.tse.jus.br/" target="_blank" rel="noopener">sistema do TSE</a>, e o resultado oficial é só o divulgado pelo TSE.</li>
      <li><strong>Avisos não são acusações.</strong> Os pontos para conferir e os alertas são indícios encontrados em dados públicos. Eles não afirmam que alguém cometeu irregularidade nem substituem decisão da Justiça ou dos órgãos de controle.</li>
      <li><strong>Os dados podem ter erros ou atrasos.</strong> Tudo vem de fontes oficiais, que às vezes corrigem ou atualizam as informações depois. Cruzamentos por nome e CPF parcial podem, raramente, confundir pessoas diferentes. Antes de tirar conclusões, confira no link da fonte que aparece em cada aviso.</li>
      <li><strong>As notas seguem um método próprio.</strong> A nota geral, a integridade, o desempenho e a afinidade são cálculos deste site, explicados na aba Metodologia, e não uma avaliação oficial. A afinidade usa só ${quizDados?.perguntas?.length || 15} votações da Câmara.</li>
      <li><strong>Sem ligação com campanhas.</strong> O site não tem ligação com candidatos, partidos ou órgãos públicos e não recomenda em quem votar.</li>
    </ul>
    <h3>Privacidade</h3>
    <p>A sua cédula e as respostas do questionário ficam guardadas só no seu navegador. O servidor não tem login e não recebe nem guarda votos. O CPF e o título de eleitor dos candidatos, que o TSE publica, são usados só para cruzar os dados e nunca aparecem na tela.</p>`;
}

function htmlSobreMetodologia() {
  return `<h3>Nota de integridade</h3>
    <p>Vale para todos os candidatos e mede se há algo nos registros públicos que merece atenção. Começa em 100 e perde pontos a cada aviso:</p>
    <div class="sobre-formula">Integridade = 100 − 20 por ponto para conferir − 50 por alerta sério (mínimo de 0)</div>
    <p>Alguns avisos pesam menos:</p>
    <ul>
      <li><strong>Gasto concentrado em um fornecedor</strong> e <strong>empresa aberta pouco antes da campanha</strong> tiram 10 pontos, porque costumam ter explicação simples, como uma agência contratada para cuidar de toda a campanha.</li>
      <li><strong>Patrimônio que cresceu bem acima da inflação durante um mandato</strong> tira de 5 a 20 pontos, conforme o ganho real por ano: 5 até R$ 500 mil, 10 até R$ 1 milhão, 15 até R$ 3 milhões e 20 acima disso. O aviso só aparece a partir de R$ 250 mil por ano, mais do que alguém consegue guardar só com o salário de deputado.</li>
    </ul>
    <p>Um <strong>alerta sério</strong> é algo grave e objetivo, como candidatura negada pela Justiça Eleitoral, estar nos cadastros nacionais de punidos, contas julgadas irregulares pelo TCU, estar na lista suja do trabalho escravo ou a campanha pagar uma empresa aberta às vésperas que ficou com grande parte dos gastos. Um <strong>ponto para conferir</strong> é algo que foge do padrão, mas pode ter explicação: patrimônio que cresceu muito acima da inflação enquanto a pessoa tinha mandato, fornecedor com atividade que não combina com o serviço, empresa de outro candidato recebendo da campanha, embargo ambiental, entre outros. Avisos informativos aparecem na ficha, mas não tiram pontos.</p>
    <p>Para não punir campanhas grandes só por serem grandes, o que envolve fornecedores é medido em proporção: um problema com uma empresa só tira pontos se a campanha pagou pelo menos R$ 10 mil ou 10% dos gastos a ela. Por isso um candidato a presidente e um a deputado são comparados com a mesma régua.</p>
    <h3>Empresas ligadas a candidatos</h3>
    <p>A Receita Federal publica todo mês os sócios de todas as empresas do país, com o CPF parcialmente escondido. O site cruza esses dados com os candidatos de 2026 pelo nome completo e pelos 6 dígitos do meio do CPF, que o TSE publica, e chega a mais de 10 mil candidatos sócios de empresas. A partir daí aparecem três tipos de aviso:</p>
    <ul>
      <li><strong>Campanha pagou empresa de outro candidato:</strong> a campanha pagou uma empresa que tem como sócio alguém que também disputa a eleição de 2026, do mesmo partido ou de outro. Pode ser um serviço comum, mas também é um caminho para o dinheiro de campanha chegar a um aliado. Tira pontos se o valor for relevante (R$ 10 mil ou 10% dos gastos).</li>
      <li><strong>Campanha pagou empresa do próprio candidato:</strong> a lei permite, mas o dinheiro volta para quem está concorrendo.</li>
      <li><strong>Empresa do candidato recebeu de outras campanhas ou de emendas:</strong> o outro lado do mesmo cruzamento, somando também as emendas parlamentares pagas a ela.</li>
    </ul>
    <p>O cruzamento é refeito todo mês, quando a Receita publica novos dados. Como usa nome e parte do CPF, pode raramente juntar duas pessoas diferentes com o mesmo nome; por isso cada aviso mostra a empresa e o sócio, para conferir.</p>
    <h3>Dinheiro que circula entre campanhas</h3>
    <ul>
      <li><strong>Doador que recebeu mais do que doou:</strong> quando alguém doou R$ 5 mil ou mais para a campanha e depois recebeu dela, como pagamento, mais do que doou. Tira pontos, porque é um jeito de o dinheiro doado voltar para quem doou, embora também aconteça com gente da equipe.</li>
      <li><strong>Doadores de muitos candidatos:</strong> quem doou para 5 candidatos ou mais aparece na aba Dinheiro, com os partidos. Só informa.</li>
      <li><strong>Emenda e campanha na mesma empresa:</strong> quando uma empresa recebeu emenda indicada pelo próprio deputado e depois foi paga pela campanha dele. Só informa, e plataformas e grandes empresas ficam de fora.</li>
      <li><strong>Repasses entre candidatos:</strong> dividir o Fundo Eleitoral entre candidatos do mesmo partido é permitido e comum, e aparece só como contexto.</li>
    </ul>
    <h3>Gabinete e campanha</h3>
    <p>Para quem já tem mandato, o site cruza quem trabalha ou trabalhou no gabinete (Senado, Câmara e as assembleias de SP, RJ, PR e SC publicam essas listas; as outras assembleias ainda não publicam de um jeito que dê para ler) com quem doou para a campanha ou foi pago por ela, pelo nome completo e só dentro da campanha do próprio chefe. Assessor doar para o chefe é permitido e comum: metade dessas doações é de até R$ 3 mil. O aviso só tira pontos (10) quando um assessor doou mais de R$ 10 mil, mais do que um mês de salário da maioria deles, porque devolver parte do salário ao político (a "rachadinha") é crime. Assessor pago pela campanha só informa.</p>
    <h3>Condenações por improbidade</h3>
    <p>O Conselho Nacional de Justiça mantém o cadastro de condenados por improbidade administrativa, que só inclui decisões definitivas ou de tribunal. O site consulta o cadastro pelo CPF de cada candidato. Uma condenação é alerta sério (50 pontos), e a ficha mostra o processo, o tribunal, a data e as penas.</p>
    <h3>Cassações em eleições anteriores</h3>
    <p>O TSE publica por que cada candidatura foi cassada ou teve o registro negado, eleição por eleição. O site olha de 2014 a 2024 e ignora os motivos burocráticos (documento faltando, lista do partido não registrada). Abuso de poder, compra de votos, gasto ilícito ou conduta vedada tiram 30 pontos, mas só quando a candidatura terminou barrada; se terminou liberada, a decisão caiu em recurso e só aparece como informação. Inelegibilidade antiga pela Ficha Limpa só informa: ela é consequência de outra decisão (condenação, contas rejeitadas), que pode ter sido anulada depois, e as que ainda valem já aparecem pelos cadastros atuais (CNJ, TCU, CGU). Fraude à cota de gênero cassa a lista inteira do partido, culpados ou não, então só informa. A pessoa é ligada pelo CPF e, em 2024, quando o TSE deixou de publicar o CPF, pelo nome completo e pela data de nascimento.</p>
    <h3>Auxílio Emergencial</h3>
    <p>Quem recebeu o Auxílio Emergencial (julho de 2020 ou junho de 2021) e tinha declarado ao TSE, entre 2018 e 2022, bens de R$ 500 mil ou mais recebe um ponto para conferir (10 pontos): o benefício era para quem tinha renda baixa, e esse é o padrão que a CGU e o TCU apontaram em pagamentos indevidos. Quem recebeu com patrimônio menor não aparece, porque tinha direito. A pessoa é ligada pelo nome e por parte do CPF.</p>
    <h3>Dívida ativa com a União</h3>
    <p>A Procuradoria-Geral da Fazenda Nacional publica todo trimestre quem deve à União (impostos, INSS e FGTS) em dívida ativa. O site liga essas dívidas ao candidato pelo nome e por parte do CPF, e às empresas em que ele é sócio pelo CNPJ. Só a dívida em cobrança pesa: tira 10 pontos a partir de R$ 100 mil no nome do candidato e 20 a partir de R$ 1 milhão; empresas do candidato com R$ 1 milhão ou mais em cobrança tiram 10. Dívida parcelada, garantida ou suspensa pela Justiça aparece, mas não tira pontos.</p>
    <h3>Contratos com o governo federal</h3>
    <p>Quando uma empresa do candidato tem contrato com órgãos federais (Portal da Transparência, desde 2023), a ficha mostra. Vender para o governo é permitido, então só informa: é conflito de interesse que vale conhecer.</p>
    <h3>Campanhas anteriores</h3>
    <p>Para quem também disputou em 2014, 2018 ou 2022, os mesmos cruzamentos são feitos com as contas dessas campanhas e aparecem juntos num aviso só, com o ano e o que foi achado no título (por exemplo, "Campanha de 2018: doador que recebeu mais do que doou"): doador que recebeu mais do que doou, empresa do próprio candidato paga pela campanha e doação de quem trabalha ou trabalhou no gabinete. Cada problema encontrado (por tipo e por ano) tira 10 pontos, no máximo 20 somando tudo. A pessoa é ligada entre as eleições pelo CPF.</p>
    <h3>Desempenho no mandato</h3>
    <p>Vale só para quem já é deputado federal ou deputado estadual de São Paulo, que são as casas com dados abertos completos. Em cada critério, a pessoa é comparada com os colegas da mesma casa e recebe uma posição de 0 a 100, em que 50 é o deputado típico. O desempenho é a média dessas posições.</p>
    <ul>
      <li><strong>Câmara dos Deputados:</strong> presença nas votações do plenário, projetos aprovados que mudam regras, relatorias, poucos projetos simbólicos (homenagens, datas e nomes de obras, com peso dobrado), economia na cota parlamentar e menos emendas Pix (as transferências especiais, que são mais difíceis de rastrear).</li>
      <li><strong>ALESP:</strong> presença nas comissões, leis aprovadas que mudam regras, poucos projetos simbólicos (com peso dobrado) e economia na verba de gabinete.</li>
    </ul>
    <h3>Nota final de cada pessoa</h3>
    <div class="sobre-formula">Sem mandato: nota = integridade<br>Com mandato: nota = integridade + 0,4 × (desempenho − 50), entre 0 e 100</div>
    <p>Assim, o desempenho soma ou tira no máximo 20 pontos, e quem está na média não ganha nem perde. Ter mandato não pesa contra ninguém.</p>
    <h3>Nota da federação ou do partido</h3>
    <p>Na tela de deputados, cada lista tem a média da nota geral de quem ocuparia as vagas pela estimativa, porque é esse o grupo que o seu voto ajuda a eleger. Numa lista que elege uma ou duas pessoas, um só candidato com avisos derrubaria a média; por isso ela é ajustada como se cada lista tivesse mais 5 pessoas com a nota média de todas as listas do estado. Numa lista grande o ajuste quase não muda nada; numa pequena, evita que uma pessoa só decida a nota.</p>
    <h3>Estimativa de vagas para deputado</h3>
    <p>Não é previsão. A conta repete os votos de 2022 com as regras e os partidos de 2026:</p>
    <ol>
      <li>Soma os votos de cada partido no estado em 2022, contando os votos nos candidatos e na legenda. Partidos que se fundiram são somados: PTB e Patriota viraram PRD, o PSC entrou no Podemos e o PROS no Solidariedade.</li>
      <li>Junta os partidos nas federações de 2026 e distribui as vagas como manda o Código Eleitoral: quociente eleitoral, quociente partidário e sobras pela maior média entre as listas que chegaram a 80% do quociente. Se ainda sobra vaga, todas participam, como decidiu o STF em 2024.</li>
      <li>Ordena os candidatos de cada lista por uma força de 0 a 100: metade vem da maior votação recente da pessoa (deputado em 2022 ou vereador e prefeito em 2024) e metade do dinheiro arrecadado em 2026, sempre em comparação com o melhor da mesma lista.</li>
    </ol>
    <p>Aplicada à eleição de 2022, a conta das vagas acertou 1.536 das 1.572 vagas de deputado federal e estadual do país (97,7%). A ordem dentro de cada lista é bem mais incerta: testando com 2022 em São Paulo e Minas Gerais, ela acertou 211 dos 294 eleitos (71,8%). Por isso cada pessoa aparece numa faixa de chance: na faixa "Alta", cerca de 7 em cada 10 se elegeram no teste; na "Disputada", 3 em cada 10; na "Baixa", 1 em cada 10; e na "Muito baixa", 1 em cada 100.</p>
    <h3>Afinidade do questionário</h3>
    <p>O questionário usa ${quizDados?.perguntas?.length || 15} votações nominais do plenário da Câmara, de 2023 a 2026, escolhidas por terem placar disputado e temas variados. Responder "Concordo" equivale a votar Sim. Ficaram de fora votações em que lados opostos votaram igual por motivos opostos, porque um Sim ou Não não representaria a posição de ninguém.</p>
    <div class="sobre-formula">Afinidade = votações em que a bancada votou como você ÷ votações que você respondeu e em que a bancada tinha posição clara</div>
    <ul>
      <li>A posição de um partido é a da maioria da bancada, quando pelo menos 3 deputados votaram e não houve empate.</li>
      <li>Uma federação funciona como um partido só na eleição, então as bancadas dos partidos dela são somadas.</li>
      <li>Para senador, governador e presidente, vale a afinidade do partido do candidato.</li>
      <li>Só quem já é deputado federal tem afinidade pessoal, porque só essas pessoas têm o próprio voto registrado nessas votações.</li>
      <li>Com menos de 3 votações em comum, a afinidade não aparece. Na ordem, quem tem poucas votações em comum sobe menos: 3 de 3 fica abaixo de 14 de 15, porque 3 respostas dizem menos que 15.</li>
    </ul>`;
}

function htmlSobreDados() {
  return `<div class="sobre-codigo">
      <p><strong>O código é aberto.</strong> Qualquer pessoa pode ler como cada número é calculado, conferir as regras acima direto no código, apontar erros ou sugerir melhorias.</p>
      <a class="btn primario" href="${REPOSITORIO}" target="_blank" rel="noopener">Ver o código no GitHub</a>
    </div>
    <p>Achou um dado errado ou um aviso injusto? Abra uma <a href="${REPOSITORIO}/issues" target="_blank" rel="noopener">issue no GitHub</a> explicando o caso, com o link da fonte se tiver.</p>
    <h3>De onde vêm os dados</h3>
    <p>Tudo vem de fontes públicas oficiais, baixadas e atualizadas automaticamente pelo servidor. Nada é digitado à mão, exceto os textos explicativos do questionário, que citam as fontes em cada votação.</p>
    <ul>
      <li><strong>TSE:</strong> candidaturas, bens declarados, histórico eleitoral, prestação de contas de campanha e resultados de 2022 e 2024.</li>
      <li><strong>Câmara dos Deputados e ALESP:</strong> votações, presença, projetos, relatorias, cota parlamentar e verba de gabinete.</li>
      <li><strong>Receita Federal:</strong> cadastro das empresas e sócios, para saber de quem são os fornecedores e em que empresas cada candidato é sócio.</li>
      <li><strong>CGU e Portal da Transparência:</strong> cadastros de empresas e pessoas punidas (CEIS, CNEP e CEAF) e emendas parlamentares.</li>
      <li><strong>Senado, Câmara e assembleias de SP, RJ, PR e SC:</strong> quem trabalha ou trabalhou nos gabinetes.</li>
      <li><strong>PGFN:</strong> dívida ativa com a União.</li>
      <li><strong>CNJ:</strong> cadastro nacional de condenações por improbidade administrativa.</li>
      <li><strong>TCU, Ministério do Trabalho e Ibama:</strong> contas julgadas irregulares, lista suja do trabalho escravo e áreas embargadas.</li>
      <li><strong>Banco Central:</strong> inflação (IPCA), para comparar patrimônios de anos diferentes.</li>
      <li><strong>Wikipédia e Wikimedia Commons:</strong> logos dos partidos, que são marcas de cada partido e aparecem só para identificá-los.</li>
    </ul>
    <h3>Atualização das bases neste servidor</h3>
    <ul class="sobre-bases" id="sobre-bases"><li><span>Consultando…</span></li></ul>
    <p class="nota-pequena">Quando uma base está sendo atualizada, o site continua usando a versão anterior. Se uma atualização falhar (por exemplo, com o site do órgão fora do ar), o servidor tenta de novo a cada hora.</p>`;
}

async function preencherBases() {
  let r;
  try { r = await api("/api/status"); } catch { r = null; }
  const alvo = $("#sobre-bases");
  if (!alvo) return;
  if (!r) { alvo.innerHTML = `<li><span>Não foi possível consultar agora.</span></li>`; return; }
  alvo.innerHTML = r.bases.map((b) => {
    const selo = b.pronto
      ? `<span class="badge ok">✓ Atualizada em ${esc(b.atualizadoEm)}</span>`
      : b.atualizando ? `<span class="badge warn">Sendo preparada</span>`
        : `<span class="badge">Ainda não disponível</span>`;
    return `<li><span>${esc(b.descricao)}<small>${esc(b.fonte)}</small></span>${selo}</li>`;
  }).join("");
}

(function ligarSobre() {
  const dlg = $("#sobre");
  $("#abrir-sobre").addEventListener("click", () => abrirSobre());
  dlg.addEventListener("click", (e) => {
    if (e.target === dlg || e.target.closest("[data-fechar-sobre]")) return dlg.close();
    const aba = e.target.closest("[data-sobre-aba]");
    if (aba) {
      sobre.aba = aba.dataset.sobreAba;
      desenharSobre();
      $("#sobre-rolagem").scrollTop = 0;
      return;
    }
    const ir = e.target.closest("[data-abrir-sobre]");
    if (ir) abrirSobre(ir.dataset.abrirSobre);
  });
})();

// Links "Como calculamos" espalhados pelo site abrem direto a metodologia.
document.addEventListener("click", (e) => {
  const link = e.target.closest("[data-abrir-sobre]");
  if (link && !$("#sobre").contains(link)) abrirSobre(link.dataset.abrirSobre);
});
