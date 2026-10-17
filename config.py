"""Configurações da aplicação, lidas das variáveis de ambiente (ou do .env)."""

from __future__ import annotations

import os
from pathlib import Path

try:  # python-dotenv é opcional, mas recomendado
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass

BASE_DIR = Path(__file__).resolve().parent


def _bool(nome: str, padrao: bool) -> bool:
    valor = os.environ.get(nome)
    if valor is None:
        return padrao
    return valor.strip().lower() in {"1", "true", "sim", "yes", "on"}


def _int(nome: str, padrao: int) -> int:
    try:
        return int(os.environ.get(nome, padrao))
    except (TypeError, ValueError):
        return padrao


class Config:
    # --- Aplicação ---
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-troque-esta-chave")
    DEBUG = _bool("DEBUG", True)
    TESTING = False
    BASE_URL = os.environ.get("BASE_URL", "http://localhost:5000").rstrip("/")
    MODO_DEMO = _bool("MODO_DEMO", True)
    CARREGAR_DADOS_DEMO = _bool("CARREGAR_DADOS_DEMO", True)

    # --- Mensagens ---
    PROVEDOR_WHATSAPP = os.environ.get("PROVEDOR_WHATSAPP", "console")
    PROVEDOR_SMS = os.environ.get("PROVEDOR_SMS", "console")
    FILA_ASSINCRONA = _bool("FILA_ASSINCRONA", False)
    TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID", "")
    TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN", "")
    TWILIO_NUMERO_SMS = os.environ.get("TWILIO_NUMERO_SMS", "")
    TWILIO_NUMERO_WHATSAPP = os.environ.get("TWILIO_NUMERO_WHATSAPP", "")
    META_WHATSAPP_TOKEN = os.environ.get("META_WHATSAPP_TOKEN", "")
    META_WHATSAPP_PHONE_ID = os.environ.get("META_WHATSAPP_PHONE_ID", "")
    META_GRAPH_VERSAO = os.environ.get("META_GRAPH_VERSAO", "v21.0")

    # --- Lembretes automáticos ---
    AGENDADOR_ATIVO = _bool("AGENDADOR_ATIVO", True)
    AGENDADOR_INTERVALO_SEGUNDOS = _int("AGENDADOR_INTERVALO_SEGUNDOS", 60)

    # --- Uploads (logo e portfólio) ---
    PASTA_UPLOADS = BASE_DIR / "app" / "static" / "uploads"
    MAX_CONTENT_LENGTH = 5 * 1024 * 1024  # 5 MB por envio

    # --- Segurança ---
    CSRF_ATIVO = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = _bool("SESSION_COOKIE_SECURE", False)

    # --- Regras anti-trote do código de 4 dígitos ---
    CODIGO_VALIDADE_MINUTOS = 10
    CODIGO_MAX_TENTATIVAS = 5
    CODIGO_INTERVALO_REENVIO_SEGUNDOS = 60
    CODIGO_MAX_ENVIOS_POR_HORA = 5
    LIMITE_AGENDAMENTOS_ATIVOS_POR_TELEFONE = 3
    TELEFONE_VERIFICADO_VALIDADE_MINUTOS = 30


class TestConfig(Config):
    TESTING = True
    DEBUG = False
    MODO_DEMO = True
    CARREGAR_DADOS_DEMO = False
    AGENDADOR_ATIVO = False
    FILA_ASSINCRONA = False
    CSRF_ATIVO = False
    PROVEDOR_WHATSAPP = "console"
    PROVEDOR_SMS = "console"
    BASE_URL = "http://teste.local"
    SECRET_KEY = "chave-de-teste"
