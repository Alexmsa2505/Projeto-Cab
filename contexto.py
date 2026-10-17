"""Acesso aos serviços da aplicação a partir das rotas.

Funciona como o "container" do Laravel: as rotas pedem `repo()`,
`notificador()` etc. em vez de criar as dependências na mão.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from flask import current_app, g

from .negocio.notificacoes import Notificador
from .negocio.verificacao import PoliticaAntiTrote
from .repositorios import Repositorio
from .tarefas import FilaDeMensagens
from .utils import agora_local


@dataclass
class ContextoApp:
    repo: Repositorio
    notificador: Notificador
    fila: FilaDeMensagens
    politica: PoliticaAntiTrote
    base_url: str
    modo_demo: bool
    pasta_uploads: Path


def contexto() -> ContextoApp:
    return current_app.extensions["codewave"]


def repo() -> Repositorio:
    return contexto().repo


def notificador() -> Notificador:
    return contexto().notificador


def agora() -> datetime:
    """Hora atual no fuso da barbearia da URL."""
    barbearia = g.get("barbearia")
    return agora_local(barbearia.fuso_horario if barbearia else None)
