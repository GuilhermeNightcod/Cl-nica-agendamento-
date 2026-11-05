"""
Atendimento humano pelo WhatsApp, dentro do próprio sistema (sem depender do Chatwoot).

  bot ──(urgência / pedido)──► FILA ──(atendente assume)──► EM ATENDIMENTO ──► FINALIZADO ──► bot
"""
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import config, textos as T
from .mensagens import Modelo, Texto, resumo
from .models import Atendimento, Conversa, Mensagem, Paciente, Setor


class ForaDaJanela(Exception):
    """Passaram 24h da última mensagem do paciente: só é permitido enviar template."""


def setor_padrao(s: Session, urgente: bool = False) -> Setor | None:
    if urgente and (u := s.scalar(select(Setor).where(Setor.nome.ilike("urg%"), Setor.ativo))):
        return u
    return s.scalar(select(Setor).where(Setor.padrao, Setor.ativo)) or s.scalar(select(Setor).where(Setor.ativo))


def aberto_do_paciente(s: Session, paciente_id: int) -> Atendimento | None:
    return s.scalar(
        select(Atendimento)
        .where(Atendimento.paciente_id == paciente_id, Atendimento.status.in_(["fila", "em_atendimento"]))
        .order_by(Atendimento.id.desc())
    )


def abrir(s: Session, p: Paciente, motivo: str, urgente: bool = False, atendente: str | None = None) -> Atendimento:
    """Coloca o paciente na fila (ou já com um atendente, se `atendente` for informado)."""
    at = aberto_do_paciente(s, p.id)
    agora = config.agora()
    if at is None:
        setor = setor_padrao(s, urgente)
        at = Atendimento(paciente_id=p.id, setor_id=setor.id if setor else None, motivo=motivo[:200], urgente=urgente,
                         status="fila", nao_lidas=0, aberto_em=agora, ultima_msg_em=agora)
        s.add(at)
    elif urgente and not at.urgente:
        at.urgente = True
        if (u := setor_padrao(s, urgente=True)):
            at.setor_id = u.id
    if atendente and at.status == "fila":
        assumir(at, atendente)
    conv = p.conversa
    if conv:
        conv.atendimento_humano = True
        conv.motivo_humano = motivo[:200]
        conv.estado = "humano"
    s.flush()
    return at


def assumir(at: Atendimento, login: str) -> None:
    if at.status == "fila" or at.assumido_por != login:
        at.status = "em_atendimento"
        at.assumido_por = login
        at.assumido_em = at.assumido_em or config.agora()


def proximo_da_fila(s: Session, login: str, setor_id: int | None = None) -> Atendimento | None:
    q = select(Atendimento).where(Atendimento.status == "fila")
    if setor_id:
        q = q.where(Atendimento.setor_id == setor_id)
    at = s.scalar(q.order_by(Atendimento.urgente.desc(), Atendimento.aberto_em).with_for_update(skip_locked=True).limit(1))
    if at:
        assumir(at, login)
    return at


def janela_aberta(conv: Conversa | None) -> bool:
    return bool(conv and conv.ultima_msg_paciente_em and config.agora() - conv.ultima_msg_paciente_em < timedelta(hours=24))


def registrar(s: Session, p: Paciente, direcao: str, conteudo: str, autor: str | None = None,
              at: Atendimento | None = None, wa_id: str | None = None) -> Mensagem:
    m = Mensagem(paciente_id=p.id, direcao=direcao, conteudo=conteudo, autor=autor, wa_message_id=wa_id,
                 atendimento_id=at.id if at else None)
    s.add(m)
    if at:
        at.ultima_msg_em = config.agora()
    return m


def responder(s: Session, servico, at: Atendimento, login: str, texto: str) -> None:
    p = at.paciente
    if not janela_aberta(p.conversa):
        raise ForaDaJanela("Passaram 24h da última mensagem do paciente. O WhatsApp só permite enviar um modelo aprovado.")
    assumir(at, login)
    at.nao_lidas = 0
    servico.enviar(p.telefone, [Texto(texto)])
    registrar(s, p, "saida", texto, autor=login, at=at)


def enviar_modelo_contato(s: Session, servico, at: Atendimento, login: str) -> None:
    """Fora da janela de 24h: envia o template de contato para o paciente responder."""
    if not config.TEMPLATE_CONTATO:
        raise ForaDaJanela("Configure TEMPLATE_CONTATO no .env (modelo aprovado na Meta) para iniciar conversa.")
    p = at.paciente
    nome = (p.nome or p.nome_perfil or "paciente").split()[0]
    msg = Modelo(config.TEMPLATE_CONTATO, [nome], texto_resumo=f"Modelo de contato enviado para {nome}")
    assumir(at, login)
    servico.enviar(p.telefone, [msg])
    registrar(s, p, "saida", resumo(msg), autor=login, at=at)


def transferir(at: Atendimento, setor_id: int) -> None:
    at.setor_id = setor_id
    at.status = "fila"
    at.assumido_por = None


def finalizar(s: Session, servico, at: Atendimento, login: str, avisar: bool = True) -> None:
    at.status = "finalizado"
    at.finalizado_por = login
    at.finalizado_em = config.agora()
    at.nao_lidas = 0
    p = at.paciente
    conv = p.conversa
    if conv:
        conv.atendimento_humano = False
        conv.motivo_humano = None
        conv.estado = "inicio"
        conv.contexto = {}
    if avisar and p.telefone and janela_aberta(conv):
        servico.enviar(p.telefone, [Texto(T.ATENDIMENTO_ENCERRADO)])
        registrar(s, p, "saida", T.ATENDIMENTO_ENCERRADO, autor="bot", at=at)
