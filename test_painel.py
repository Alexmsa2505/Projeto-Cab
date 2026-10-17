"""Painel da barbearia: login, isolamento entre barbearias, permissões e ações."""

from datetime import datetime, time, timedelta

from app import create_app
from app.models import Agendamento, Cliente, StatusAgendamento
from app.negocio import agenda
from app.negocio.barbearias import NovaBarbearia, adicionar_barbeiro, criar_barbearia
from app.utils import agora_local
from config import TestConfig


def test_painel_exige_login(http, barbearia):
    resposta = http.get("/teste/admin/")
    assert resposta.status_code == 302 and "/teste/admin/entrar" in resposta.headers["Location"]


def test_login_errado_e_certo(http, barbearia, login):
    assert login(senha="errada").status_code == 401
    assert login().status_code == 302
    assert http.get("/teste/admin/").status_code == 200


def test_sessao_de_uma_barbearia_nao_abre_outra(http, repo, barbearia, login):
    criar_barbearia(repo, NovaBarbearia(
        nome="Outra Casa", slug="outra", dono_nome="Bia", email="dono@teste.com", senha="segredo1",
    ), agora_local())
    login()
    resposta = http.get("/outra/admin/")
    assert resposta.status_code == 302 and "/outra/admin/entrar" in resposta.headers["Location"]


def test_barbeiro_ve_agenda_mas_nao_o_financeiro(http, repo, barbearia, login):
    adicionar_barbeiro(repo, barbearia, nome="Caio Lima", especialidade="", comissao=40,
                       email="caio@teste.com", senha="segredo2")
    login(email="caio@teste.com", senha="segredo2")
    assert http.get("/teste/admin/").status_code == 200
    assert http.get("/teste/admin/financeiro").status_code == 302


def test_concluir_atendimento_congela_comissao_e_entra_no_financeiro(http, repo, barbearia, login):
    login()
    barbeiro = repo.barbeiros.listar(barbearia.id)[0]
    cliente = repo.clientes.adicionar(Cliente(barbearia_id=barbearia.id, nome="Lucas", telefone="+5511987654321"))
    inicio = agora_local().replace(second=0) - timedelta(hours=1)
    ag = repo.agendamentos.adicionar(Agendamento(
        barbearia_id=barbearia.id, cliente_id=cliente.id, barbeiro_id=barbeiro.id,
        inicio=inicio, fim=inicio + timedelta(minutes=30), valor_centavos=4500, token="tok-1",
    ))
    resposta = http.post(f"/teste/admin/agendamentos/{ag.id}/status", data={"acao": "concluir"},
                         headers={"HX-Request": "true"})
    assert resposta.status_code == 200 and 'id="quadro"' in resposta.get_data(as_text=True)
    ag = repo.agendamentos.obter(barbearia.id, ag.id)
    assert ag.status == StatusAgendamento.CONCLUIDO and ag.comissao_percentual == 50
    html = http.get(f"/teste/admin/financeiro?periodo=dia&data={inicio.date().isoformat()}").get_data(as_text=True)
    assert "R$\u00a022,50" in html


def test_bloqueio_rapido_pelo_quadro_some_da_agenda_do_cliente(http, repo, barbearia, login, amanha):
    login()
    barbeiro = repo.barbeiros.listar(barbearia.id)[0]
    inicio = datetime.combine(amanha, time(10))
    resposta = http.post("/teste/admin/bloqueios/rapido", headers={"HX-Request": "true"}, data={
        "barbeiro_id": barbeiro.id, "inicio": inicio.isoformat(timespec="minutes"), "minutos": 30,
    })
    assert resposta.status_code == 200 and "item--bloqueio" in resposta.get_data(as_text=True)
    livres = agenda.horarios_disponiveis(repo, barbearia, barbeiro.id, amanha, 30)
    assert inicio not in livres


def test_cores_invalidas_sao_recusadas(http, repo, barbearia, login):
    login()
    dados = {"nome": "Barbearia Teste", "endereco": "", "whatsapp": "", "cor_primaria": "red", "cor_secundaria": "#000000"}
    http.post("/teste/admin/configuracoes/identidade", data=dados)
    assert repo.barbearias.obter(barbearia.id).cor_primaria != "red"
    dados["cor_primaria"] = "#112233"
    http.post("/teste/admin/configuracoes/identidade", data=dados)
    assert repo.barbearias.obter(barbearia.id).cor_primaria == "#112233"


def test_csrf_recusa_post_sem_token(barbearia):
    class ComCsrf(TestConfig):
        CSRF_ATIVO = True
    app = create_app(ComCsrf)
    assert app.test_client().post("/cadastro", data={"nome": "x"}).status_code == 400


def test_todas_as_paginas_com_dados_de_demonstracao():
    class Demo(TestConfig):
        CARREGAR_DADOS_DEMO = True
    http = create_app(Demo).test_client()
    for url in ("/", "/cadastro", "/navalha-de-ouro/", "/corte-fino/"):
        assert http.get(url).status_code == 200, url
    http.post("/navalha-de-ouro/admin/entrar", data={"email": "dono@navalha.com", "senha": "demo123"})
    for pagina in ("", "bloqueios", "financeiro?periodo=mes", "clientes", "clientes?filtro=inativos",
                   "clientes/1", "equipe", "configuracoes", "divulgacao", "mensagens"):
        assert http.get(f"/navalha-de-ouro/admin/{pagina}").status_code == 200, pagina
