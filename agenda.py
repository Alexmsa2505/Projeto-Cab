"""Agenda: horários livres, dias abertos, bloqueios e o quadro do dia do painel."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from ..models import Agendamento, Barbearia, Barbeiro, Bloqueio, Cliente, StatusAgendamento
from ..repositorios import Repositorio
from ..utils import DIAS_SEMANA_CURTO, MESES_CURTO
from . import ErroNegocio

MOTIVOS_BLOQUEIO = ("Almoço", "Pausa", "Imprevisto", "Folga", "Compromisso")

PERIODOS_DO_DIA = (
    ("Manhã", time(0, 0), time(12, 0)),
    ("Tarde", time(12, 0), time(18, 0)),
    ("Noite", time(18, 0), time.max),
)


# ----------------------------------------------------------------- expediente
def inicio_do_dia(dia: date) -> datetime:
    return datetime.combine(dia, time.min)


def expediente(barbearia: Barbearia, dia: date) -> tuple[datetime, datetime] | None:
    """(abertura, fechamento) do dia ou None se a barbearia não abre."""
    if dia.weekday() not in barbearia.dias_funcionamento:
        return None
    return datetime.combine(dia, barbearia.abre_as), datetime.combine(dia, barbearia.fecha_as)


def _sobrepoe(a_ini: datetime, a_fim: datetime, b_ini: datetime, b_fim: datetime) -> bool:
    return a_ini < b_fim and b_ini < a_fim


def ocupacoes(
    repo: Repositorio, barbearia: Barbearia, barbeiro_id: int, dia: date,
    ignorar_agendamento_id: int | None = None,
) -> list[tuple[datetime, datetime]]:
    """Intervalos indisponíveis do profissional: agendamentos + bloqueios."""
    ini, fim = inicio_do_dia(dia), inicio_do_dia(dia + timedelta(days=1))
    intervalos = [
        (a.inicio, a.fim)
        for a in repo.agendamentos.listar_periodo(barbearia.id, ini, fim, barbeiro_id=barbeiro_id)
        if a.status in StatusAgendamento.OCUPAM_AGENDA and a.id != ignorar_agendamento_id
    ]
    intervalos += [
        (b.inicio, b.fim)
        for b in repo.bloqueios.listar_periodo(barbearia.id, ini, fim, barbeiro_id=barbeiro_id)
    ]
    return intervalos


def horarios_disponiveis(
    repo: Repositorio,
    barbearia: Barbearia,
    barbeiro_id: int,
    dia: date,
    duracao_minutos: int,
    agora: datetime | None = None,
    ignorar_agendamento_id: int | None = None,
) -> list[datetime]:
    """Inícios possíveis para um atendimento de `duracao_minutos`.

    `agora=None` ignora a antecedência mínima (útil para dados de exemplo).
    """
    janela = expediente(barbearia, dia)
    if janela is None or duracao_minutos <= 0:
        return []
    abertura, fechamento = janela
    passo = timedelta(minutes=max(5, barbearia.intervalo_minutos))
    duracao = timedelta(minutes=duracao_minutos)
    minimo = agora + timedelta(minutes=barbearia.antecedencia_minima_minutos) if agora else None
    ocupado = ocupacoes(repo, barbearia, barbeiro_id, dia, ignorar_agendamento_id)

    livres: list[datetime] = []
    inicio = abertura
    while inicio + duracao <= fechamento:
        fim = inicio + duracao
        if (minimo is None or inicio >= minimo) and not any(
            _sobrepoe(inicio, fim, o_ini, o_fim) for o_ini, o_fim in ocupado
        ):
            livres.append(inicio)
        inicio += passo
    return livres


def horario_esta_livre(
    repo: Repositorio, barbearia: Barbearia, barbeiro_id: int, inicio: datetime,
    duracao_minutos: int, agora: datetime | None = None, ignorar_agendamento_id: int | None = None,
) -> bool:
    return inicio in horarios_disponiveis(
        repo, barbearia, barbeiro_id, inicio.date(), duracao_minutos, agora, ignorar_agendamento_id
    )


def agrupar_por_periodo(horarios: list[datetime]) -> list[tuple[str, list[datetime]]]:
    grupos = []
    for rotulo, ini, fim in PERIODOS_DO_DIA:
        itens = [h for h in horarios if ini <= h.time() < fim]
        if itens:
            grupos.append((rotulo, itens))
    return grupos


# --------------------------------------------------------------- dias abertos
@dataclass(frozen=True)
class DiaAgendavel:
    data: date
    aberto: bool
    rotulo: str
    dia: int
    mes: str


def dias_agendaveis(barbearia: Barbearia, agora: datetime) -> list[DiaAgendavel]:
    hoje = agora.date()
    antecedencia = timedelta(minutes=barbearia.antecedencia_minima_minutos)
    dias = []
    for i in range(max(1, barbearia.janela_agendamento_dias)):
        d = hoje + timedelta(days=i)
        janela = expediente(barbearia, d)
        aberto = janela is not None and (agora + antecedencia) < janela[1]
        if i == 0:
            rotulo = "Hoje"
        elif i == 1:
            rotulo = "Amanhã"
        else:
            rotulo = DIAS_SEMANA_CURTO[d.weekday()].capitalize()
        dias.append(DiaAgendavel(d, aberto, rotulo, d.day, MESES_CURTO[d.month - 1]))
    return dias


def ultimo_dia_agendavel(barbearia: Barbearia, agora: datetime) -> date:
    return agora.date() + timedelta(days=max(1, barbearia.janela_agendamento_dias) - 1)


# ------------------------------------------------------------------ bloqueios
def criar_bloqueio(
    repo: Repositorio, barbearia: Barbearia, barbeiro_id: int | None,
    inicio: datetime, fim: datetime, motivo: str, agora: datetime,
) -> Bloqueio:
    motivo = " ".join((motivo or "").split())[:60] or "Pausa"
    if fim <= inicio:
        raise ErroNegocio("O horário final precisa ser depois do inicial.")
    if fim.date() != inicio.date() and fim != inicio_do_dia(inicio.date() + timedelta(days=1)):
        raise ErroNegocio("O bloqueio precisa começar e terminar no mesmo dia.")
    if fim <= agora:
        raise ErroNegocio("Esse horário já passou.")
    if barbeiro_id is not None and repo.barbeiros.obter(barbearia.id, barbeiro_id) is None:
        raise ErroNegocio("Profissional não encontrado.")

    with repo.transacao():
        conflitos = [
            a for a in repo.agendamentos.listar_periodo(barbearia.id, inicio, fim, barbeiro_id=barbeiro_id)
            if a.ativo
        ]
        if conflitos:
            horas = ", ".join(f"{a.inicio:%H:%M}" for a in conflitos[:3])
            raise ErroNegocio(
                f"Já tem cliente marcado nesse intervalo ({horas}). "
                "Remarque ou cancele o horário antes de bloquear."
            )
        return repo.bloqueios.adicionar(Bloqueio(
            barbearia_id=barbearia.id, barbeiro_id=barbeiro_id,
            inicio=inicio, fim=fim, motivo=motivo, criado_em=agora,
        ))


# --------------------------------------------------------- quadro do painel
@dataclass
class ItemLinha:
    tipo: str  # "agendamento" | "bloqueio" | "livre"
    inicio: datetime
    fim: datetime
    agendamento: Agendamento | None = None
    bloqueio: Bloqueio | None = None
    cliente: Cliente | None = None
    passado: bool = False

    @property
    def minutos(self) -> int:
        return int((self.fim - self.inicio).total_seconds() // 60)


@dataclass
class ColunaBarbeiro:
    barbeiro: Barbeiro
    itens: list[ItemLinha] = field(default_factory=list)
    qtd_agendamentos: int = 0
    previsto_centavos: int = 0


@dataclass
class QuadroDia:
    dia: date
    aberto: bool
    colunas: list[ColunaBarbeiro]
    total_agendamentos: int = 0
    aguardando_confirmacao: int = 0
    horarios_vagos: int = 0
    ocupacao_percentual: int = 0
    previsto_centavos: int = 0
    realizado_centavos: int = 0


def _livres(ini: datetime, fim: datetime, abertura: datetime, passo_min: int, agora: datetime) -> list[ItemLinha]:
    """Fatias livres alinhadas à grade da agenda (ex.: de 30 em 30 minutos)."""
    itens = []
    cursor = ini
    while cursor < fim:
        deslocamento = int((cursor - abertura).total_seconds() // 60)
        proximo = abertura + timedelta(minutes=(deslocamento // passo_min + 1) * passo_min)
        proximo = min(proximo, fim)
        itens.append(ItemLinha("livre", cursor, proximo, passado=proximo <= agora))
        cursor = proximo
    return itens


def linha_do_tempo(
    barbearia: Barbearia, dia: date, agendamentos: list[Agendamento], bloqueios: list[Bloqueio],
    clientes: dict[int, Cliente], agora: datetime,
) -> list[ItemLinha]:
    eventos: list[ItemLinha] = [
        ItemLinha("agendamento", a.inicio, a.fim, agendamento=a, cliente=clientes.get(a.cliente_id))
        for a in agendamentos
    ] + [ItemLinha("bloqueio", b.inicio, b.fim, bloqueio=b) for b in bloqueios]
    eventos.sort(key=lambda e: (e.inicio, e.tipo))

    janela = expediente(barbearia, dia)
    if janela is None:
        return eventos

    abertura, fechamento = janela
    passo = max(5, barbearia.intervalo_minutos)
    itens: list[ItemLinha] = []
    cursor = abertura
    for evento in eventos:
        if evento.inicio > cursor and cursor < fechamento:
            itens += _livres(cursor, min(evento.inicio, fechamento), abertura, passo, agora)
        itens.append(evento)
        cursor = max(cursor, evento.fim)
    if cursor < fechamento:
        itens += _livres(cursor, fechamento, abertura, passo, agora)
    return itens


def montar_quadro(
    repo: Repositorio, barbearia: Barbearia, dia: date, agora: datetime,
    barbeiros: list[Barbeiro] | None = None,
) -> QuadroDia:
    ini, fim = inicio_do_dia(dia), inicio_do_dia(dia + timedelta(days=1))
    barbeiros = barbeiros if barbeiros is not None else repo.barbeiros.listar(barbearia.id, apenas_ativos=True)
    agendamentos = [
        a for a in repo.agendamentos.listar_periodo(barbearia.id, ini, fim)
        if a.status in StatusAgendamento.OCUPAM_AGENDA
    ]
    bloqueios = repo.bloqueios.listar_periodo(barbearia.id, ini, fim)
    clientes = repo.clientes.obter_varios(barbearia.id, {a.cliente_id for a in agendamentos})

    quadro = QuadroDia(dia=dia, aberto=expediente(barbearia, dia) is not None, colunas=[])
    minutos_ocupados = minutos_livres = 0

    for barbeiro in barbeiros:
        dele = [a for a in agendamentos if a.barbeiro_id == barbeiro.id]
        bloqueios_dele = [b for b in bloqueios if b.barbeiro_id in (None, barbeiro.id)]
        coluna = ColunaBarbeiro(
            barbeiro=barbeiro,
            itens=linha_do_tempo(barbearia, dia, dele, bloqueios_dele, clientes, agora),
        )
        for item in coluna.itens:
            if item.tipo == "agendamento":
                minutos_ocupados += item.minutos
            elif item.tipo == "livre":
                minutos_livres += item.minutos
                if not item.passado:
                    quadro.horarios_vagos += 1
        for a in dele:
            if a.status in StatusAgendamento.ENTRAM_NA_PREVISAO:
                coluna.qtd_agendamentos += 1
                coluna.previsto_centavos += a.valor_centavos
        quadro.colunas.append(coluna)

    for a in agendamentos:
        if a.status in StatusAgendamento.ENTRAM_NA_PREVISAO:
            quadro.total_agendamentos += 1
            quadro.previsto_centavos += a.valor_centavos
        if a.status == StatusAgendamento.CONCLUIDO:
            quadro.realizado_centavos += a.valor_centavos
        if a.status == StatusAgendamento.AGENDADO:
            quadro.aguardando_confirmacao += 1

    capacidade = minutos_ocupados + minutos_livres
    quadro.ocupacao_percentual = round(100 * minutos_ocupados / capacidade) if capacidade else 0
    return quadro
