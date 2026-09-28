"use strict";

const $ = (sel) => document.querySelector(sel);
let criando = false;

async function iniciar() {
  const r = await fetch("/api/login").then((x) => x.json()).catch(() => null);
  if (r?.logado) { location.replace("/"); return; }
  criando = r ? !r.existe : false;
  if (criando) {
    $("#subtitulo").textContent = "Crie seu usuário e senha para proteger o app.";
    $("#senha").autocomplete = "new-password";
    $("#bloco-confirma").hidden = false;
    $("#nota").hidden = false;
    $("#enviar").textContent = "Criar login e entrar";
  }
  $("#usuario").focus();
}

$("#form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const usuario = $("#usuario").value.trim();
  const senha = $("#senha").value;
  $("#erro").textContent = "";
  if (!usuario || !senha) { $("#erro").textContent = "Preencha usuário e senha."; return; }
  if (criando && senha !== $("#confirma").value) { $("#erro").textContent = "As duas senhas não são iguais."; return; }

  const botao = $("#enviar");
  botao.disabled = true;
  try {
    const r = await fetch(criando ? "/api/login/criar" : "/api/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ usuario, senha }),
    });
    const dados = await r.json().catch(() => ({}));
    if (r.ok) { location.replace("/"); return; }
    $("#erro").textContent = dados.erro || `Erro ${r.status}`;
    if (r.status === 409) { criando = false; iniciar(); }
  } catch {
    $("#erro").textContent = "Não foi possível falar com o computador. Ele está ligado com o app aberto?";
  } finally {
    botao.disabled = false;
  }
});

iniciar();
