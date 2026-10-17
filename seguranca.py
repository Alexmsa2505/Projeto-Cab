"""Segurança: proteção CSRF, login do painel e permissões."""

from __future__ import annotations

import hmac
import secrets
from functools import wraps

from flask import abort, current_app, flash, g, redirect, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from .models import Barbearia, Usuario

CHAVE_CSRF = "_csrf"
# Hash descartável: o login gasta o mesmo tempo com e-mail existente ou não
_HASH_FALSO = generate_password_hash(secrets.token_hex(8))


# ------------------------------------------------------------------------ CSRF
def token_csrf() -> str:
    if CHAVE_CSRF not in session:
        session[CHAVE_CSRF] = secrets.token_urlsafe(32)
    return session[CHAVE_CSRF]


def configurar_csrf(app) -> None:
    app.jinja_env.globals["csrf_token"] = token_csrf

    @app.before_request
    def _verificar_csrf():
        if not app.config.get("CSRF_ATIVO", True):
            return None
        if request.method not in ("POST", "PUT", "PATCH", "DELETE"):
            return None
        enviado = request.form.get(CHAVE_CSRF) or request.headers.get("X-CSRFToken", "")
        esperado = session.get(CHAVE_CSRF, "")
        if not esperado or not hmac.compare_digest(enviado, esperado):
            abort(400, description="A página ficou aberta por muito tempo. Recarregue e tente de novo.")
        return None


# ----------------------------------------------------------------------- login
def autenticar(repo, barbearia: Barbearia, email: str, senha: str) -> Usuario | None:
    usuario = repo.usuarios.por_email(barbearia.id, email)
    if usuario is None or not usuario.ativo:
        check_password_hash(_HASH_FALSO, senha or "")
        return None
    return usuario if check_password_hash(usuario.senha_hash, senha or "") else None


def iniciar_sessao(usuario: Usuario) -> None:
    session.clear()  # evita fixação de sessão
    session["usuario_id"] = usuario.id
    session["barbearia_id"] = usuario.barbearia_id
    session.permanent = True


def encerrar_sessao() -> None:
    session.pop("usuario_id", None)
    session.pop("barbearia_id", None)


def usuario_logado(repo, barbearia: Barbearia) -> Usuario | None:
    """Só vale se a sessão for desta mesma barbearia (isolamento multi-tenant)."""
    if session.get("barbearia_id") != barbearia.id:
        return None
    usuario = repo.usuarios.obter(session.get("usuario_id") or 0)
    if usuario is None or not usuario.ativo or usuario.barbearia_id != barbearia.id:
        return None
    return usuario


def destino_seguro(url: str | None) -> bool:
    """Evita redirecionamento para outro site depois do login."""
    return bool(url) and url.startswith("/") and not url.startswith("//") and "\\" not in url


# ----------------------------------------------------------------- permissões
def pode_gerenciar_barbeiro(usuario: Usuario | None, barbeiro_id: int | None) -> bool:
    if usuario is None:
        return False
    if usuario.e_dono:
        return True
    return barbeiro_id is not None and usuario.barbeiro_id == barbeiro_id


def somente_dono(view):
    @wraps(view)
    def envoltorio(*args, **kwargs):
        usuario = g.get("usuario")
        if usuario is None or not usuario.e_dono:
            if request.headers.get("HX-Request"):
                abort(403)
            flash("Essa área é só para o dono da barbearia.", "erro")
            return redirect(url_for("admin.dashboard"))
        return view(*args, **kwargs)

    return envoltorio


def sessao_permanente_por(app, horas: int = 12) -> None:
    from datetime import timedelta

    app.permanent_session_lifetime = timedelta(hours=horas)


def configurar_cabecalhos(app) -> None:
    @app.after_request
    def _cabecalhos(resposta):
        resposta.headers.setdefault("X-Content-Type-Options", "nosniff")
        resposta.headers.setdefault("Referrer-Policy", "same-origin")
        resposta.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        if current_app.config.get("SESSION_COOKIE_SECURE"):
            resposta.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
        return resposta
