"""
Rotinas automáticas (rodam a cada INTERVALO_TAREFAS_MIN minutos):
  * Lembrete: envia o template de lembrete X horas antes da consulta.
  * Recuperação: chama de volta quem parou no meio do agendamento.
"""
import logging
from datetime import timedelta

from sqlalchemy import select

from . import config, textos as T
from .fluxo import ESTADOS_AGENDAMENTO, fmt_data, fmt_hora, primeiro_nome, registrar
from .mensagens import Botoes, Modelo, resumo
from .models import Agendamento, Conversa, Vaga

log = logging.getLogger("tarefas")


def enviar_lembretes(s, servico) -> int:
    agora = config.agora()
    limite = agora + timedelta(hours=config.LEMBRETE_HORAS_ANTES)
    ags = s.scalars(
        select(Agendamento)
        .join(Vaga)
        .where(
            Agendamento.status == "agendado",
            Agendamento.lembrete_enviado_em.is_(None),
            Vaga.bloqueada.is_(False),
            Vaga.inicio > agora,
            Vaga.inicio <= limite,
        )
    ).all()
    for ag in ags:
        p, v = ag.paciente, ag.vaga
        if not p.telefone:  # paciente sem WhatsApp: a recepção liga
            ag.lembrete_enviado_em = agora
            continue
        # Template na Meta (exemplo):
        #   "Olá {{1}}! Lembrete da sua consulta de {{2}} na clínica-escola:
        #    {{3}} às {{4}}. Você confirma presença?"   [Confirmo] [Remarcar]
        msg = Modelo(
            config.TEMPLATE_LEMBRETE,
            [primeiro_nome(p) or "paciente", ag.descricao, fmt_data(v.inicio), fmt_hora(v.inicio)],
            texto_resumo=f"Lembrete {ag.descricao} {fmt_data(v.inicio)} {fmt_hora(v.inicio)}",
            payloads_botoes=[f"confirma:{ag.id}", f"remarca:{ag.id}"],
        )
        servico.enviar(p.telefone, [msg])
        ag.lembrete_enviado_em = agora
        registrar(s, p, "saida", resumo(msg))
    return len(ags)


def recuperar_abandonos(s, servico) -> int:
    """
    Só manda mensagem dentro da janela de 24h do WhatsApp (mensagem grátis e
    permitida sem template). Fora dela, o paciente aparece no painel como pendente.
    """
    agora = config.agora()
    convs = s.scalars(
        select(Conversa).where(
            Conversa.estado.in_(ESTADOS_AGENDAMENTO),
            Conversa.atendimento_humano.is_(False),
            Conversa.recuperacao_enviada_em.is_(None),
            Conversa.ultima_msg_paciente_em <= agora - timedelta(hours=config.RECUPERACAO_APOS_HORAS),
            Conversa.ultima_msg_paciente_em > agora - timedelta(hours=23),
        )
    ).all()
    for c in convs:
        nome = primeiro_nome(c.paciente)
        msg = Botoes(
            T.RECUPERACAO.format(nome=f", {nome}" if nome else ""),
            [("continuar", T.BOTAO_CONTINUAR), ("menu:humano", T.MENU_HUMANO), ("menu", T.BOTAO_MENU)],
        )
        servico.enviar(c.paciente.telefone, [msg])
        c.recuperacao_enviada_em = agora
        c.contexto = {**(c.contexto or {}), "estado_anterior": c.estado, "opcoes": [[i, t] for i, t in msg.opcoes]}
        c.estado = "recuperacao"
        registrar(s, c.paciente, "saida", resumo(msg))
    return len(convs)


def rodar_tudo(servico) -> None:
    from .db import sessao

    try:
        with sessao() as s:
            n1 = enviar_lembretes(s, servico)
            n2 = recuperar_abandonos(s, servico)
        if n1 or n2:
            log.info("Rotinas: %s lembretes, %s recuperações", n1, n2)
    except Exception:
        log.exception("Erro nas rotinas automáticas")
