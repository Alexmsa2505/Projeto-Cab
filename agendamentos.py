"""Fluxo de agendamento do cliente e mudanças de status feitas pelo painel."""

from __future__ import annotations

import hmac
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from ..models import (
    Agendamento, Barbearia, Barbeiro, Canal, Cliente, ItemAgendamento, Servico,
    StatusAgendamento, TipoMensagem, VerificacaoTelefone,
)
from ..repositorios import Repositorio
from ..utils import formatar_duracao, normalizar_telefone
from . import ErroNegocio, HorarioIndisponivel, agenda
from .notificacoes import Notificador
from .verificacao import PoliticaAntiTrote, gerar_codigo, gerar_token, segundos_para_reenvio


# ------------------------------------------------------------------ seleção
@dataclass
class Selecao:
    """O que o cliente escolheu até agora (serviços + profissional)."""

    servicos: list[Servico] = field(default_factory=list)
    barbeiro: Barbeiro | None = None

    @property
    def total_centavos(self) -> int:
        return sum(s.preco_centavos for s in self.servicos)

    @property
    def duracao_minutos(self) -> int:
        return sum(s.duracao_minutos for s in self.servicos)


def carregar_selecao(
    repo: Repositorio, barbearia: Barbearia, servico_ids: list[int], barbeiro_id: int | None
) -> Selecao:
    ativos = repo.servicos.listar(barbearia.id, apenas_ativos=True)
    escolhidos = set(servico_ids or [])
    barbeiro = repo.barbeiros.obter(barbearia.id, barbeiro_id) if barbeiro_id else None
    if barbeiro is not None and not barbeiro.ativo:
        barbeiro = None
    return Selecao(servicos=[s for s in ativos if s.id in escolhidos], barbeiro=barbeiro)


# ------------------------------------------------------------- solicitação
@dataclass
class Solicitacao:
    nome: str
    telefone: str
    canal: str
    servico_ids: list[int]
    barbeiro_id: int
    inicio: datetime

    def para_dict(self) -> dict:
        return {
            "nome": self.nome, "telefone": self.telefone, "canal": self.canal,
            "servico_ids": self.servico_ids, "barbeiro_id": self.barbeiro_id,
            "inicio": self.inicio.isoformat(timespec="minutes"),
        }

    @classmethod
    def de_dict(cls, dados: dict) -> "Solicitacao":
        return cls(
            nome=dados["nome"], telefone=dados["telefone"], canal=dados["canal"],
            servico_ids=list(dados["servico_ids"]), barbeiro_id=int(dados["barbeiro_id"]),
            inicio=datetime.fromisoformat(dados["inicio"]),
        )


def validar_solicitacao(
    repo: Repositorio, politica: PoliticaAntiTrote, barbearia: Barbearia, *,
    nome: str, telefone: str, canal: str, servico_ids: list[int], barbeiro_id: int | None,
    data: date | None, horario: time | None, agora: datetime,
) -> Solicitacao:
    """Confere tudo antes de mandar o código. Não grava nada."""
    selecao = carregar_selecao(repo, barbearia, servico_ids, barbeiro_id)
    if not selecao.servicos:
        raise ErroNegocio("Escolha pelo menos um serviço.")
    if selecao.barbeiro is None:
        raise ErroNegocio("Escolha o profissional.")
    if data is None or horario is None:
        raise ErroNegocio("Escolha o dia e o horário.")

    nome = " ".join((nome or "").split())[:80]
    if len(nome) < 2:
        raise ErroNegocio("Informe seu nome.")
    telefone_e164 = normalizar_telefone(telefone)
    if telefone_e164 is None:
        raise ErroNegocio("Informe um celular válido com DDD, como (11) 98765-4321.")
    canal = canal if canal in Canal.TODOS else Canal.WHATSAPP

    if data > agenda.ultimo_dia_agendavel(barbearia, agora):
        raise ErroNegocio("Esse dia ainda não está aberto para agendamento.")
    inicio = datetime.combine(data, horario)
    if not agenda.horario_esta_livre(repo, barbearia, selecao.barbeiro.id, inicio, selecao.duracao_minutos, agora):
        raise HorarioIndisponivel("Esse horário não está mais livre. Escolha outro.")

    cliente = repo.clientes.por_telefone(barbearia.id, telefone_e164)
    if cliente is not None:
        ativos = [a for a in repo.agendamentos.listar_do_cliente(barbearia.id, cliente.id) if a.ativo and a.fim > agora]
        if len(ativos) >= politica.max_agendamentos_ativos:
            raise ErroNegocio(
                f"Este número já tem {len(ativos)} horários marcados. "
                "Cancele um deles pelo link do comprovante para marcar outro."
            )

    return Solicitacao(
        nome=nome, telefone=telefone_e164, canal=canal,
        servico_ids=[s.id for s in selecao.servicos], barbeiro_id=selecao.barbeiro.id, inicio=inicio,
    )


def _checar_limite_envios(repo, politica, barbearia, telefone, agora):
    enviados = repo.mensagens.contar_desde(barbearia.id, telefone, TipoMensagem.CODIGO, agora - timedelta(hours=1))
    if enviados >= politica.max_envios_por_hora:
        raise ErroNegocio("Já enviamos vários códigos para este número. Tente de novo daqui a pouco.")


def iniciar_verificacao(
    repo: Repositorio, notificador: Notificador, politica: PoliticaAntiTrote,
    barbearia: Barbearia, solicitacao: Solicitacao, agora: datetime,
) -> VerificacaoTelefone:
    """Gera o código de 4 dígitos e envia por WhatsApp ou SMS."""
    _checar_limite_envios(repo, politica, barbearia, solicitacao.telefone, agora)
    codigo = gerar_codigo()
    verificacao = repo.verificacoes.adicionar(VerificacaoTelefone(
        barbearia_id=barbearia.id, token=gerar_token(), telefone=solicitacao.telefone,
        canal=solicitacao.canal, codigo=codigo, dados=solicitacao.para_dict(),
        expira_em=agora + timedelta(minutes=politica.validade_minutos),
        ultimo_envio_em=agora, criado_em=agora,
    ))
    notificador.codigo_verificacao(barbearia, solicitacao.telefone, solicitacao.canal, codigo, politica.validade_minutos)
    return verificacao


def reenviar_codigo(
    repo: Repositorio, notificador: Notificador, politica: PoliticaAntiTrote,
    barbearia: Barbearia, token: str, agora: datetime,
) -> VerificacaoTelefone:
    verificacao = repo.verificacoes.por_token(barbearia.id, token)
    if verificacao is None:
        raise ErroNegocio("Esse pedido expirou. Faça o agendamento de novo.")
    espera = segundos_para_reenvio(politica, verificacao.ultimo_envio_em, agora)
    if espera > 0:
        raise ErroNegocio(f"Aguarde {espera} segundos para pedir outro código.")
    _checar_limite_envios(repo, politica, barbearia, verificacao.telefone, agora)
    verificacao.codigo = gerar_codigo()
    verificacao.tentativas = 0
    verificacao.expira_em = agora + timedelta(minutes=politica.validade_minutos)
    verificacao.ultimo_envio_em = agora
    repo.verificacoes.atualizar(verificacao)
    notificador.codigo_verificacao(barbearia, verificacao.telefone, verificacao.canal, verificacao.codigo, politica.validade_minutos)
    return verificacao


def conferir_codigo(
    repo: Repositorio, politica: PoliticaAntiTrote, barbearia: Barbearia,
    token: str, codigo: str, agora: datetime,
) -> VerificacaoTelefone:
    """Valida o código digitado. Devolve a verificação se estiver certo."""
    verificacao = repo.verificacoes.por_token(barbearia.id, token)
    if verificacao is None:
        raise ErroNegocio("Esse pedido expirou. Faça o agendamento de novo.")
    if agora > verificacao.expira_em:
        raise ErroNegocio("O código expirou. Toque em “Reenviar código” para receber outro.")
    if verificacao.tentativas >= politica.max_tentativas:
        raise ErroNegocio("Muitas tentativas erradas. Peça um novo código.")
    digitado = re.sub(r"\D", "", codigo or "")
    if not hmac.compare_digest(digitado, verificacao.codigo):
        verificacao.tentativas += 1
        repo.verificacoes.atualizar(verificacao)
        restantes = politica.max_tentativas - verificacao.tentativas
        if restantes <= 0:
            raise ErroNegocio("Código incorreto. Peça um novo código.")
        plural = "tentativa" if restantes == 1 else "tentativas"
        raise ErroNegocio(f"Código incorreto. Você ainda tem {restantes} {plural}.")
    return verificacao


def criar_agendamento(
    repo: Repositorio, notificador: Notificador, barbearia: Barbearia,
    solicitacao: Solicitacao, agora: datetime,
) -> Agendamento:
    """Grava o agendamento (telefone já validado) e envia o comprovante."""
    with repo.transacao():
        selecao = carregar_selecao(repo, barbearia, solicitacao.servico_ids, solicitacao.barbeiro_id)
        if not selecao.servicos or selecao.barbeiro is None:
            raise ErroNegocio("Um dos serviços ou o profissional escolhido não está mais disponível.")
        if not agenda.horario_esta_livre(
            repo, barbearia, selecao.barbeiro.id, solicitacao.inicio, selecao.duracao_minutos, agora
        ):
            raise HorarioIndisponivel("Esse horário acabou de ser ocupado. Escolha outro.")

        cliente = repo.clientes.por_telefone(barbearia.id, solicitacao.telefone)
        if cliente is None:
            cliente = repo.clientes.adicionar(Cliente(
                barbearia_id=barbearia.id, nome=solicitacao.nome, telefone=solicitacao.telefone,
                canal_preferido=solicitacao.canal, criado_em=agora,
            ))
        else:
            cliente.nome = solicitacao.nome
            cliente.canal_preferido = solicitacao.canal
            cliente = repo.clientes.atualizar(cliente)

        agendamento = repo.agendamentos.adicionar(Agendamento(
            barbearia_id=barbearia.id, cliente_id=cliente.id, barbeiro_id=selecao.barbeiro.id,
            inicio=solicitacao.inicio,
            fim=solicitacao.inicio + timedelta(minutes=selecao.duracao_minutos),
            itens=[
                ItemAgendamento(servico_id=s.id, nome=s.nome, preco_centavos=s.preco_centavos,
                                duracao_minutos=s.duracao_minutos)
                for s in selecao.servicos
            ],
            valor_centavos=selecao.total_centavos, status=StatusAgendamento.AGENDADO,
            token=gerar_token(), canal=solicitacao.canal, criado_em=agora,
        ))
    notificador.agendamento_criado(barbearia, agendamento, cliente, selecao.barbeiro)
    return agendamento


# ---------------------------------------------------- ações do próprio cliente
def prazo_para_alterar(barbearia: Barbearia) -> str:
    return formatar_duracao(barbearia.antecedencia_minima_minutos)


def pode_alterar(barbearia: Barbearia, ag: Agendamento, agora: datetime) -> bool:
    """Remarcar/cancelar online só até a antecedência mínima configurada."""
    limite = timedelta(minutes=barbearia.antecedencia_minima_minutos)
    return ag.ativo and ag.inicio - agora >= limite


def pode_confirmar(ag: Agendamento, agora: datetime) -> bool:
    return ag.status == StatusAgendamento.AGENDADO and ag.inicio > agora


def _partes(repo: Repositorio, barbearia: Barbearia, ag: Agendamento):
    cliente = repo.clientes.obter(barbearia.id, ag.cliente_id)
    barbeiro = repo.barbeiros.obter(barbearia.id, ag.barbeiro_id)
    return cliente, barbeiro


def confirmar_presenca(repo: Repositorio, barbearia: Barbearia, ag: Agendamento, agora: datetime) -> Agendamento:
    if ag.status == StatusAgendamento.CONFIRMADO:
        return ag
    if not pode_confirmar(ag, agora):
        raise ErroNegocio("Este horário não pode mais ser confirmado.")
    ag.status = StatusAgendamento.CONFIRMADO
    ag.confirmado_em = agora
    return repo.agendamentos.atualizar(ag)


def cancelar_pelo_cliente(
    repo: Repositorio, notificador: Notificador, barbearia: Barbearia, ag: Agendamento, agora: datetime
) -> Agendamento:
    if not ag.ativo:
        raise ErroNegocio("Este horário já foi encerrado.")
    if not pode_alterar(barbearia, ag, agora):
        raise ErroNegocio(
            f"Cancelamentos pelo link valem até {prazo_para_alterar(barbearia)} antes do horário. "
            "Fale com a barbearia pelo WhatsApp."
        )
    ag.status = StatusAgendamento.CANCELADO
    ag.cancelado_em = agora
    ag = repo.agendamentos.atualizar(ag)
    cliente, barbeiro = _partes(repo, barbearia, ag)
    notificador.agendamento_cancelado(barbearia, ag, cliente, barbeiro, pela_barbearia=False)
    return ag


def remarcar(
    repo: Repositorio, notificador: Notificador, barbearia: Barbearia, ag: Agendamento,
    novo_inicio: datetime, agora: datetime,
) -> Agendamento:
    if not pode_alterar(barbearia, ag, agora):
        raise ErroNegocio(
            f"Remarcações pelo link valem até {prazo_para_alterar(barbearia)} antes do horário. "
            "Fale com a barbearia pelo WhatsApp."
        )
    if novo_inicio.date() > agenda.ultimo_dia_agendavel(barbearia, agora):
        raise ErroNegocio("Esse dia ainda não está aberto para agendamento.")
    duracao = ag.duracao_minutos
    with repo.transacao():
        if not agenda.horario_esta_livre(
            repo, barbearia, ag.barbeiro_id, novo_inicio, duracao, agora, ignorar_agendamento_id=ag.id
        ):
            raise HorarioIndisponivel("Esse horário não está mais livre. Escolha outro.")
        ag.inicio = novo_inicio
        ag.fim = novo_inicio + timedelta(minutes=duracao)
        ag.status = StatusAgendamento.AGENDADO
        ag.confirmado_em = None
        ag.lembrete_enviado_em = None
        ag.remarcado_em = agora
        ag = repo.agendamentos.atualizar(ag)
    cliente, barbeiro = _partes(repo, barbearia, ag)
    notificador.agendamento_remarcado(barbearia, ag, cliente, barbeiro)
    return ag


# ------------------------------------------------------- ações do painel
ACOES_PAINEL = ("confirmar", "concluir", "faltou", "cancelar", "reabrir")


def alterar_status(
    repo: Repositorio, notificador: Notificador, barbearia: Barbearia,
    ag: Agendamento, acao: str, agora: datetime,
) -> Agendamento:
    s = StatusAgendamento
    if acao == "confirmar":
        if ag.status != s.AGENDADO:
            raise ErroNegocio("Só dá para confirmar um horário que está agendado.")
        ag.status, ag.confirmado_em = s.CONFIRMADO, agora
    elif acao == "concluir":
        if ag.status not in (s.AGENDADO, s.CONFIRMADO, s.NAO_COMPARECEU):
            raise ErroNegocio("Este horário não pode ser concluído.")
        barbeiro = repo.barbeiros.obter(barbearia.id, ag.barbeiro_id)
        ag.status, ag.concluido_em = s.CONCLUIDO, agora
        ag.comissao_percentual = barbeiro.comissao_percentual if barbeiro else 50
    elif acao == "faltou":
        if not ag.ativo:
            raise ErroNegocio("Este horário já foi encerrado.")
        if agora < ag.inicio:
            raise ErroNegocio("Só dá para marcar falta depois do horário começar.")
        ag.status = s.NAO_COMPARECEU
    elif acao == "cancelar":
        if not ag.ativo:
            raise ErroNegocio("Este horário já foi encerrado.")
        ag.status, ag.cancelado_em = s.CANCELADO, agora
    elif acao == "reabrir":
        if ag.status not in (s.CONCLUIDO, s.NAO_COMPARECEU):
            raise ErroNegocio("Só dá para reabrir um horário concluído ou com falta.")
        ag.status = s.CONFIRMADO if ag.confirmado_em else s.AGENDADO
        ag.concluido_em = None
        ag.comissao_percentual = None
    else:
        raise ErroNegocio("Ação desconhecida.")

    ag = repo.agendamentos.atualizar(ag)
    if acao == "cancelar":
        cliente, barbeiro = _partes(repo, barbearia, ag)
        notificador.agendamento_cancelado(barbearia, ag, cliente, barbeiro, pela_barbearia=True)
    return ag
