"""Disparo de mensagens por WhatsApp e SMS.

- `Notificador` monta os textos e registra cada envio na caixa de saída.
- Os provedores fazem a entrega de fato. Hoje o padrão é o console
  (imprime no terminal); Twilio e WhatsApp Cloud API (Meta) já estão
  prontos para receber as credenciais pelo .env.

Importante para produção: no WhatsApp oficial, mensagens iniciadas pela
empresa (código, lembrete, campanha) precisam usar templates aprovados pela
Meta. Os textos abaixo servem de base para cadastrar esses templates.
"""

from __future__ import annotations

import base64
import json
import logging
from abc import ABC, abstractmethod
from datetime import datetime
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from ..models import (
    Agendamento, Barbearia, Barbeiro, Canal, Cliente, Mensagem, StatusMensagem, TipoMensagem,
)
from ..utils import DIAS_SEMANA, agora_local, formatar_moeda

log = logging.getLogger("codewave.mensagens")


# ------------------------------------------------------------------ provedores
class ProvedorMensagens(ABC):
    @abstractmethod
    def enviar(self, telefone: str, texto: str) -> str | None:
        """Entrega a mensagem e devolve o id do provedor (se houver)."""


class ProvedorConsole(ProvedorMensagens):
    """Para desenvolvimento: mostra a mensagem no terminal."""

    def __init__(self, canal: str):
        self.canal = canal

    def enviar(self, telefone: str, texto: str) -> str | None:
        rotulo = Canal.ROTULOS.get(self.canal, self.canal)
        log.info("\n┌─ %s para %s\n│ %s\n└─", rotulo, telefone, texto.replace("\n", "\n│ "))
        return None


class ProvedorTwilio(ProvedorMensagens):
    """SMS ou WhatsApp via Twilio (API REST, sem SDK)."""

    def __init__(self, account_sid: str, auth_token: str, remetente: str, canal: str):
        if not (account_sid and auth_token and remetente):
            raise ValueError("Configure TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN e o número remetente.")
        self.account_sid = account_sid
        self.auth_token = auth_token
        self.remetente = remetente
        self.canal = canal

    def enviar(self, telefone: str, texto: str) -> str | None:
        prefixo = "whatsapp:" if self.canal == Canal.WHATSAPP else ""
        de = self.remetente if self.remetente.startswith(prefixo) else prefixo + self.remetente
        corpo = urlencode({"To": prefixo + telefone, "From": de, "Body": texto}).encode()
        url = f"https://api.twilio.com/2010-04-01/Accounts/{self.account_sid}/Messages.json"
        credencial = base64.b64encode(f"{self.account_sid}:{self.auth_token}".encode()).decode()
        requisicao = Request(url, data=corpo, method="POST", headers={"Authorization": f"Basic {credencial}"})
        with urlopen(requisicao, timeout=15) as resposta:
            return json.load(resposta).get("sid")


class ProvedorMetaWhatsApp(ProvedorMensagens):
    """WhatsApp Cloud API (Meta). Texto livre só funciona dentro da janela de
    24h após o cliente falar com a empresa; fora dela, use templates."""

    def __init__(self, token: str, phone_number_id: str, versao: str = "v21.0"):
        if not (token and phone_number_id):
            raise ValueError("Configure META_WHATSAPP_TOKEN e META_WHATSAPP_PHONE_ID.")
        self.token = token
        self.phone_number_id = phone_number_id
        self.versao = versao

    def enviar(self, telefone: str, texto: str) -> str | None:
        url = f"https://graph.facebook.com/{self.versao}/{self.phone_number_id}/messages"
        payload = {
            "messaging_product": "whatsapp",
            "to": telefone.lstrip("+"),
            "type": "text",
            "text": {"preview_url": False, "body": texto},
        }
        requisicao = Request(
            url, data=json.dumps(payload).encode(), method="POST",
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
        )
        with urlopen(requisicao, timeout=15) as resposta:
            dados = json.load(resposta)
            return (dados.get("messages") or [{}])[0].get("id")


def criar_provedores(config) -> dict[str, ProvedorMensagens]:
    def whatsapp() -> ProvedorMensagens:
        tipo = config.get("PROVEDOR_WHATSAPP", "console")
        if tipo == "twilio":
            return ProvedorTwilio(config["TWILIO_ACCOUNT_SID"], config["TWILIO_AUTH_TOKEN"],
                                  config["TWILIO_NUMERO_WHATSAPP"], Canal.WHATSAPP)
        if tipo == "meta":
            return ProvedorMetaWhatsApp(config["META_WHATSAPP_TOKEN"], config["META_WHATSAPP_PHONE_ID"],
                                        config.get("META_GRAPH_VERSAO", "v21.0"))
        return ProvedorConsole(Canal.WHATSAPP)

    def sms() -> ProvedorMensagens:
        if config.get("PROVEDOR_SMS", "console") == "twilio":
            return ProvedorTwilio(config["TWILIO_ACCOUNT_SID"], config["TWILIO_AUTH_TOKEN"],
                                  config["TWILIO_NUMERO_SMS"], Canal.SMS)
        return ProvedorConsole(Canal.SMS)

    return {Canal.WHATSAPP: whatsapp(), Canal.SMS: sms()}


# ------------------------------------------------------------------ links
def link_agendar(base_url: str, barbearia: Barbearia) -> str:
    return f"{base_url}/{barbearia.slug}/"


def link_agendamento(base_url: str, barbearia: Barbearia, ag: Agendamento, acao: str | None = None) -> str:
    # Os links abrem a página do comprovante, onde o cliente toca no botão.
    # Nunca confirme/cancele direto num GET: a pré-visualização de links do
    # WhatsApp acessa a URL sozinha e dispararia a ação.
    url = f"{base_url}/{barbearia.slug}/agendamento/{ag.token}"
    return f"{url}?acao={acao}" if acao else url


# ------------------------------------------------------------------ notificador
class Notificador:
    def __init__(self, repo, provedores: dict[str, ProvedorMensagens], fila, base_url: str):
        self.repo = repo
        self.provedores = provedores
        self.fila = fila
        self.base_url = base_url.rstrip("/")

    # -- infraestrutura -------------------------------------------------------
    def _enviar(self, barbearia: Barbearia, telefone: str, canal: str, tipo: str, texto: str,
                cliente_id: int | None = None, agendamento_id: int | None = None) -> Mensagem:
        mensagem = self.repo.mensagens.adicionar(Mensagem(
            barbearia_id=barbearia.id, telefone=telefone, canal=canal, tipo=tipo, texto=texto,
            cliente_id=cliente_id, agendamento_id=agendamento_id,
            criado_em=agora_local(barbearia.fuso_horario),
        ))
        self.fila.enfileirar(self.entregar, mensagem.id, barbearia.fuso_horario)
        return mensagem

    def entregar(self, mensagem_id: int, fuso_horario: str) -> None:
        """Executado pela fila: chama o provedor e anota o resultado."""
        mensagem = self.repo.mensagens.obter(mensagem_id)
        if mensagem is None:
            return
        provedor = self.provedores.get(mensagem.canal) or self.provedores[Canal.WHATSAPP]
        try:
            mensagem.id_externo = provedor.enviar(mensagem.telefone, mensagem.texto)
            mensagem.status = StatusMensagem.ENVIADA
            mensagem.erro = None
            mensagem.enviado_em = agora_local(fuso_horario)
        except Exception as exc:  # noqa: BLE001 - qualquer falha do provedor vira "falhou"
            log.exception("Falha ao enviar mensagem %s", mensagem_id)
            mensagem.status = StatusMensagem.FALHOU
            mensagem.erro = str(exc)[:300]
        self.repo.mensagens.atualizar(mensagem)

    def reenviar(self, barbearia: Barbearia, mensagem_id: int) -> None:
        mensagem = self.repo.mensagens.obter(mensagem_id)
        if mensagem is None or mensagem.barbearia_id != barbearia.id:
            return
        mensagem.status = StatusMensagem.PENDENTE
        self.repo.mensagens.atualizar(mensagem)
        self.fila.enfileirar(self.entregar, mensagem.id, barbearia.fuso_horario)

    # -- textos ---------------------------------------------------------------
    @staticmethod
    def _quando(barbearia: Barbearia, inicio: datetime) -> str:
        hoje = agora_local(barbearia.fuso_horario).date()
        dias = (inicio.date() - hoje).days
        if dias == 0:
            return f"hoje às {inicio:%H:%M}"
        if dias == 1:
            return f"amanhã às {inicio:%H:%M}"
        return f"{DIAS_SEMANA[inicio.weekday()]}, {inicio:%d/%m} às {inicio:%H:%M}"

    def codigo_verificacao(self, barbearia: Barbearia, telefone: str, canal: str, codigo: str, validade: int) -> Mensagem:
        texto = f"{codigo} é o seu código para confirmar o horário na {barbearia.nome}. Vale por {validade} minutos."
        return self._enviar(barbearia, telefone, canal, TipoMensagem.CODIGO, texto)

    def agendamento_criado(self, barbearia: Barbearia, ag: Agendamento, cliente: Cliente, barbeiro: Barbeiro) -> Mensagem:
        texto = (
            f"Horário marcado na {barbearia.nome}!\n"
            f"{self._quando(barbearia, ag.inicio).capitalize()} com {barbeiro.nome}.\n"
            f"{ag.descricao_servicos}: {formatar_moeda(ag.valor_centavos)}\n\n"
            f"Para remarcar ou cancelar: {link_agendamento(self.base_url, barbearia, ag)}"
        )
        return self._enviar(barbearia, cliente.telefone, ag.canal, TipoMensagem.CONFIRMACAO, texto, cliente.id, ag.id)

    def lembrete(self, barbearia: Barbearia, ag: Agendamento, cliente: Cliente, barbeiro: Barbeiro) -> Mensagem:
        texto = (
            f"Oi, {cliente.primeiro_nome}! Lembrete do seu horário na {barbearia.nome}: "
            f"{self._quando(barbearia, ag.inicio)} com {barbeiro.nome}.\n\n"
            f"Vai conseguir vir? Confirme aqui: {link_agendamento(self.base_url, barbearia, ag, 'confirmar')}\n"
            f"Precisa desmarcar? {link_agendamento(self.base_url, barbearia, ag, 'cancelar')}"
        )
        return self._enviar(barbearia, cliente.telefone, ag.canal, TipoMensagem.LEMBRETE, texto, cliente.id, ag.id)

    def agendamento_remarcado(self, barbearia: Barbearia, ag: Agendamento, cliente: Cliente, barbeiro: Barbeiro) -> Mensagem:
        texto = (
            f"Pronto, {cliente.primeiro_nome}! Seu horário na {barbearia.nome} agora é "
            f"{self._quando(barbearia, ag.inicio)} com {barbeiro.nome}.\n"
            f"Detalhes: {link_agendamento(self.base_url, barbearia, ag)}"
        )
        return self._enviar(barbearia, cliente.telefone, ag.canal, TipoMensagem.REMARCACAO, texto, cliente.id, ag.id)

    def agendamento_cancelado(self, barbearia: Barbearia, ag: Agendamento, cliente: Cliente,
                              barbeiro: Barbeiro | None, pela_barbearia: bool) -> Mensagem:
        quando = self._quando(barbearia, ag.inicio)
        novo = link_agendar(self.base_url, barbearia)
        if pela_barbearia:
            texto = (
                f"{cliente.primeiro_nome}, a {barbearia.nome} precisou cancelar seu horário de {quando}. "
                f"Desculpe o transtorno! Escolha outro horário: {novo}"
            )
        else:
            texto = f"Seu horário de {quando} na {barbearia.nome} foi cancelado. Quando quiser, é só marcar de novo: {novo}"
        return self._enviar(barbearia, cliente.telefone, ag.canal, TipoMensagem.CANCELAMENTO, texto, cliente.id, ag.id)

    def reativacao(self, barbearia: Barbearia, cliente: Cliente, modelo: str) -> Mensagem:
        texto = (
            modelo.replace("{nome}", cliente.primeiro_nome)
            .replace("{barbearia}", barbearia.nome)
            .replace("{link}", link_agendar(self.base_url, barbearia))
        )
        return self._enviar(barbearia, cliente.telefone, cliente.canal_preferido, TipoMensagem.REATIVACAO, texto, cliente.id)
