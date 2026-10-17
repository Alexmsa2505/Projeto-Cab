"""Dados de demonstração: duas barbearias completas para explorar o sistema.

Logins (senha demo123):
  Navalha de Ouro   -> dono@navalha.com (dono) | rafael@navalha.com (barbeiro)
  Corte Fino        -> dono@cortefino.com (dono)
"""

from __future__ import annotations

import random
from datetime import date, datetime, time, timedelta
from urllib.parse import quote

from werkzeug.security import generate_password_hash

from .models import (
    Agendamento, Barbearia, Barbeiro, Bloqueio, Canal, Cliente, ItemAgendamento, Papel,
    Servico, StatusAgendamento, Usuario,
)
from .negocio import agenda
from .negocio.verificacao import gerar_token
from .repositorios import Repositorio
from .utils import agora_local

SENHA_DEMO = "demo123"
CONTAS_DEMO = {
    "navalha-de-ouro": [("dono@navalha.com", "Dono"), ("rafael@navalha.com", "Barbeiro")],
    "corte-fino": [("dono@cortefino.com", "Dono")],
}

_ICONES = {
    "tesoura": '<circle cx="22" cy="46" r="7"/><circle cx="42" cy="46" r="7"/><path d="M26 40 46 12M38 40 18 12"/>',
    "navalha": '<path d="M10 42 40 24l6 7-30 17z"/><path d="M40 24l14-10"/>',
    "pente": '<rect x="10" y="16" width="44" height="9" rx="2"/><path d="M15 25v18M21 25v18M27 25v18M33 25v18M39 25v18M45 25v18M51 25v14"/>',
}


def _foto(titulo: str, cor_a: str, cor_b: str, icone: str, detalhe: str = "#FFFFFF") -> str:
    """Imagem de exemplo para o portfólio (substitua por fotos reais no painel)."""
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 300 380">'
        '<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">'
        f'<stop offset="0" stop-color="{cor_a}"/><stop offset="1" stop-color="{cor_b}"/>'
        '</linearGradient></defs><rect width="300" height="380" fill="url(#g)"/>'
        f'<g transform="translate(86 104) scale(2)" fill="none" stroke="{detalhe}" stroke-width="2.4" '
        f'stroke-linecap="round" stroke-linejoin="round" opacity=".85">{_ICONES[icone]}</g>'
        f'<text x="24" y="344" font-family="Archivo, Arial, sans-serif" font-size="28" '
        f'font-weight="700" fill="{detalhe}">{titulo}</text></svg>'
    )
    return "data:image/svg+xml;charset=utf-8," + quote(svg)


NOMES_CLIENTES = [
    "Lucas Andrade", "Pedro Henrique Costa", "Gabriel Martins", "Thiago Ribeiro",
    "Bruno Carvalho", "Felipe Nogueira", "Matheus Oliveira", "Rodrigo Teixeira",
    "André Moreira", "Caio Fernandes", "Vinícius Rocha", "Leonardo Pires",
    "Gustavo Almeida", "Renato Barros", "Eduardo Lima", "Samuel Duarte",
    "Diego Pacheco", "Marcelo Antunes",
]


PRIMEIROS_NOMES = [
    "Arthur", "Bernardo", "Heitor", "Davi", "Lorenzo", "Théo", "Miguel", "Gael", "Ravi", "Benício",
    "Enzo", "Joaquim", "Nicolas", "Murilo", "Henrique", "Otávio", "Igor", "Danilo", "Wesley", "Fábio",
    "Luan", "Márcio", "Paulo", "César", "Alexandre", "Jorge",
]
SOBRENOMES = [
    "Silva", "Santos", "Oliveira", "Souza", "Rodrigues", "Ferreira", "Alves", "Pereira", "Gomes", "Costa",
    "Ribeiro", "Martins", "Carvalho", "Araújo", "Melo", "Barbosa", "Cardoso", "Rocha", "Dias", "Teixeira",
]


class _Construtor:
    def __init__(self, repo: Repositorio, barbearia: Barbearia, rnd: random.Random):
        self.repo = repo
        self.b = barbearia
        self.rnd = rnd
        self.agora = agora_local(barbearia.fuso_horario)
        self.servicos: list[Servico] = []
        self.barbeiros: list[Barbeiro] = []

    def servico(self, nome: str, preco: int, duracao: int) -> None:
        self.servicos.append(self.repo.servicos.adicionar(Servico(
            barbearia_id=self.b.id, nome=nome, preco_centavos=preco,
            duracao_minutos=duracao, ordem=len(self.servicos),
        )))

    def barbeiro(self, nome: str, especialidade: str, comissao: int, fotos: list[str]) -> Barbeiro:
        barbeiro = self.repo.barbeiros.adicionar(Barbeiro(
            barbearia_id=self.b.id, nome=nome, especialidade=especialidade,
            comissao_percentual=comissao, fotos=fotos,
        ))
        self.barbeiros.append(barbeiro)
        return barbeiro

    def usuario(self, nome: str, email: str, papel: str, barbeiro_id: int | None = None) -> None:
        self.repo.usuarios.adicionar(Usuario(
            barbearia_id=self.b.id, nome=nome, email=email,
            senha_hash=generate_password_hash(SENHA_DEMO), papel=papel, barbeiro_id=barbeiro_id,
        ))

    def cliente(self, nome: str, criado_em: datetime) -> Cliente:
        telefone = "+55119" + "".join(str(self.rnd.randint(0, 9)) for _ in range(8))
        canal = Canal.SMS if self.rnd.random() < 0.15 else Canal.WHATSAPP
        return self.repo.clientes.adicionar(Cliente(
            barbearia_id=self.b.id, nome=nome, telefone=telefone, canal_preferido=canal, criado_em=criado_em,
        ))

    def almoco(self, barbeiro: Barbeiro, dia: date, inicio: time, minutos: int = 60) -> None:
        if agenda.expediente(self.b, dia) is None:
            return
        ini = datetime.combine(dia, inicio)
        self.repo.bloqueios.adicionar(Bloqueio(
            barbearia_id=self.b.id, barbeiro_id=barbeiro.id, inicio=ini,
            fim=ini + timedelta(minutes=minutos), motivo="Almoço", criado_em=self.agora,
        ))

    def _combo(self) -> list[Servico]:
        cabelo, barba, sobrancelha = self.servicos[:3]
        return self.rnd.choices(
            [[cabelo], [cabelo, barba], [barba], [cabelo, sobrancelha], [cabelo, barba, sobrancelha]],
            weights=[40, 30, 12, 10, 8],
        )[0]

    def agendar(self, cliente: Cliente, barbeiro: Barbeiro, dia: date, status: str | None = None,
                preferir_depois: datetime | None = None) -> Agendamento | None:
        servicos = self._combo()
        duracao = sum(s.duracao_minutos for s in servicos)
        livres = agenda.horarios_disponiveis(self.repo, self.b, barbeiro.id, dia, duracao)
        if preferir_depois:
            livres = [h for h in livres if h >= preferir_depois] or livres
        if not livres:
            return None
        inicio = self.rnd.choice(livres)
        fim = inicio + timedelta(minutes=duracao)
        criado_em = inicio - timedelta(days=self.rnd.randint(1, 6), hours=self.rnd.randint(1, 9))
        if status is None:
            if fim <= self.agora:
                status = StatusAgendamento.NAO_COMPARECEU if self.rnd.random() < 0.07 else StatusAgendamento.CONCLUIDO
            elif inicio <= self.agora:
                status = StatusAgendamento.CONFIRMADO
            else:
                status = StatusAgendamento.CONFIRMADO if self.rnd.random() < 0.45 else StatusAgendamento.AGENDADO
        ag = Agendamento(
            barbearia_id=self.b.id, cliente_id=cliente.id, barbeiro_id=barbeiro.id,
            inicio=inicio, fim=fim, status=status, token=gerar_token(), canal=cliente.canal_preferido,
            itens=[ItemAgendamento(servico_id=s.id, nome=s.nome, preco_centavos=s.preco_centavos,
                                   duracao_minutos=s.duracao_minutos) for s in servicos],
            valor_centavos=sum(s.preco_centavos for s in servicos), criado_em=criado_em,
        )
        if status == StatusAgendamento.CONFIRMADO:
            ag.lembrete_enviado_em = inicio - timedelta(hours=self.b.lembrete_horas_antes)
            ag.confirmado_em = ag.lembrete_enviado_em + timedelta(minutes=12)
        if status == StatusAgendamento.CONCLUIDO:
            ag.concluido_em = fim
            ag.comissao_percentual = barbeiro.comissao_percentual
        return self.repo.agendamentos.adicionar(ag)

    def proximos_dias_abertos(self, quantidade: int) -> list[date]:
        dias, d = [], self.agora.date()
        while len(dias) < quantidade:
            if agenda.expediente(self.b, d):
                dias.append(d)
            d += timedelta(days=1)
        return dias

    def movimento_recente(self, frequentes: list[Cliente], avulsos: int, dias: int = 21) -> None:
        """Atendimentos das últimas semanas, com clientes avulsos (dá volume ao financeiro)."""
        hoje = self.agora.date()
        nomes: set[str] = set()
        while len(nomes) < avulsos:
            nomes.add(f"{self.rnd.choice(PRIMEIROS_NOMES)} {self.rnd.choice(SOBRENOMES)}")
        lista = sorted(nomes)
        criados: dict[str, Cliente] = {}
        for n in range(dias, 0, -1):
            dia = hoje - timedelta(days=n)
            if agenda.expediente(self.b, dia) is None:
                continue
            for barbeiro in self.barbeiros:
                for _ in range(self.rnd.randint(2, 3)):
                    if frequentes and self.rnd.random() < 0.3:
                        cliente = self.rnd.choice(frequentes)
                    else:
                        nome = self.rnd.choice(lista)
                        if nome not in criados:  # o cliente nasce no primeiro atendimento
                            criados[nome] = self.cliente(nome, datetime.combine(dia, time(9)))
                        cliente = criados[nome]
                    self.agendar(cliente, barbeiro, dia)

    def popular(self, nomes: list[str], almocos: list[time], avulsos: int = 0) -> None:
        hoje = self.agora.date()
        clientes_ativos: list[tuple[Cliente, Barbeiro]] = []

        # Histórico: cada cliente tem um barbeiro preferido e um ritmo de visitas
        for i, nome in enumerate(nomes):
            preferido = self.barbeiros[i % len(self.barbeiros)]
            inativo = i % 4 == 3  # 1 em cada 4 sumiu há mais de 30 dias
            ultima_ha = self.rnd.randint(36, 95) if inativo else self.rnd.randint(2, 24)
            ritmo = self.rnd.choice([14, 21, 21, 28, 30])
            visitas = self.rnd.randint(2, 6)
            cliente = self.cliente(nome, datetime.combine(
                hoje - timedelta(days=ultima_ha + ritmo * visitas + 5), time(10)))
            for k in range(visitas):
                dia = hoje - timedelta(days=ultima_ha + k * ritmo + self.rnd.randint(-2, 2))
                if dia >= hoje:
                    continue
                barbeiro = preferido if self.rnd.random() < 0.8 else self.rnd.choice(self.barbeiros)
                self.agendar(cliente, barbeiro, dia)
            if not inativo:
                clientes_ativos.append((cliente, preferido))

        if avulsos:
            self.movimento_recente([c for c, _ in clientes_ativos], avulsos)

        # Agenda de hoje e dos próximos dias (almoço primeiro, para os horários respeitarem)
        dias = self.proximos_dias_abertos(4)
        for dia in dias:
            for barbeiro, inicio_almoco in zip(self.barbeiros, almocos):
                self.almoco(barbeiro, dia, inicio_almoco)
        for n, dia in enumerate(dias):
            por_barbeiro = 5 if n == 0 else 3
            for barbeiro in self.barbeiros:
                for _ in range(por_barbeiro):
                    cliente, _preferido = self.rnd.choice(clientes_ativos)
                    self.agendar(cliente, barbeiro, dia)


def carregar_dados_demo(repo: Repositorio) -> list[str]:
    if repo.barbearias.por_slug("navalha-de-ouro"):
        return []
    rnd = random.Random(2026)

    # ---------------------------------------------------- Barbearia 1
    navalha = repo.barbearias.adicionar(Barbearia(
        slug="navalha-de-ouro", nome="Navalha de Ouro",
        endereco="Rua Augusta, 1520, Consolação, São Paulo",
        whatsapp="+5511987654321", cor_primaria="#B98B2F", cor_secundaria="#173A30",
        abre_as=time(9), fecha_as=time(19), dias_funcionamento=[0, 1, 2, 3, 4, 5],
    ))
    c = _Construtor(repo, navalha, rnd)
    c.servico("Cabelo", 4500, 30)
    c.servico("Barba", 3500, 30)
    c.servico("Sobrancelha", 1500, 15)
    rafael = c.barbeiro("Rafael Souza", "Degradê e navalhado", 50, [
        _foto("Degradê", "#2B4A3F", "#0F241D", "tesoura"),
        _foto("Navalhado", "#3A3226", "#14110C", "navalha", "#E8C77A"),
    ])
    c.barbeiro("Diego Lima", "Barba e toalha quente", 50, [
        _foto("Barba desenhada", "#4A2E22", "#1C110C", "navalha", "#F3D7B5"),
    ])
    c.barbeiro("Marcos Vieira", "Cortes clássicos na tesoura", 40, [
        _foto("Social", "#24343F", "#0D161C", "pente"),
        _foto("Tesoura", "#3F3A2B", "#18160F", "tesoura", "#E8C77A"),
    ])
    c.usuario("Ricardo Gomes", "dono@navalha.com", Papel.DONO)
    c.usuario("Rafael Souza", "rafael@navalha.com", Papel.BARBEIRO, barbeiro_id=rafael.id)
    c.popular(NOMES_CLIENTES, [time(12), time(12, 30), time(13)], avulsos=55)

    # ---------------------------------------------------- Barbearia 2
    corte = repo.barbearias.adicionar(Barbearia(
        slug="corte-fino", nome="Corte Fino Barber Club",
        endereco="Av. Sete de Setembro, 870, Centro, Curitiba",
        whatsapp="+5541991234567", cor_primaria="#3B6FD8", cor_secundaria="#0E1A33",
        abre_as=time(10), fecha_as=time(20), dias_funcionamento=[1, 2, 3, 4, 5],
        intervalo_minutos=30, lembrete_horas_antes=4,
    ))
    c2 = _Construtor(repo, corte, rnd)
    c2.servico("Cabelo", 5500, 40)
    c2.servico("Barba", 4000, 30)
    c2.servico("Sobrancelha", 2000, 15)
    c2.barbeiro("Júlio César", "Tesoura e cortes clássicos", 50, [
        _foto("Clássico", "#1D2B4F", "#0A1022", "tesoura"),
    ])
    c2.barbeiro("Kauã Mendes", "Freestyle e desenhos", 45, [
        _foto("Freestyle", "#2C3E7A", "#101A3A", "navalha"),
        _foto("Risco", "#253055", "#0C1226", "pente"),
    ])
    c2.usuario("Fernanda Prado", "dono@cortefino.com", Papel.DONO)
    c2.popular(NOMES_CLIENTES[:8], [time(13), time(14)], avulsos=25)

    return [navalha.slug, corte.slug]
