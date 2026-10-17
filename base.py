"""Contratos (interfaces) da camada de dados.

O restante do sistema conversa só com estas interfaces. Hoje elas são
implementadas em memória (memoria.py). Quando o banco de dados entrar, basta
criar outra implementação (ex.: repositorios/sql.py com SQLAlchemy) seguindo
estes mesmos métodos; rotas e regras de negócio não mudam.

Regra de ouro multi-tenant: toda consulta de dados de uma barbearia recebe
`barbearia_id`. Nunca busque agendamento, cliente etc. apenas pelo id.

Convenção: os objetos devolvidos são cópias. Depois de alterar um objeto,
chame `atualizar()` para gravar, exatamente como será com o banco.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from contextlib import AbstractContextManager
from datetime import datetime

from ..models import (
    Agendamento, Barbearia, Barbeiro, Bloqueio, Cliente, Mensagem, Servico,
    Usuario, VerificacaoTelefone,
)


class RepositorioBarbearias(ABC):
    @abstractmethod
    def adicionar(self, barbearia: Barbearia) -> Barbearia: ...

    @abstractmethod
    def atualizar(self, barbearia: Barbearia) -> Barbearia: ...

    @abstractmethod
    def obter(self, barbearia_id: int) -> Barbearia | None: ...

    @abstractmethod
    def por_slug(self, slug: str) -> Barbearia | None: ...

    @abstractmethod
    def listar(self) -> list[Barbearia]: ...


class RepositorioServicos(ABC):
    @abstractmethod
    def adicionar(self, servico: Servico) -> Servico: ...

    @abstractmethod
    def atualizar(self, servico: Servico) -> Servico: ...

    @abstractmethod
    def obter(self, barbearia_id: int, servico_id: int) -> Servico | None: ...

    @abstractmethod
    def listar(self, barbearia_id: int, apenas_ativos: bool = False) -> list[Servico]:
        """Ordenados por `ordem` e nome."""


class RepositorioBarbeiros(ABC):
    @abstractmethod
    def adicionar(self, barbeiro: Barbeiro) -> Barbeiro: ...

    @abstractmethod
    def atualizar(self, barbeiro: Barbeiro) -> Barbeiro: ...

    @abstractmethod
    def obter(self, barbearia_id: int, barbeiro_id: int) -> Barbeiro | None: ...

    @abstractmethod
    def listar(self, barbearia_id: int, apenas_ativos: bool = False) -> list[Barbeiro]: ...


class RepositorioClientes(ABC):
    @abstractmethod
    def adicionar(self, cliente: Cliente) -> Cliente: ...

    @abstractmethod
    def atualizar(self, cliente: Cliente) -> Cliente: ...

    @abstractmethod
    def obter(self, barbearia_id: int, cliente_id: int) -> Cliente | None: ...

    @abstractmethod
    def obter_varios(self, barbearia_id: int, ids: set[int]) -> dict[int, Cliente]: ...

    @abstractmethod
    def por_telefone(self, barbearia_id: int, telefone: str) -> Cliente | None: ...

    @abstractmethod
    def listar(self, barbearia_id: int) -> list[Cliente]: ...


class RepositorioAgendamentos(ABC):
    @abstractmethod
    def adicionar(self, agendamento: Agendamento) -> Agendamento: ...

    @abstractmethod
    def atualizar(self, agendamento: Agendamento) -> Agendamento: ...

    @abstractmethod
    def obter(self, barbearia_id: int, agendamento_id: int) -> Agendamento | None: ...

    @abstractmethod
    def por_token(self, barbearia_id: int, token: str) -> Agendamento | None: ...

    @abstractmethod
    def listar_periodo(
        self, barbearia_id: int, inicio: datetime, fim: datetime, barbeiro_id: int | None = None
    ) -> list[Agendamento]:
        """Agendamentos (de qualquer status) que encostam no intervalo [inicio, fim).
        barbeiro_id=None traz de todos os profissionais. Ordenados por início."""

    @abstractmethod
    def listar_do_cliente(self, barbearia_id: int, cliente_id: int) -> list[Agendamento]: ...

    @abstractmethod
    def listar_todos(self, barbearia_id: int) -> list[Agendamento]:
        """Usado pelo CRM. No banco, prefira uma consulta agregada."""


class RepositorioBloqueios(ABC):
    @abstractmethod
    def adicionar(self, bloqueio: Bloqueio) -> Bloqueio: ...

    @abstractmethod
    def obter(self, barbearia_id: int, bloqueio_id: int) -> Bloqueio | None: ...

    @abstractmethod
    def remover(self, barbearia_id: int, bloqueio_id: int) -> bool: ...

    @abstractmethod
    def listar_periodo(
        self, barbearia_id: int, inicio: datetime, fim: datetime, barbeiro_id: int | None = None
    ) -> list[Bloqueio]:
        """Bloqueios que encostam em [inicio, fim).
        Com barbeiro_id: os daquele profissional + os da barbearia inteira.
        Sem barbeiro_id: todos. Ordenados por início."""


class RepositorioUsuarios(ABC):
    @abstractmethod
    def adicionar(self, usuario: Usuario) -> Usuario: ...

    @abstractmethod
    def atualizar(self, usuario: Usuario) -> Usuario: ...

    @abstractmethod
    def obter(self, usuario_id: int) -> Usuario | None: ...

    @abstractmethod
    def por_email(self, barbearia_id: int, email: str) -> Usuario | None: ...

    @abstractmethod
    def por_barbeiro(self, barbearia_id: int, barbeiro_id: int) -> Usuario | None: ...


class RepositorioVerificacoes(ABC):
    @abstractmethod
    def adicionar(self, verificacao: VerificacaoTelefone) -> VerificacaoTelefone: ...

    @abstractmethod
    def atualizar(self, verificacao: VerificacaoTelefone) -> VerificacaoTelefone: ...

    @abstractmethod
    def por_token(self, barbearia_id: int, token: str) -> VerificacaoTelefone | None: ...

    @abstractmethod
    def remover(self, verificacao_id: int) -> None: ...


class RepositorioMensagens(ABC):
    @abstractmethod
    def adicionar(self, mensagem: Mensagem) -> Mensagem: ...

    @abstractmethod
    def atualizar(self, mensagem: Mensagem) -> Mensagem: ...

    @abstractmethod
    def obter(self, mensagem_id: int) -> Mensagem | None: ...

    @abstractmethod
    def listar(self, barbearia_id: int, limite: int = 200) -> list[Mensagem]:
        """Mais recentes primeiro."""

    @abstractmethod
    def contar_desde(self, barbearia_id: int, telefone: str, tipo: str, desde: datetime) -> int: ...


class Repositorio(ABC):
    """Agrupa todos os repositórios (unit of work)."""

    barbearias: RepositorioBarbearias
    servicos: RepositorioServicos
    barbeiros: RepositorioBarbeiros
    clientes: RepositorioClientes
    agendamentos: RepositorioAgendamentos
    bloqueios: RepositorioBloqueios
    usuarios: RepositorioUsuarios
    verificacoes: RepositorioVerificacoes
    mensagens: RepositorioMensagens

    @abstractmethod
    def transacao(self) -> AbstractContextManager:
        """Bloco atômico. Em memória é uma trava; no banco, BEGIN/COMMIT
        (use SELECT ... FOR UPDATE ou a constraint de sobreposição do schema)."""
