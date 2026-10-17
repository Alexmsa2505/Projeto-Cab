"""Cadastro da barbearia (tenant) e tudo que o dono configura no painel."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time

from werkzeug.security import generate_password_hash

from ..models import Barbearia, Barbeiro, MAX_FOTOS_PORTFOLIO, Papel, Servico, Usuario
from ..repositorios import Repositorio
from ..utils import cor_valida, normalizar_telefone, reais_para_centavos, slug_valido, slugify
from . import ErroNegocio

SERVICOS_PADRAO = (
    ("Cabelo", 4500, 30),
    ("Barba", 3500, 30),
    ("Sobrancelha", 1500, 15),
)
INTERVALOS_PERMITIDOS = (15, 20, 30, 45, 60)


def _email_valido(email: str) -> bool:
    return "@" in email and "." in email.split("@")[-1] and len(email) <= 120


def _validar_senha(senha: str) -> None:
    if len(senha or "") < 6:
        raise ErroNegocio("A senha precisa ter pelo menos 6 caracteres.")


# ------------------------------------------------------------------ onboarding
@dataclass
class NovaBarbearia:
    nome: str
    slug: str
    dono_nome: str
    email: str
    senha: str
    whatsapp: str = ""
    dono_atende: bool = True


def criar_barbearia(repo: Repositorio, dados: NovaBarbearia, agora: datetime) -> tuple[Barbearia, Usuario]:
    nome = " ".join(dados.nome.split())[:80]
    if len(nome) < 3:
        raise ErroNegocio("Informe o nome da barbearia.")
    slug = slugify(dados.slug or nome)
    if not slug_valido(slug):
        raise ErroNegocio("Escolha um endereço com 3 a 40 letras, números ou hífens.")
    if repo.barbearias.por_slug(slug):
        raise ErroNegocio(f"O endereço “{slug}” já está em uso. Tente outro.")
    dono_nome = " ".join(dados.dono_nome.split())[:80]
    if len(dono_nome) < 2:
        raise ErroNegocio("Informe seu nome.")
    email = dados.email.strip().lower()
    if not _email_valido(email):
        raise ErroNegocio("Informe um e-mail válido.")
    _validar_senha(dados.senha)
    whatsapp = ""
    if dados.whatsapp.strip():
        whatsapp = normalizar_telefone(dados.whatsapp) or ""
        if not whatsapp:
            raise ErroNegocio("Confira o WhatsApp da barbearia (com DDD).")

    with repo.transacao():
        if repo.barbearias.por_slug(slug):
            raise ErroNegocio(f"O endereço “{slug}” já está em uso. Tente outro.")
        barbearia = repo.barbearias.adicionar(Barbearia(slug=slug, nome=nome, whatsapp=whatsapp, criado_em=agora))
        for ordem, (nome_servico, preco, duracao) in enumerate(SERVICOS_PADRAO):
            repo.servicos.adicionar(Servico(
                barbearia_id=barbearia.id, nome=nome_servico, preco_centavos=preco,
                duracao_minutos=duracao, ordem=ordem,
            ))
        barbeiro_id = None
        if dados.dono_atende:
            barbeiro_id = repo.barbeiros.adicionar(Barbeiro(barbearia_id=barbearia.id, nome=dono_nome)).id
        usuario = repo.usuarios.adicionar(Usuario(
            barbearia_id=barbearia.id, nome=dono_nome, email=email,
            senha_hash=generate_password_hash(dados.senha), papel=Papel.DONO, barbeiro_id=barbeiro_id,
        ))
    return barbearia, usuario


# ------------------------------------------------------------- configurações
def atualizar_identidade(
    repo: Repositorio, barbearia: Barbearia, *, nome: str, endereco: str, whatsapp: str,
    cor_primaria: str, cor_secundaria: str, logo_url: str | None, remover_logo: bool,
) -> tuple[Barbearia, str | None]:
    """Devolve (barbearia, url da logo antiga que pode ser apagada)."""
    nome = " ".join(nome.split())[:80]
    if len(nome) < 3:
        raise ErroNegocio("Informe o nome da barbearia.")
    if not (cor_valida(cor_primaria) and cor_valida(cor_secundaria)):
        raise ErroNegocio("Escolha cores válidas (formato #RRGGBB).")
    numero = ""
    if whatsapp.strip():
        numero = normalizar_telefone(whatsapp) or ""
        if not numero:
            raise ErroNegocio("Confira o WhatsApp da barbearia (com DDD).")

    logo_antiga = None
    if logo_url or remover_logo:
        logo_antiga = barbearia.logo_url
        barbearia.logo_url = logo_url
    barbearia.nome = nome
    barbearia.endereco = " ".join(endereco.split())[:160]
    barbearia.whatsapp = numero
    barbearia.cor_primaria = cor_primaria.upper()
    barbearia.cor_secundaria = cor_secundaria.upper()
    return repo.barbearias.atualizar(barbearia), logo_antiga


def atualizar_funcionamento(
    repo: Repositorio, barbearia: Barbearia, *, abre_as: time | None, fecha_as: time | None,
    dias: list[int], intervalo: int, antecedencia: int, janela: int, lembrete_horas: int,
    dias_inatividade: int, mensagem_reativacao: str,
) -> Barbearia:
    if abre_as is None or fecha_as is None or fecha_as <= abre_as:
        raise ErroNegocio("O horário de fechamento precisa ser depois da abertura.")
    dias = sorted({d for d in dias if 0 <= d <= 6})
    if not dias:
        raise ErroNegocio("Marque pelo menos um dia de funcionamento.")
    if intervalo not in INTERVALOS_PERMITIDOS:
        raise ErroNegocio("Escolha um intervalo de agenda válido.")
    if not 0 <= antecedencia <= 48 * 60:
        raise ErroNegocio("A antecedência mínima deve ficar entre 0 e 48 horas.")
    if not 1 <= janela <= 90:
        raise ErroNegocio("A agenda pode abrir de 1 a 90 dias à frente.")
    if not 1 <= lembrete_horas <= 48:
        raise ErroNegocio("O lembrete deve sair entre 1 e 48 horas antes.")
    if not 7 <= dias_inatividade <= 365:
        raise ErroNegocio("Considere inativo entre 7 e 365 dias sem visita.")
    mensagem = mensagem_reativacao.strip()
    if "{link}" not in mensagem:
        raise ErroNegocio("A mensagem de reativação precisa ter {link}.")

    barbearia.abre_as, barbearia.fecha_as = abre_as, fecha_as
    barbearia.dias_funcionamento = dias
    barbearia.intervalo_minutos = intervalo
    barbearia.antecedencia_minima_minutos = antecedencia
    barbearia.janela_agendamento_dias = janela
    barbearia.lembrete_horas_antes = lembrete_horas
    barbearia.dias_inatividade = dias_inatividade
    barbearia.mensagem_reativacao = mensagem[:500]
    return repo.barbearias.atualizar(barbearia)


# --------------------------------------------------------------------- serviços
def _validar_servico(nome: str, preco: str, duracao: str) -> tuple[str, int, int]:
    nome = " ".join((nome or "").split())[:40]
    if len(nome) < 2:
        raise ErroNegocio("Todo serviço precisa de um nome.")
    centavos = reais_para_centavos(preco)
    if centavos is None or centavos > 100_000_00:
        raise ErroNegocio(f"Confira o preço de “{nome}”.")
    try:
        minutos = int(duracao)
    except (TypeError, ValueError):
        minutos = 0
    if not 5 <= minutos <= 480:
        raise ErroNegocio(f"A duração de “{nome}” deve ficar entre 5 e 480 minutos.")
    return nome, centavos, minutos


def salvar_servicos(repo: Repositorio, barbearia: Barbearia, alteracoes: list[dict]) -> None:
    """alteracoes: [{id, nome, preco, duracao, ativo}]"""
    validados = []
    for item in alteracoes:
        servico = repo.servicos.obter(barbearia.id, int(item["id"]))
        if servico is None:
            continue
        servico.nome, servico.preco_centavos, servico.duracao_minutos = _validar_servico(
            item["nome"], item["preco"], item["duracao"]
        )
        servico.ativo = bool(item.get("ativo"))
        validados.append(servico)
    if validados and not any(s.ativo for s in validados):
        raise ErroNegocio("Deixe pelo menos um serviço ativo para os clientes poderem agendar.")
    with repo.transacao():
        for servico in validados:
            repo.servicos.atualizar(servico)


def adicionar_servico(repo: Repositorio, barbearia: Barbearia, nome: str, preco: str, duracao: str) -> Servico:
    nome, centavos, minutos = _validar_servico(nome, preco, duracao)
    ordem = len(repo.servicos.listar(barbearia.id))
    return repo.servicos.adicionar(Servico(
        barbearia_id=barbearia.id, nome=nome, preco_centavos=centavos, duracao_minutos=minutos, ordem=ordem,
    ))


# ------------------------------------------------------------------------ equipe
def _validar_comissao(valor) -> int:
    try:
        comissao = int(valor)
    except (TypeError, ValueError):
        comissao = -1
    if not 0 <= comissao <= 100:
        raise ErroNegocio("A comissão deve ficar entre 0% e 100%.")
    return comissao


def adicionar_barbeiro(
    repo: Repositorio, barbearia: Barbearia, *, nome: str, especialidade: str, comissao,
    email: str = "", senha: str = "",
) -> Barbeiro:
    nome = " ".join(nome.split())[:80]
    if len(nome) < 2:
        raise ErroNegocio("Informe o nome do profissional.")
    barbeiro = repo.barbeiros.adicionar(Barbeiro(
        barbearia_id=barbearia.id, nome=nome, especialidade=" ".join(especialidade.split())[:80],
        comissao_percentual=_validar_comissao(comissao),
    ))
    if email.strip():
        definir_acesso(repo, barbearia, barbeiro, email, senha)
    return barbeiro


def atualizar_barbeiro(
    repo: Repositorio, barbearia: Barbearia, barbeiro: Barbeiro, *, nome: str, especialidade: str,
    comissao, ativo: bool, email: str = "", senha: str = "",
) -> Barbeiro:
    nome = " ".join(nome.split())[:80]
    if len(nome) < 2:
        raise ErroNegocio("Informe o nome do profissional.")
    barbeiro.nome = nome
    barbeiro.especialidade = " ".join(especialidade.split())[:80]
    barbeiro.comissao_percentual = _validar_comissao(comissao)
    barbeiro.ativo = ativo
    barbeiro = repo.barbeiros.atualizar(barbeiro)
    usuario = repo.usuarios.por_barbeiro(barbearia.id, barbeiro.id)
    if email.strip() or senha:
        usuario = definir_acesso(repo, barbearia, barbeiro, email, senha)
    if usuario is not None and usuario.papel == Papel.BARBEIRO and usuario.ativo != ativo:
        usuario.ativo = ativo
        repo.usuarios.atualizar(usuario)
    return barbeiro


def definir_acesso(repo: Repositorio, barbearia: Barbearia, barbeiro: Barbeiro, email: str, senha: str) -> Usuario:
    """Cria ou atualiza o login do barbeiro no painel."""
    email = email.strip().lower()
    if not _email_valido(email):
        raise ErroNegocio("Informe um e-mail válido para o acesso.")
    existente = repo.usuarios.por_email(barbearia.id, email)
    usuario = repo.usuarios.por_barbeiro(barbearia.id, barbeiro.id)
    if existente and (usuario is None or existente.id != usuario.id):
        raise ErroNegocio("Esse e-mail já é usado por outro acesso.")
    if usuario is None:
        _validar_senha(senha)
        return repo.usuarios.adicionar(Usuario(
            barbearia_id=barbearia.id, nome=barbeiro.nome, email=email,
            senha_hash=generate_password_hash(senha), papel=Papel.BARBEIRO, barbeiro_id=barbeiro.id,
        ))
    usuario.email = email
    usuario.nome = barbeiro.nome if usuario.papel == Papel.BARBEIRO else usuario.nome
    if senha:
        _validar_senha(senha)
        usuario.senha_hash = generate_password_hash(senha)
    return repo.usuarios.atualizar(usuario)


def adicionar_foto(repo: Repositorio, barbeiro: Barbeiro, url: str) -> Barbeiro:
    if len(barbeiro.fotos) >= MAX_FOTOS_PORTFOLIO:
        raise ErroNegocio(f"Cada profissional pode ter até {MAX_FOTOS_PORTFOLIO} fotos. Remova uma antes.")
    barbeiro.fotos.append(url)
    return repo.barbeiros.atualizar(barbeiro)


def remover_foto(repo: Repositorio, barbeiro: Barbeiro, indice: int) -> tuple[Barbeiro, str | None]:
    if not 0 <= indice < len(barbeiro.fotos):
        return barbeiro, None
    removida = barbeiro.fotos.pop(indice)
    return repo.barbeiros.atualizar(barbeiro), removida
