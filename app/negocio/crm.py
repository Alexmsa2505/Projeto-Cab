"""Mini CRM: histórico de frequência, clientes inativos e campanhas de reativação."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from ..models import Agendamento, Barbearia, Cliente, StatusAgendamento
from ..repositorios import Repositorio
from . import ErroNegocio
from .notificacoes import Notificador

# Não manda outra campanha para o mesmo cliente antes disso
INTERVALO_ENTRE_CAMPANHAS_DIAS = 7


@dataclass
class ResumoCliente:
    cliente: Cliente
    visitas: int = 0
    faltas: int = 0
    total_gasto: int = 0
    ultima_visita: datetime | None = None
    dias_sem_vir: int | None = None
    proximo_horario: datetime | None = None
    intervalo_medio_dias: int | None = None
    recente: bool = False   # veio dentro do prazo de inatividade
    inativo: bool = False   # não vem há X dias e não tem horário marcado
    campanha_recente: bool = False
    historico: list[Agendamento] = field(default_factory=list)

    @property
    def situacao(self) -> str:
        if self.proximo_horario:
            return "agendado"
        if self.visitas == 0:
            return "novo"
        return "inativo" if self.inativo else "ativo"


def _resumir(cliente: Cliente, agendamentos: list[Agendamento], barbearia: Barbearia, agora: datetime) -> ResumoCliente:
    r = ResumoCliente(cliente=cliente, historico=sorted(agendamentos, key=lambda a: a.inicio, reverse=True))
    concluidos = sorted((a for a in agendamentos if a.status == StatusAgendamento.CONCLUIDO), key=lambda a: a.inicio)
    r.visitas = len(concluidos)
    r.faltas = sum(1 for a in agendamentos if a.status == StatusAgendamento.NAO_COMPARECEU)
    r.total_gasto = sum(a.valor_centavos for a in concluidos)
    if concluidos:
        r.ultima_visita = concluidos[-1].inicio
        r.dias_sem_vir = (agora.date() - r.ultima_visita.date()).days
    if len(concluidos) >= 2:
        intervalos = [(b.inicio - a.inicio).days for a, b in zip(concluidos, concluidos[1:])]
        r.intervalo_medio_dias = round(sum(intervalos) / len(intervalos))
    futuros = [a for a in agendamentos if a.ativo and a.inicio >= agora]
    if futuros:
        r.proximo_horario = min(a.inicio for a in futuros)
    r.recente = r.dias_sem_vir is not None and r.dias_sem_vir < barbearia.dias_inatividade
    r.inativo = (
        r.dias_sem_vir is not None
        and r.dias_sem_vir >= barbearia.dias_inatividade
        and r.proximo_horario is None
    )
    r.campanha_recente = bool(
        cliente.ultima_campanha_em
        and agora - cliente.ultima_campanha_em < timedelta(days=INTERVALO_ENTRE_CAMPANHAS_DIAS)
    )
    return r


def resumir_clientes(repo: Repositorio, barbearia: Barbearia, agora: datetime) -> list[ResumoCliente]:
    por_cliente: dict[int, list[Agendamento]] = defaultdict(list)
    for a in repo.agendamentos.listar_todos(barbearia.id):
        por_cliente[a.cliente_id].append(a)
    return [_resumir(c, por_cliente.get(c.id, []), barbearia, agora) for c in repo.clientes.listar(barbearia.id)]


def resumo_do_cliente(repo: Repositorio, barbearia: Barbearia, cliente_id: int, agora: datetime) -> ResumoCliente | None:
    cliente = repo.clientes.obter(barbearia.id, cliente_id)
    if cliente is None:
        return None
    return _resumir(cliente, repo.agendamentos.listar_do_cliente(barbearia.id, cliente.id), barbearia, agora)


@dataclass
class Indicadores:
    total: int = 0
    ativos: int = 0
    inativos: int = 0
    agendados: int = 0
    intervalo_medio_dias: int | None = None


def indicadores(resumos: list[ResumoCliente]) -> Indicadores:
    ind = Indicadores(total=len(resumos))
    intervalos = []
    for r in resumos:
        ind.inativos += r.inativo
        ind.ativos += r.recente
        ind.agendados += r.proximo_horario is not None
        if r.intervalo_medio_dias is not None:
            intervalos.append(r.intervalo_medio_dias)
    if intervalos:
        ind.intervalo_medio_dias = round(sum(intervalos) / len(intervalos))
    return ind


def enviar_reativacao(
    repo: Repositorio, notificador: Notificador, barbearia: Barbearia,
    cliente_ids: list[int], modelo: str, agora: datetime,
) -> tuple[int, int]:
    """Envia a campanha para os clientes escolhidos. Devolve (enviados, ignorados)."""
    modelo = (modelo or "").strip()
    if len(modelo) < 10:
        raise ErroNegocio("Escreva a mensagem da campanha.")
    if "{link}" not in modelo:
        raise ErroNegocio("Inclua {link} na mensagem para o cliente conseguir agendar.")
    if not cliente_ids:
        raise ErroNegocio("Selecione pelo menos um cliente.")

    enviados = ignorados = 0
    for cliente_id in dict.fromkeys(cliente_ids):
        resumo = resumo_do_cliente(repo, barbearia, cliente_id, agora)
        if resumo is None or resumo.campanha_recente or resumo.proximo_horario:
            ignorados += 1
            continue
        notificador.reativacao(barbearia, resumo.cliente, modelo)
        resumo.cliente.ultima_campanha_em = agora
        repo.clientes.atualizar(resumo.cliente)
        enviados += 1
    return enviados, ignorados
