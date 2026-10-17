"""Regras de negócio, sem HTTP (horários com data e hora fixas)."""

from datetime import date, datetime, time, timedelta

import pytest

from app.models import Agendamento, Barbearia, Barbeiro, Bloqueio, Cliente, StatusAgendamento
from app.negocio import ErroNegocio, agenda, crm, financeiro
from app.repositorios.memoria import RepositorioMemoria
from app.utils import cor_contraste, formatar_moeda, normalizar_telefone, reais_para_centavos, slugify

SEGUNDA = date(2030, 1, 7)


def as_(hora: int, minuto: int = 0, dia: date = SEGUNDA) -> datetime:
    return datetime.combine(dia, time(hora, minuto))


@pytest.fixture
def cenario():
    repo = RepositorioMemoria()
    b = repo.barbearias.adicionar(Barbearia(
        slug="x", nome="Casa X", abre_as=time(9), fecha_as=time(12),
        intervalo_minutos=30, antecedencia_minima_minutos=60, dias_funcionamento=[0, 1, 2, 3, 4, 5],
    ))
    barbeiro = repo.barbeiros.adicionar(Barbeiro(barbearia_id=b.id, nome="Rafa", comissao_percentual=50))
    cliente = repo.clientes.adicionar(Cliente(barbearia_id=b.id, nome="Lucas", telefone="+5511987654321"))
    return repo, b, barbeiro, cliente


def novo_agendamento(repo, b, barbeiro, cliente, inicio, minutos=30, status=StatusAgendamento.AGENDADO, valor=4500, **extra):
    return repo.agendamentos.adicionar(Agendamento(
        barbearia_id=b.id, cliente_id=cliente.id, barbeiro_id=barbeiro.id, inicio=inicio,
        fim=inicio + timedelta(minutes=minutos), valor_centavos=valor, status=status,
        token=f"t{inicio:%m%d%H%M}{status}", **extra,
    ))


def horas(lista):
    return [h.strftime("%H:%M") for h in lista]


def test_horarios_respeitam_agendamento_bloqueio_e_fechamento(cenario):
    repo, b, barbeiro, cliente = cenario
    novo_agendamento(repo, b, barbeiro, cliente, as_(10))
    repo.bloqueios.adicionar(Bloqueio(barbearia_id=b.id, barbeiro_id=barbeiro.id, inicio=as_(11), fim=as_(11, 30)))
    assert horas(agenda.horarios_disponiveis(repo, b, barbeiro.id, SEGUNDA, 30)) == ["09:00", "09:30", "10:30", "11:30"]
    assert horas(agenda.horarios_disponiveis(repo, b, barbeiro.id, SEGUNDA, 60)) == ["09:00"]


def test_antecedencia_minima_e_dia_fechado(cenario):
    repo, b, barbeiro, _ = cenario
    livres = agenda.horarios_disponiveis(repo, b, barbeiro.id, SEGUNDA, 30, agora=as_(9, 10))
    assert horas(livres) == ["10:30", "11:00", "11:30"]
    domingo = SEGUNDA + timedelta(days=6)
    assert agenda.horarios_disponiveis(repo, b, barbeiro.id, domingo, 30) == []


def test_cancelado_libera_e_bloqueio_da_casa_fecha_para_todos(cenario):
    repo, b, barbeiro, cliente = cenario
    novo_agendamento(repo, b, barbeiro, cliente, as_(9), status=StatusAgendamento.CANCELADO)
    assert "09:00" in horas(agenda.horarios_disponiveis(repo, b, barbeiro.id, SEGUNDA, 30))
    repo.bloqueios.adicionar(Bloqueio(barbearia_id=b.id, barbeiro_id=None, inicio=as_(9), fim=as_(12)))
    assert agenda.horarios_disponiveis(repo, b, barbeiro.id, SEGUNDA, 30) == []


def test_linha_do_tempo_encaixa_livres_na_grade(cenario):
    repo, b, barbeiro, _ = cenario
    bloqueio = repo.bloqueios.adicionar(Bloqueio(barbearia_id=b.id, barbeiro_id=barbeiro.id, inicio=as_(10, 15), fim=as_(10, 45)))
    itens = agenda.linha_do_tempo(b, SEGUNDA, [], [bloqueio], {}, agora=as_(8))
    assert [(i.tipo, i.inicio.strftime("%H:%M")) for i in itens] == [
        ("livre", "09:00"), ("livre", "09:30"), ("livre", "10:00"), ("bloqueio", "10:15"),
        ("livre", "10:45"), ("livre", "11:00"), ("livre", "11:30"),
    ]


def test_bloqueio_nao_pode_atropelar_cliente(cenario):
    repo, b, barbeiro, cliente = cenario
    novo_agendamento(repo, b, barbeiro, cliente, as_(10))
    with pytest.raises(ErroNegocio, match="cliente marcado"):
        agenda.criar_bloqueio(repo, b, barbeiro.id, as_(10), as_(11), "Almoço", agora=as_(8))
    with pytest.raises(ErroNegocio, match="depois do inicial"):
        agenda.criar_bloqueio(repo, b, barbeiro.id, as_(11), as_(10), "Almoço", agora=as_(8))
    bloqueio = agenda.criar_bloqueio(repo, b, barbeiro.id, as_(11), as_(11, 30), "  Almoço  ", agora=as_(8))
    assert bloqueio.motivo == "Almoço"


def test_fechamento_usa_comissao_congelada_e_conta_faltas(cenario):
    repo, b, barbeiro, cliente = cenario
    novo_agendamento(repo, b, barbeiro, cliente, as_(9), status=StatusAgendamento.CONCLUIDO, valor=10000, comissao_percentual=40)
    novo_agendamento(repo, b, barbeiro, cliente, as_(10), status=StatusAgendamento.CONCLUIDO, valor=4500)
    novo_agendamento(repo, b, barbeiro, cliente, as_(11), status=StatusAgendamento.NAO_COMPARECEU)
    novo_agendamento(repo, b, barbeiro, cliente, as_(11, 30), status=StatusAgendamento.CANCELADO)
    f = financeiro.calcular_fechamento(repo, b, "dia", SEGUNDA)
    assert (f.bruto, f.profissional, f.barbearia) == (14500, 6250, 8250)
    assert (f.atendimentos, f.faltas, f.cancelados) == (2, 1, 1)
    semana = financeiro.calcular_fechamento(repo, b, "semana", SEGUNDA + timedelta(days=3))
    assert semana.bruto == 14500


def test_divisao_sempre_fecha_o_valor():
    for valor in (3333, 4500, 1, 99999):
        for pct in (0, 33, 40, 50, 100):
            prof, casa = financeiro.dividir(valor, pct)
            assert prof + casa == valor


def test_crm_separa_ativos_inativos_e_agendados(cenario):
    repo, b, barbeiro, cliente = cenario
    agora = as_(9)
    sumido = repo.clientes.adicionar(Cliente(barbearia_id=b.id, nome="Sumido", telefone="+5511911112222"))
    voltando = repo.clientes.adicionar(Cliente(barbearia_id=b.id, nome="Voltando", telefone="+5511933334444"))
    novo_agendamento(repo, b, barbeiro, cliente, agora - timedelta(days=5), status=StatusAgendamento.CONCLUIDO)
    novo_agendamento(repo, b, barbeiro, sumido, agora - timedelta(days=40), status=StatusAgendamento.CONCLUIDO)
    novo_agendamento(repo, b, barbeiro, voltando, agora - timedelta(days=60), status=StatusAgendamento.CONCLUIDO)
    novo_agendamento(repo, b, barbeiro, voltando, agora + timedelta(days=1))
    resumos = {r.cliente.nome: r for r in crm.resumir_clientes(repo, b, agora)}
    assert resumos["Lucas"].recente and not resumos["Lucas"].inativo
    assert resumos["Sumido"].inativo and resumos["Sumido"].dias_sem_vir == 40
    assert not resumos["Voltando"].inativo  # já tem horário marcado
    ind = crm.indicadores(list(resumos.values()))
    assert (ind.total, ind.ativos, ind.inativos, ind.agendados) == (3, 1, 1, 1)


@pytest.mark.parametrize("entrada, esperado", [
    ("(11) 98765-4321", "+5511987654321"),
    ("+55 11 98765-4321", "+5511987654321"),
    ("11 3456-7890", "+551134567890"),
    ("11 8765-43210", None),
    ("123", None),
])
def test_normalizar_telefone(entrada, esperado):
    assert normalizar_telefone(entrada) == esperado


def test_formatos_brasileiros_e_cores():
    assert formatar_moeda(123456) == "R$\u00a01.234,56"
    assert reais_para_centavos("1.234,56") == 123456
    assert reais_para_centavos("45.9") == 4590
    assert reais_para_centavos("abc") is None
    assert slugify("Barbearia do Zé!") == "barbearia-do-ze"
    assert cor_contraste("#173A30") == "#FFFFFF"
    assert cor_contraste("#B98B2F") == "#141414"
