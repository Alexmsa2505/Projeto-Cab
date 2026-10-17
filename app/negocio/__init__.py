"""Regras de negócio (equivalente aos Services/Actions de um projeto Laravel).

Nada aqui conhece Flask: as funções recebem o repositório e os dados já
lidos, o que facilita testar e reaproveitar (API, jobs, CLI).
"""


class ErroNegocio(Exception):
    """Erro de validação com mensagem pronta para mostrar ao usuário."""


class HorarioIndisponivel(ErroNegocio):
    """O horário escolhido foi ocupado por outra pessoa no meio do caminho."""
