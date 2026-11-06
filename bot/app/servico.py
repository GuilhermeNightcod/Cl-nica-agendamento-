"""Junta tudo: recebe mensagens, roda o fluxo, envia respostas e aciona o Chatwoot."""
import logging
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import config
from .chatwoot import ClienteChatwoot
from .fluxo import Resultado, fmt_data, fmt_hora, processar, registrar
from .mensagens import Entrada, Modelo, Resposta, Texto, resumo
from .models import Conversa, Mensagem, Paciente
from .whatsapp import ClienteWhatsApp

log = logging.getLogger("servico")


class Servico:
    def __init__(self, whatsapp=None, chatwoot=None) -> None:
        self.whatsapp = whatsapp or ClienteWhatsApp()
        self._chatwoot = chatwoot

    @property
    def chatwoot(self):
        if self._chatwoot is None and config.chatwoot_ativo():
            self._chatwoot = ClienteChatwoot()
        return self._chatwoot

    def enviar(self, telefone: str, respostas: list[Resposta]) -> None:
        for r in respostas:
            try:
                self.whatsapp.enviar(telefone, r)
            except Exception:
                log.exception("Falha ao enviar mensagem para %s", telefone)

    def receber(self, s: Session, e: Entrada) -> Resultado:
        res = processar(s, e)
        if res.duplicada:
            return res
        self.enviar(e.telefone, res.respostas)
        p = s.scalar(select(Paciente).where(Paciente.telefone == e.telefone))
        if res.chamar_humano:
            from . import atendimentos

            at = atendimentos.abrir(s, p, res.chamar_humano, urgente=res.urgente, setor_nome=res.setor)
            # liga ao atendimento as mensagens desta troca (a do paciente e a resposta do bot)
            for m in s.scalars(select(Mensagem).where(Mensagem.paciente_id == p.id, Mensagem.atendimento_id.is_(None))
                               .order_by(Mensagem.id.desc()).limit(1 + len(res.respostas))):
                m.atendimento_id = at.id
            self._abrir_humano(s, p, res.chamar_humano)
        elif res.repassar_para_humano and self.chatwoot and p.conversa.chatwoot_conversa_id:
            try:
                self.chatwoot.mensagem_do_paciente(p.conversa.chatwoot_conversa_id, e.texto or f"[{e.tipo}]")
            except Exception:
                log.exception("Falha ao repassar mensagem ao Chatwoot")
        return res

    def _abrir_humano(self, s: Session, p: Paciente, motivo: str) -> None:
        if not self.chatwoot:  # Chatwoot é opcional: a caixa de atendimento do próprio sistema já recebe
            return
        historico = s.scalars(
            select(Mensagem).where(Mensagem.paciente_id == p.id).order_by(Mensagem.id.desc()).limit(12)
        ).all()
        prox = [a for a in p.agendamentos if a.status in ("agendado", "confirmado") and a.vaga.inicio >= config.agora()]
        linhas = [
            f"🤖 *Transferido pelo bot* — {motivo}",
            f"Paciente: {p.nome or p.nome_perfil or '-'} | Tel: +{p.telefone}",
            f"Nascimento: {p.data_nascimento:%d/%m/%Y}" if p.data_nascimento else "Nascimento: -",
            f"Queixa: {(p.conversa.contexto or {}).get('queixa') or '-'}",
        ]
        if prox:
            linhas.append(
                "Próximos agendamentos: "
                + "; ".join(f"{a.descricao} {fmt_data(a.vaga.inicio)} {fmt_hora(a.vaga.inicio)}" for a in prox)
            )
        linhas.append("\n— Últimas mensagens —")
        for m in reversed(historico):
            quem = "Paciente" if m.direcao == "entrada" else "Bot"
            linhas.append(f"{quem}: {m.conteudo[:200]}")
        try:
            p.conversa.chatwoot_conversa_id = self.chatwoot.abrir_conversa(p, "\n".join(linhas))
        except Exception:
            log.exception("Falha ao abrir conversa no Chatwoot")

    def notificar_agendamento(self, s: Session, ag) -> str:
        """Avisa o paciente quando a RECEPÇÃO agenda. Retorna o que aconteceu (para mostrar na tela)."""
        p, v = ag.paciente, ag.vaga
        if not p.telefone:
            return "Paciente sem WhatsApp cadastrado: avise por telefone."
        conv = p.conversa
        dentro_24h = bool(conv and conv.ultima_msg_paciente_em and config.agora() - conv.ultima_msg_paciente_em < timedelta(hours=23))
        if dentro_24h:
            from . import textos as T

            msg = Texto(T.AGENDAMENTO_OK.format(especialidade=ag.descricao, data=fmt_data(ag.inicio), hora=fmt_hora(ag.inicio)))
        elif config.TEMPLATE_AGENDAMENTO:
            msg = Modelo(
                config.TEMPLATE_AGENDAMENTO,
                [(p.nome or p.nome_perfil or "paciente").split()[0], ag.descricao, fmt_data(ag.inicio), fmt_hora(ag.inicio)],
                texto_resumo=f"Agendamento {ag.descricao} {fmt_data(ag.inicio)} {fmt_hora(ag.inicio)}",
            )
        else:
            return "Agendado. O paciente receberá o lembrete automático antes da consulta."
        self.enviar(p.telefone, [msg])
        registrar(s, p, "saida", resumo(msg))
        return "Agendado e o paciente foi avisado pelo WhatsApp."

    # ---- eventos vindos do Chatwoot -------------------------------------------------
    def evento_chatwoot(self, s: Session, evento: dict) -> None:
        tipo = evento.get("event")
        conv_cw = evento.get("conversation") or {}
        conv_id = conv_cw.get("id") or (evento.get("id") if tipo != "message_created" else None)
        if not conv_id:
            return
        conv = s.scalar(select(Conversa).where(Conversa.chatwoot_conversa_id == conv_id))
        if not conv:
            return
        p = conv.paciente

        if tipo == "message_created":
            if evento.get("message_type") != "outgoing" or evento.get("private"):
                return
            texto = (evento.get("content") or "").strip()
            if not texto:
                return
            conv.atendimento_humano = True  # atendente assumiu a conversa
            conv.estado = "humano"
            from . import atendimentos

            registrar(s, p, "saida", texto, autor="chatwoot")
            if at := atendimentos.aberto_do_paciente(s, p.id):
                atendimentos.assumir(at, "chatwoot")
            self.enviar(p.telefone, [Texto(texto)])

        elif tipo == "conversation_status_changed":
            status = evento.get("status") or conv_cw.get("status")
            if status == "resolved" and conv.atendimento_humano:
                from . import atendimentos

                at = atendimentos.aberto_do_paciente(s, p.id) or atendimentos.abrir(s, p, "Chatwoot")
                atendimentos.finalizar(s, self, at, "chatwoot")
