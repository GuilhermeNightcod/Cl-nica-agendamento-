"""Tabelas do banco de dados."""
from datetime import date, datetime, time

from sqlalchemy import JSON, Boolean, Column, Date, DateTime, ForeignKey, Integer, String, Table, Text, Time, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .config import agora
from .db import Base

DIAS_SEMANA = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]


# ============================================================ pacientes
class Paciente(Base):
    __tablename__ = "pacientes"

    id: Mapped[int] = mapped_column(primary_key=True)
    telefone: Mapped[str | None] = mapped_column(String(32), unique=True, index=True)  # wa_id: 55 + DDD + número
    nome_perfil: Mapped[str | None] = mapped_column(String(120))  # nome do perfil do WhatsApp
    nome: Mapped[str | None] = mapped_column(String(120), index=True)
    data_nascimento: Mapped[date | None] = mapped_column(Date)
    cpf: Mapped[str | None] = mapped_column(String(14), index=True)
    numero_prontuario: Mapped[str | None] = mapped_column(String(30), index=True)  # nº da pasta física
    observacoes: Mapped[str | None] = mapped_column(Text)
    aceitou_privacidade_em: Mapped[datetime | None] = mapped_column(DateTime)
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=agora)

    conversa: Mapped["Conversa"] = relationship(back_populates="paciente", uselist=False)
    agendamentos: Mapped[list["Agendamento"]] = relationship(back_populates="paciente")
    documentos: Mapped[list["Documento"]] = relationship(back_populates="paciente", order_by="Documento.data_documento.desc()")

    @property
    def nome_exibicao(self) -> str:
        return self.nome or self.nome_perfil or (f"+{self.telefone}" if self.telefone else "Sem nome")

    def idade(self, em: date | None = None) -> int | None:
        if not self.data_nascimento:
            return None
        em = em or agora().date()
        d = self.data_nascimento
        return em.year - d.year - ((em.month, em.day) < (d.month, d.day))


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


# ============================================================ clínica
class Especialidade(Base):
    """Área de atendimento: Endodontia, Prótese, Hebiatria..."""

    __tablename__ = "especialidades"

    id: Mapped[int] = mapped_column(primary_key=True)
    codigo: Mapped[str] = mapped_column(String(40), unique=True)
    nome: Mapped[str] = mapped_column(String(60))
    descricao: Mapped[str] = mapped_column(String(300), default="")
    ativa: Mapped[bool] = mapped_column(Boolean, default=True)
    mostrar_no_bot: Mapped[bool] = mapped_column(Boolean, default=True)

    procedimentos: Mapped[list["Procedimento"]] = relationship(back_populates="especialidade", order_by="Procedimento.nome")


class Procedimento(Base):
    __tablename__ = "procedimentos"
    __table_args__ = (UniqueConstraint("especialidade_id", "nome"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    especialidade_id: Mapped[int] = mapped_column(ForeignKey("especialidades.id"))
    nome: Mapped[str] = mapped_column(String(80))

    especialidade: Mapped[Especialidade] = relationship(back_populates="procedimentos")


class EspacoClinico(Base):
    """Clínica física (ex.: Odontocase), com um número de boxes/cadeiras. Várias turmas podem dividir."""

    __tablename__ = "espacos_clinicos"

    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(80), unique=True)
    boxes: Mapped[int | None] = mapped_column(Integer)  # None = ainda não informado


sessao_especialidade = Table(
    "sessao_especialidade",
    Base.metadata,
    Column("sessao_id", ForeignKey("sessoes_clinica.id", ondelete="CASCADE"), primary_key=True),
    Column("especialidade_id", ForeignKey("especialidades.id", ondelete="CASCADE"), primary_key=True),
)


class SessaoClinica(Base):
    """
    Um horário fixo semanal de clínica de uma turma.
    Ex.: 8º semestre, terça 08:00–12:00, Profª Jhennifer, Triagem + Endodontia, 10 vagas.
    """

    __tablename__ = "sessoes_clinica"

    id: Mapped[int] = mapped_column(primary_key=True)
    turma: Mapped[str] = mapped_column(String(40), index=True)  # "8º semestre"
    nome: Mapped[str] = mapped_column(String(80), default="")  # "Clínica Integrada VIII"
    dia_semana: Mapped[int] = mapped_column(Integer)  # 0 = segunda ... 5 = sábado
    hora_inicio: Mapped[time] = mapped_column(Time)
    hora_fim: Mapped[time] = mapped_column(Time)
    professor: Mapped[str] = mapped_column(String(120), default="")
    procedimentos_texto: Mapped[str] = mapped_column(Text, default="")  # "anamnese, capeamento pulpar, acesso"
    vagas: Mapped[int] = mapped_column(Integer, default=10)
    espaco_id: Mapped[int | None] = mapped_column(ForeignKey("espacos_clinicos.id"))
    alunos: Mapped[int | None] = mapped_column(Integer)  # alunos da turma nesta clínica
    pacientes_por_dupla: Mapped[int] = mapped_column(Integer, default=1)
    idade_min: Mapped[int | None] = mapped_column(Integer)
    idade_max: Mapped[int | None] = mapped_column(Integer)
    ativa: Mapped[bool] = mapped_column(Boolean, default=True)

    especialidades: Mapped[list[Especialidade]] = relationship(secondary=sessao_especialidade, order_by="Especialidade.nome")
    espaco: Mapped[EspacoClinico | None] = relationship()

    @property
    def duplas(self) -> int | None:
        """Cada dupla de alunos ocupa um box."""
        return (self.alunos + 1) // 2 if self.alunos else None

    def recalcular_vagas(self) -> None:
        if self.duplas:
            self.vagas = self.duplas * max(1, self.pacientes_por_dupla or 1)

    @property
    def dia_nome(self) -> str:
        return DIAS_SEMANA[self.dia_semana]

    @property
    def horario(self) -> str:
        return f"{self.hora_inicio:%H:%M}–{self.hora_fim:%H:%M}"

    @property
    def areas(self) -> str:
        return ", ".join(e.nome for e in self.especialidades)

    @property
    def faixa_etaria(self) -> str:
        if self.idade_min is None and self.idade_max is None:
            return "Todas as idades"
        if self.idade_max is None:
            return f"A partir de {self.idade_min} anos"
        if self.idade_min is None:
            return f"Até {self.idade_max} anos"
        return f"{self.idade_min} a {self.idade_max} anos"

    def aceita_idade(self, idade: int | None) -> bool:
        if idade is None:
            return True  # sem data de nascimento: a recepção confere
        return (self.idade_min is None or idade >= self.idade_min) and (self.idade_max is None or idade <= self.idade_max)


class Vaga(Base):
    """Uma data concreta de uma sessão de clínica (ex.: terça 10/11, 8º semestre)."""

    __tablename__ = "vagas"
    __table_args__ = (UniqueConstraint("sessao_id", "inicio"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    sessao_id: Mapped[int] = mapped_column(ForeignKey("sessoes_clinica.id"), index=True)
    inicio: Mapped[datetime] = mapped_column(DateTime, index=True)
    fim: Mapped[datetime] = mapped_column(DateTime)
    capacidade: Mapped[int] = mapped_column(Integer, default=1)
    ocupadas: Mapped[int] = mapped_column(Integer, default=0)
    bloqueada: Mapped[bool] = mapped_column(Boolean, default=False)
    motivo_bloqueio: Mapped[str | None] = mapped_column(String(200))

    sessao: Mapped[SessaoClinica] = relationship()
    agendamentos: Mapped[list["Agendamento"]] = relationship(back_populates="vaga", order_by="Agendamento.id")

    @property
    def turno(self) -> str:
        h = self.inicio.hour
        return "manha" if h < 12 else ("tarde" if h < 18 else "noite")

    @property
    def livres(self) -> int:
        return 0 if self.bloqueada else max(0, self.capacidade - self.ocupadas)

    @property
    def ativos(self) -> list["Agendamento"]:
        return [a for a in self.agendamentos if a.status != "cancelado"]


class Agendamento(Base):
    __tablename__ = "agendamentos"

    id: Mapped[int] = mapped_column(primary_key=True)
    paciente_id: Mapped[int] = mapped_column(ForeignKey("pacientes.id"), index=True)
    vaga_id: Mapped[int] = mapped_column(ForeignKey("vagas.id"), index=True)
    especialidade_id: Mapped[int | None] = mapped_column(ForeignKey("especialidades.id"))
    procedimento_id: Mapped[int | None] = mapped_column(ForeignKey("procedimentos.id"))
    queixa: Mapped[str | None] = mapped_column(Text)
    observacao: Mapped[str | None] = mapped_column(Text)
    aluno: Mapped[str | None] = mapped_column(String(120))
    hora: Mapped[time | None] = mapped_column(Time)  # horário de chegada do paciente (opcional)
    origem: Mapped[str] = mapped_column(String(20), default="bot")  # bot | recepcao
    criado_por: Mapped[str | None] = mapped_column(String(60))
    # agendado | confirmado | cancelado | compareceu | faltou
    status: Mapped[str] = mapped_column(String(20), default="agendado", index=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=agora)
    lembrete_enviado_em: Mapped[datetime | None] = mapped_column(DateTime)

    paciente: Mapped[Paciente] = relationship(back_populates="agendamentos")
    vaga: Mapped[Vaga] = relationship(back_populates="agendamentos")
    especialidade: Mapped[Especialidade | None] = relationship()
    procedimento: Mapped[Procedimento | None] = relationship()

    @property
    def inicio(self) -> datetime:
        """Data e hora do paciente: o horário dele, ou o início da clínica."""
        return datetime.combine(self.vaga.inicio.date(), self.hora) if self.hora else self.vaga.inicio

    @property
    def descricao(self) -> str:
        if self.procedimento:
            return self.procedimento.nome
        if self.especialidade:
            return self.especialidade.nome
        return self.vaga.sessao.areas


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


# ============================================================ prontuário digitalizado
class Documento(Base):
    """Folha do prontuário físico digitalizada (foto ou PDF)."""

    __tablename__ = "documentos"

    id: Mapped[int] = mapped_column(primary_key=True)
    paciente_id: Mapped[int] = mapped_column(ForeignKey("pacientes.id"), index=True)
    tipo: Mapped[str] = mapped_column(String(40))  # anamnese | odontograma | radiografia | ...
    descricao: Mapped[str | None] = mapped_column(String(200))
    data_documento: Mapped[date | None] = mapped_column(Date)
    arquivo: Mapped[str] = mapped_column(String(120))  # nome interno no disco
    nome_original: Mapped[str] = mapped_column(String(200))
    tipo_arquivo: Mapped[str] = mapped_column(String(60))
    tamanho: Mapped[int] = mapped_column(Integer)
    enviado_por: Mapped[str | None] = mapped_column(String(60))
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=agora)

    paciente: Mapped[Paciente] = relationship(back_populates="documentos")

    @property
    def eh_imagem(self) -> bool:
        return self.tipo_arquivo.startswith("image/")


class RegistroAcesso(Base):
    """Quem viu ou alterou dados de paciente, e quando (LGPD)."""

    __tablename__ = "registro_acessos"

    id: Mapped[int] = mapped_column(primary_key=True)
    usuario: Mapped[str] = mapped_column(String(60), index=True)
    acao: Mapped[str] = mapped_column(String(60))
    paciente_id: Mapped[int | None] = mapped_column(ForeignKey("pacientes.id"), index=True)
    detalhe: Mapped[str | None] = mapped_column(String(300))
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=agora, index=True)


class Mensagem(Base):
    """Histórico de mensagens do WhatsApp."""

    __tablename__ = "mensagens"

    id: Mapped[int] = mapped_column(primary_key=True)
    paciente_id: Mapped[int] = mapped_column(ForeignKey("pacientes.id"), index=True)
    direcao: Mapped[str] = mapped_column(String(10))  # entrada | saida
    conteudo: Mapped[str] = mapped_column(Text)
    wa_message_id: Mapped[str | None] = mapped_column(String(128), unique=True)
    autor: Mapped[str | None] = mapped_column(String(60))  # bot | login do atendente | None (paciente)
    atendimento_id: Mapped[int | None] = mapped_column(ForeignKey("atendimentos.id"), index=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=agora, index=True)


# ============================================================ atendimento humano (WhatsApp)
class Setor(Base):
    """Fila de atendimento: Recepção, Urgência, Dúvidas clínicas..."""

    __tablename__ = "setores"

    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(60), unique=True)
    cor: Mapped[str] = mapped_column(String(9), default="#0f5c8c")
    padrao: Mapped[bool] = mapped_column(Boolean, default=False)
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)


class Etiqueta(Base):
    __tablename__ = "etiquetas"

    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(40), unique=True)
    cor: Mapped[str] = mapped_column(String(9), default="#6b7280")


atendimento_etiqueta = Table(
    "atendimento_etiqueta",
    Base.metadata,
    Column("atendimento_id", ForeignKey("atendimentos.id", ondelete="CASCADE"), primary_key=True),
    Column("etiqueta_id", ForeignKey("etiquetas.id", ondelete="CASCADE"), primary_key=True),
)


class Atendimento(Base):
    """
    Uma conversa com atendimento humano.
      fila            -> aguardando alguém assumir
      em_atendimento  -> um atendente assumiu
      finalizado      -> encerrado (o bot volta a responder)
    """

    __tablename__ = "atendimentos"

    id: Mapped[int] = mapped_column(primary_key=True)
    paciente_id: Mapped[int] = mapped_column(ForeignKey("pacientes.id"), index=True)
    setor_id: Mapped[int | None] = mapped_column(ForeignKey("setores.id"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="fila", index=True)
    motivo: Mapped[str | None] = mapped_column(String(200))
    urgente: Mapped[bool] = mapped_column(Boolean, default=False)
    assumido_por: Mapped[str | None] = mapped_column(String(60), index=True)
    finalizado_por: Mapped[str | None] = mapped_column(String(60))
    aberto_em: Mapped[datetime] = mapped_column(DateTime, default=agora, index=True)
    assumido_em: Mapped[datetime | None] = mapped_column(DateTime)
    finalizado_em: Mapped[datetime | None] = mapped_column(DateTime)
    ultima_msg_em: Mapped[datetime] = mapped_column(DateTime, default=agora, index=True)
    nao_lidas: Mapped[int] = mapped_column(Integer, default=0)

    paciente: Mapped[Paciente] = relationship()
    setor: Mapped[Setor | None] = relationship()
    etiquetas: Mapped[list[Etiqueta]] = relationship(secondary=atendimento_etiqueta, order_by="Etiqueta.nome")

    @property
    def aberto(self) -> bool:
        return self.status in ("fila", "em_atendimento")


# ============================================================ odontograma
DENTES_PERMANENTES = [
    [18, 17, 16, 15, 14, 13, 12, 11, 21, 22, 23, 24, 25, 26, 27, 28],
    [48, 47, 46, 45, 44, 43, 42, 41, 31, 32, 33, 34, 35, 36, 37, 38],
]
DENTES_DECIDUOS = [
    [55, 54, 53, 52, 51, 61, 62, 63, 64, 65],
    [85, 84, 83, 82, 81, 71, 72, 73, 74, 75],
]
REGIOES = {
    "maxila": "Maxila", "mandibula": "Mandíbula", "face": "Face",
    "arcada_sup": "Arcada superior", "arcada_inf": "Arcada inferior", "arcadas": "Arcadas",
}
STATUS_DENTE = {
    "aberto": "Em tratamento", "finalizado": "Finalizado", "existente": "Já existente", "ausente": "Ausente/extraído",
}


class RegistroDente(Base):
    """Um registro do odontograma: procedimento num dente (ou região), com faces e status."""

    __tablename__ = "odontograma"

    id: Mapped[int] = mapped_column(primary_key=True)
    paciente_id: Mapped[int] = mapped_column(ForeignKey("pacientes.id"), index=True)
    dente: Mapped[str] = mapped_column(String(12))  # "11".."85" ou código de região
    faces: Mapped[str] = mapped_column(String(10), default="")  # letras: M O D V L
    procedimento_id: Mapped[int | None] = mapped_column(ForeignKey("procedimentos.id"))
    descricao: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(12), default="aberto")
    anotacao: Mapped[str | None] = mapped_column(Text)
    aluno: Mapped[str | None] = mapped_column(String(120))
    criado_por: Mapped[str | None] = mapped_column(String(60))
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=agora)
    finalizado_em: Mapped[datetime | None] = mapped_column(DateTime)

    procedimento: Mapped[Procedimento | None] = relationship()

    @property
    def local(self) -> str:
        return REGIOES.get(self.dente, f"Dente {self.dente}")
