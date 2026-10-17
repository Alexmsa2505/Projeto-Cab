/* Code Wave: comportamentos pequenos de interface, sem dependências.
   A parte reativa (horários livres, total, quadro do dia) é feita pelo HTMX. */
(() => {
  "use strict";

  const $ = (seletor, raiz = document) => raiz.querySelector(seletor);
  const pad = (n) => String(n).padStart(2, "0");

  // Campanha: confirma quantos clientes vão receber a mensagem
  document.addEventListener("submit", (evento) => {
    const form = evento.target;
    if (form.id !== "form-campanha") return;
    const total = form.querySelectorAll('input[name="cliente_ids"]:checked').length;
    if (!total) {
      evento.preventDefault();
      window.alert("Selecione pelo menos um cliente.");
    } else if (!window.confirm(`Enviar a mensagem para ${total} cliente(s)?`)) {
      evento.preventDefault();
    }
  });

  // Confirmação antes de ações destrutivas (formulários com hx-post usam hx-confirm)
  document.addEventListener("submit", (evento) => {
    const form = evento.target;
    const mensagem = form.dataset.confirmar;
    if (!mensagem || evento.defaultPrevented) return;
    if (window.htmx && form.hasAttribute("hx-post")) return;
    if (!window.confirm(mensagem)) evento.preventDefault();
  });

  // Evita clique duplo nos envios
  document.addEventListener("submit", (evento) => {
    const form = evento.target;
    if (!form.hasAttribute("data-enviando") || evento.defaultPrevented) return;
    const botao = evento.submitter || form.querySelector("[type=submit]");
    if (botao) setTimeout(() => { botao.disabled = true; botao.setAttribute("aria-busy", "true"); }, 0);
  });
  window.addEventListener("pageshow", () => {
    document.querySelectorAll('[aria-busy="true"]').forEach((botao) => {
      botao.disabled = false;
      botao.removeAttribute("aria-busy");
    });
  });

  // Máscara de celular: (11) 98765-4321
  const mascarar = (valor) => {
    const d = valor.replace(/\D/g, "").replace(/^55(?=\d{10,11}$)/, "").slice(0, 11);
    if (!d) return "";
    if (d.length <= 2) return `(${d}`;
    if (d.length <= 6) return `(${d.slice(0, 2)}) ${d.slice(2)}`;
    if (d.length <= 10) return `(${d.slice(0, 2)}) ${d.slice(2, 6)}-${d.slice(6)}`;
    return `(${d.slice(0, 2)}) ${d.slice(2, 7)}-${d.slice(7)}`;
  };
  document.addEventListener("input", (evento) => {
    const campo = evento.target;
    if (!campo.matches("input[data-telefone]")) return;
    if (evento.inputType && evento.inputType.startsWith("delete")) return;
    campo.value = mascarar(campo.value);
  });
  document.addEventListener("focusout", (evento) => {
    if (evento.target.matches("input[data-telefone]")) evento.target.value = mascarar(evento.target.value);
  });

  // Portfólio: foto ampliada
  document.addEventListener("click", (evento) => {
    const gatilho = evento.target.closest("[data-ampliar]");
    if (gatilho) {
      const dialogo = $("#ampliacao");
      if (!dialogo || typeof dialogo.showModal !== "function") return;
      const img = $("img", dialogo);
      img.src = gatilho.dataset.ampliar;
      img.alt = gatilho.dataset.legenda || "";
      $(".ampliacao__legenda", dialogo).textContent = gatilho.dataset.legenda || "";
      dialogo.showModal();
      return;
    }
    // Clique fora da foto fecha
    if (evento.target instanceof HTMLDialogElement && evento.target.open) evento.target.close();
  });

  // Copiar link
  document.addEventListener("click", async (evento) => {
    const botao = evento.target.closest("[data-copiar]");
    if (!botao) return;
    const original = botao.textContent;
    try {
      await navigator.clipboard.writeText(botao.dataset.copiar);
      botao.textContent = "Link copiado";
      setTimeout(() => { botao.textContent = original; }, 2000);
    } catch {
      window.prompt("Copie o link:", botao.dataset.copiar);
    }
  });

  // Contagem regressiva para reenviar o código
  document.querySelectorAll("[data-contagem]").forEach((botao) => {
    let restante = parseInt(botao.dataset.contagem, 10) || 0;
    if (restante <= 0) return;
    const texto = botao.textContent;
    botao.disabled = true;
    const tique = () => {
      if (restante <= 0) {
        botao.disabled = false;
        botao.textContent = texto;
        return;
      }
      botao.textContent = `${texto} em ${restante}s`;
      restante -= 1;
      setTimeout(tique, 1000);
    };
    tique();
  });

  // Envia o formulário ao trocar o valor (ex.: data do painel)
  document.addEventListener("change", (evento) => {
    if (evento.target.matches("[data-enviar-ao-mudar]")) evento.target.form?.requestSubmit();
  });

  // Marcar/desmarcar todos
  document.addEventListener("change", (evento) => {
    const mestre = evento.target.closest("[data-marcar-todos]");
    if (!mestre) return;
    const nome = mestre.dataset.marcarTodos;
    mestre.form?.querySelectorAll(`input[name="${nome}"]:not(:disabled)`).forEach((c) => { c.checked = mestre.checked; });
  });

  // Mostra o nome do arquivo escolhido
  document.addEventListener("change", (evento) => {
    const campo = evento.target;
    if (campo.type !== "file" || !campo.files.length) return;
    const rotulo = campo.closest(".portfolio__enviar")?.querySelector("span");
    if (rotulo) rotulo.textContent = campo.files[0].name;
  });

  // Endereço da página (slug) gerado a partir do nome da barbearia
  const slugify = (texto) => texto.normalize("NFKD").replace(/[\u0300-\u036f]/g, "").toLowerCase()
    .replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 40).replace(/-+$/, "");
  document.querySelectorAll("[data-gerar-slug]").forEach((origem) => {
    const destino = $(origem.dataset.gerarSlug);
    if (!destino) return;
    let editadoAMao = destino.value !== "";
    destino.addEventListener("input", () => { editadoAMao = destino.value !== ""; });
    origem.addEventListener("input", () => { if (!editadoAMao) destino.value = slugify(origem.value); });
  });

  // Prévia das cores (configurações)
  const luminancia = (hex) => {
    const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255)
      .map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  };
  const contraste = (hex) => {
    const l = luminancia(hex);
    return 1.05 / (l + 0.05) >= (l + 0.05) / 0.05 ? "#FFFFFF" : "#141414";
  };
  document.addEventListener("input", (evento) => {
    const campo = evento.target;
    const previa = $(".previa");
    if (!previa) return;
    if (campo.matches("input[data-previa]") && /^#[0-9a-f]{6}$/i.test(campo.value)) {
      previa.style.setProperty(`--${campo.dataset.previa}`, campo.value);
      previa.style.setProperty(`--${campo.dataset.previa}t`, contraste(campo.value));
    }
    if (campo.matches("input[data-previa-texto]")) $(".previa__topo", previa).textContent = campo.value || " ";
  });

  // Atalhos do bloqueio de agenda
  document.addEventListener("click", (evento) => {
    const botao = evento.target.closest("[data-atalho]");
    const form = $("#form-bloqueio");
    if (!botao || !form) return;
    const campo = (nome) => form.elements.namedItem(nome);
    const agora = new Date();
    agora.setMinutes(Math.floor(agora.getMinutes() / 5) * 5, 0, 0);
    const daqui = (minutos) => new Date(agora.getTime() + minutos * 60000);
    const hhmm = (d) => `${pad(d.getHours())}:${pad(d.getMinutes())}`;
    const hoje = `${agora.getFullYear()}-${pad(agora.getMonth() + 1)}-${pad(agora.getDate())}`;
    const preencher = (inicio, fim, motivo, dia) => {
      campo("inicio").value = inicio;
      campo("fim").value = fim;
      campo("motivo").value = motivo;
      if (dia) campo("data").value = dia;
    };
    switch (botao.dataset.atalho) {
      case "almoco": preencher("12:00", "13:00", "Almoço"); break;
      case "pausa": preencher(hhmm(agora), hhmm(daqui(15)), "Pausa", hoje); break;
      case "imprevisto": preencher(hhmm(agora), hhmm(daqui(60)), "Imprevisto", hoje); break;
      case "dia": preencher(botao.dataset.abre, botao.dataset.fecha, "Folga"); break;
      default: return;
    }
    form.querySelector("[type=submit]")?.focus();
  });

  // Login de demonstração: preenche e entra
  document.addEventListener("click", (evento) => {
    const botao = evento.target.closest("[data-preencher-login]");
    const form = botao?.closest(".acesso__cartao")?.querySelector("form");
    if (!form) return;
    form.elements.namedItem("email").value = botao.dataset.preencherLogin;
    form.elements.namedItem("senha").value = botao.dataset.senha;
    form.requestSubmit();
  });

  // Imprimir cartaz
  document.addEventListener("click", (evento) => {
    if (evento.target.closest("[data-imprimir]")) window.print();
  });

  // Falhas nas requisições do HTMX
  document.addEventListener("htmx:responseError", () => {
    window.alert("Não deu para concluir a ação. Recarregue a página e tente de novo.");
  });
  document.addEventListener("htmx:sendError", () => {
    window.alert("Sem conexão com o servidor. Confira a internet e tente de novo.");
  });
})();
