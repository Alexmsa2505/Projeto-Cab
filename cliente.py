"""Área do cliente: /<slug>/... (white-label: logo e cores da barbearia).

Fluxo: escolher serviços, profissional, dia e horário -> informar nome e
celular -> digitar o código de 4 dígitos -> comprovante com link de gestão.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from urllib.parse import urlencode

from flask import Blueprint, Response, abort, flash, g, redirect, render_template, request, session, url_for

from ..contexto import agora, contexto, repo
from ..models import Agendamento, Barbearia
from ..negocio import ErroNegocio, agenda, agendamentos, divulgacao
from ..negocio.agendamentos import Solicitacao
from ..negocio.notificacoes import link_agendar
from ..negocio.verificacao import segundos_para_reenvio
from ..utils import formatar_telefone, parse_data, parse_hora

bp = Blueprint("cliente", __name__, url_prefix="/<slug>")


# --------------------------------------------------------------- utilidades
def _int(valor) -> int | None:
    try:
        return int(valor)
    except (TypeError, ValueError):
        return None


def _ints(valores) -> list[int]:
    return [n for n in (_int(v) for v in valores) if n is not None]


def _verificado(barbearia: Barbearia, telefone: str | None = None) -> dict | None:
    """Telefone já confirmado por código nesta sessão (evita pedir de novo)."""
    dados = session.get("verificados", {}).get(str(barbearia.id))
    if not dados or datetime.fromisoformat(dados["ate"]) < agora():
        return None
    if telefone and dados["telefone"] != telefone:
        return None
    return dados


def _marcar_verificado(barbearia: Barbearia, telefone: str, nome: str) -> None:
    validade = contexto().politica.validade_telefone_verificado_minutos
    verificados = dict(session.get("verificados", {}))
    verificados[str(barbearia.id)] = {
        "telefone": telefone, "nome": nome,
        "ate": (agora() + timedelta(minutes=validade)).isoformat(),
    }
    session["verificados"] = verificados


def _horarios(barbearia, barbeiro_id, dia, duracao, momento, ignorar=None, excluir=None):
    if duracao <= 0:
        return [], "Escolha pelo menos um serviço para ver os horários."
    if not barbeiro_id:
        return [], "Escolha o profissional para ver os horários."
    if dia is None:
        return [], "Não há dias abertos para agendamento agora."
    livres = agenda.horarios_disponiveis(repo(), barbearia, barbeiro_id, dia, duracao, momento, ignorar)
    livres = [h for h in livres if h != excluir]
    if not livres:
        return [], "Nenhum horário livre neste dia. Experimente outro dia ou outro profissional."
    return agenda.agrupar_por_periodo(livres), None


def _horario_escolhido(grupos, dia, texto):
    hora = parse_hora(texto)
    if dia is None or hora is None:
        return None
    escolhido = datetime.combine(dia, hora)
    return escolhido if any(escolhido in hs for _, hs in grupos) else None


def _contexto_agendar(barbearia: Barbearia, fonte, momento: datetime, erro: str | None = None) -> dict:
    servicos = repo().servicos.listar(barbearia.id, apenas_ativos=True)
    barbeiros = repo().barbeiros.listar(barbearia.id, apenas_ativos=True)
    dias = agenda.dias_agendaveis(barbearia, momento)
    abertos = [d.data for d in dias if d.aberto]

    barbeiro_id = _int(fonte.get("barbeiro_id"))
    if barbeiro_id is None and len(barbeiros) == 1:
        barbeiro_id = barbeiros[0].id
    selecao = agendamentos.carregar_selecao(repo(), barbearia, _ints(fonte.getlist("servicos")), barbeiro_id)
    dia = parse_data(fonte.get("data"))
    if dia not in abertos:
        dia = abertos[0] if abertos else None

    grupos, aviso = _horarios(
        barbearia, selecao.barbeiro.id if selecao.barbeiro else None, dia, selecao.duracao_minutos, momento
    )
    escolhido = _horario_escolhido(grupos, dia, fonte.get("horario"))
    verificado = _verificado(barbearia) or {}
    return {
        "servicos": servicos,
        "barbeiros": barbeiros,
        "dias": dias,
        "selecao": selecao,
        "sel_servicos": {s.id for s in selecao.servicos},
        "sel_barbeiro": selecao.barbeiro.id if selecao.barbeiro else None,
        "sel_dia": dia,
        "grupos": grupos,
        "aviso": aviso,
        "horario_escolhido": escolhido,
        "horario_sel": escolhido.strftime("%H:%M") if escolhido else "",
        "nome": fonte.get("nome") or verificado.get("nome", ""),
        "telefone": fonte.get("telefone") or formatar_telefone(verificado.get("telefone")),
        "canal": fonte.get("canal") or "whatsapp",
        "telefone_verificado": bool(verificado),
        "erro": erro,
    }


def _parametros_selecao(solicitacao: Solicitacao) -> dict:
    return {
        "servicos": solicitacao.servico_ids,
        "barbeiro_id": solicitacao.barbeiro_id,
        "data": solicitacao.inicio.date().isoformat(),
    }


def _carregar(token: str) -> Agendamento:
    ag = repo().agendamentos.por_token(g.barbearia.id, token)
    if ag is None:
        abort(404, description="Não encontramos esse agendamento. Confira o link recebido.")
    return ag


def _link_google(barbearia: Barbearia, ag: Agendamento, nome_barbeiro: str, link: str) -> str:
    parametros = {
        "action": "TEMPLATE",
        "text": f"{ag.descricao_servicos} na {barbearia.nome}",
        "dates": f"{ag.inicio:%Y%m%dT%H%M%S}/{ag.fim:%Y%m%dT%H%M%S}",
        "details": f"Com {nome_barbeiro}. Para remarcar ou cancelar: {link}",
        "location": barbearia.endereco,
        "ctz": barbearia.fuso_horario,
    }
    return "https://calendar.google.com/calendar/render?" + urlencode(parametros)


# ------------------------------------------------------------------ agendar
@bp.get("/")
def agendar():
    b = g.barbearia
    if not repo().barbeiros.listar(b.id, apenas_ativos=True) or not repo().servicos.listar(b.id, apenas_ativos=True):
        return render_template("cliente/indisponivel.html")
    return render_template("cliente/agendar.html", **_contexto_agendar(b, request.args, agora()))


@bp.get("/disponibilidade")
def disponibilidade():
    """Parcial HTMX: horários livres + resumo com o total (atualiza a cada escolha)."""
    return render_template("cliente/_disponibilidade.html", **_contexto_agendar(g.barbearia, request.args, agora()))


@bp.post("/agendar")
def solicitar():
    b, ctx, momento, f = g.barbearia, contexto(), agora(), request.form
    try:
        solicitacao = agendamentos.validar_solicitacao(
            ctx.repo, ctx.politica, b,
            nome=f.get("nome", ""), telefone=f.get("telefone", ""), canal=f.get("canal", ""),
            servico_ids=_ints(f.getlist("servicos")), barbeiro_id=_int(f.get("barbeiro_id")),
            data=parse_data(f.get("data")), horario=parse_hora(f.get("horario")), agora=momento,
        )
        if _verificado(b, solicitacao.telefone):
            ag = agendamentos.criar_agendamento(ctx.repo, ctx.notificador, b, solicitacao, momento)
            return redirect(url_for(".agendamento", token=ag.token, novo=1))
        verificacao = agendamentos.iniciar_verificacao(ctx.repo, ctx.notificador, ctx.politica, b, solicitacao, momento)
    except ErroNegocio as exc:
        return render_template("cliente/agendar.html", **_contexto_agendar(b, f, momento, erro=str(exc))), 422
    return redirect(url_for(".verificar", token=verificacao.token))


# ------------------------------------------------------------------ código
@bp.route("/verificar/<token>", methods=["GET", "POST"])
def verificar(token: str):
    b, ctx, momento = g.barbearia, contexto(), agora()
    verificacao = ctx.repo.verificacoes.por_token(b.id, token)
    if verificacao is None:
        flash("Esse pedido expirou. Escolha o horário de novo.", "erro")
        return redirect(url_for(".agendar"))

    erro = None
    if request.method == "POST":
        try:
            verificacao = agendamentos.conferir_codigo(
                ctx.repo, ctx.politica, b, token, request.form.get("codigo", ""), momento
            )
        except ErroNegocio as exc:
            erro = str(exc)
            verificacao = ctx.repo.verificacoes.por_token(b.id, token) or verificacao
        else:
            solicitacao = Solicitacao.de_dict(verificacao.dados)
            ctx.repo.verificacoes.remover(verificacao.id)
            _marcar_verificado(b, solicitacao.telefone, solicitacao.nome)
            try:
                ag = agendamentos.criar_agendamento(ctx.repo, ctx.notificador, b, solicitacao, momento)
            except ErroNegocio as exc:
                flash(f"{exc} Seu número já está confirmado, é só escolher de novo.", "erro")
                return redirect(url_for(".agendar", **_parametros_selecao(solicitacao)))
            return redirect(url_for(".agendamento", token=ag.token, novo=1))

    solicitacao = Solicitacao.de_dict(verificacao.dados)
    selecao = agendamentos.carregar_selecao(ctx.repo, b, solicitacao.servico_ids, solicitacao.barbeiro_id)
    return render_template(
        "cliente/verificar.html",
        verificacao=verificacao,
        solicitacao=solicitacao,
        selecao=selecao,
        erro=erro,
        espera=segundos_para_reenvio(ctx.politica, verificacao.ultimo_envio_em, momento),
        codigo_demo=verificacao.codigo if ctx.modo_demo else None,
        voltar=url_for(".agendar", **_parametros_selecao(solicitacao)),
    ), (422 if erro else 200)


@bp.post("/verificar/<token>/reenviar")
def reenviar(token: str):
    ctx = contexto()
    try:
        agendamentos.reenviar_codigo(ctx.repo, ctx.notificador, ctx.politica, g.barbearia, token, agora())
        flash("Enviamos um novo código.", "sucesso")
    except ErroNegocio as exc:
        flash(str(exc), "erro")
    return redirect(url_for(".verificar", token=token))


# ------------------------------------------------------------- comprovante
@bp.get("/agendamento/<token>")
def agendamento(token: str):
    b, momento = g.barbearia, agora()
    ag = _carregar(token)
    cliente = repo().clientes.obter(b.id, ag.cliente_id)
    barbeiro = repo().barbeiros.obter(b.id, ag.barbeiro_id)
    link = url_for(".agendamento", token=ag.token, _external=True)
    return render_template(
        "cliente/agendamento.html",
        ag=ag, cliente=cliente, barbeiro=barbeiro,
        novo=request.args.get("novo") == "1",
        acao=request.args.get("acao"),
        pode_confirmar=agendamentos.pode_confirmar(ag, momento),
        pode_alterar=agendamentos.pode_alterar(b, ag, momento),
        passou=ag.fim <= momento,
        prazo=agendamentos.prazo_para_alterar(b),
        link_gestao=link,
        link_google=_link_google(b, ag, barbeiro.nome if barbeiro else "", link),
    )


@bp.post("/agendamento/<token>/confirmar")
def confirmar(token: str):
    try:
        agendamentos.confirmar_presenca(repo(), g.barbearia, _carregar(token), agora())
        flash("Presença confirmada. Até lá!", "sucesso")
    except ErroNegocio as exc:
        flash(str(exc), "erro")
    return redirect(url_for(".agendamento", token=token))


@bp.post("/agendamento/<token>/cancelar")
def cancelar(token: str):
    ctx = contexto()
    try:
        agendamentos.cancelar_pelo_cliente(ctx.repo, ctx.notificador, g.barbearia, _carregar(token), agora())
        flash("Horário cancelado. Quando quiser, é só marcar de novo.", "sucesso")
    except ErroNegocio as exc:
        flash(str(exc), "erro")
    return redirect(url_for(".agendamento", token=token))


def _contexto_remarcar(b: Barbearia, ag: Agendamento, fonte, momento: datetime) -> dict:
    dias = agenda.dias_agendaveis(b, momento)
    abertos = [d.data for d in dias if d.aberto]
    dia = parse_data(fonte.get("data"))
    if dia not in abertos:
        dia = ag.inicio.date() if ag.inicio.date() in abertos else (abertos[0] if abertos else None)
    grupos, aviso = _horarios(b, ag.barbeiro_id, dia, ag.duracao_minutos, momento, ignorar=ag.id, excluir=ag.inicio)
    escolhido = _horario_escolhido(grupos, dia, fonte.get("horario"))
    return {
        "dias": dias, "sel_dia": dia, "grupos": grupos, "aviso": aviso,
        "horario_sel": escolhido.strftime("%H:%M") if escolhido else "",
        "barbeiro": repo().barbeiros.obter(b.id, ag.barbeiro_id),
    }


@bp.route("/agendamento/<token>/remarcar", methods=["GET", "POST"])
def remarcar(token: str):
    b, ctx, momento = g.barbearia, contexto(), agora()
    ag = _carregar(token)
    if not agendamentos.pode_alterar(b, ag, momento):
        flash(f"Remarcações pelo link valem até {agendamentos.prazo_para_alterar(b)} antes do horário.", "erro")
        return redirect(url_for(".agendamento", token=token))

    erro = None
    if request.method == "POST":
        dia, hora = parse_data(request.form.get("data")), parse_hora(request.form.get("horario"))
        if dia is None or hora is None:
            erro = "Escolha o dia e o novo horário."
        else:
            try:
                agendamentos.remarcar(ctx.repo, ctx.notificador, b, ag, datetime.combine(dia, hora), momento)
            except ErroNegocio as exc:
                erro = str(exc)
            else:
                flash("Horário remarcado. Enviamos os novos detalhes para o seu celular.", "sucesso")
                return redirect(url_for(".agendamento", token=token))

    fonte = request.form if request.method == "POST" else request.args
    return render_template(
        "cliente/remarcar.html", ag=ag, erro=erro, **_contexto_remarcar(b, ag, fonte, momento)
    ), (422 if erro else 200)


@bp.get("/agendamento/<token>/horarios")
def horarios_remarcar(token: str):
    """Parcial HTMX com os horários livres para remarcar."""
    ag = _carregar(token)
    return render_template("cliente/_horarios.html", **_contexto_remarcar(g.barbearia, ag, request.args, agora()))


# --------------------------------------------------------------- QR Code
@bp.get("/qrcode.<formato>")
def qrcode(formato: str):
    b = g.barbearia
    url = link_agendar(contexto().base_url, b)
    if formato == "svg":
        conteudo, tipo = divulgacao.qr_svg_arquivo(url, b.cor_secundaria), "image/svg+xml"
    elif formato == "png":
        conteudo, tipo = divulgacao.qr_png(url, b.cor_secundaria), "image/png"
    else:
        abort(404)
    return Response(conteudo, mimetype=tipo, headers={
        "Content-Disposition": f'attachment; filename="qrcode-{b.slug}.{formato}"',
    })
