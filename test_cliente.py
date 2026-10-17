"""Fluxo do cliente pela web: agendar, código de 4 dígitos, comprovante, remarcar, cancelar."""

import re
from datetime import timedelta

from app.models import Agendamento, Cliente, StatusAgendamento, TipoMensagem
from app.tarefas import processar_lembretes
from app.utils import agora_local


def agendar(http, repo, barbearia, dia, horario="10:00", telefone="(11) 98765-4321"):
    servico = repo.servicos.listar(barbearia.id)[0]
    barbeiro = repo.barbeiros.listar(barbearia.id)[0]
    return http.post("/teste/agendar", data={
        "servicos": [servico.id], "barbeiro_id": barbeiro.id, "data": dia.isoformat(),
        "horario": horario, "nome": "Lucas Andrade", "telefone": telefone, "canal": "whatsapp",
    })


def ultimo_codigo(repo, barbearia):
    mensagem = next(m for m in repo.mensagens.listar(barbearia.id) if m.tipo == TipoMensagem.CODIGO)
    return re.match(r"\d{4}", mensagem.texto).group(0)


def agendar_e_confirmar(http, repo, barbearia, dia, horario="10:00"):
    url = agendar(http, repo, barbearia, dia, horario).headers["Location"]
    return http.post(url, data={"codigo": ultimo_codigo(repo, barbearia)})


def test_pagina_de_agendamento_lista_servicos(http, barbearia):
    html = http.get("/teste/").get_data(as_text=True)
    for nome in ("Cabelo", "Barba", "Sobrancelha", "Ana Souza"):
        assert nome in html


def test_disponibilidade_htmx_traz_horarios_e_total(http, repo, barbearia, amanha):
    cabelo, barba, _ = repo.servicos.listar(barbearia.id)
    barbeiro = repo.barbeiros.listar(barbearia.id)[0]
    html = http.get(
        f"/teste/disponibilidade?servicos={cabelo.id}&servicos={barba.id}&barbeiro_id={barbeiro.id}&data={amanha.isoformat()}"
    ).get_data(as_text=True)
    assert 'value="10:00"' in html
    assert "R$\u00a080,00" in html
    assert 'hx-swap-oob="true"' in html


def test_fluxo_completo_com_codigo(http, repo, barbearia, amanha):
    resposta = agendar(http, repo, barbearia, amanha)
    assert resposta.status_code == 302 and "/teste/verificar/" in resposta.headers["Location"]
    url = resposta.headers["Location"]
    codigo = ultimo_codigo(repo, barbearia)

    errado = http.post(url, data={"codigo": "1111" if codigo == "0000" else "0000"})
    assert errado.status_code == 422 and "Código incorreto" in errado.get_data(as_text=True)

    certo = http.post(url, data={"codigo": codigo})
    assert certo.status_code == 302 and "/teste/agendamento/" in certo.headers["Location"]
    ag = repo.agendamentos.listar_todos(barbearia.id)[0]
    assert ag.status == StatusAgendamento.AGENDADO
    assert ag.inicio.strftime("%H:%M") == "10:00" and ag.valor_centavos == 4500
    assert any(m.tipo == TipoMensagem.CONFIRMACAO for m in repo.mensagens.listar(barbearia.id))

    comprovante = http.get(certo.headers["Location"]).get_data(as_text=True)
    assert "10:00" in comprovante and "Remarcar" in comprovante


def test_numero_confirmado_na_sessao_nao_pede_codigo_de_novo(http, repo, barbearia, amanha):
    agendar_e_confirmar(http, repo, barbearia, amanha)
    segundo = agendar(http, repo, barbearia, amanha, horario="11:00")
    assert "/teste/agendamento/" in segundo.headers["Location"]


def test_horario_ocupado_nao_pode_ser_agendado(app, http, repo, barbearia, amanha):
    agendar_e_confirmar(http, repo, barbearia, amanha)
    outro_cliente = app.test_client()
    resposta = agendar(outro_cliente, repo, barbearia, amanha, telefone="(21) 99888-7766")
    assert resposta.status_code == 422
    assert "não está mais livre" in resposta.get_data(as_text=True)


def test_remarcar_e_cancelar_pelo_link(http, repo, barbearia, amanha):
    link = agendar_e_confirmar(http, repo, barbearia, amanha).headers["Location"].split("?")[0]
    r = http.post(f"{link}/remarcar", data={"data": amanha.isoformat(), "horario": "14:00"})
    assert r.status_code == 302
    ag = repo.agendamentos.listar_todos(barbearia.id)[0]
    assert ag.inicio.strftime("%H:%M") == "14:00" and ag.remarcado_em is not None

    http.post(f"{link}/cancelar")
    ag = repo.agendamentos.obter(barbearia.id, ag.id)
    assert ag.status == StatusAgendamento.CANCELADO
    assert any(m.tipo == TipoMensagem.CANCELAMENTO for m in repo.mensagens.listar(barbearia.id))


def test_tentativas_de_codigo_sao_limitadas(http, repo, barbearia, amanha):
    url = agendar(http, repo, barbearia, amanha).headers["Location"]
    codigo = ultimo_codigo(repo, barbearia)
    errado = "1111" if codigo == "0000" else "0000"
    for _ in range(5):
        http.post(url, data={"codigo": errado})
    resposta = http.post(url, data={"codigo": codigo})
    assert "Muitas tentativas" in resposta.get_data(as_text=True)


def test_limite_de_codigos_por_hora(http, repo, barbearia, amanha):
    for _ in range(5):
        assert agendar(http, repo, barbearia, amanha).status_code == 302
    bloqueado = agendar(http, repo, barbearia, amanha)
    assert bloqueado.status_code == 422
    assert "vários códigos" in bloqueado.get_data(as_text=True)


def test_lembrete_sai_uma_vez_dentro_da_janela(ctx, repo, barbearia):
    agora = agora_local(barbearia.fuso_horario)
    cliente = repo.clientes.adicionar(Cliente(barbearia_id=barbearia.id, nome="Pedro", telefone="+5511912345678"))
    barbeiro = repo.barbeiros.listar(barbearia.id)[0]
    inicio = agora + timedelta(hours=2)
    repo.agendamentos.adicionar(Agendamento(
        barbearia_id=barbearia.id, cliente_id=cliente.id, barbeiro_id=barbeiro.id,
        inicio=inicio, fim=inicio + timedelta(minutes=30), token="tok-lembrete",
        criado_em=agora - timedelta(days=2),
    ))
    assert processar_lembretes(repo, ctx.notificador) == 1
    assert processar_lembretes(repo, ctx.notificador) == 0
    lembrete = next(m for m in repo.mensagens.listar(barbearia.id) if m.tipo == TipoMensagem.LEMBRETE)
    assert "?acao=confirmar" in lembrete.texto and "?acao=cancelar" in lembrete.texto


def test_qrcode_svg_e_png(http, barbearia):
    assert http.get("/teste/qrcode.svg").mimetype == "image/svg+xml"
    png = http.get("/teste/qrcode.png")
    assert png.mimetype == "image/png" and png.data.startswith(b"\x89PNG")
