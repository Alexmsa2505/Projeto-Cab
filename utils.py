"""Funções utilitárias: formatação brasileira, telefones, cores, datas e slugs."""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime, time
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from urllib.parse import quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from markupsafe import Markup, escape

FUSO_PADRAO = "America/Sao_Paulo"

DIAS_SEMANA = (
    "segunda-feira", "terça-feira", "quarta-feira", "quinta-feira",
    "sexta-feira", "sábado", "domingo",
)
DIAS_SEMANA_CURTO = ("seg", "ter", "qua", "qui", "sex", "sáb", "dom")
MESES = (
    "janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho",
    "agosto", "setembro", "outubro", "novembro", "dezembro",
)
MESES_CURTO = ("jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez")

# Caminhos que não podem virar endereço de barbearia
SLUGS_RESERVADOS = frozenset({
    "admin", "api", "app", "cadastro", "codewave", "entrar", "favicon.ico",
    "login", "painel", "robots.txt", "sair", "static", "suporte", "www",
})

_RE_SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_RE_COR = re.compile(r"#[0-9a-fA-F]{6}")
_RE_HORA = re.compile(r"([01]?\d|2[0-3]):([0-5]\d)")
_RE_URL = re.compile(r"https?://[^\s<>\"']+")


# --------------------------------------------------------------------------- slug
def slugify(texto: str) -> str:
    """'Barbearia do Zé!' -> 'barbearia-do-ze'"""
    texto = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode("ascii")
    texto = re.sub(r"[^a-zA-Z0-9]+", "-", texto).strip("-").lower()
    return texto[:40].strip("-")


def slug_valido(slug: str) -> bool:
    return 3 <= len(slug or "") <= 40 and bool(_RE_SLUG.fullmatch(slug)) and slug not in SLUGS_RESERVADOS


# ---------------------------------------------------------------------- telefones
def normalizar_telefone(texto: str | None) -> str | None:
    """Converte qualquer digitação para E.164 (+55DDDNUMERO) ou None se inválido."""
    digitos = re.sub(r"\D", "", texto or "")
    if len(digitos) in (12, 13) and digitos.startswith("55"):
        digitos = digitos[2:]
    digitos = digitos.lstrip("0")
    if len(digitos) not in (10, 11):
        return None
    if not 11 <= int(digitos[:2]) <= 99:
        return None
    if len(digitos) == 11 and digitos[2] != "9":  # celular tem o 9 na frente
        return None
    return "+55" + digitos


def _digitos_nacionais(telefone: str) -> str:
    digitos = re.sub(r"\D", "", telefone or "")
    if digitos.startswith("55") and len(digitos) in (12, 13):
        return digitos[2:]
    return digitos


def formatar_telefone(telefone: str | None) -> str:
    d = _digitos_nacionais(telefone or "")
    if len(d) == 11:
        return f"({d[:2]}) {d[2:7]}-{d[7:]}"
    if len(d) == 10:
        return f"({d[:2]}) {d[2:6]}-{d[6:]}"
    return telefone or ""


def mascarar_telefone(telefone: str | None) -> str:
    d = _digitos_nacionais(telefone or "")
    if len(d) >= 10:
        return f"({d[:2]}) {d[2]}••••-{d[-4:]}"
    return "••••"


def link_whatsapp(telefone: str | None, texto: str = "") -> str:
    digitos = re.sub(r"\D", "", telefone or "")
    if not digitos:
        return ""
    url = f"https://wa.me/{digitos}"
    return f"{url}?text={quote(texto)}" if texto else url


# -------------------------------------------------------------------------- moeda
def formatar_moeda(centavos: int | None) -> str:
    """12345 -> 'R$ 123,45' (com espaço que não quebra linha)."""
    valor = int(centavos or 0)
    sinal = "-" if valor < 0 else ""
    reais, resto = divmod(abs(valor), 100)
    inteiro = f"{reais:,}".replace(",", ".")
    return f"{sinal}R$\u00a0{inteiro},{resto:02d}"


def reais_para_centavos(texto: str | int | float | None) -> int | None:
    """'45,90' / '45.90' / 'R$ 1.234,56' -> centavos. None se inválido."""
    bruto = str(texto if texto is not None else "").strip()
    bruto = bruto.replace("R$", "").replace(" ", "").replace("\u00a0", "")
    if not bruto:
        return None
    if "," in bruto:
        bruto = bruto.replace(".", "").replace(",", ".")
    try:
        valor = Decimal(bruto)
    except InvalidOperation:
        return None
    if valor < 0:
        return None
    return int((valor * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def centavos_para_reais(centavos: int | None) -> str:
    """Valor para preencher <input type=number>: 4590 -> '45.90'."""
    reais, resto = divmod(int(centavos or 0), 100)
    return f"{reais}.{resto:02d}"


# --------------------------------------------------------------------------- cores
def cor_valida(cor: str | None) -> bool:
    return bool(cor) and bool(_RE_COR.fullmatch(cor))


def _luminancia(cor: str) -> float:
    def canal(valor: float) -> float:
        return valor / 12.92 if valor <= 0.03928 else ((valor + 0.055) / 1.055) ** 2.4

    r, g, b = (int(cor[i:i + 2], 16) / 255 for i in (1, 3, 5))
    return 0.2126 * canal(r) + 0.7152 * canal(g) + 0.0722 * canal(b)


def cor_contraste(cor: str | None) -> str:
    """Escolhe texto branco ou quase preto, o que der mais contraste sobre `cor`."""
    if not cor_valida(cor):
        return "#FFFFFF"
    lum = _luminancia(cor)
    contra_branco = 1.05 / (lum + 0.05)
    contra_preto = (lum + 0.05) / 0.05
    return "#FFFFFF" if contra_branco >= contra_preto else "#141414"


# ---------------------------------------------------------------------------- datas
def fuso(nome: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(nome or FUSO_PADRAO)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo(FUSO_PADRAO)


def agora_local(nome_fuso: str | None = FUSO_PADRAO) -> datetime:
    """Data/hora atual no fuso da barbearia, sem tzinfo (padrão do sistema)."""
    return datetime.now(fuso(nome_fuso)).replace(tzinfo=None, microsecond=0)


def parse_data(texto: str | None) -> date | None:
    if not texto:
        return None
    try:
        return date.fromisoformat(str(texto)[:10])
    except ValueError:
        return None


def parse_hora(texto: str | None) -> time | None:
    m = _RE_HORA.fullmatch((texto or "").strip())
    return time(int(m[1]), int(m[2])) if m else None


def parse_data_hora(texto: str | None) -> datetime | None:
    if not texto:
        return None
    try:
        return datetime.fromisoformat(str(texto)).replace(tzinfo=None)
    except ValueError:
        return None


def data_extensa(valor: date | datetime | None) -> str:
    """sexta-feira, 16 de outubro"""
    if not valor:
        return ""
    return f"{DIAS_SEMANA[valor.weekday()]}, {valor.day} de {MESES[valor.month - 1]}"


def data_curta(valor: date | datetime | None) -> str:
    """sex, 16/10"""
    if not valor:
        return ""
    return f"{DIAS_SEMANA_CURTO[valor.weekday()]}, {valor:%d/%m}"


def formatar_duracao(minutos: int | None) -> str:
    """30 -> '30 min' | 60 -> '1h' | 75 -> '1h 15min'"""
    minutos = int(minutos or 0)
    horas, resto = divmod(minutos, 60)
    if not horas:
        return f"{resto} min"
    return f"{horas}h {resto:02d}min" if resto else f"{horas}h"


def linkify(texto: str | None) -> Markup:
    """Escapa o texto e transforma URLs em links clicáveis (caixa de saída)."""
    seguro = str(escape(texto or ""))

    def trocar(m: re.Match) -> str:
        url = m.group(0)
        return f'<a href="{url}" target="_blank" rel="noopener">{url}</a>'

    return Markup(_RE_URL.sub(trocar, seguro).replace("\n", "<br>"))
