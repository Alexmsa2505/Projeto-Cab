"""Entidades do domínio.

Cada dataclass aqui corresponde a uma tabela do banco de dados que será
adicionado depois (veja database/schema.sql). Tudo que pertence a uma
barbearia carrega `barbearia_id`: é esse campo que garante o isolamento
multi-tenant.

Valores em dinheiro ficam em centavos (int) para evitar erros de arredondamento.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time


class StatusAgendamento:
    AGENDADO = "agendado"              # código validado, aguardando o dia
    CONFIRMADO = "confirmado"          # cliente confirmou presença (lembrete)
    CONCLUIDO = "concluido"            # atendido: entra no financeiro
    NAO_COMPARECEU = "nao_compareceu"  # no-show
    CANCELADO = "cancelado"

    ATIVOS = frozenset({AGENDADO, CONFIRMADO})
    OCUPAM_AGENDA = frozenset({AGENDADO, CONFIRMADO, CONCLUIDO, NAO_COMPARECEU})
    ENTRAM_NA_PREVISAO = frozenset({AGENDADO, CONFIRMADO, CONCLUIDO})

    ROTULOS = {
        AGENDADO: "Agendado",
        CONFIRMADO: "Confirmado",
        CONCLUIDO: "Concluído",
        NAO_COMPARECEU: "Não compareceu",
        CANCELADO: "Cancelado",
    }


class Canal:
    WHATSAPP = "whatsapp"
    SMS = "sms"
    TODOS = (WHATSAPP, SMS)
    ROTULOS = {WHATSAPP: "WhatsApp", SMS: "SMS"}


class Papel:
    DONO = "dono"
    BARBEIRO = "barbeiro"
    ROTULOS = {DONO: "Dono", BARBEIRO: "Barbeiro"}


class TipoMensagem:
    CODIGO = "codigo"
    CONFIRMACAO = "confirmacao"
    LEMBRETE = "lembrete"
    REMARCACAO = "remarcacao"
    CANCELAMENTO = "cancelamento"
    REATIVACAO = "reativacao"
    ROTULOS = {
        CODIGO: "Código",
        CONFIRMACAO: "Confirmação",
        LEMBRETE: "Lembrete",
        REMARCACAO: "Remarcação",
        CANCELAMENTO: "Cancelamento",
        REATIVACAO: "Reativação",
    }


class StatusMensagem:
    PENDENTE = "pendente"
    ENVIADA = "enviada"
    FALHOU = "falhou"
    ROTULOS = {PENDENTE: "Na fila", ENVIADA: "Enviada", FALHOU: "Falhou"}


MAX_FOTOS_PORTFOLIO = 2

MENSAGEM_REATIVACAO_PADRAO = (
    "Fala, {nome}! Faz um tempo que você não aparece na {barbearia}. "
    "Que tal deixar o visual em dia? Agende em menos de 1 minuto: {link}"
)


@dataclass(kw_only=True)
class Barbearia:
    """O tenant. Cada barbearia tem seu link: /<slug>."""

    id: int | None = None
    slug: str
    nome: str
    whatsapp: str = ""
    endereco: str = ""
    # White-label
    logo_url: str | None = None
    cor_primaria: str = "#B98B2F"
    cor_secundaria: str = "#173A30"
    # Funcionamento
    fuso_horario: str = "America/Sao_Paulo"
    abre_as: time = time(9, 0)
    fecha_as: time = time(19, 0)
    dias_funcionamento: list[int] = field(default_factory=lambda: [0, 1, 2, 3, 4, 5])  # 0 = segunda
    intervalo_minutos: int = 30
    antecedencia_minima_minutos: int = 60
    janela_agendamento_dias: int = 14
    # Lembretes e CRM
    lembrete_horas_antes: int = 3
    dias_inatividade: int = 30
    mensagem_reativacao: str = MENSAGEM_REATIVACAO_PADRAO
    criado_em: datetime = field(default_factory=datetime.now)


@dataclass(kw_only=True)
class Servico:
    id: int | None = None
    barbearia_id: int
    nome: str
    preco_centavos: int
    duracao_minutos: int
    ativo: bool = True
    ordem: int = 0


@dataclass(kw_only=True)
class Barbeiro:
    id: int | None = None
    barbearia_id: int
    nome: str
    especialidade: str = ""
    comissao_percentual: int = 50  # parte do profissional; o resto fica com a barbearia
    fotos: list[str] = field(default_factory=list)  # portfólio (até 2) -> tabela barbeiro_fotos
    ativo: bool = True

    @property
    def iniciais(self) -> str:
        partes = self.nome.split()
        if not partes:
            return "?"
        if len(partes) == 1:
            return partes[0][:2].upper()
        return (partes[0][0] + partes[-1][0]).upper()

    @property
    def primeiro_nome(self) -> str:
        return self.nome.split()[0] if self.nome.split() else self.nome


@dataclass(kw_only=True)
class Cliente:
    id: int | None = None
    barbearia_id: int
    nome: str
    telefone: str  # formato E.164: +5511987654321
    canal_preferido: str = Canal.WHATSAPP
    criado_em: datetime = field(default_factory=datetime.now)
    ultima_campanha_em: datetime | None = None

    @property
    def primeiro_nome(self) -> str:
        return self.nome.split()[0] if self.nome.split() else self.nome


@dataclass(kw_only=True)
class ItemAgendamento:
    """Cópia do serviço no momento do agendamento (o preço pode mudar depois)."""

    servico_id: int
    nome: str
    preco_centavos: int
    duracao_minutos: int


@dataclass(kw_only=True)
class Agendamento:
    id: int | None = None
    barbearia_id: int
    cliente_id: int
    barbeiro_id: int
    inicio: datetime
    fim: datetime
    itens: list[ItemAgendamento] = field(default_factory=list)
    valor_centavos: int = 0
    status: str = StatusAgendamento.AGENDADO
    token: str = ""  # usado no link de gestão do cliente
    canal: str = Canal.WHATSAPP
    criado_em: datetime = field(default_factory=datetime.now)
    remarcado_em: datetime | None = None
    lembrete_enviado_em: datetime | None = None
    confirmado_em: datetime | None = None
    cancelado_em: datetime | None = None
    concluido_em: datetime | None = None
    # Percentual de comissão "congelado" quando o atendimento é concluído
    comissao_percentual: int | None = None

    @property
    def ativo(self) -> bool:
        return self.status in StatusAgendamento.ATIVOS

    @property
    def duracao_minutos(self) -> int:
        return int((self.fim - self.inicio).total_seconds() // 60)

    @property
    def descricao_servicos(self) -> str:
        nomes = [item.nome for item in self.itens]
        if len(nomes) <= 1:
            return "".join(nomes)
        return ", ".join(nomes[:-1]) + " e " + nomes[-1]


@dataclass(kw_only=True)
class Bloqueio:
    """Horário fechado na agenda (almoço, pausa, imprevisto...)."""

    id: int | None = None
    barbearia_id: int
    barbeiro_id: int | None  # None = barbearia inteira (feriado, por exemplo)
    inicio: datetime
    fim: datetime
    motivo: str = "Pausa"
    criado_em: datetime = field(default_factory=datetime.now)


@dataclass(kw_only=True)
class Usuario:
    """Acesso ao painel. O dono vê tudo; o barbeiro cuida da própria agenda."""

    id: int | None = None
    barbearia_id: int
    nome: str
    email: str
    senha_hash: str
    papel: str = Papel.DONO
    barbeiro_id: int | None = None
    ativo: bool = True

    @property
    def e_dono(self) -> bool:
        return self.papel == Papel.DONO


@dataclass(kw_only=True)
class VerificacaoTelefone:
    """Pedido de agendamento aguardando o código de 4 dígitos."""

    id: int | None = None
    barbearia_id: int
    token: str
    telefone: str
    canal: str
    codigo: str
    dados: dict  # nome, barbeiro_id, servico_ids, inicio (ISO) -> vira JSONB no banco
    expira_em: datetime
    ultimo_envio_em: datetime
    tentativas: int = 0
    criado_em: datetime = field(default_factory=datetime.now)


@dataclass(kw_only=True)
class Mensagem:
    """Registro de cada WhatsApp/SMS disparado (caixa de saída e auditoria)."""

    id: int | None = None
    barbearia_id: int
    telefone: str
    canal: str
    tipo: str
    texto: str
    status: str = StatusMensagem.PENDENTE
    erro: str | None = None
    id_externo: str | None = None
    cliente_id: int | None = None
    agendamento_id: int | None = None
    criado_em: datetime = field(default_factory=datetime.now)
    enviado_em: datetime | None = None
