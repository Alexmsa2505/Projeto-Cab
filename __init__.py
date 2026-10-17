"""Fábrica da aplicação (create_app)."""

from __future__ import annotations

import logging
import os

from flask import Flask, abort, current_app, g, render_template, request

from config import Config

from .contexto import ContextoApp
from .contexto import contexto as contexto_app
from .filtros import registrar_filtros
from .negocio.notificacoes import Notificador, criar_provedores
from .negocio.verificacao import PoliticaAntiTrote
from .repositorios import criar_repositorio
from .seguranca import configurar_cabecalhos, configurar_csrf, sessao_permanente_por
from .tarefas import AgendadorDeLembretes, FilaDeMensagens, processar_lembretes


def _configurar_logs() -> None:
    log = logging.getLogger("codewave")
    if not log.handlers:
        manipulador = logging.StreamHandler()
        manipulador.setFormatter(logging.Formatter("%(asctime)s [%(name)s] %(message)s", "%H:%M:%S"))
        log.addHandler(manipulador)
        log.setLevel(logging.INFO)
        log.propagate = False


def _processo_principal(app: Flask) -> bool:
    """Com o auto-reload do modo debug, o Flask sobe dois processos.
    As threads de segundo plano só rodam no processo que atende as requisições."""
    return not app.debug or os.environ.get("WERKZEUG_RUN_MAIN") == "true"


def _configurar_tenant(app: Flask) -> None:
    """Toda URL /<slug>/... carrega a barbearia em g.barbearia (multi-tenant)."""

    @app.url_value_preprocessor
    def _carregar_barbearia(endpoint, valores):
        if valores and "slug" in valores:
            slug = valores.pop("slug")
            barbearia = contexto_app().repo.barbearias.por_slug(slug)
            if barbearia is None:
                abort(404, description="Não encontramos essa barbearia. Confira o endereço.")
            g.barbearia = barbearia

    @app.url_defaults
    def _injetar_slug(endpoint, valores):
        if "slug" in valores:
            return
        barbearia = g.get("barbearia")
        if barbearia and current_app.url_map.is_endpoint_expecting(endpoint, "slug"):
            valores["slug"] = barbearia.slug

    @app.context_processor
    def _variaveis_globais():
        return {
            "barbearia": g.get("barbearia"),
            "usuario": g.get("usuario"),
            "modo_demo": contexto_app().modo_demo,
        }


def _configurar_erros(app: Flask) -> None:
    def pagina(codigo: int, titulo: str, padrao: str):
        def manipulador(erro):
            descricao = getattr(erro, "description", None) or padrao
            if request.headers.get("HX-Request"):
                return descricao, codigo
            return render_template("erro.html", codigo=codigo, titulo=titulo, mensagem=descricao), codigo
        return manipulador

    app.register_error_handler(400, pagina(400, "Não deu para concluir", "Recarregue a página e tente de novo."))
    app.register_error_handler(403, pagina(403, "Acesso restrito", "Você não tem permissão para isso."))
    app.register_error_handler(404, pagina(404, "Página não encontrada", "Confira o endereço digitado."))
    app.register_error_handler(413, pagina(413, "Arquivo grande demais", "Envie imagens de até 5 MB."))
    app.register_error_handler(500, pagina(500, "Algo deu errado", "Tente de novo em instantes."))


def create_app(config_class: type = Config) -> Flask:
    app = Flask(__name__)
    app.config.from_object(config_class)
    _configurar_logs()

    if not app.config["DEBUG"] and not app.config["TESTING"] and app.config["SECRET_KEY"].startswith("dev-"):
        logging.getLogger("codewave").warning("SECRET_KEY padrão em uso! Defina uma chave no .env.")

    # Dependências (o "container")
    repo = criar_repositorio(app.config)
    fila = FilaDeMensagens(assincrona=app.config["FILA_ASSINCRONA"])
    notificador = Notificador(repo, criar_provedores(app.config), fila, app.config["BASE_URL"])
    app.extensions["codewave"] = ContextoApp(
        repo=repo,
        notificador=notificador,
        fila=fila,
        politica=PoliticaAntiTrote.da_config(app.config),
        base_url=app.config["BASE_URL"],
        modo_demo=app.config["MODO_DEMO"],
        pasta_uploads=app.config["PASTA_UPLOADS"],
    )

    registrar_filtros(app)
    configurar_csrf(app)
    configurar_cabecalhos(app)
    sessao_permanente_por(app, horas=12)
    _configurar_tenant(app)
    _configurar_erros(app)

    from .rotas import admin, cliente, publico

    app.register_blueprint(publico.bp)
    app.register_blueprint(admin.bp)
    app.register_blueprint(cliente.bp)

    if app.config["CARREGAR_DADOS_DEMO"]:
        from .seed import carregar_dados_demo

        slugs = carregar_dados_demo(repo)
        if slugs and _processo_principal(app):
            logging.getLogger("codewave").info(
                "Dados de demonstração carregados: %s", ", ".join(f"/{s}/" for s in slugs)
            )

    @app.cli.command("lembretes")
    def comando_lembretes():
        """Envia os lembretes pendentes (para usar em cron)."""
        print(f"{processar_lembretes(repo, notificador)} lembrete(s) enviado(s).")

    if app.config["AGENDADOR_ATIVO"] and _processo_principal(app):
        AgendadorDeLembretes(repo, notificador, app.config["AGENDADOR_INTERVALO_SEGUNDOS"]).iniciar()

    return app
