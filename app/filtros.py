"""Filtros usados nos templates Jinja ({{ valor|moeda }}, {{ data|data_extensa }}...)."""

from __future__ import annotations

from flask import url_for

from .models import Canal, Papel, StatusAgendamento, StatusMensagem, TipoMensagem
from .utils import (
    DIAS_SEMANA, MESES, centavos_para_reais, cor_contraste, data_curta, data_extensa,
    formatar_duracao, formatar_moeda, formatar_telefone, link_whatsapp, linkify, mascarar_telefone,
)


def imagem_url(valor: str | None) -> str:
    """Imagens enviadas ficam em /static/uploads; as de exemplo são data: URIs."""
    if not valor:
        return ""
    if valor.startswith(("data:", "http://", "https://", "/")):
        return valor
    return url_for("static", filename=valor)


def data_br(valor) -> str:
    return valor.strftime("%d/%m/%Y") if valor else ""


def hora(valor) -> str:
    return valor.strftime("%H:%M") if valor else ""


def dia_semana(valor) -> str:
    return DIAS_SEMANA[valor.weekday()] if valor else ""


def mes_ano(valor) -> str:
    return f"{MESES[valor.month - 1]} de {valor.year}" if valor else ""


def registrar_filtros(app) -> None:
    app.jinja_env.filters.update({
        "moeda": formatar_moeda,
        "reais": centavos_para_reais,
        "duracao": formatar_duracao,
        "data_br": data_br,
        "data_curta": data_curta,
        "data_extensa": data_extensa,
        "dia_semana": dia_semana,
        "mes_ano": mes_ano,
        "hora": hora,
        "telefone": formatar_telefone,
        "telefone_mascarado": mascarar_telefone,
        "whatsapp": link_whatsapp,
        "cor_contraste": cor_contraste,
        "linkify": linkify,
        "imagem_url": imagem_url,
        "status_rotulo": lambda s: StatusAgendamento.ROTULOS.get(s, s),
        "canal_rotulo": lambda c: Canal.ROTULOS.get(c, c),
        "papel_rotulo": lambda p: Papel.ROTULOS.get(p, p),
        "tipo_mensagem": lambda t: TipoMensagem.ROTULOS.get(t, t),
        "status_mensagem": lambda s: StatusMensagem.ROTULOS.get(s, s),
    })
