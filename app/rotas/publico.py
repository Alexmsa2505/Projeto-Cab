"""Página inicial da Code Wave e cadastro de novas barbearias (onboarding)."""

from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, request, url_for
from markupsafe import Markup

from ..contexto import contexto, repo
from ..negocio import ErroNegocio, divulgacao
from ..negocio.barbearias import NovaBarbearia, criar_barbearia
from ..negocio.notificacoes import link_agendar
from ..seguranca import iniciar_sessao
from ..seed import CONTAS_DEMO, SENHA_DEMO
from ..utils import agora_local

bp = Blueprint("publico", __name__)

DOMINIO_EXIBIDO = "app.codewave.com.br"


@bp.get("/")
def inicio():
    ctx = contexto()
    barbearias = repo().barbearias.listar() if ctx.modo_demo else []
    placa = None
    if barbearias:
        # A "placa de balcão" da página inicial mostra um QR Code de verdade
        destaque = next((b for b in barbearias if b.slug == "navalha-de-ouro"), barbearias[0])
        qr = divulgacao.qr_svg_inline(link_agendar(ctx.base_url, destaque), destaque.cor_secundaria)
        placa = {"barbearia": destaque, "qr": Markup(qr)}
    return render_template(
        "publico/inicio.html", barbearias=barbearias, senha_demo=SENHA_DEMO,
        contas=CONTAS_DEMO, placa=placa,
    )


@bp.route("/cadastro", methods=["GET", "POST"])
def cadastro():
    valores = request.form if request.method == "POST" else {}
    erro = None
    if request.method == "POST":
        try:
            barbearia, usuario = criar_barbearia(repo(), NovaBarbearia(
                nome=request.form.get("nome", ""),
                slug=request.form.get("slug", ""),
                dono_nome=request.form.get("dono_nome", ""),
                email=request.form.get("email", ""),
                senha=request.form.get("senha", ""),
                whatsapp=request.form.get("whatsapp", ""),
                dono_atende=request.form.get("dono_atende") == "1",
            ), agora_local())
        except ErroNegocio as exc:
            erro = str(exc)
        else:
            iniciar_sessao(usuario)
            flash("Barbearia criada! Ajuste as cores e o logo, e cadastre sua equipe.", "sucesso")
            return redirect(url_for("admin.configuracoes", slug=barbearia.slug))
    return render_template(
        "publico/cadastro.html", valores=valores, erro=erro, dominio=DOMINIO_EXIBIDO,
    ), (422 if erro else 200)
