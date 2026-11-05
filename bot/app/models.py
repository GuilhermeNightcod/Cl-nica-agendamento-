"""Tabelas do banco de dados."""
from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .config import agora
from .db import Base


class Paciente(Base):
    __tablename__ = "pacientes"

    id: Mapped[int] = mapped_column(primary_key=True)
    telefone: Mapped[str] = mapped_column(String(32), unique=True, index=True)  # wa_id
    nome_perfil: Mapped[str | None] = mapped_column(String(120))  # nome do perfil do WhatsApp
    nome: Mapped[str | None] = mapped_column(String(120))
    data_nascimento: Mapped[date | None] = mapped_column(Date)
    aceitou_privacidade_em: Mapped[datetime | None] = mapped_column(DateTime)
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=agora)

    conversa: Mapped["Conversa"] = relationship(back_populates="paciente", uselist=False)
    agendamentos: Mapped[list["Agendamento"]] = relationship(back_populates="paciente")


class Conversa(Base):
    """Estado atual do paciente no fluxo do bot."""

    __tablename__ = "conversas"

    id: Mapped[int] = mapped_column(primary_key=True)
    paciente_id: Mapped[int] = mapped_column(ForeignKey("pacientes.id"), unique=True)
    estado: Mapped[str] = mapped_column(String(40), default="inicio")
    contexto: Mapped[dict] = mapped_column(JSON, default=dict)
    atendimento_humano: Mapped[bool] = mapped_column(Boolean, default=False)
    motivo_humano: Mapped[str | None] = mapped_column(String(200))
    chatwoot_conversa_id: Mapped[int | None] = mapped_column(Integer, index=True)
    ultima_msg_paciente_em: Mapped[datetime | None] = mapped_column(DateTime)
    atualizado_em: Mapped[datetime] = mapped_column(DateTime, default=agora)
    recuperacao_enviada_em: Mapped[datetime | None] = mapped_column(DateTime)

    paciente: Mapped[Paciente] = relationship(back_populates="conversa")


class Especialidade(Base):
    __tablename__ = "especialidades"

    id: Mapped[int] = mapped_column(primary_key=True)
    codigo: Mapped[str] = mapped_column(String(40), unique=True)
    nome: Mapped[str] = mapped_column(String(60))
    descricao: Mapped[str] = mapped_column(String(300), default="")
    ativa: Mapped[bool] = mapped_column(Boolean, default=True)


class Vaga(Base):
    """Um horário de atendimento de uma especialidade, com N vagas."""

    __tablename__ = "vagas"
    __table_args__ = (UniqueConstraint("especialidade_id", "inicio"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    especialidade_id: Mapped[int] = mapped_column(ForeignKey("especialidades.id"), index=True)
    inicio: Mapped[datetime] = mapped_column(DateTime, index=True)
    capacidade: Mapped[int] = mapped_column(Integer, default=1)
    ocupadas: Mapped[int] = mapped_column(Integer, default=0)

    especialidade: Mapped[Especialidade] = relationship()

    @property
    def turno(self) -> str:
        h = self.inicio.hour
        return "manha" if h < 12 else ("tarde" if h < 18 else "noite")

    @property
    def livres(self) -> int:
        return self.capacidade - self.ocupadas


class Agendamento(Base):
    __tablename__ = "agendamentos"

    id: Mapped[int] = mapped_column(primary_key=True)
    paciente_id: Mapped[int] = mapped_column(ForeignKey("pacientes.id"), index=True)
    vaga_id: Mapped[int] = mapped_column(ForeignKey("vagas.id"), index=True)
    queixa: Mapped[str | None] = mapped_column(Text)
    # agendado | confirmado | cancelado | compareceu | faltou
    status: Mapped[str] = mapped_column(String(20), default="agendado", index=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=agora)
    lembrete_enviado_em: Mapped[datetime | None] = mapped_column(DateTime)

    paciente: Mapped[Paciente] = relationship(back_populates="agendamentos")
    vaga: Mapped[Vaga] = relationship()


class ListaEspera(Base):
    __tablename__ = "lista_espera"

    id: Mapped[int] = mapped_column(primary_key=True)
    paciente_id: Mapped[int] = mapped_column(ForeignKey("pacientes.id"), index=True)
    especialidade_id: Mapped[int] = mapped_column(ForeignKey("especialidades.id"), index=True)
    turno: Mapped[str | None] = mapped_column(String(10))
    queixa: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="aguardando")  # aguardando | atendido
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=agora)

    paciente: Mapped[Paciente] = relationship()
    especialidade: Mapped[Especialidade] = relationship()


class Mensagem(Base):
    """Histórico de mensagens (para auditoria e indicadores)."""

    __tablename__ = "mensagens"

    id: Mapped[int] = mapped_column(primary_key=True)
    paciente_id: Mapped[int] = mapped_column(ForeignKey("pacientes.id"), index=True)
    direcao: Mapped[str] = mapped_column(String(10))  # entrada | saida
    conteudo: Mapped[str] = mapped_column(Text)
    wa_message_id: Mapped[str | None] = mapped_column(String(128), unique=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=agora, index=True)
