"""Upload de imagens (logo e portfólio).

Hoje salva em app/static/uploads/<slug>/. Para produção com várias
instâncias, troque estas duas funções por um armazenamento como S3.
"""

from __future__ import annotations

import secrets
from pathlib import Path

from werkzeug.datastructures import FileStorage

from . import ErroNegocio

# Assinatura (primeiros bytes) de cada formato aceito. SVG fica de fora de
# propósito: pode carregar scripts.
_ASSINATURAS = {
    "png": (b"\x89PNG\r\n\x1a\n",),
    "jpg": (b"\xff\xd8\xff",),
    "gif": (b"GIF87a", b"GIF89a"),
    "webp": (b"RIFF",),
}


def _detectar_formato(cabecalho: bytes) -> str | None:
    for formato, assinaturas in _ASSINATURAS.items():
        if any(cabecalho.startswith(a) for a in assinaturas):
            if formato == "webp" and cabecalho[8:12] != b"WEBP":
                continue
            return formato
    return None


def salvar_imagem(arquivo: FileStorage | None, pasta_uploads: Path, slug: str) -> str:
    """Valida e grava a imagem. Devolve o caminho relativo a /static."""
    if arquivo is None or not arquivo.filename:
        raise ErroNegocio("Escolha uma imagem.")
    cabecalho = arquivo.stream.read(16)
    arquivo.stream.seek(0)
    formato = _detectar_formato(cabecalho)
    if formato is None:
        raise ErroNegocio("Envie uma imagem PNG, JPG, WEBP ou GIF.")
    destino = pasta_uploads / slug
    destino.mkdir(parents=True, exist_ok=True)
    nome = f"{secrets.token_hex(8)}.{formato}"
    arquivo.save(destino / nome)
    return f"uploads/{slug}/{nome}"


def remover_imagem(caminho_relativo: str | None, pasta_uploads: Path) -> None:
    """Apaga um arquivo enviado (ignora URLs externas e imagens de exemplo)."""
    if not caminho_relativo or not caminho_relativo.startswith("uploads/"):
        return
    alvo = (pasta_uploads.parent / caminho_relativo).resolve()
    if pasta_uploads.resolve() in alvo.parents and alvo.is_file():
        alvo.unlink()
