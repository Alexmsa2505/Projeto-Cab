"""Implementação em memória dos repositórios.

Serve para desenvolver e testar sem banco de dados. Os dados somem quando o
servidor reinicia. Para imitar um banco de verdade, tudo que entra e sai é
copiado: alterar um objeto sem chamar `atualizar()` não tem efeito.
"""

from __future__ import annotations

import copy
import itertools
import threading
from collections.abc import Callable
from datetime import datetime
from typing import Generic, TypeVar

from ..models import (
    Agendamento, Barbearia, Barbeiro, Bloqueio, Cliente, Mensagem, Servico,
    Usuario, VerificacaoTelefone,
)
from .base import (
    Repositorio, RepositorioAgendamentos, RepositorioBarbearias, RepositorioBarbeiros,
    RepositorioBloqueios, RepositorioClientes, RepositorioMensagens, RepositorioServicos,
    RepositorioUsuarios, RepositorioVerificacoes,
)

T = TypeVar("T")


class _Tabela(Generic[T]):
    def __init__(self, trava: threading.RLock):
        self._trava = trava
        self._linhas: dict[int, T] = {}
        self._ids = itertools.count(1)

    def inserir(self, obj: T) -> T:
        with self._trava:
            novo = copy.deepcopy(obj)
            novo.id = next(self._ids)
            self._linhas[novo.id] = novo
            return copy.deepcopy(novo)

    def gravar(self, obj: T) -> T:
        with self._trava:
            if obj.id not in self._linhas:
                raise KeyError(f"Registro {obj.id} não existe")
            self._linhas[obj.id] = copy.deepcopy(obj)
            return copy.deepcopy(obj)

    def buscar(self, chave: int) -> T | None:
        with self._trava:
            obj = self._linhas.get(chave)
            return copy.deepcopy(obj) if obj is not None else None

    def apagar(self, chave: int) -> bool:
        with self._trava:
            return self._linhas.pop(chave, None) is not None

    def filtrar(self, condicao: Callable[[T], bool], ordem: Callable[[T], object] | None = None) -> list[T]:
        with self._trava:
            achados = [copy.deepcopy(o) for o in self._linhas.values() if condicao(o)]
        if ordem:
            achados.sort(key=ordem)
        return achados

    def primeiro(self, condicao: Callable[[T], bool]) -> T | None:
        with self._trava:
            for obj in self._linhas.values():
                if condicao(obj):
                    return copy.deepcopy(obj)
        return None


def _encosta(inicio: datetime, fim: datetime, ini: datetime, fim_periodo: datetime) -> bool:
    return inicio < fim_periodo and fim > ini


class _Barbearias(RepositorioBarbearias):
    def __init__(self, trava):
        self.t: _Tabela[Barbearia] = _Tabela(trava)

    def adicionar(self, barbearia):
        return self.t.inserir(barbearia)

    def atualizar(self, barbearia):
        return self.t.gravar(barbearia)

    def obter(self, barbearia_id):
        return self.t.buscar(barbearia_id)

    def por_slug(self, slug):
        return self.t.primeiro(lambda b: b.slug == slug)

    def listar(self):
        return self.t.filtrar(lambda b: True, ordem=lambda b: b.nome.lower())


class _Servicos(RepositorioServicos):
    def __init__(self, trava):
        self.t: _Tabela[Servico] = _Tabela(trava)

    def adicionar(self, servico):
        return self.t.inserir(servico)

    def atualizar(self, servico):
        return self.t.gravar(servico)

    def obter(self, barbearia_id, servico_id):
        s = self.t.buscar(servico_id)
        return s if s and s.barbearia_id == barbearia_id else None

    def listar(self, barbearia_id, apenas_ativos=False):
        return self.t.filtrar(
            lambda s: s.barbearia_id == barbearia_id and (s.ativo or not apenas_ativos),
            ordem=lambda s: (s.ordem, s.nome.lower()),
        )


class _Barbeiros(RepositorioBarbeiros):
    def __init__(self, trava):
        self.t: _Tabela[Barbeiro] = _Tabela(trava)

    def adicionar(self, barbeiro):
        return self.t.inserir(barbeiro)

    def atualizar(self, barbeiro):
        return self.t.gravar(barbeiro)

    def obter(self, barbearia_id, barbeiro_id):
        b = self.t.buscar(barbeiro_id)
        return b if b and b.barbearia_id == barbearia_id else None

    def listar(self, barbearia_id, apenas_ativos=False):
        return self.t.filtrar(
            lambda b: b.barbearia_id == barbearia_id and (b.ativo or not apenas_ativos),
            ordem=lambda b: b.id,
        )


class _Clientes(RepositorioClientes):
    def __init__(self, trava):
        self.t: _Tabela[Cliente] = _Tabela(trava)

    def adicionar(self, cliente):
        return self.t.inserir(cliente)

    def atualizar(self, cliente):
        return self.t.gravar(cliente)

    def obter(self, barbearia_id, cliente_id):
        c = self.t.buscar(cliente_id)
        return c if c and c.barbearia_id == barbearia_id else None

    def obter_varios(self, barbearia_id, ids):
        ids = set(ids)
        return {c.id: c for c in self.t.filtrar(lambda c: c.barbearia_id == barbearia_id and c.id in ids)}

    def por_telefone(self, barbearia_id, telefone):
        return self.t.primeiro(lambda c: c.barbearia_id == barbearia_id and c.telefone == telefone)

    def listar(self, barbearia_id):
        return self.t.filtrar(lambda c: c.barbearia_id == barbearia_id, ordem=lambda c: c.nome.lower())


class _Agendamentos(RepositorioAgendamentos):
    def __init__(self, trava):
        self.t: _Tabela[Agendamento] = _Tabela(trava)

    def adicionar(self, agendamento):
        return self.t.inserir(agendamento)

    def atualizar(self, agendamento):
        return self.t.gravar(agendamento)

    def obter(self, barbearia_id, agendamento_id):
        a = self.t.buscar(agendamento_id)
        return a if a and a.barbearia_id == barbearia_id else None

    def por_token(self, barbearia_id, token):
        if not token:
            return None
        return self.t.primeiro(lambda a: a.barbearia_id == barbearia_id and a.token == token)

    def listar_periodo(self, barbearia_id, inicio, fim, barbeiro_id=None):
        return self.t.filtrar(
            lambda a: a.barbearia_id == barbearia_id
            and (barbeiro_id is None or a.barbeiro_id == barbeiro_id)
            and _encosta(a.inicio, a.fim, inicio, fim),
            ordem=lambda a: (a.inicio, a.id),
        )

    def listar_do_cliente(self, barbearia_id, cliente_id):
        return self.t.filtrar(
            lambda a: a.barbearia_id == barbearia_id and a.cliente_id == cliente_id,
            ordem=lambda a: a.inicio,
        )

    def listar_todos(self, barbearia_id):
        return self.t.filtrar(lambda a: a.barbearia_id == barbearia_id, ordem=lambda a: a.inicio)


class _Bloqueios(RepositorioBloqueios):
    def __init__(self, trava):
        self.t: _Tabela[Bloqueio] = _Tabela(trava)

    def adicionar(self, bloqueio):
        return self.t.inserir(bloqueio)

    def obter(self, barbearia_id, bloqueio_id):
        b = self.t.buscar(bloqueio_id)
        return b if b and b.barbearia_id == barbearia_id else None

    def remover(self, barbearia_id, bloqueio_id):
        if self.obter(barbearia_id, bloqueio_id) is None:
            return False
        return self.t.apagar(bloqueio_id)

    def listar_periodo(self, barbearia_id, inicio, fim, barbeiro_id=None):
        return self.t.filtrar(
            lambda b: b.barbearia_id == barbearia_id
            and (barbeiro_id is None or b.barbeiro_id in (None, barbeiro_id))
            and _encosta(b.inicio, b.fim, inicio, fim),
            ordem=lambda b: (b.inicio, b.id),
        )


class _Usuarios(RepositorioUsuarios):
    def __init__(self, trava):
        self.t: _Tabela[Usuario] = _Tabela(trava)

    def adicionar(self, usuario):
        usuario.email = usuario.email.strip().lower()
        return self.t.inserir(usuario)

    def atualizar(self, usuario):
        usuario.email = usuario.email.strip().lower()
        return self.t.gravar(usuario)

    def obter(self, usuario_id):
        return self.t.buscar(usuario_id)

    def por_email(self, barbearia_id, email):
        email = (email or "").strip().lower()
        return self.t.primeiro(lambda u: u.barbearia_id == barbearia_id and u.email == email)

    def por_barbeiro(self, barbearia_id, barbeiro_id):
        return self.t.primeiro(lambda u: u.barbearia_id == barbearia_id and u.barbeiro_id == barbeiro_id)


class _Verificacoes(RepositorioVerificacoes):
    def __init__(self, trava):
        self.t: _Tabela[VerificacaoTelefone] = _Tabela(trava)

    def adicionar(self, verificacao):
        return self.t.inserir(verificacao)

    def atualizar(self, verificacao):
        return self.t.gravar(verificacao)

    def por_token(self, barbearia_id, token):
        if not token:
            return None
        return self.t.primeiro(lambda v: v.barbearia_id == barbearia_id and v.token == token)

    def remover(self, verificacao_id):
        self.t.apagar(verificacao_id)


class _Mensagens(RepositorioMensagens):
    def __init__(self, trava):
        self.t: _Tabela[Mensagem] = _Tabela(trava)

    def adicionar(self, mensagem):
        return self.t.inserir(mensagem)

    def atualizar(self, mensagem):
        return self.t.gravar(mensagem)

    def obter(self, mensagem_id):
        return self.t.buscar(mensagem_id)

    def listar(self, barbearia_id, limite=200):
        itens = self.t.filtrar(lambda m: m.barbearia_id == barbearia_id, ordem=lambda m: (m.criado_em, m.id))
        return list(reversed(itens))[:limite]

    def contar_desde(self, barbearia_id, telefone, tipo, desde):
        return len(self.t.filtrar(
            lambda m: m.barbearia_id == barbearia_id and m.telefone == telefone
            and m.tipo == tipo and m.criado_em >= desde
        ))


class RepositorioMemoria(Repositorio):
    def __init__(self) -> None:
        self._trava = threading.RLock()
        self.barbearias = _Barbearias(self._trava)
        self.servicos = _Servicos(self._trava)
        self.barbeiros = _Barbeiros(self._trava)
        self.clientes = _Clientes(self._trava)
        self.agendamentos = _Agendamentos(self._trava)
        self.bloqueios = _Bloqueios(self._trava)
        self.usuarios = _Usuarios(self._trava)
        self.verificacoes = _Verificacoes(self._trava)
        self.mensagens = _Mensagens(self._trava)

    def transacao(self):
        return self._trava
