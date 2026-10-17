"""Configuração dos testes (pytest)."""

import sys
from datetime import time, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import create_app  # noqa: E402
from app.negocio.barbearias import NovaBarbearia, criar_barbearia  # noqa: E402
from app.utils import agora_local  # noqa: E402
from config import TestConfig  # noqa: E402


@pytest.fixture
def app():
    return create_app(TestConfig)


@pytest.fixture
def ctx(app):
    return app.extensions["codewave"]


@pytest.fixture
def repo(ctx):
    return ctx.repo


@pytest.fixture
def http(app):
    return app.test_client()


@pytest.fixture
def barbearia(repo):
    """Barbearia aberta todos os dias, das 8h às 20h, com a dona atendendo."""
    b, _ = criar_barbearia(repo, NovaBarbearia(
        nome="Barbearia Teste", slug="teste", dono_nome="Ana Souza",
        email="dono@teste.com", senha="segredo1", dono_atende=True,
    ), agora_local())
    b.dias_funcionamento = list(range(7))
    b.abre_as, b.fecha_as = time(8), time(20)
    return repo.barbearias.atualizar(b)


@pytest.fixture
def amanha():
    return agora_local().date() + timedelta(days=1)


@pytest.fixture
def login(http):
    def entrar(slug="teste", email="dono@teste.com", senha="segredo1"):
        return http.post(f"/{slug}/admin/entrar", data={"email": email, "senha": senha})
    return entrar
