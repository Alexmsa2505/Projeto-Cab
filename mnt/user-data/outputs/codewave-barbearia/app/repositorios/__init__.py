"""Camada de dados.

- base.py    -> contratos (o que o sistema precisa do armazenamento)
- memoria.py -> implementação atual, em memória
- sql.py     -> (futuro) implementação com banco de dados

Para trocar o armazenamento, altere apenas `criar_repositorio` abaixo.
"""

from .base import Repositorio
from .memoria import RepositorioMemoria


def criar_repositorio(config) -> Repositorio:
    # Quando o banco entrar:
    #   if config.get("DATABASE_URL"):
    #       from .sql import RepositorioSQL
    #       return RepositorioSQL(config["DATABASE_URL"])
    return RepositorioMemoria()


__all__ = ["Repositorio", "RepositorioMemoria", "criar_repositorio"]
