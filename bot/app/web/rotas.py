"""
Telas do sistema da clínica (recepção e coordenação).

  /agenda            agenda da semana, por turma
  /agenda/vaga/{id}  um dia de clínica: pacientes, presença, encaixe, bloqueio
  /agendar           encontrar horário para um procedimento
  /pacientes         busca, cadastro, ficha e prontuário digitalizado
  /espera            lista de espera
  /painel            indicadores
  /clinicas          configuração das sessões das turmas (coordenação)
"""
import csv
import io
import re
import secrets
import uuid
from datetime import date, datetime, time, timedelta
from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, or_, select

from .. import config, dados
from ..agenda import STATUS_ATIVOS, VagaIndisponivel, agendar, gerar_vagas, mudar_status, uso_de_boxes, vagas_disponiveis
from ..db import sessao
from ..fluxo import ESTADOS_AGENDAMENTO
from ..models import (
    DIAS_SEMANA,
    Agendamento,
    Atendimento,
    Conversa,
    Documento,
    EspacoClinico,
    Especialidade,
    ListaEspera,
    Paciente,
    Procedimento,
    DENTES_DECIDUOS,
    DENTES_PERMANENTES,
    REGIOES,
    STATUS_DENTE,
    RegistroAcesso,
    RegistroDente,
    Usuario,
    SessaoClinica,
    Vaga,
)

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))
templates.env.globals.update(DIAS_SEMANA=DIAS_SEMANA, config=config)


def formatar_telefone(tel: str | None) -> str:
    """'5511981234567' -> '(11) 98123-4567'"""
    if not tel:
        return ""
    d = tel[2:] if tel.startswith("55") and len(tel) >= 12 else tel
    if len(d) == 11:
        return f"({d[:2]}) {d[2:7]}-{d[7:]}"
    if len(d) == 10:
        return f"({d[:2]}) {d[2:6]}-{d[6:]}"
    return tel


templates.env.filters["fone"] = formatar_telefone
servico = None  # definido em main.py

TIPOS_DOCUMENTO = [
    ("anamnese", "Ficha de anamnese"),
    ("odontograma", "Odontograma / exame clínico"),
    ("plano", "Plano de tratamento"),
    ("evolucao", "Evolução / procedimentos realizados"),
    ("radiografia", "Radiografia"),
    ("termo", "Termo de consentimento"),
    ("documento", "Documento pessoal"),
    ("outro", "Outro"),
]
ASSINATURAS = {
    b"\xff\xd8\xff": ("image/jpeg", ".jpg"),
    b"\x89PNG": ("image/png", ".png"),
    b"%PDF": ("application/pdf", ".pdf"),
}


# ============================================================ login
class Redirecionar(HTTPException):
    def __init__(self, url: str):
        super().__init__(status_code=303, headers={"Location": url})


def usuario(request: Request) -> dict:
    u = request.session.get("usuario")
    if not u:
        raise Redirecionar("/entrar?" + urlencode({"voltar": str(request.url.path)}))
    # confere a cada acesso: usuário desativado ou com papel trocado vale na hora
    with sessao() as s:
        cad = s.scalar(select(Usuario).where(Usuario.login == u["login"]))
        if not cad or not cad.ativo:
            request.session.clear()
            raise Redirecionar("/entrar?" + urlencode({"erro": "Sua sessão foi encerrada. Entre novamente."}))
        u = {"id": cad.id, "login": cad.login, "papel": cad.papel, "nome": cad.nome, "trocar_senha": cad.trocar_senha,
             "turma": cad.turma, "dupla_id": cad.dupla_id}
    request.session["usuario"] = u
    if u["trocar_senha"] and request.url.path not in ("/minha-senha", "/sair"):
        raise Redirecionar("/minha-senha")
    return u


def equipe(u: dict = Depends(usuario)) -> dict:
    """Recepção e coordenação (alunos têm telas próprias em /aluno)."""
    if u["papel"] == "aluno":
        raise Redirecionar("/aluno")
    return u


def ids_da_dupla(u: dict) -> set[int]:
    return {i for i in (u.get("id"), u.get("dupla_id")) if i}


def pode_ver_paciente(s, u: dict, pid: int) -> bool:
    """Equipe vê todos. Aluno só vê pacientes que têm (ou tiveram) consulta com a sua dupla."""
    if u["papel"] != "aluno":
        return True
    ids = ids_da_dupla(u)
    return bool(s.scalar(select(Agendamento.id).where(
        Agendamento.paciente_id == pid, or_(Agendamento.aluno1_id.in_(ids), Agendamento.aluno2_id.in_(ids))).limit(1)))


def ficha_de(u: dict, pid: int) -> str:
    return f"/aluno/paciente/{pid}" if u["papel"] == "aluno" else f"/pacientes/{pid}"


def coordenacao(u: dict = Depends(usuario)) -> dict:
    if u["papel"] != "coordenacao":
        raise HTTPException(403, "Apenas a coordenação pode acessar esta tela.")
    return u


def registrar_acesso(s, u: dict, acao: str, paciente_id: int | None = None, detalhe: str | None = None) -> None:
    s.add(RegistroAcesso(usuario=u["login"], acao=acao, paciente_id=paciente_id, detalhe=(detalhe or "")[:300]))


def render(request: Request, nome: str, **ctx) -> HTMLResponse:
    ctx.setdefault("msg", request.query_params.get("msg"))
    ctx.setdefault("erro", request.query_params.get("erro"))
    if request.session.get("usuario") and "fila_count" not in ctx:
        with sessao() as s:
            ctx["fila_count"] = s.scalar(select(func.count(Atendimento.id)).where(Atendimento.status == "fila")) or 0
    return templates.TemplateResponse(request, nome, {"usuario": request.session.get("usuario"), **ctx})


def ir(url: str, **params) -> RedirectResponse:
    params = {k: v for k, v in params.items() if v}
    return RedirectResponse(url + ("?" + urlencode(params) if params else ""), status_code=303)


@router.get("/entrar", response_class=HTMLResponse)
def tela_entrar(request: Request, voltar: str = "/agenda"):
    return render(request, "entrar.html", voltar=voltar, sem_avisos=True)


@router.post("/entrar")
def entrar(request: Request, login: str = Form(...), senha: str = Form(...), voltar: str = Form("/agenda")):
    from ..usuarios import ErroUsuario, autenticar

    with sessao() as s:
        try:
            u = autenticar(s, login, senha)
        except ErroUsuario as e:
            erro = str(e)
            u = None
        if u:
            request.session["usuario"] = {"id": u.id, "login": u.login, "papel": u.papel, "nome": u.nome,
                                          "trocar_senha": u.trocar_senha, "turma": u.turma, "dupla_id": u.dupla_id}
            destino_padrao = "/aluno" if u.papel == "aluno" else "/agenda"
            s.add(RegistroAcesso(usuario=u.login, acao="entrou no sistema"))
    if not u:
        return ir("/entrar", erro=erro, voltar=voltar)
    if voltar in ("", "/agenda") or not voltar.startswith("/") or voltar.startswith("//"):
        voltar = destino_padrao
    return ir(voltar)


@router.get("/sair")
def sair(request: Request):
    request.session.clear()
    return ir("/entrar")


@router.get("/")
def inicio(request: Request):
    u = request.session.get("usuario") or {}
    return ir("/aluno" if u.get("papel") == "aluno" else "/agenda")


# ============================================================ utilidades
def normalizar_telefone(txt: str | None) -> str | None:
    """'(11) 98888-7777' -> '5511988887777' (formato do WhatsApp)."""
    digitos = re.sub(r"\D", "", txt or "")
    if not digitos:
        return None
    if len(digitos) in (10, 11):
        digitos = "55" + digitos
    if not (12 <= len(digitos) <= 13):
        raise ValueError("Telefone inválido. Use DDD + número, ex.: (11) 98888-7777")
    return digitos


def data_ou_none(txt: str | None) -> date | None:
    try:
        return date.fromisoformat(txt) if txt else None
    except ValueError:
        return None


def hora_ou_none(txt: str | None) -> time | None:
    try:
        return time.fromisoformat(txt) if txt else None
    except ValueError:
        return None


def int_ou_none(txt) -> int | None:
    return int(txt) if str(txt or "").strip().isdigit() else None


def segunda_da_semana(d: date) -> date:
    return d - timedelta(days=d.weekday())


def ordem_turma(nome: str) -> tuple:
    """'6º semestre' antes de '10º semestre' (ordem numérica, não alfabética)."""
    m = re.match(r"\s*(\d+)", nome or "")
    return (int(m.group(1)) if m else 999, nome)


def turmas(s) -> list[str]:
    return sorted(s.scalars(select(SessaoClinica.turma).distinct()), key=ordem_turma)


def buscar_pacientes(s, termo: str, limite: int = 30) -> list[Paciente]:
    termo = (termo or "").strip()
    if not termo:
        return []
    digitos = re.sub(r"\D", "", termo)
    filtros = [Paciente.nome.ilike(f"%{termo}%"), Paciente.nome_perfil.ilike(f"%{termo}%"), Paciente.numero_prontuario == termo]
    if len(digitos) >= 4:
        filtros += [Paciente.telefone.contains(digitos), Paciente.cpf.contains(digitos)]
    return list(s.scalars(select(Paciente).where(or_(*filtros)).order_by(Paciente.nome).limit(limite)))


def procedimentos_por_area(s, sessao_clinica: SessaoClinica | None = None) -> list[tuple[Especialidade, list[Procedimento]]]:
    areas = sessao_clinica.especialidades if sessao_clinica else s.scalars(
        select(Especialidade).where(Especialidade.ativa).order_by(Especialidade.nome)
    ).all()
    return [(e, list(e.procedimentos)) for e in areas]


# ============================================================ agenda
CORES_TURMA = ["#3557c9", "#2e8a6e", "#8e3f82", "#b5651d", "#4b6b2a", "#5b4fa8"]  # papel articular


def _layout_dia(vagas: list[Vaga]) -> list[tuple[Vaga, int, int]]:
    """Distribui clínicas que acontecem no mesmo horário lado a lado: (vaga, coluna, total de colunas)."""
    colunas: list[datetime] = []
    pos = []
    for v in sorted(vagas, key=lambda v: v.inicio):
        for i, fim in enumerate(colunas):
            if fim <= v.inicio:
                colunas[i] = v.fim
                pos.append((v, i))
                break
        else:
            colunas.append(v.fim)
            pos.append((v, len(colunas) - 1))
    return [(v, i, max(1, len(colunas))) for v, i in pos]


@router.get("/agenda", response_class=HTMLResponse)
def agenda(request: Request, semana: str = "", turma: str = "", professor: str = "", visao: str = "semana", u=Depends(equipe)):
    ref = data_ou_none(semana) or config.agora().date()
    seg = segunda_da_semana(ref)
    dias_vistos = [ref] if visao == "dia" else [seg + timedelta(days=i) for i in range(6)]
    with sessao() as s:
        q = (
            select(Vaga).join(SessaoClinica)
            .where(Vaga.inicio >= datetime.combine(dias_vistos[0], time()),
                   Vaga.inicio < datetime.combine(dias_vistos[-1] + timedelta(days=1), time()))
            .order_by(Vaga.inicio, SessaoClinica.turma)
        )
        if turma:
            q = q.where(SessaoClinica.turma == turma)
        if professor:
            q = q.where(SessaoClinica.professor == professor)
        vagas = s.scalars(q).all()
        lista_turmas = turmas(s)
        cores = {t: CORES_TURMA[i % len(CORES_TURMA)] for i, t in enumerate(lista_turmas)}
        if vagas:
            h_ini = min(v.inicio.hour for v in vagas)
            h_fim = max(v.fim.hour + (1 if v.fim.minute else 0) for v in vagas)
        else:
            h_ini, h_fim = 18, 23
        h_ini, h_fim = max(0, h_ini - 1), min(24, max(h_fim + 1, h_ini + 4))
        if visao != "dia" and not any(v.inicio.date() == dias_vistos[-1] for v in vagas):
            dias_vistos = dias_vistos[:5]  # sem clínica no sábado: mostra só seg–sex
        dias = [(d, _layout_dia([v for v in vagas if v.inicio.date() == d])) for d in dias_vistos]
        boxes_dia = {d: uso_de_boxes([v.sessao for v, _, _ in blocos if not v.bloqueada]) for d, blocos in dias}
        professores = sorted({p for p in s.scalars(select(SessaoClinica.professor).distinct()) if p})
        passo = timedelta(days=1 if visao == "dia" else 7)
        return render(
            request, "agenda.html", dias=dias, seg=seg, ref=ref, turma=turma, professor=professor, visao=visao,
            turmas=lista_turmas, professores=professores, cores=cores, hoje=config.agora().date(),
            anterior=ref - passo, proxima=ref + passo, boxes_dia=boxes_dia, h_ini=h_ini, h_fim=h_fim, px_hora=120 if visao == "dia" else 110,
        )


@router.get("/agenda/vaga/{vaga_id}", response_class=HTMLResponse)
def ver_vaga(request: Request, vaga_id: int, busca: str = "", u=Depends(equipe)):
    with sessao() as s:
        v = s.get(Vaga, vaga_id)
        if not v:
            raise HTTPException(404)
        lista_turmas = turmas(s)
        cor = CORES_TURMA[lista_turmas.index(v.sessao.turma) % len(CORES_TURMA)] if v.sessao.turma in lista_turmas else CORES_TURMA[0]
        return render(
            request, "vaga.html", v=v, busca=busca, resultados=buscar_pacientes(s, busca), cor_turma=cor,
            areas=procedimentos_por_area(s, v.sessao),
        )


@router.post("/agenda/vaga/{vaga_id}/agendar")
def agendar_na_vaga(
    vaga_id: int,
    paciente_id: str = Form(""),
    novo_nome: str = Form(""),
    novo_telefone: str = Form(""),
    novo_nascimento: str = Form(""),
    procedimento: str = Form(""),  # "proc:<id>" ou "esp:<id>"
    aluno: str = Form(""),
    observacao: str = Form(""),
    hora: str = Form(""),
    encaixe: str = Form(""),
    avisar: str = Form(""),
    espera_id: str = Form(""),
    voltar: str = Form(""),
    u=Depends(equipe),
):
    voltar = voltar if voltar.startswith("/") else f"/agenda/vaga/{vaga_id}"
    with sessao() as s:
        v = s.get(Vaga, vaga_id)
        if not v:
            raise HTTPException(404)
        # paciente existente ou novo cadastro rápido
        if int_ou_none(paciente_id):
            p = s.get(Paciente, int(paciente_id))
        elif novo_nome.strip():
            try:
                tel = normalizar_telefone(novo_telefone)
            except ValueError as e:
                return ir(voltar, erro=str(e))
            if tel and (existe := s.scalar(select(Paciente).where(Paciente.telefone == tel))):
                return ir(voltar, erro=f"Já existe paciente com esse telefone: {existe.nome_exibicao}. Busque pelo nome.")
            p = Paciente(nome=" ".join(novo_nome.split()).title(), telefone=tel, data_nascimento=data_ou_none(novo_nascimento))
            s.add(p)
            s.flush()
            registrar_acesso(s, u, "cadastrou paciente", p.id)
        else:
            return ir(voltar, erro="Escolha um paciente da busca ou preencha o nome do novo paciente.")
        if not p:
            raise HTTPException(404)

        esp_id = proc_id = None
        if procedimento.startswith("proc:"):
            proc = s.get(Procedimento, int(procedimento[5:]))
            proc_id, esp_id = proc.id, proc.especialidade_id
        elif procedimento.startswith("esp:"):
            esp_id = int(procedimento[4:])
        elif v.sessao.especialidades:
            esp_id = v.sessao.especialidades[0].id

        if not v.sessao.aceita_idade(p.idade(v.inicio.date())) and not encaixe:
            s.rollback()  # não deixa o cadastro novo pela metade
            return ir(voltar, erro=f"{p.nome_exibicao} ({p.idade()} anos) está fora da faixa etária desta clínica "
                                   f"({v.sessao.faixa_etaria}). Marque 'encaixe' para agendar mesmo assim.")
        try:
            ag = agendar(
                s, p, v.id, especialidade_id=esp_id, procedimento_id=proc_id, origem="recepcao", usuario=u["login"],
                observacao=observacao.strip() or None, aluno=aluno.strip() or None, forcar=bool(encaixe),
            )
        except VagaIndisponivel as e:
            s.rollback()
            return ir(voltar, erro=f"{e} Marque 'encaixe' para agendar além do limite." if "vagas" in str(e) else str(e))
        ag.hora = hora_ou_none(hora)
        if int_ou_none(espera_id) and (item := s.get(ListaEspera, int(espera_id))):
            item.status = "atendido"
        registrar_acesso(s, u, "agendou", p.id, f"{ag.descricao} {v.inicio:%d/%m/%Y %H:%M}")
        aviso = servico.notificar_agendamento(s, ag) if (avisar and servico) else "Agendado."
    return ir(f"/agenda/vaga/{vaga_id}", msg=aviso)


@router.post("/agenda/agendamento/{ag_id}/status")
def status_agendamento(ag_id: int, status: str = Form(...), voltar: str = Form(""), u=Depends(equipe)):
    with sessao() as s:
        ag = s.get(Agendamento, ag_id)
        if not ag:
            raise HTTPException(404)
        mudar_status(ag, status)
        registrar_acesso(s, u, f"status: {status}", ag.paciente_id, f"agendamento {ag.id}")
        vaga_id = ag.vaga_id
    return ir(voltar if voltar.startswith("/") else f"/agenda/vaga/{vaga_id}")


@router.post("/agenda/agendamento/{ag_id}/editar")
def editar_agendamento(ag_id: int, aluno: str = Form(""), observacao: str = Form(""), hora: str = Form(""), u=Depends(equipe)):
    with sessao() as s:
        ag = s.get(Agendamento, ag_id)
        if not ag:
            raise HTTPException(404)
        ag.aluno, ag.observacao = aluno.strip() or None, observacao.strip() or None
        ag.hora = hora_ou_none(hora)
        vaga_id = ag.vaga_id
    return ir(f"/agenda/vaga/{vaga_id}", msg="Salvo.")


@router.post("/agenda/vaga/{vaga_id}/bloqueio")
def bloquear_vaga(vaga_id: int, acao: str = Form(...), motivo: str = Form(""), u=Depends(equipe)):
    with sessao() as s:
        v = s.get(Vaga, vaga_id)
        if not v:
            raise HTTPException(404)
        v.bloqueada = acao == "bloquear"
        v.motivo_bloqueio = (motivo.strip() or "Sem atendimento") if v.bloqueada else None
        n = len([a for a in v.ativos if a.status in STATUS_ATIVOS])
    texto = f"Dia bloqueado. {n} paciente(s) precisam ser remarcados." if acao == "bloquear" and n else "Atualizado."
    return ir(f"/agenda/vaga/{vaga_id}", msg=texto)


@router.get("/agendar", response_class=HTMLResponse)
def encontrar_horario(
    request: Request, paciente_id: str = "", busca: str = "", procedimento: str = "", turma: str = "",
    turno: str = "qualquer", espera_id: str = "", u=Depends(equipe),
):
    with sessao() as s:
        p = s.get(Paciente, int(paciente_id)) if int_ou_none(paciente_id) else None
        esp_id = None
        if procedimento.startswith("proc:"):
            proc = s.get(Procedimento, int(procedimento[5:]))
            esp_id = proc.especialidade_id if proc else None
        elif procedimento.startswith("esp:"):
            esp_id = int(procedimento[4:])
        vagas = (
            vagas_disponiveis(
                s, esp_id, turno, idade=p.idade() if p else None, turma=turma or None,
                a_partir=datetime.combine(config.agora().date(), time()), limite=40,
            )
            if esp_id else []
        )
        return render(
            request, "agendar.html", p=p, busca=busca, resultados=buscar_pacientes(s, busca) if not p else [],
            procedimento=procedimento, areas=procedimentos_por_area(s), vagas=vagas, turma=turma, turmas=turmas(s),
            turno=turno, espera_id=espera_id,
        )


# ============================================================ pacientes
@router.get("/pacientes", response_class=HTMLResponse)
def pacientes(request: Request, busca: str = "", u=Depends(equipe)):
    with sessao() as s:
        lista = buscar_pacientes(s, busca, 100) if busca else list(
            s.scalars(select(Paciente).order_by(Paciente.criado_em.desc()).limit(50))
        )
        total = s.scalar(select(func.count(Paciente.id)))
        return render(request, "pacientes.html", lista=lista, busca=busca, total=total)


@router.get("/pacientes/novo", response_class=HTMLResponse)
def novo_paciente(request: Request, u=Depends(equipe)):
    return render(request, "paciente_form.html", p=None)


def _salvar_paciente(s, p: Paciente, nome, telefone, nascimento, cpf, numero_prontuario, observacoes) -> str | None:
    try:
        tel = normalizar_telefone(telefone)
    except ValueError as e:
        return str(e)
    if tel and (outro := s.scalar(select(Paciente).where(Paciente.telefone == tel, Paciente.id != (p.id or 0)))):
        return f"Este telefone já pertence a {outro.nome_exibicao} (ficha {outro.id})."
    if not nome.strip():
        return "Informe o nome."
    p.nome = " ".join(nome.split()).title()
    p.telefone = tel
    p.data_nascimento = data_ou_none(nascimento)
    p.cpf = re.sub(r"\D", "", cpf or "") or None
    p.numero_prontuario = numero_prontuario.strip() or None
    p.observacoes = observacoes.strip() or None
    return None


@router.post("/pacientes/novo")
def criar_paciente(
    nome: str = Form(""), telefone: str = Form(""), nascimento: str = Form(""), cpf: str = Form(""),
    numero_prontuario: str = Form(""), observacoes: str = Form(""), u=Depends(equipe),
):
    with sessao() as s:
        p = Paciente()
        if erro := _salvar_paciente(s, p, nome, telefone, nascimento, cpf, numero_prontuario, observacoes):
            return ir("/pacientes/novo", erro=erro)
        s.add(p)
        s.flush()
        registrar_acesso(s, u, "cadastrou paciente", p.id)
        pid = p.id
    return ir(f"/pacientes/{pid}", msg="Paciente cadastrado.")


@router.get("/pacientes/{pid:int}", response_class=HTMLResponse)
def ficha(request: Request, pid: int, u=Depends(equipe)):
    with sessao() as s:
        p = s.get(Paciente, pid)
        if not p:
            raise HTTPException(404)
        registrar_acesso(s, u, "abriu ficha", p.id)
        ags = s.scalars(select(Agendamento).join(Vaga).where(Agendamento.paciente_id == p.id).order_by(Vaga.inicio.desc())).all()
        espera = s.scalars(select(ListaEspera).where(ListaEspera.paciente_id == p.id, ListaEspera.status == "aguardando")).all()
        regs = s.scalars(select(RegistroDente).where(RegistroDente.paciente_id == p.id)
                         .order_by(RegistroDente.status != "aberto", RegistroDente.criado_em.desc())).all()
        idade = p.idade()
        return render(request, "paciente.html", p=p, ags=ags, espera=espera, tipos=TIPOS_DOCUMENTO,
                      tipos_dict=dict(TIPOS_DOCUMENTO), hoje=config.agora().date(),
                      regs=regs, odo=montar_odontograma(regs), arcadas_perm=DENTES_PERMANENTES, arcadas_dec=DENTES_DECIDUOS,
                      regioes=REGIOES, status_dente=STATUS_DENTE, areas=procedimentos_por_area(s),
                      aba_odonto="dec" if idade is not None and idade < 6 else "perm")


PRIORIDADE = {"ausente": 4, "aberto": 3, "finalizado": 2, "existente": 1}


def montar_odontograma(regs: list[RegistroDente]) -> dict:
    """{dente: {"status": ..., "faces": {"M": status}, "nota": bool, "n": quantidade}}"""
    odo: dict[str, dict] = {}
    for r in regs:
        d = odo.setdefault(r.dente, {"status": None, "faces": {}, "nota": False, "n": 0})
        d["n"] += 1
        d["nota"] = d["nota"] or bool(r.anotacao)
        if PRIORIDADE.get(r.status, 0) > PRIORIDADE.get(d["status"], 0):
            d["status"] = r.status
        for f in r.faces or "":
            if PRIORIDADE.get(r.status, 0) > PRIORIDADE.get(d["faces"].get(f), 0):
                d["faces"][f] = r.status
    return odo


@router.post("/pacientes/{pid:int}/odontograma")
def novo_registro_dente(
    pid: int, dente: str = Form(...), faces: list[str] = Form([]), procedimento: str = Form(""), descricao: str = Form(""),
    status: str = Form("aberto"), anotacao: str = Form(""), aluno: str = Form(""), u=Depends(usuario),
):
    validos = {str(n) for arc in DENTES_PERMANENTES + DENTES_DECIDUOS for n in arc} | set(REGIOES)
    if dente not in validos:
        return ir(ficha_de(u, pid), erro="Escolha um dente ou região no odontograma.")
    with sessao() as s:
        if not s.get(Paciente, pid) or not pode_ver_paciente(s, u, pid):
            raise HTTPException(404)
        if u["papel"] == "aluno" and not aluno.strip():
            aluno = u["nome"]
        proc = s.get(Procedimento, int(procedimento[5:])) if procedimento.startswith("proc:") else None
        texto = (descricao.strip() or (proc.nome if proc else "")).strip()
        if not texto and status != "ausente":
            return ir(ficha_de(u, pid), erro="Escolha o procedimento ou escreva a descrição.")
        r = RegistroDente(
            paciente_id=pid, dente=dente, faces="".join(f for f in "MODVL" if f in faces), procedimento_id=proc.id if proc else None,
            descricao=texto or "Ausente", status=status if status in STATUS_DENTE else "aberto", anotacao=anotacao.strip() or None,
            aluno=aluno.strip() or None, criado_por=u["login"], finalizado_em=config.agora() if status == "finalizado" else None,
        )
        s.add(r)
        registrar_acesso(s, u, "registrou no odontograma", pid, f"{r.local} {r.faces} {r.descricao}")
    return RedirectResponse(f"{ficha_de(u, pid)}?msg=Registrado+no+odontograma.#odontograma", status_code=303)


@router.post("/odontograma/{rid}/status")
def status_registro_dente(rid: int, status: str = Form(...), u=Depends(usuario)):
    with sessao() as s:
        r = s.get(RegistroDente, rid)
        if not r or status not in STATUS_DENTE or not pode_ver_paciente(s, u, r.paciente_id):
            raise HTTPException(404)
        r.status = status
        r.finalizado_em = config.agora() if status == "finalizado" else None
        registrar_acesso(s, u, f"odontograma: {status}", r.paciente_id, f"{r.local} {r.descricao}")
        pid = r.paciente_id
    return RedirectResponse(f"{ficha_de(u, pid)}#odontograma", status_code=303)


@router.post("/odontograma/{rid}/excluir")
def excluir_registro_dente(rid: int, u=Depends(usuario)):
    with sessao() as s:
        r = s.get(RegistroDente, rid)
        if not r:
            raise HTTPException(404)
        if u["papel"] != "coordenacao" and r.criado_por != u["login"]:
            raise HTTPException(403, "Só quem registrou ou a coordenação pode excluir.")
        pid = r.paciente_id
        registrar_acesso(s, u, "excluiu do odontograma", pid, f"{r.local} {r.descricao}")
        s.delete(r)
    return RedirectResponse(f"{ficha_de(u, pid)}#odontograma", status_code=303)


@router.post("/pacientes/{pid:int}")
def atualizar_paciente(
    pid: int, nome: str = Form(""), telefone: str = Form(""), nascimento: str = Form(""), cpf: str = Form(""),
    numero_prontuario: str = Form(""), observacoes: str = Form(""), u=Depends(equipe),
):
    with sessao() as s:
        p = s.get(Paciente, pid)
        if not p:
            raise HTTPException(404)
        if erro := _salvar_paciente(s, p, nome, telefone, nascimento, cpf, numero_prontuario, observacoes):
            return ir(f"/pacientes/{pid}", erro=erro)
        registrar_acesso(s, u, "editou ficha", p.id)
    return ir(f"/pacientes/{pid}", msg="Dados salvos.")


@router.post("/pacientes/{pid}/documentos")
async def enviar_documentos(
    pid: int, arquivos: list[UploadFile] = File(...), tipo: str = Form("outro"), data_documento: str = Form(""),
    descricao: str = Form(""), u=Depends(equipe),
):
    pasta = Path(config.ARQUIVOS_DIR) / "prontuarios" / str(pid)
    pasta.mkdir(parents=True, exist_ok=True)
    limite = config.TAMANHO_MAX_ARQUIVO_MB * 1024 * 1024
    salvos, recusados = 0, []
    with sessao() as s:
        if not s.get(Paciente, pid):
            raise HTTPException(404)
        for arq in arquivos:
            conteudo = await arq.read(limite + 1)
            if not conteudo:
                continue
            tipo_arq = next((t for assin, t in ASSINATURAS.items() if conteudo.startswith(assin)), None)
            if not tipo_arq or len(conteudo) > limite:
                recusados.append(arq.filename or "arquivo")
                continue
            nome_interno = uuid.uuid4().hex + tipo_arq[1]
            (pasta / nome_interno).write_bytes(conteudo)
            s.add(Documento(
                paciente_id=pid, tipo=tipo, descricao=descricao.strip() or None,
                data_documento=data_ou_none(data_documento) or config.agora().date(),
                arquivo=f"prontuarios/{pid}/{nome_interno}", nome_original=(arq.filename or nome_interno)[:200],
                tipo_arquivo=tipo_arq[0], tamanho=len(conteudo), enviado_por=u["login"],
            ))
            salvos += 1
        registrar_acesso(s, u, "anexou documentos", pid, f"{salvos} arquivo(s) - {tipo}")
    erro = f"Não aceito (use JPG, PNG ou PDF até {config.TAMANHO_MAX_ARQUIVO_MB} MB): {', '.join(recusados)}" if recusados else None
    return ir(f"/pacientes/{pid}", msg=f"{salvos} arquivo(s) anexado(s) ao prontuário." if salvos else None, erro=erro)


@router.get("/documentos/{doc_id}")
def ver_documento(doc_id: int, baixar: int = 0, u=Depends(usuario)):
    with sessao() as s:
        d = s.get(Documento, doc_id)
        if not d or not pode_ver_paciente(s, u, d.paciente_id):
            raise HTTPException(404)
        registrar_acesso(s, u, "viu documento", d.paciente_id, f"{d.tipo} #{d.id}")
        caminho = (Path(config.ARQUIVOS_DIR) / d.arquivo).resolve()
        if not caminho.is_relative_to(Path(config.ARQUIVOS_DIR).resolve()) or not caminho.exists():
            raise HTTPException(404, "Arquivo não encontrado no disco.")
        return FileResponse(
            caminho, media_type=d.tipo_arquivo, filename=d.nome_original,
            content_disposition_type="attachment" if baixar else "inline",
            headers={"Cache-Control": "private, no-store"},
        )


@router.post("/documentos/{doc_id}/excluir")
def excluir_documento(doc_id: int, u=Depends(coordenacao)):
    with sessao() as s:
        d = s.get(Documento, doc_id)
        if not d:
            raise HTTPException(404)
        pid = d.paciente_id
        (Path(config.ARQUIVOS_DIR) / d.arquivo).unlink(missing_ok=True)
        registrar_acesso(s, u, "excluiu documento", pid, f"{d.tipo} {d.nome_original}")
        s.delete(d)
    return ir(f"/pacientes/{pid}", msg="Documento excluído.")


# ============================================================ lista de espera
@router.get("/espera", response_class=HTMLResponse)
def lista_espera(request: Request, area: str = "", u=Depends(equipe)):
    with sessao() as s:
        q = select(ListaEspera).where(ListaEspera.status == "aguardando").order_by(ListaEspera.criado_em)
        if int_ou_none(area):
            q = q.where(ListaEspera.especialidade_id == int(area))
        areas = s.scalars(select(Especialidade).where(Especialidade.ativa).order_by(Especialidade.nome)).all()
        return render(request, "espera.html", itens=s.scalars(q).all(), areas=areas, area=area)


@router.post("/espera/{item_id}/resolver")
def espera_resolver(item_id: int, u=Depends(equipe)):
    with sessao() as s:
        if item := s.get(ListaEspera, item_id):
            item.status = "atendido"
    return ir("/espera", msg="Removido da lista de espera.")


# ============================================================ indicadores
def _indicadores(s) -> dict:
    agora = config.agora()
    d7, d30 = agora - timedelta(days=7), agora - timedelta(days=30)
    novos30 = s.scalar(select(func.count(Paciente.id)).where(Paciente.criado_em >= d30)) or 0
    com_ag30 = s.scalar(
        select(func.count(func.distinct(Agendamento.paciente_id))).join(Paciente).where(Paciente.criado_em >= d30)
    ) or 0
    contagem = dict(s.execute(
        select(Agendamento.status, func.count()).join(Vaga)
        .where(Vaga.inicio >= d30, Vaga.inicio < agora, Agendamento.status.in_(["compareceu", "faltou"]))
        .group_by(Agendamento.status)
    ).all())
    total = sum(contagem.values())
    ocupacao = s.execute(
        select(SessaoClinica.turma, SessaoClinica.dia_semana, SessaoClinica.nome, func.sum(Vaga.ocupadas), func.sum(Vaga.capacidade))
        .join(Vaga)
        .where(Vaga.inicio >= agora, Vaga.inicio < agora + timedelta(days=28), Vaga.bloqueada.is_(False))
        .group_by(SessaoClinica.id, SessaoClinica.turma, SessaoClinica.dia_semana, SessaoClinica.nome)
        .order_by(SessaoClinica.turma, SessaoClinica.dia_semana)
    ).all()
    por_origem = dict(s.execute(
        select(Agendamento.origem, func.count()).where(Agendamento.criado_em >= d30).group_by(Agendamento.origem)
    ).all())
    return {
        "contatos_7": s.scalar(select(func.count(Paciente.id)).where(Paciente.criado_em >= d7)) or 0,
        "contatos_30": novos30,
        "agendamentos_7": s.scalar(select(func.count(Agendamento.id)).where(Agendamento.criado_em >= d7)) or 0,
        "conversao": round(100 * com_ag30 / novos30) if novos30 else 0,
        "faltas_pct": round(100 * contagem.get("faltou", 0) / total) if total else 0,
        "ocupacao": [(t, DIAS_SEMANA[d], n, int(o or 0), int(c or 0)) for t, d, n, o, c in ocupacao],
        "pelo_bot": por_origem.get("bot", 0),
        "pela_recepcao": por_origem.get("recepcao", 0),
        "espera": s.scalar(select(func.count(ListaEspera.id)).where(ListaEspera.status == "aguardando")) or 0,
    }


@router.get("/painel", response_class=HTMLResponse)
def painel(request: Request, u=Depends(equipe)):
    with sessao() as s:
        agora = config.agora()
        humanos = s.scalars(select(Conversa).where(Conversa.atendimento_humano)).all()
        abandonos = s.scalars(
            select(Conversa)
            .where(Conversa.estado.in_(ESTADOS_AGENDAMENTO | {"recuperacao"}), Conversa.atendimento_humano.is_(False))
            .order_by(Conversa.atualizado_em.desc()).limit(50)
        ).all()
        remarcar = s.scalars(
            select(Agendamento).join(Vaga)
            .where(Vaga.bloqueada, Vaga.inicio >= agora, Agendamento.status.in_(STATUS_ATIVOS)).order_by(Vaga.inicio)
        ).all()
        return render(request, "painel.html", ind=_indicadores(s), humanos=humanos, abandonos=abandonos, remarcar=remarcar)


@router.get("/exportar/agendamentos.csv")
def exportar(u=Depends(equipe)):
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["data", "hora", "turma", "clinica", "professor", "procedimento", "paciente", "telefone",
                "nascimento", "prontuario", "aluno", "queixa", "observacao", "origem", "status"])
    with sessao() as s:
        registrar_acesso(s, u, "exportou agendamentos")
        for a in s.scalars(select(Agendamento).join(Vaga).order_by(Vaga.inicio)):
            p, v = a.paciente, a.vaga
            w.writerow([
                f"{v.inicio:%d/%m/%Y}", f"{v.inicio:%H:%M}", v.sessao.turma, v.sessao.nome, v.sessao.professor, a.descricao,
                p.nome_exibicao, p.telefone or "", f"{p.data_nascimento:%d/%m/%Y}" if p.data_nascimento else "",
                p.numero_prontuario or "", a.aluno or "", a.queixa or "", a.observacao or "", a.origem, a.status,
            ])
    return Response(
        "﻿" + buf.getvalue(), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename=agendamentos_{config.agora():%Y%m%d}.csv"},
    )


# ============================================================ configuração das clínicas
@router.get("/clinicas", response_class=HTMLResponse)
def clinicas(request: Request, u=Depends(coordenacao)):
    with sessao() as s:
        sessoes = s.scalars(select(SessaoClinica).order_by(SessaoClinica.turma, SessaoClinica.dia_semana, SessaoClinica.hora_inicio)).all()
        por_turma: dict[str, list] = {}
        for se in sessoes:
            por_turma.setdefault(se.turma, []).append(se)
        por_turma = dict(sorted(por_turma.items(), key=lambda kv: ordem_turma(kv[0])))
        espacos = s.scalars(select(EspacoClinico).order_by(EspacoClinico.nome)).all()
        return render(request, "clinicas.html", por_turma=por_turma, espacos=espacos, boxes=uso_de_boxes(list(sessoes)))


@router.post("/clinicas/espaco")
def salvar_espaco(nome: str = Form(...), boxes: str = Form(""), espaco_id: str = Form(""), u=Depends(coordenacao)):
    with sessao() as s:
        e = s.get(EspacoClinico, int(espaco_id)) if int_ou_none(espaco_id) else EspacoClinico()
        e.nome, e.boxes = nome.strip()[:80], int_ou_none(boxes)
        s.add(e)
    return ir("/clinicas", msg="Clínica física salva.")


@router.get("/clinicas/{sid:int}", response_class=HTMLResponse)
@router.get("/clinicas/nova", response_class=HTMLResponse)
def form_clinica(request: Request, sid: int | None = None, u=Depends(coordenacao)):
    with sessao() as s:
        se = s.get(SessaoClinica, sid) if sid else None
        if sid and not se:
            raise HTTPException(404)
        areas = s.scalars(select(Especialidade).where(Especialidade.ativa).order_by(Especialidade.nome)).all()
        return render(request, "clinica_form.html", se=se, areas=areas, turmas=turmas(s),
                      espacos=s.scalars(select(EspacoClinico).order_by(EspacoClinico.nome)).all(),
                      marcadas={e.id for e in se.especialidades} if se else set())


@router.post("/clinicas/{sid:int}")
@router.post("/clinicas/nova")
async def salvar_clinica(request: Request, sid: int | None = None, u=Depends(coordenacao)):
    f = await request.form()
    volta = f"/clinicas/{sid}" if sid else "/clinicas/nova"
    try:
        inicio, fim = time.fromisoformat(f["hora_inicio"]), time.fromisoformat(f["hora_fim"])
        dia = int(f["dia_semana"])
    except (KeyError, ValueError):
        return ir(volta, erro="Preencha dia e horários corretamente.")
    if fim <= inicio:
        return ir(volta, erro="O horário de fim precisa ser depois do início.")
    with sessao() as s:
        se = s.get(SessaoClinica, sid) if sid else SessaoClinica()
        area_ids = [int(x) for x in f.getlist("areas") if str(x).isdigit()]
        if not area_ids:
            return ir(volta, erro="Marque pelo menos uma área atendida.")
        if not str(f.get("turma", "")).strip():
            return ir(volta, erro="Informe a turma.")
        se.turma = str(f["turma"]).strip()
        se.nome = str(f.get("nome", "")).strip()
        se.dia_semana, se.hora_inicio, se.hora_fim = dia, inicio, fim
        se.professor = str(f.get("professor", "")).strip()
        se.procedimentos_texto = str(f.get("procedimentos_texto", "")).strip()
        se.vagas = max(1, int_ou_none(f.get("vagas")) or 1)
        se.alunos = int_ou_none(f.get("alunos"))
        se.pacientes_por_dupla = max(1, int_ou_none(f.get("pacientes_por_dupla")) or 1)
        se.recalcular_vagas()
        nome_espaco = str(f.get("espaco", "")).strip()
        if nome_espaco:
            esp = s.scalar(select(EspacoClinico).where(EspacoClinico.nome == nome_espaco))
            if not esp:
                esp = EspacoClinico(nome=nome_espaco[:80])
                s.add(esp)
            se.espaco = esp
        else:
            se.espaco = None
        se.idade_min, se.idade_max = int_ou_none(f.get("idade_min")), int_ou_none(f.get("idade_max"))
        se.ativa = f.get("ativa") == "1"
        se.especialidades = list(s.scalars(select(Especialidade).where(Especialidade.id.in_(area_ids))))
        s.add(se)
        s.flush()
        res = gerar_vagas(s, dados.feriados())
        registrar_acesso(s, u, "configurou clínica", None, f"{se.turma} {se.dia_nome} {se.horario}")
    return ir("/clinicas", msg=f"Salvo. Agenda atualizada: {res['vagas_criadas']} datas criadas, "
                               f"{res['vagas_atualizadas']} atualizadas, {res['vagas_removidas']} removidas.")


@router.post("/clinicas-gerar")
def gerar(u=Depends(coordenacao)):
    with sessao() as s:
        res = dados.carregar(s)
    return ir("/clinicas", msg=f"Agenda do semestre atualizada: {res['vagas_criadas']} datas criadas.")


@router.get("/acessos", response_class=HTMLResponse)
def acessos(request: Request, u=Depends(coordenacao)):
    with sessao() as s:
        regs = s.scalars(select(RegistroAcesso).order_by(RegistroAcesso.id.desc()).limit(300)).all()
        nomes = {p.id: p.nome_exibicao for p in s.scalars(select(Paciente).where(Paciente.id.in_({r.paciente_id for r in regs if r.paciente_id})))}
        return render(request, "acessos.html", regs=regs, nomes=nomes)
