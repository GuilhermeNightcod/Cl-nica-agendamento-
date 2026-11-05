"""
Área do aluno (feita para o celular).

  /aluno                         próximas clínicas da turma + meus pacientes
  /aluno/vaga/{id}               um dia de clínica: agendar paciente da dupla
  /aluno/agendamento/{id}        alterar horário/procedimento, remarcar, presença, cancelar
  /aluno/pacientes               pacientes da dupla
  /aluno/paciente/{id}           ficha do paciente da dupla (odontograma e prontuário)
"""
import re
from datetime import datetime, time, timedelta

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import or_, select

from .. import config
from ..agenda import STATUS_ATIVOS, VagaIndisponivel, agendar, cancelar, mudar_status
from ..db import sessao
from ..models import (
    DENTES_DECIDUOS, DENTES_PERMANENTES, REGIOES, STATUS_DENTE,
    Agendamento, Paciente, Procedimento, RegistroDente, SessaoClinica, Usuario, Vaga,
)
from . import rotas
from .rotas import (
    TIPOS_DOCUMENTO, data_ou_none, hora_ou_none, ids_da_dupla, int_ou_none, ir, montar_odontograma,
    normalizar_telefone, pode_ver_paciente, procedimentos_por_area, registrar_acesso, render, usuario,
)

router = APIRouter()
DIAS_A_FRENTE = 35


def aluno(u: dict = Depends(usuario)) -> dict:
    if u["papel"] != "aluno":
        raise rotas.Redirecionar("/agenda")
    if not u.get("turma"):
        raise HTTPException(403, "Seu usuário de aluno está sem turma. Peça à coordenação para informar.")
    return u


def _eu(s, u) -> Usuario:
    return s.get(Usuario, u["id"])


def _rotulo_dupla(eu: Usuario, parceiro: Usuario | None) -> str:
    return f"{eu.nome} e {parceiro.nome}" if parceiro else eu.nome


def _meus(s, u, vaga_id: int | None = None, futuros: bool = False) -> list[Agendamento]:
    ids = ids_da_dupla(u)
    q = select(Agendamento).join(Vaga).where(
        or_(Agendamento.aluno1_id.in_(ids), Agendamento.aluno2_id.in_(ids)), Agendamento.status != "cancelado")
    if vaga_id:
        q = q.where(Agendamento.vaga_id == vaga_id)
    if futuros:
        q = q.where(Vaga.inicio >= datetime.combine(config.agora().date(), time()))
    return sorted(s.scalars(q), key=lambda a: a.inicio)


def _vaga_da_turma(s, u, vid: int) -> Vaga:
    v = s.get(Vaga, vid)
    if not v or v.sessao.turma != u["turma"]:
        raise HTTPException(404, "Este dia de clínica não é da sua turma.")
    return v


def _meu_ag(s, u, ag_id: int) -> Agendamento:
    ag = s.get(Agendamento, ag_id)
    if not ag or not ({ag.aluno1_id, ag.aluno2_id} & ids_da_dupla(u)):
        raise HTTPException(404, "Agendamento não encontrado entre os pacientes da sua dupla.")
    return ag


def _proximas(s, u, dias: int = DIAS_A_FRENTE) -> list[Vaga]:
    hoje = datetime.combine(config.agora().date(), time())
    return list(s.scalars(
        select(Vaga).join(SessaoClinica)
        .where(SessaoClinica.turma == u["turma"], SessaoClinica.ativa, Vaga.inicio >= hoje,
               Vaga.inicio < hoje + timedelta(days=dias))
        .order_by(Vaga.inicio)))


def _pode_mexer(v: Vaga) -> bool:
    return v.inicio.date() >= config.agora().date()


# ------------------------------------------------------------------ início
@router.get("/aluno", response_class=HTMLResponse)
def inicio(request: Request, semanas: int = 2, u=Depends(aluno)):
    semanas = min(max(semanas, 1), 8)
    with sessao() as s:
        eu = _eu(s, u)
        parceiro = s.get(Usuario, eu.dupla_id) if eu.dupla_id else None
        colegas = s.scalars(select(Usuario).where(Usuario.papel == "aluno", Usuario.ativo, Usuario.turma == eu.turma,
                                                  Usuario.id != eu.id).order_by(Usuario.nome)).all()
        vagas = _proximas(s, u, dias=7 * semanas)
        meus = _meus(s, u, futuros=True)
        por_vaga = {}
        for a in meus:
            por_vaga.setdefault(a.vaga_id, []).append(a)
        return render(request, "aluno_inicio.html", eu=eu, parceiro=parceiro, colegas=colegas, vagas=vagas,
                      por_vaga=por_vaga, total_meus=len(meus), hoje=config.agora().date(), semanas=semanas)


@router.post("/aluno/dupla")
def escolher_dupla(dupla_id: str = Form(""), u=Depends(aluno)):
    with sessao() as s:
        eu = _eu(s, u)
        if not int_ou_none(dupla_id):
            if eu.dupla_id and (antigo := s.get(Usuario, eu.dupla_id)) and antigo.dupla_id == eu.id:
                antigo.dupla_id = None
            eu.dupla_id = None
            return ir("/aluno", msg="Você está sem dupla.")
        par = s.get(Usuario, int(dupla_id))
        if not par or par.papel != "aluno" or par.turma != eu.turma or par.id == eu.id:
            return ir("/aluno", erro="Escolha um colega da sua turma.")
        if par.dupla_id and par.dupla_id != eu.id:
            outro = s.get(Usuario, par.dupla_id)
            return ir("/aluno", erro=f"{par.nome} já está em dupla com {outro.nome if outro else 'outra pessoa'}.")
        if eu.dupla_id and eu.dupla_id != par.id and (antigo := s.get(Usuario, eu.dupla_id)) and antigo.dupla_id == eu.id:
            antigo.dupla_id = None
        eu.dupla_id, par.dupla_id = par.id, eu.id
        s.add(rotas.RegistroAcesso(usuario=eu.login, acao="formou dupla", detalhe=f"{eu.login} e {par.login}"))
    return ir("/aluno", msg=f"Dupla formada com {par.nome}.")


# ------------------------------------------------------------------ dia de clínica e agendar
def _buscar(s, termo: str) -> list[Paciente]:
    termo = (termo or "").strip()
    if len(termo) < 3:
        return []
    dig = re.sub(r"\D", "", termo)
    filtros = [Paciente.nome.ilike(f"%{termo}%")]
    if len(dig) >= 4:
        filtros.append(Paciente.telefone.contains(dig))
    return list(s.scalars(select(Paciente).where(or_(*filtros)).order_by(Paciente.nome).limit(10)))


@router.get("/aluno/vaga/{vid}", response_class=HTMLResponse)
def dia(request: Request, vid: int, busca: str = "", u=Depends(aluno)):
    with sessao() as s:
        v = _vaga_da_turma(s, u, vid)
        return render(request, "aluno_vaga.html", v=v, meus=_meus(s, u, vaga_id=v.id), busca=busca, busca_curta=0 < len(busca.strip()) < 3,
                      resultados=_buscar(s, busca), areas=procedimentos_por_area(s, v.sessao), pode=_pode_mexer(v))


@router.post("/aluno/vaga/{vid}/agendar")
def agendar_paciente(
    vid: int, paciente_id: str = Form(""), novo_nome: str = Form(""), novo_telefone: str = Form(""),
    novo_nascimento: str = Form(""), procedimento: str = Form(""), hora: str = Form(""), observacao: str = Form(""),
    avisar: str = Form(""), u=Depends(aluno),
):
    volta = f"/aluno/vaga/{vid}"
    with sessao() as s:
        v = _vaga_da_turma(s, u, vid)
        if not _pode_mexer(v):
            return ir(volta, erro="Esse dia já passou.")
        if int_ou_none(paciente_id):
            p = s.get(Paciente, int(paciente_id))
        elif novo_nome.strip():
            try:
                tel = normalizar_telefone(novo_telefone)
            except ValueError as e:
                return ir(volta, erro=str(e))
            if tel and s.scalar(select(Paciente).where(Paciente.telefone == tel)):
                return ir(volta, erro="Já existe paciente com esse WhatsApp. Busque pelo nome.")
            p = Paciente(nome=" ".join(novo_nome.split()).title(), telefone=tel, data_nascimento=data_ou_none(novo_nascimento))
            s.add(p)
            s.flush()
        else:
            return ir(volta, erro="Escolha um paciente da busca ou cadastre um novo.")
        if not p:
            raise HTTPException(404)
        if not v.sessao.aceita_idade(p.idade(v.inicio.date())):
            s.rollback()
            return ir(volta, erro=f"{p.nome_exibicao} está fora da faixa etária desta clínica ({v.sessao.faixa_etaria}). Fale com a recepção.")
        esp_id = proc_id = None
        if procedimento.startswith("proc:") and (pr := s.get(Procedimento, int(procedimento[5:]))):
            proc_id, esp_id = pr.id, pr.especialidade_id
        elif procedimento.startswith("esp:"):
            esp_id = int(procedimento[4:])
        elif v.sessao.especialidades:
            esp_id = v.sessao.especialidades[0].id
        eu = _eu(s, u)
        parceiro = s.get(Usuario, eu.dupla_id) if eu.dupla_id else None
        try:
            ag = agendar(s, p, v.id, especialidade_id=esp_id, procedimento_id=proc_id, origem="aluno", usuario=u["login"],
                         observacao=observacao.strip() or None, aluno=_rotulo_dupla(eu, parceiro))
        except VagaIndisponivel as e:
            s.rollback()
            return ir(volta, erro=f"{e} Se precisar de encaixe, fale com a recepção.")
        ag.aluno1_id, ag.aluno2_id = eu.id, parceiro.id if parceiro else None
        ag.hora = hora_ou_none(hora)
        registrar_acesso(s, u, "aluno agendou", p.id, f"{ag.descricao} {v.inicio:%d/%m/%Y}")
        aviso = rotas.servico.notificar_agendamento(s, ag) if (avisar and rotas.servico) else "Agendado."
    return ir(volta, msg=aviso)


# ------------------------------------------------------------------ alterar agendamento
@router.get("/aluno/agendamento/{ag_id}", response_class=HTMLResponse)
def ver_agendamento(request: Request, ag_id: int, u=Depends(aluno)):
    with sessao() as s:
        ag = _meu_ag(s, u, ag_id)
        idade = ag.paciente.idade()
        outras = [v for v in _proximas(s, u) if v.id != ag.vaga_id and v.livres > 0 and _pode_mexer(v)
                  and v.sessao.aceita_idade(idade)
                  and (not ag.especialidade_id or ag.especialidade_id in {e.id for e in v.sessao.especialidades})]
        return render(request, "aluno_agendamento.html", ag=ag, outras=outras[:12],
                      areas=procedimentos_por_area(s, ag.vaga.sessao), pode=_pode_mexer(ag.vaga))


@router.post("/aluno/agendamento/{ag_id}")
def alterar(ag_id: int, hora: str = Form(""), procedimento: str = Form(""), observacao: str = Form(""), u=Depends(aluno)):
    with sessao() as s:
        ag = _meu_ag(s, u, ag_id)
        ag.hora = hora_ou_none(hora)
        ag.observacao = observacao.strip() or None
        if procedimento.startswith("proc:") and (pr := s.get(Procedimento, int(procedimento[5:]))):
            ag.procedimento_id, ag.especialidade_id = pr.id, pr.especialidade_id
        elif procedimento.startswith("esp:"):
            ag.procedimento_id, ag.especialidade_id = None, int(procedimento[4:])
        registrar_acesso(s, u, "aluno alterou agendamento", ag.paciente_id, f"agendamento {ag.id}")
    return ir(f"/aluno/agendamento/{ag_id}", msg="Alterações salvas.")


@router.post("/aluno/agendamento/{ag_id}/status")
def status(ag_id: int, status: str = Form(...), u=Depends(aluno)):
    if status not in ("compareceu", "faltou", "cancelado", "confirmado"):
        raise HTTPException(400)
    with sessao() as s:
        ag = _meu_ag(s, u, ag_id)
        mudar_status(ag, status)
        registrar_acesso(s, u, f"aluno: {status}", ag.paciente_id, f"agendamento {ag.id}")
        vid = ag.vaga_id
    textos = {"compareceu": "Presença registrada.", "faltou": "Falta registrada.", "cancelado": "Consulta cancelada. A vaga foi liberada.",
              "confirmado": "Consulta confirmada."}
    return ir(f"/aluno/vaga/{vid}" if status == "cancelado" else f"/aluno/agendamento/{ag_id}", msg=textos[status])


@router.post("/aluno/agendamento/{ag_id}/remarcar")
def remarcar(ag_id: int, vaga_id: int = Form(...), u=Depends(aluno)):
    with sessao() as s:
        ag = _meu_ag(s, u, ag_id)
        nova = _vaga_da_turma(s, u, vaga_id)
        if not _pode_mexer(nova) or not nova.sessao.aceita_idade(ag.paciente.idade(nova.inicio.date())):
            return ir(f"/aluno/agendamento/{ag_id}", erro="Esse dia não serve para este paciente.")
        try:
            novo = agendar(s, ag.paciente, nova.id, especialidade_id=ag.especialidade_id, procedimento_id=ag.procedimento_id,
                           queixa=ag.queixa, origem="aluno", usuario=u["login"], observacao=ag.observacao, aluno=ag.aluno)
        except VagaIndisponivel as e:
            return ir(f"/aluno/agendamento/{ag_id}", erro=str(e))
        novo.aluno1_id, novo.aluno2_id = ag.aluno1_id, ag.aluno2_id
        cancelar(ag)
        registrar_acesso(s, u, "aluno remarcou", ag.paciente_id, f"{ag.vaga.inicio:%d/%m} → {nova.inicio:%d/%m}")
        novo_id = novo.id
    return ir(f"/aluno/agendamento/{novo_id}", msg=f"Remarcado para {nova.inicio:%d/%m}.")


# ------------------------------------------------------------------ pacientes da dupla
@router.get("/aluno/pacientes", response_class=HTMLResponse)
def pacientes(request: Request, u=Depends(aluno)):
    with sessao() as s:
        todos = _meus(s, u)
        por_pac: dict[int, dict] = {}
        agora = config.agora()
        for a in todos:
            d = por_pac.setdefault(a.paciente_id, {"p": a.paciente, "proxima": None, "ultima": None, "n": 0})
            d["n"] += 1
            if a.inicio >= agora and (not d["proxima"] or a.inicio < d["proxima"].inicio):
                d["proxima"] = a
            if a.inicio < agora and (not d["ultima"] or a.inicio > d["ultima"].inicio):
                d["ultima"] = a
        lista = sorted(por_pac.values(), key=lambda d: (d["proxima"] is None, d["proxima"].inicio if d["proxima"] else datetime.min))
        return render(request, "aluno_pacientes.html", lista=lista)


@router.get("/aluno/paciente/{pid}", response_class=HTMLResponse)
def paciente(request: Request, pid: int, u=Depends(aluno)):
    with sessao() as s:
        p = s.get(Paciente, pid)
        if not p or not pode_ver_paciente(s, u, pid):
            raise HTTPException(404, "Paciente não encontrado entre os pacientes da sua dupla.")
        registrar_acesso(s, u, "aluno abriu ficha", p.id)
        regs = s.scalars(select(RegistroDente).where(RegistroDente.paciente_id == p.id)
                         .order_by(RegistroDente.status != "aberto", RegistroDente.criado_em.desc())).all()
        idade = p.idade()
        return render(request, "aluno_paciente.html", p=p, ags=[a for a in _meus(s, u) if a.paciente_id == p.id],
                      regs=regs, odo=montar_odontograma(regs), arcadas_perm=DENTES_PERMANENTES, arcadas_dec=DENTES_DECIDUOS,
                      regioes=REGIOES, status_dente=STATUS_DENTE, areas=procedimentos_por_area(s),
                      aba_odonto="dec" if idade is not None and idade < 6 else "perm", tipos_dict=dict(TIPOS_DOCUMENTO))
