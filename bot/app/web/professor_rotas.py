"""
Área do professor (celular ou computador).

  /professor                 próximos dias das clínicas que supervisiona (todas as turmas)
  /professor/vaga/{id}       pacientes do dia: dupla, procedimento, horário, presença
  /professor/paciente/{id}   ficha, odontograma e prontuário (pacientes das suas clínicas)
"""
from datetime import datetime, time, timedelta

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select

from .. import config
from ..agenda import mudar_status
from ..db import sessao
from ..models import DENTES_DECIDUOS, DENTES_PERMANENTES, REGIOES, STATUS_DENTE, Agendamento, Paciente, RegistroDente, SessaoClinica, Vaga
from . import rotas
from .rotas import (
    CORES_TURMA, TIPOS_DOCUMENTO, ir, montar_odontograma, pode_ver_paciente, procedimentos_por_area, registrar_acesso, render,
    turmas, usuario,
)

router = APIRouter()


def professor(u: dict = Depends(usuario)) -> dict:
    if u["papel"] != "professor":
        raise rotas.Redirecionar(rotas.AREA_PROPRIA.get(u["papel"], "/agenda"))
    if not u.get("nome_grade"):
        raise HTTPException(403, "Seu usuário de professor não está ligado a nenhuma clínica. Peça à coordenação.")
    return u


def _minha_vaga(s, u, vid: int) -> Vaga:
    v = s.get(Vaga, vid)
    if not v or v.sessao.professor != u["nome_grade"]:
        raise HTTPException(404, "Este dia não é de uma clínica que você supervisiona.")
    return v


def _cores(s) -> dict:
    return {t: CORES_TURMA[i % len(CORES_TURMA)] for i, t in enumerate(turmas(s))}


@router.get("/professor", response_class=HTMLResponse)
def inicio(request: Request, semanas: int = 2, u=Depends(professor)):
    semanas = min(max(semanas, 1), 8)
    hoje = datetime.combine(config.agora().date(), time())
    with sessao() as s:
        vagas = s.scalars(
            select(Vaga).join(SessaoClinica)
            .where(SessaoClinica.professor == u["nome_grade"], SessaoClinica.ativa, Vaga.inicio >= hoje,
                   Vaga.inicio < hoje + timedelta(days=7 * semanas))
            .order_by(Vaga.inicio)).all()
        clinicas = s.scalars(select(SessaoClinica).where(SessaoClinica.professor == u["nome_grade"], SessaoClinica.ativa)
                             .order_by(SessaoClinica.dia_semana, SessaoClinica.hora_inicio)).all()
        return render(request, "professor_inicio.html", vagas=vagas, clinicas=clinicas, semanas=semanas,
                      hoje=config.agora().date(), cores=_cores(s))


@router.get("/professor/vaga/{vid}", response_class=HTMLResponse)
def dia(request: Request, vid: int, u=Depends(professor)):
    with sessao() as s:
        v = _minha_vaga(s, u, vid)
        registrar_acesso(s, u, "professor abriu lista do dia", None, f"{v.sessao.turma} {v.inicio:%d/%m/%Y}")
        return render(request, "professor_vaga.html", v=v, ags=sorted(v.ativos, key=lambda a: a.inicio),
                      cor=_cores(s).get(v.sessao.turma, CORES_TURMA[0]))


@router.post("/professor/agendamento/{ag_id}/status")
def status(ag_id: int, status: str = Form(...), u=Depends(professor)):
    if status not in ("compareceu", "faltou"):
        raise HTTPException(400)
    with sessao() as s:
        ag = s.get(Agendamento, ag_id)
        if not ag:
            raise HTTPException(404)
        _minha_vaga(s, u, ag.vaga_id)
        mudar_status(ag, status)
        registrar_acesso(s, u, f"professor: {status}", ag.paciente_id, f"agendamento {ag.id}")
        vid = ag.vaga_id
    return ir(f"/professor/vaga/{vid}", msg="Presença registrada." if status == "compareceu" else "Falta registrada.")


@router.get("/professor/paciente/{pid}", response_class=HTMLResponse)
def paciente(request: Request, pid: int, u=Depends(professor)):
    with sessao() as s:
        p = s.get(Paciente, pid)
        if not p or not pode_ver_paciente(s, u, pid):
            raise HTTPException(404, "Paciente não encontrado nas suas clínicas.")
        registrar_acesso(s, u, "professor abriu ficha", p.id)
        ags = s.scalars(select(Agendamento).join(Vaga).join(SessaoClinica)
                        .where(Agendamento.paciente_id == p.id, SessaoClinica.professor == u["nome_grade"])
                        .order_by(Vaga.inicio.desc())).all()
        regs = s.scalars(select(RegistroDente).where(RegistroDente.paciente_id == p.id)
                         .order_by(RegistroDente.status != "aberto", RegistroDente.criado_em.desc())).all()
        idade = p.idade()
        return render(request, "professor_paciente.html", p=p, ags=ags, regs=regs, odo=montar_odontograma(regs),
                      arcadas_perm=DENTES_PERMANENTES, arcadas_dec=DENTES_DECIDUOS, regioes=REGIOES, status_dente=STATUS_DENTE,
                      areas=procedimentos_por_area(s), aba_odonto="dec" if idade is not None and idade < 6 else "perm",
                      tipos_dict=dict(TIPOS_DOCUMENTO))
