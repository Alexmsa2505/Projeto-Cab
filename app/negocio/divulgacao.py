"""QR Code que leva o cliente direto para a tela de agendamento."""

from __future__ import annotations

import io

import segno

from ..utils import cor_contraste, cor_valida


def _qr(url: str) -> segno.QRCode:
    # Nível "M" de correção: aguenta impressão gasta e reflexo no balcão
    return segno.make(url, error="m", micro=False)


def _cor(cor: str | None) -> str:
    # QR precisa de contraste com o fundo branco: cor clara demais vira preto
    if not cor_valida(cor) or cor_contraste(cor) != "#FFFFFF":
        return "#141414"
    return cor


def qr_svg_inline(url: str, cor: str | None = None) -> str:
    """SVG responsivo (com viewBox) para exibir direto no HTML."""
    return _qr(url).svg_inline(scale=1, border=2, dark=_cor(cor), light="#FFFFFF",
                               omitsize=True, svgclass="qr", title="QR Code para agendar")


def qr_svg_arquivo(url: str, cor: str | None = None) -> bytes:
    buffer = io.BytesIO()
    _qr(url).save(buffer, kind="svg", scale=16, border=2, dark=_cor(cor), light="#FFFFFF", xmldecl=True)
    return buffer.getvalue()


def qr_png(url: str, cor: str | None = None) -> bytes:
    buffer = io.BytesIO()
    _qr(url).save(buffer, kind="png", scale=16, border=2, dark=_cor(cor), light="#FFFFFF")
    return buffer.getvalue()
