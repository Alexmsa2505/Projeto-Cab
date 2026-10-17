"""Validação de identidade por código de 4 dígitos (anti-trote).

Com só 10.000 combinações, a proteção real não é esconder o código, e sim
limitar tentativas, reenvios e quantidade de horários por número.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class PoliticaAntiTrote:
    validade_minutos: int = 10
    max_tentativas: int = 5
    intervalo_reenvio_segundos: int = 60
    max_envios_por_hora: int = 5
    max_agendamentos_ativos: int = 3
    validade_telefone_verificado_minutos: int = 30

    @classmethod
    def da_config(cls, config) -> "PoliticaAntiTrote":
        return cls(
            validade_minutos=config["CODIGO_VALIDADE_MINUTOS"],
            max_tentativas=config["CODIGO_MAX_TENTATIVAS"],
            intervalo_reenvio_segundos=config["CODIGO_INTERVALO_REENVIO_SEGUNDOS"],
            max_envios_por_hora=config["CODIGO_MAX_ENVIOS_POR_HORA"],
            max_agendamentos_ativos=config["LIMITE_AGENDAMENTOS_ATIVOS_POR_TELEFONE"],
            validade_telefone_verificado_minutos=config["TELEFONE_VERIFICADO_VALIDADE_MINUTOS"],
        )


def gerar_codigo() -> str:
    return f"{secrets.randbelow(10_000):04d}"


def gerar_token() -> str:
    """Token imprevisível para links (agendamento e verificação)."""
    return secrets.token_urlsafe(16)


def segundos_para_reenvio(politica: PoliticaAntiTrote, ultimo_envio_em: datetime, agora: datetime) -> int:
    decorridos = int((agora - ultimo_envio_em).total_seconds())
    return max(0, politica.intervalo_reenvio_segundos - decorridos)
