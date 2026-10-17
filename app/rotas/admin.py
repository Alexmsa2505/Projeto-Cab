"""Painel da barbearia: /<slug>/admin/...

O dono vê tudo. O barbeiro (papel "barbeiro") vê a agenda do dia e cuida dos
próprios bloqueios e atendimentos.
"""

from __future__ import annotations

from collections import OrderedDict
from datetime import date, datetime, timedelta

from flask import (
    Blueprint, abort, current_app, flash, g, redirect, render_template, request, url_for,
)
from markupsafe import Markup

from ..contexto import agora, contexto, notificador, repo
from ..models import MAX_FOTOS_PORTFOLIO, StatusAgendamento
from ..negocio import ErroNegocio, agenda, agendamentos, arquivos, barbearias, crm, divulgacao
from ..negocio import financeiro as fin
from ..negocio.barbearias import INTERVALOS_PERMITIDOS
from ..negocio.notificacoes import link_agendar
from ..seed import CONTAS_DEMO, SENHA_DEMO
from ..seguranca import (
    autenticar, destino_seguro, encerrar_sessao, iniciar_sessao, pode_gerenciar_barbeiro,
    somente_dono, usuario_logado,
)
from ..tarefas import processar_lembretes
from ..utils import DIAS_SEMANA, parse_data, parse_data_hora, parse_hora

bp = Blueprint("admin", __name__, url_prefix="/<slug>/admin")

# (rótulo, endpoint, só para o dono, endpoints que deixam o item ativo)
MENU = (
    ("Agenda do dia", "admin.dashboard", False, ("admin.dashboard",)),
    ("Bloqueios", "admin.bloqueios", False, ("admin.bloqueios",)),
    ("Financeiro", "admin.financeiro", True, ("admin.financeiro",)),
    ("Clientes", "admin.clientes", True, ("admin.clientes", "admin.cliente_detalhe")),
    ("Equipe", "admin.equipe", True, ("admin.equipe",)),
    ("QR Code", "admin.divulgacao", True, ("admin.divulgacao",)),
    ("Configurações", "admin.configuracoes", True, ("admin.configuracoes",)),
    ("Mensagens", "admin.mensagens", True, ("admin.mensagens",)),
)


def _int(valor, padrao=None):
    try:
        return int(valor)
    except (TypeError, ValueError):
        return padrao


def _ints(valores) -> list[int]:
    return [n for n in (_int(v) for v in valores) if n is not None]


def _htmx() -> bool:
    return bool(request.headers.get("HX-Request"))


@bp.before_request
def _exigir_login():
    if request.endpoint == "admin.login":
        return None
    usuario = usuario_logado(repo(), g.barbearia)
    if usuario is None:
        proximo = request.full_path.rstrip("?") if request.method == "GET" else None
        destino = url_for("admin.login", proximo=proximo)
        if _htmx():
            return "", 200, {"HX-Redirect": destino}
        return redirect(destino)
    g.usuario = usuario
    return None


@bp.context_processor
def _variaveis_painel():
    usuario = g.get("usuario")
    return {
        "menu": [item for item in MENU if usuario and (usuario.e_dono or not item[2])],
        "pode": lambda barbeiro_id: pode_gerenciar_barbeiro(usuario, barbeiro_id),
        "Status": StatusAgendamento,
    }


# ------------------------------------------------------------------- acesso
@bp.route("/entrar", methods=["GET", "POST"])
def login():
    b = g.barbearia
    if usuario_logado(repo(), b):
        return redirect(url_for(".dashboard"))
    erro = None
    if request.method == "POST":
        usuario = autenticar(repo(), b, request.form.get("email", ""), request.form.get("senha", ""))
        if usuario:
            iniciar_sessao(usuario)
            proximo = request.args.get("proximo")
            return redirect(proximo if destino_seguro(proximo) else url_for(".dashboard"))
        erro = "E-mail ou senha incorretos."
    contas = CONTAS_DEMO.get(b.slug, []) if contexto().modo_demo else []
    return render_template(
        "admin/login.html", erro=erro, email=request.form.get("email", ""),
        contas_demo=contas, senha_demo=SENHA_DEMO,
    ), (401 if erro else 200)


@bp.post("/sair")
def sair():
    encerrar_sessao()
    flash("Você saiu do painel.", "info")
    return redirect(url_for(".login"))


# --------------------------------------------------------- agenda do dia
def _dia_param() -> date:
    return parse_data(request.values.get("data")) or agora().date()


def _render_quadro(dia: date, erro: str | None = None, parcial: bool = False):
    momento = agora()
    quadro = agenda.montar_quadro(repo(), g.barbearia, dia, momento)
    return render_template(
        "admin/_quadro.html" if parcial else "admin/dashboard.html",
        quadro=quadro, dia=dia, hoje=momento.date(), agora_=momento, erro=erro,
        ontem=dia - timedelta(days=1), amanha=dia + timedelta(days=1),
    )


def _responder_quadro(dia: date, erro: str | None = None, sucesso: str | None = None):
    if _htmx():
        return _render_quadro(dia, erro=erro, parcial=True)
    if erro:
        flash(erro, "erro")
    elif sucesso:
        flash(sucesso, "sucesso")
    return redirect(url_for(".dashboard", data=dia.isoformat()))


@bp.get("/")
def dashboard():
    return _render_quadro(_dia_param())


@bp.get("/quadro")
def quadro():
    """Parcial HTMX (atualiza sozinho a cada minuto)."""
    return _render_quadro(_dia_param(), parcial=True)


@bp.post("/agendamentos/<int:agendamento_id>/status")
def alterar_status(agendamento_id: int):
    ag = repo().agendamentos.obter(g.barbearia.id, agendamento_id)
    if ag is None:
        abort(404)
    if not pode_gerenciar_barbeiro(g.usuario, ag.barbeiro_id):
        return _responder_quadro(ag.inicio.date(), erro="Você só pode alterar a sua própria agenda.")
    try:
        agendamentos.alterar_status(repo(), notificador(), g.barbearia, ag, request.form.get("acao", ""), agora())
    except ErroNegocio as exc:
        return _responder_quadro(ag.inicio.date(), erro=str(exc))
    return _responder_quadro(ag.inicio.date(), sucesso="Agendamento atualizado.")


@bp.post("/bloqueios/rapido")
def bloqueio_rapido():
    """Bloqueia um horário livre com um clique, direto do quadro."""
    inicio = parse_data_hora(request.form.get("inicio"))
    minutos = _int(request.form.get("minutos"), 0)
    barbeiro_id = _int(request.form.get("barbeiro_id"))
    dia = inicio.date() if inicio else _dia_param()
    if inicio is None or minutos <= 0 or barbeiro_id is None:
        return _responder_quadro(dia, erro="Não deu para identificar o horário.")
    if not pode_gerenciar_barbeiro(g.usuario, barbeiro_id):
        return _responder_quadro(dia, erro="Você só pode bloquear a sua própria agenda.")
    try:
        agenda.criar_bloqueio(
            repo(), g.barbearia, barbeiro_id, inicio, inicio + timedelta(minutes=minutos),
            request.form.get("motivo") or "Pausa", agora(),
        )
    except ErroNegocio as exc:
        return _responder_quadro(dia, erro=str(exc))
    return _responder_quadro(dia, sucesso="Horário bloqueado.")


@bp.post("/bloqueios/<int:bloqueio_id>/remover")
def remover_bloqueio(bloqueio_id: int):
    bloqueio = repo().bloqueios.obter(g.barbearia.id, bloqueio_id)
    if bloqueio is None:
        abort(404)
    if not pode_gerenciar_barbeiro(g.usuario, bloqueio.barbeiro_id):
        erro = "Só o dono libera bloqueios da barbearia inteira ou de outros profissionais."
        if request.form.get("voltar") == "bloqueios":
            flash(erro, "erro")
            return redirect(url_for(".bloqueios"))
        return _responder_quadro(bloqueio.inicio.date(), erro=erro)
    repo().bloqueios.remover(g.barbearia.id, bloqueio_id)
    if request.form.get("voltar") == "bloqueios":
        flash("Horário liberado para os clientes.", "sucesso")
        return redirect(url_for(".bloqueios"))
    return _responder_quadro(bloqueio.inicio.date(), sucesso="Horário liberado.")


# --------------------------------------------------------------- bloqueios
@bp.route("/bloqueios", methods=["GET", "POST"])
def bloqueios():
    b, usuario, momento = g.barbearia, g.usuario, agora()
    todos_barbeiros = repo().barbeiros.listar(b.id)
    barbeiros = [x for x in todos_barbeiros if x.ativo and pode_gerenciar_barbeiro(usuario, x.id)]
    erro = None

    if request.method == "POST":
        f = request.form
        alvo = f.get("barbeiro_id", "")
        barbeiro_id = None if alvo == "todos" else _int(alvo)
        dia, ini, fim = parse_data(f.get("data")), parse_hora(f.get("inicio")), parse_hora(f.get("fim"))
        if alvo == "todos" and not usuario.e_dono:
            erro = "Só o dono pode fechar a barbearia inteira."
        elif alvo != "todos" and not pode_gerenciar_barbeiro(usuario, barbeiro_id):
            erro = "Escolha o profissional."
        elif not (dia and ini and fim):
            erro = "Preencha o dia e os horários de início e fim."
        else:
            try:
                agenda.criar_bloqueio(
                    repo(), b, barbeiro_id, datetime.combine(dia, ini), datetime.combine(dia, fim),
                    f.get("motivo", ""), momento,
                )
            except ErroNegocio as exc:
                erro = str(exc)
            else:
                flash("Horário bloqueado. Ele já não aparece para os clientes.", "sucesso")
                return redirect(url_for(".bloqueios"))

    hoje = momento.date()
    proximos = repo().bloqueios.listar_periodo(
        b.id, agenda.inicio_do_dia(hoje), agenda.inicio_do_dia(hoje + timedelta(days=60))
    )
    if not usuario.e_dono:
        proximos = [x for x in proximos if x.barbeiro_id in (None, usuario.barbeiro_id)]
    por_dia: OrderedDict[date, list] = OrderedDict()
    for bloqueio in proximos:
        if bloqueio.fim > momento:
            por_dia.setdefault(bloqueio.inicio.date(), []).append(bloqueio)

    return render_template(
        "admin/bloqueios.html",
        barbeiros=barbeiros, nomes={x.id: x.nome for x in todos_barbeiros}, por_dia=por_dia,
        motivos=agenda.MOTIVOS_BLOQUEIO, erro=erro, valores=request.form, hoje=hoje,
    ), (422 if erro else 200)


# ------------------------------------------------------------- financeiro
@bp.get("/financeiro")
@somente_dono
def financeiro():
    tipo = request.args.get("periodo", "semana")
    tipo = tipo if tipo in fin.PERIODOS else "semana"
    referencia = parse_data(request.args.get("data")) or agora().date()
    fechamento = fin.calcular_fechamento(repo(), g.barbearia, tipo, referencia)
    return render_template(
        "admin/financeiro.html",
        f=fechamento, periodos=fin.PERIODOS, referencia=referencia,
        anterior=fin.navegar(tipo, referencia, -1), seguinte=fin.navegar(tipo, referencia, 1),
    )


# ------------------------------------------------------------------- CRM
FILTROS_CLIENTES = {"todos": "Todos", "inativos": "Inativos", "ativos": "Ativos", "agendados": "Com horário marcado"}


@bp.get("/clientes")
@somente_dono
def clientes():
    b = g.barbearia
    filtro = request.args.get("filtro", "todos")
    filtro = filtro if filtro in FILTROS_CLIENTES else "todos"
    busca = request.args.get("busca", "").strip()
    resumos = crm.resumir_clientes(repo(), b, agora())
    indicadores = crm.indicadores(resumos)

    criterios = {
        "inativos": lambda r: r.inativo,
        "ativos": lambda r: r.recente,
        "agendados": lambda r: r.proximo_horario is not None,
    }
    if filtro in criterios:
        resumos = [r for r in resumos if criterios[filtro](r)]
    if busca:
        termo, digitos = busca.lower(), "".join(ch for ch in busca if ch.isdigit())
        resumos = [
            r for r in resumos
            if termo in r.cliente.nome.lower() or (digitos and digitos in r.cliente.telefone)
        ]
    if filtro == "inativos":
        resumos.sort(key=lambda r: -(r.dias_sem_vir or 0))
    else:
        # Mais recentes primeiro; quem nunca veio fica no fim
        resumos.sort(key=lambda r: r.ultima_visita or datetime.min, reverse=True)

    return render_template(
        "admin/clientes.html",
        resumos=resumos, ind=indicadores, filtro=filtro, filtros=FILTROS_CLIENTES, busca=busca,
        intervalo_campanha=crm.INTERVALO_ENTRE_CAMPANHAS_DIAS,
    )


@bp.get("/clientes/<int:cliente_id>")
@somente_dono
def cliente_detalhe(cliente_id: int):
    resumo = crm.resumo_do_cliente(repo(), g.barbearia, cliente_id, agora())
    if resumo is None:
        abort(404)
    nomes = {x.id: x.nome for x in repo().barbeiros.listar(g.barbearia.id)}
    return render_template("admin/cliente_detalhe.html", r=resumo, nomes=nomes)


@bp.post("/clientes/campanha")
@somente_dono
def campanha():
    try:
        enviados, ignorados = crm.enviar_reativacao(
            repo(), notificador(), g.barbearia, _ints(request.form.getlist("cliente_ids")),
            request.form.get("mensagem", ""), agora(),
        )
    except ErroNegocio as exc:
        flash(str(exc), "erro")
    else:
        texto = f"Mensagem enviada para {enviados} cliente(s)."
        if ignorados:
            texto += f" {ignorados} ficaram de fora (já têm horário ou receberam campanha há pouco)."
        flash(texto, "sucesso")
    return redirect(url_for(".clientes", filtro="inativos"))


# ------------------------------------------------------------------ equipe
@bp.route("/equipe", methods=["GET", "POST"])
@somente_dono
def equipe():
    b = g.barbearia
    erro = None
    if request.method == "POST":
        f = request.form
        try:
            barbearias.adicionar_barbeiro(
                repo(), b, nome=f.get("nome", ""), especialidade=f.get("especialidade", ""),
                comissao=f.get("comissao", "50"), email=f.get("email", ""), senha=f.get("senha", ""),
            )
        except ErroNegocio as exc:
            erro = str(exc)
        else:
            flash("Profissional adicionado. Ele já aparece para os clientes.", "sucesso")
            return redirect(url_for(".equipe"))
    lista = repo().barbeiros.listar(b.id)
    acessos = {x.id: repo().usuarios.por_barbeiro(b.id, x.id) for x in lista}
    return render_template(
        "admin/equipe.html", barbeiros=lista, acessos=acessos, erro=erro,
        valores=request.form, max_fotos=MAX_FOTOS_PORTFOLIO,
    ), (422 if erro else 200)


@bp.post("/equipe/<int:barbeiro_id>")
@somente_dono
def editar_barbeiro(barbeiro_id: int):
    b, pasta, f = g.barbearia, contexto().pasta_uploads, request.form
    barbeiro = repo().barbeiros.obter(b.id, barbeiro_id)
    if barbeiro is None:
        abort(404)
    try:
        barbeiro = barbearias.atualizar_barbeiro(
            repo(), b, barbeiro, nome=f.get("nome", ""), especialidade=f.get("especialidade", ""),
            comissao=f.get("comissao", ""), ativo=f.get("ativo") == "1",
            email=f.get("email", ""), senha=f.get("senha", ""),
        )
        foto = request.files.get("foto")
        if foto and foto.filename:
            caminho = arquivos.salvar_imagem(foto, pasta, b.slug)
            try:
                barbearias.adicionar_foto(repo(), barbeiro, caminho)
            except ErroNegocio:
                arquivos.remover_imagem(caminho, pasta)
                raise
    except ErroNegocio as exc:
        flash(f"{barbeiro.nome}: {exc}", "erro")
    else:
        flash(f"{barbeiro.nome}: alterações salvas.", "sucesso")
    return redirect(url_for(".equipe") + f"#barbeiro-{barbeiro_id}")


@bp.post("/equipe/<int:barbeiro_id>/fotos/<int:indice>/remover")
@somente_dono
def remover_foto(barbeiro_id: int, indice: int):
    barbeiro = repo().barbeiros.obter(g.barbearia.id, barbeiro_id)
    if barbeiro is None:
        abort(404)
    _, removida = barbearias.remover_foto(repo(), barbeiro, indice)
    arquivos.remover_imagem(removida, contexto().pasta_uploads)
    flash("Foto removida do portfólio.", "sucesso")
    return redirect(url_for(".equipe") + f"#barbeiro-{barbeiro_id}")


# ------------------------------------------------------------ configurações
@bp.get("/configuracoes")
@somente_dono
def configuracoes():
    return render_template(
        "admin/configuracoes.html",
        servicos=repo().servicos.listar(g.barbearia.id),
        dias_semana=list(enumerate(DIAS_SEMANA)),
        intervalos=INTERVALOS_PERMITIDOS,
    )


@bp.post("/configuracoes/identidade")
@somente_dono
def salvar_identidade():
    b, pasta, f = g.barbearia, contexto().pasta_uploads, request.form
    nova_logo = None
    try:
        arquivo = request.files.get("logo")
        if arquivo and arquivo.filename:
            nova_logo = arquivos.salvar_imagem(arquivo, pasta, b.slug)
        _, antiga = barbearias.atualizar_identidade(
            repo(), b, nome=f.get("nome", ""), endereco=f.get("endereco", ""), whatsapp=f.get("whatsapp", ""),
            cor_primaria=f.get("cor_primaria", ""), cor_secundaria=f.get("cor_secundaria", ""),
            logo_url=nova_logo, remover_logo=f.get("remover_logo") == "1",
        )
        if antiga and antiga != nova_logo:
            arquivos.remover_imagem(antiga, pasta)
    except ErroNegocio as exc:
        if nova_logo:
            arquivos.remover_imagem(nova_logo, pasta)
        flash(str(exc), "erro")
    else:
        flash("Identidade visual salva. Confira na página de agendamento.", "sucesso")
    return redirect(url_for(".configuracoes") + "#identidade")


@bp.post("/configuracoes/funcionamento")
@somente_dono
def salvar_funcionamento():
    f = request.form
    try:
        barbearias.atualizar_funcionamento(
            repo(), g.barbearia,
            abre_as=parse_hora(f.get("abre_as")), fecha_as=parse_hora(f.get("fecha_as")),
            dias=_ints(f.getlist("dias")), intervalo=_int(f.get("intervalo"), 0),
            antecedencia=_int(f.get("antecedencia"), -1), janela=_int(f.get("janela"), 0),
            lembrete_horas=_int(f.get("lembrete_horas"), 0), dias_inatividade=_int(f.get("dias_inatividade"), 0),
            mensagem_reativacao=f.get("mensagem_reativacao", ""),
        )
    except ErroNegocio as exc:
        flash(str(exc), "erro")
    else:
        flash("Funcionamento salvo.", "sucesso")
    return redirect(url_for(".configuracoes") + "#funcionamento")


@bp.post("/configuracoes/servicos")
@somente_dono
def salvar_servicos():
    f = request.form
    alteracoes = [
        {"id": sid, "nome": f.get(f"nome_{sid}", ""), "preco": f.get(f"preco_{sid}", ""),
         "duracao": f.get(f"duracao_{sid}", ""), "ativo": f.get(f"ativo_{sid}") == "1"}
        for sid in f.getlist("servico_id") if _int(sid) is not None
    ]
    try:
        barbearias.salvar_servicos(repo(), g.barbearia, alteracoes)
    except ErroNegocio as exc:
        flash(str(exc), "erro")
    else:
        flash("Serviços e preços salvos.", "sucesso")
    return redirect(url_for(".configuracoes") + "#servicos")


@bp.post("/configuracoes/servicos/novo")
@somente_dono
def novo_servico():
    f = request.form
    try:
        barbearias.adicionar_servico(repo(), g.barbearia, f.get("nome", ""), f.get("preco", ""), f.get("duracao", ""))
    except ErroNegocio as exc:
        flash(str(exc), "erro")
    else:
        flash("Serviço adicionado.", "sucesso")
    return redirect(url_for(".configuracoes") + "#servicos")


# --------------------------------------------------------------- QR Code
@bp.get("/divulgacao", endpoint="divulgacao")
@somente_dono
def divulgacao_qr():
    b = g.barbearia
    url = link_agendar(contexto().base_url, b)
    return render_template(
        "admin/divulgacao.html",
        url=url,
        qr=Markup(divulgacao.qr_svg_inline(url, b.cor_secundaria)),
        url_local=any(host in url for host in ("localhost", "127.0.0.1")),
    )



# --------------------------------------------------------------- mensagens
@bp.get("/mensagens")
@somente_dono
def mensagens():
    config = current_app.config
    return render_template(
        "admin/mensagens.html",
        mensagens=repo().mensagens.listar(g.barbearia.id, 200),
        provedor_whatsapp=config["PROVEDOR_WHATSAPP"], provedor_sms=config["PROVEDOR_SMS"],
    )


@bp.post("/mensagens/lembretes")
@somente_dono
def disparar_lembretes():
    total = processar_lembretes(repo(), notificador(), barbearia_id=g.barbearia.id)
    flash(f"{total} lembrete(s) enviado(s)." if total else "Nenhum lembrete pendente agora.", "sucesso")
    return redirect(url_for(".mensagens"))


@bp.post("/mensagens/<int:mensagem_id>/reenviar")
@somente_dono
def reenviar_mensagem(mensagem_id: int):
    notificador().reenviar(g.barbearia, mensagem_id)
    flash("Mensagem colocada na fila de novo.", "sucesso")
    return redirect(url_for(".mensagens"))
