"""
Regras da agenda, usadas tanto pelo bot quanto pela tela da recepção.

  SessaoClinica (grade semanal da turma)  ──gera──►  Vaga (cada data do semestre)
  Vaga  ◄──  Agendamento (paciente + área/procedimento)
"""
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import config
from .models import Agendamento, Especialidade, Paciente, SessaoClinica, Vaga, sessao_especialidade

STATUS_ATIVOS = ("agendado", "confirmado")


class VagaIndisponivel(Exception):
    pass


# ------------------------------------------------------------------ geração das datas
def datas_da_sessao(sessao: SessaoClinica, inicio: date, fim: date, feriados: set[date]) -> list[date]:
    d = inicio + timedelta(days=(sessao.dia_semana - inicio.weekday()) % 7)
    datas = []
    while d <= fim:
        if d not in feriados:
            datas.append(d)
        d += timedelta(days=7)
    return datas


def gerar_vagas(s: Session, feriados: set[date], inicio: date | None = None, fim: date | None = None) -> dict:
    """
    Cria/atualiza as datas de todas as sessões no período do semestre.
    Só mexe em datas futuras. Datas que deixaram de existir são apagadas se
    estiverem vazias; se tiverem pacientes, ficam (e aparecem para remarcar).
    """
    inicio = max(inicio or config.SEMESTRE_INICIO, config.agora().date())
    fim = fim or config.SEMESTRE_FIM
    criadas = atualizadas = removidas = 0
    for sessao in s.scalars(select(SessaoClinica)):
        desejadas = {}
        if sessao.ativa:
            for d in datas_da_sessao(sessao, inicio, fim, feriados):
                desejadas[datetime.combine(d, sessao.hora_inicio)] = datetime.combine(d, sessao.hora_fim)
        existentes = {
            v.inicio.date(): v
            for v in s.scalars(
                select(Vaga).where(Vaga.sessao_id == sessao.id, Vaga.inicio >= datetime.combine(inicio, datetime.min.time()))
            )
        }
        for ini, fim_ in desejadas.items():
            v = existentes.pop(ini.date(), None)
            if v is None:
                s.add(Vaga(sessao_id=sessao.id, inicio=ini, fim=fim_, capacidade=sessao.vagas))
                criadas += 1
            elif (v.inicio, v.fim, v.capacidade) != (ini, fim_, max(sessao.vagas, v.ocupadas)):
                v.inicio, v.fim, v.capacidade = ini, fim_, max(sessao.vagas, v.ocupadas)
                atualizadas += 1
        for v in existentes.values():  # datas que não existem mais (feriado novo, sessão desativada...)
            if not v.agendamentos:
                s.delete(v)
                removidas += 1
            elif not v.bloqueada:
                v.bloqueada = True
                v.motivo_bloqueio = "Sessão alterada/feriado — remarcar pacientes" if v.ativos else "Sem atendimento"
    s.flush()
    return {"vagas_criadas": criadas, "vagas_atualizadas": atualizadas, "vagas_removidas": removidas}


# ------------------------------------------------------------------ consulta
def vagas_disponiveis(
    s: Session,
    especialidade_id: int | None = None,
    turno: str = "qualquer",
    idade: int | None = None,
    a_partir: datetime | None = None,
    limite: int | None = None,
    turma: str | None = None,
) -> list[Vaga]:
    a_partir = a_partir or datetime.combine(
        config.agora().date() + timedelta(days=config.DIAS_ANTECEDENCIA_MIN), datetime.min.time()
    )
    q = (
        select(Vaga)
        .join(SessaoClinica)
        .where(Vaga.inicio >= a_partir, Vaga.ocupadas < Vaga.capacidade, Vaga.bloqueada.is_(False), SessaoClinica.ativa)
        .order_by(Vaga.inicio)
    )
    if especialidade_id:
        q = q.join(sessao_especialidade, sessao_especialidade.c.sessao_id == SessaoClinica.id).where(
            sessao_especialidade.c.especialidade_id == especialidade_id
        )
    if turma:
        q = q.where(SessaoClinica.turma == turma)
    vagas = [v for v in s.scalars(q.limit(500)) if v.sessao.aceita_idade(idade)]
    if turno != "qualquer":
        vagas = [v for v in vagas if v.turno == turno]
    return vagas[:limite] if limite else vagas


def especialidades_atendidas(s: Session, idade: int | None = None, so_bot: bool = False) -> list[Especialidade]:
    """Áreas que têm pelo menos uma sessão ativa que aceita essa idade."""
    sessoes = s.scalars(select(SessaoClinica).where(SessaoClinica.ativa)).all()
    ids = {e.id for se in sessoes if se.aceita_idade(idade) for e in se.especialidades}
    q = select(Especialidade).where(Especialidade.ativa, Especialidade.id.in_(ids))
    if so_bot:
        q = q.where(Especialidade.mostrar_no_bot)
    return list(s.scalars(q.order_by(Especialidade.codigo != "triagem", Especialidade.nome)))


# ------------------------------------------------------------------ ações
def agendar(
    s: Session,
    paciente: Paciente,
    vaga_id: int,
    especialidade_id: int | None = None,
    procedimento_id: int | None = None,
    queixa: str | None = None,
    origem: str = "bot",
    usuario: str | None = None,
    observacao: str | None = None,
    aluno: str | None = None,
    forcar: bool = False,
) -> Agendamento:
    """forcar=True deixa a recepção encaixar além do limite de vagas."""
    v = s.get(Vaga, vaga_id, with_for_update=True)
    if not v:
        raise VagaIndisponivel("Horário não encontrado.")
    if v.bloqueada:
        raise VagaIndisponivel(f"Este dia está bloqueado: {v.motivo_bloqueio or ''}")
    if v.ocupadas >= v.capacidade and not forcar:
        raise VagaIndisponivel("Não há mais vagas neste horário.")
    if any(a.paciente_id == paciente.id and a.status in STATUS_ATIVOS for a in v.agendamentos):
        raise VagaIndisponivel("Este paciente já está agendado neste horário.")
    v.ocupadas += 1
    ag = Agendamento(
        paciente_id=paciente.id,
        vaga_id=v.id,
        especialidade_id=especialidade_id,
        procedimento_id=procedimento_id,
        queixa=queixa,
        origem=origem,
        criado_por=usuario,
        observacao=observacao,
        aluno=aluno,
    )
    s.add(ag)
    s.flush()
    return ag


def cancelar(ag: Agendamento) -> None:
    if ag.status in STATUS_ATIVOS:
        ag.status = "cancelado"
        ag.vaga.ocupadas = max(0, ag.vaga.ocupadas - 1)


def mudar_status(ag: Agendamento, status: str) -> None:
    if status == "cancelado":
        cancelar(ag)
    elif ag.status != "cancelado" and status in ("agendado", "confirmado", "compareceu", "faltou"):
        ag.status = status


def agendamentos_futuros(s: Session, p: Paciente) -> list[Agendamento]:
    return list(
        s.scalars(
            select(Agendamento)
            .join(Vaga)
            .where(Agendamento.paciente_id == p.id, Agendamento.status.in_(STATUS_ATIVOS), Vaga.inicio >= config.agora())
            .order_by(Vaga.inicio)
        )
    )
