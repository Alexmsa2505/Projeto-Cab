"""Fechamento financeiro: rateio automático entre barbearia e profissional."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from ..models import Agendamento, Barbearia, Barbeiro, StatusAgendamento
from ..repositorios import Repositorio
from ..utils import DIAS_SEMANA, MESES, MESES_CURTO

PERIODOS = {"dia": "Dia", "semana": "Semana", "mes": "Mês"}


def intervalo_periodo(tipo: str, referencia: date) -> tuple[date, date]:
    """[inicio, fim) do período que contém a data de referência."""
    if tipo == "semana":
        inicio = referencia - timedelta(days=referencia.weekday())
        return inicio, inicio + timedelta(days=7)
    if tipo == "mes":
        inicio = referencia.replace(day=1)
        proximo = (inicio + timedelta(days=32)).replace(day=1)
        return inicio, proximo
    return referencia, referencia + timedelta(days=1)


def navegar(tipo: str, referencia: date, passo: int) -> date:
    """Data de referência do período anterior (-1) ou seguinte (+1)."""
    if tipo == "semana":
        return referencia + timedelta(days=7 * passo)
    if tipo == "mes":
        primeiro = referencia.replace(day=1)
        if passo < 0:
            return (primeiro - timedelta(days=1)).replace(day=1)
        return (primeiro + timedelta(days=32)).replace(day=1)
    return referencia + timedelta(days=passo)


def rotulo_periodo(tipo: str, inicio: date, fim: date) -> str:
    ultimo = fim - timedelta(days=1)
    if tipo == "mes":
        return f"{MESES[inicio.month - 1].capitalize()} de {inicio.year}"
    if tipo == "semana":
        if inicio.month == ultimo.month:
            return f"{inicio.day} a {ultimo.day} de {MESES[ultimo.month - 1]} de {ultimo.year}"
        return f"{inicio.day} {MESES_CURTO[inicio.month - 1]} a {ultimo.day} {MESES_CURTO[ultimo.month - 1]} de {ultimo.year}"
    return f"{DIAS_SEMANA[inicio.weekday()].capitalize()}, {inicio.day} de {MESES[inicio.month - 1]} de {inicio.year}"


def dividir(valor_centavos: int, percentual: int) -> tuple[int, int]:
    """(parte do profissional, parte da barbearia). A soma sempre fecha."""
    profissional = (valor_centavos * percentual + 50) // 100
    return profissional, valor_centavos - profissional


@dataclass
class LinhaProfissional:
    barbeiro: Barbeiro
    atendimentos: int = 0
    bruto: int = 0
    profissional: int = 0
    barbearia: int = 0
    faltas: int = 0

    @property
    def percentual_efetivo(self) -> int:
        return round(100 * self.profissional / self.bruto) if self.bruto else self.barbeiro.comissao_percentual


@dataclass
class LancamentoDetalhado:
    agendamento: Agendamento
    barbeiro_nome: str
    cliente_nome: str
    percentual: int
    profissional: int
    barbearia: int


@dataclass
class Fechamento:
    tipo: str
    inicio: date
    fim: date
    rotulo: str
    linhas: list[LinhaProfissional] = field(default_factory=list)
    lancamentos: list[LancamentoDetalhado] = field(default_factory=list)
    bruto: int = 0
    profissional: int = 0
    barbearia: int = 0
    atendimentos: int = 0
    faltas: int = 0
    cancelados: int = 0

    @property
    def ticket_medio(self) -> int:
        return self.bruto // self.atendimentos if self.atendimentos else 0

    @property
    def taxa_faltas(self) -> int:
        base = self.atendimentos + self.faltas
        return round(100 * self.faltas / base) if base else 0


def calcular_fechamento(repo: Repositorio, barbearia: Barbearia, tipo: str, referencia: date) -> Fechamento:
    tipo = tipo if tipo in PERIODOS else "dia"
    inicio, fim = intervalo_periodo(tipo, referencia)
    fechamento = Fechamento(tipo=tipo, inicio=inicio, fim=fim, rotulo=rotulo_periodo(tipo, inicio, fim))

    agendamentos = [
        a for a in repo.agendamentos.listar_periodo(
            barbearia.id, datetime.combine(inicio, time.min), datetime.combine(fim, time.min)
        )
        if inicio <= a.inicio.date() < fim
    ]
    barbeiros = {b.id: b for b in repo.barbeiros.listar(barbearia.id)}
    clientes = repo.clientes.obter_varios(barbearia.id, {a.cliente_id for a in agendamentos})

    linhas: dict[int, LinhaProfissional] = {
        b.id: LinhaProfissional(barbeiro=b) for b in barbeiros.values() if b.ativo
    }
    for a in agendamentos:
        barbeiro = barbeiros.get(a.barbeiro_id)
        if barbeiro is None:
            continue
        linha = linhas.setdefault(barbeiro.id, LinhaProfissional(barbeiro=barbeiro))
        if a.status == StatusAgendamento.NAO_COMPARECEU:
            linha.faltas += 1
            fechamento.faltas += 1
            continue
        if a.status == StatusAgendamento.CANCELADO:
            fechamento.cancelados += 1
            continue
        if a.status != StatusAgendamento.CONCLUIDO:
            continue

        percentual = a.comissao_percentual if a.comissao_percentual is not None else barbeiro.comissao_percentual
        parte_prof, parte_casa = dividir(a.valor_centavos, percentual)
        linha.atendimentos += 1
        linha.bruto += a.valor_centavos
        linha.profissional += parte_prof
        linha.barbearia += parte_casa
        cliente = clientes.get(a.cliente_id)
        fechamento.lancamentos.append(LancamentoDetalhado(
            agendamento=a, barbeiro_nome=barbeiro.nome,
            cliente_nome=cliente.nome if cliente else "Cliente removido",
            percentual=percentual, profissional=parte_prof, barbearia=parte_casa,
        ))

    fechamento.linhas = sorted(linhas.values(), key=lambda l: (-l.bruto, l.barbeiro.nome))
    fechamento.lancamentos.sort(key=lambda l: l.agendamento.inicio)
    for linha in fechamento.linhas:
        fechamento.bruto += linha.bruto
        fechamento.profissional += linha.profissional
        fechamento.barbearia += linha.barbearia
        fechamento.atendimentos += linha.atendimentos
    return fechamento
