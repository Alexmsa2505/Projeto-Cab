"""Tarefas em segundo plano (equivalente às filas/jobs do Laravel).

- FilaDeMensagens: entrega WhatsApp/SMS sem travar a requisição do cliente.
- AgendadorDeLembretes: a cada minuto procura horários que precisam de lembrete.

Para produção com banco de dados, troque a fila por RQ ou Celery (Redis) e
rode `flask --app run lembretes` num cron/worker separado. A função
`processar_lembretes` é idempotente: pode rodar quantas vezes quiser.
"""

from __future__ import annotations

import logging
import queue
import threading
from datetime import timedelta

from .models import StatusAgendamento
from .utils import agora_local

log = logging.getLogger("codewave.tarefas")


class FilaDeMensagens:
    def __init__(self, assincrona: bool = False):
        self.assincrona = assincrona
        self._fila: queue.Queue = queue.Queue()
        if assincrona:
            threading.Thread(target=self._trabalhar, name="fila-mensagens", daemon=True).start()

    def enfileirar(self, funcao, *args, **kwargs) -> None:
        if not self.assincrona:
            funcao(*args, **kwargs)
            return
        self._fila.put((funcao, args, kwargs))

    def aguardar(self) -> None:
        """Espera a fila esvaziar (útil em testes)."""
        if self.assincrona:
            self._fila.join()

    def _trabalhar(self) -> None:
        while True:
            funcao, args, kwargs = self._fila.get()
            try:
                funcao(*args, **kwargs)
            except Exception:  # noqa: BLE001
                log.exception("Falha ao executar tarefa da fila")
            finally:
                self._fila.task_done()


def processar_lembretes(repo, notificador, barbearia_id: int | None = None) -> int:
    """Envia o lembrete X horas antes de cada horário (X é configurável por
    barbearia). Devolve quantos lembretes saíram."""
    enviados = 0
    for barbearia in repo.barbearias.listar():
        if barbearia_id is not None and barbearia.id != barbearia_id:
            continue
        agora = agora_local(barbearia.fuso_horario)
        janela = timedelta(hours=barbearia.lembrete_horas_antes)
        for ag in repo.agendamentos.listar_periodo(barbearia.id, agora, agora + janela):
            if ag.status != StatusAgendamento.AGENDADO or ag.lembrete_enviado_em or ag.inicio <= agora:
                continue
            if ag.inicio > agora + janela:
                continue
            # Marcou (ou remarcou) já dentro da janela: o comprovante faz o papel de lembrete
            referencia = ag.remarcado_em or ag.criado_em
            if referencia >= ag.inicio - janela:
                continue
            with repo.transacao():
                atual = repo.agendamentos.obter(barbearia.id, ag.id)
                if atual is None or atual.lembrete_enviado_em or atual.status != StatusAgendamento.AGENDADO:
                    continue
                atual.lembrete_enviado_em = agora
                repo.agendamentos.atualizar(atual)
            cliente = repo.clientes.obter(barbearia.id, ag.cliente_id)
            barbeiro = repo.barbeiros.obter(barbearia.id, ag.barbeiro_id)
            if cliente and barbeiro:
                notificador.lembrete(barbearia, atual, cliente, barbeiro)
                enviados += 1
    return enviados


class AgendadorDeLembretes:
    def __init__(self, repo, notificador, intervalo_segundos: int = 60):
        self.repo = repo
        self.notificador = notificador
        self.intervalo = max(10, intervalo_segundos)
        self._parar = threading.Event()

    def iniciar(self) -> None:
        threading.Thread(target=self._executar, name="agendador-lembretes", daemon=True).start()
        log.info("Agendador de lembretes ativo (a cada %ss)", self.intervalo)

    def parar(self) -> None:
        self._parar.set()

    def _executar(self) -> None:
        while not self._parar.is_set():
            try:
                total = processar_lembretes(self.repo, self.notificador)
                if total:
                    log.info("%s lembrete(s) enviado(s)", total)
            except Exception:  # noqa: BLE001
                log.exception("Falha ao processar lembretes")
            self._parar.wait(self.intervalo)
