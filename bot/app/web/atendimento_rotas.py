"""
Central de atendimentos do WhatsApp (atendimento humano).

  /atendimentos                 caixa de entrada: abas Fila / Meus / Em atendimento / Bot / Finalizados
  /atendimentos/painel          tempo real por setor e por atendente (TME, TMA)
  /atendimentos/config          setores e etiquetas (coordenação)
"""
from datetime import datetime, time, timedelta

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import func, or_, select

from .. import atendimentos as A
from .. import config
from ..db import sessao
from ..models import Atendimento, Conversa, Etiqueta, Mensagem, Paciente, Setor, atendimento_etiqueta
from . import rotas
from .rotas import coordenacao, int_ou_none, ir, registrar_acesso, render, templates, usuario

router = APIRouter()
ABAS = [("fila", "Fila"), ("meus", "Meus"), ("todos", "Em atend."), ("bot", "Com o bot"), ("finalizados", "Finalizados")]


def ha_quanto(d: datetime | None) -> str:
    if not d:
        return ""
    seg = (config.agora() - d).total_seconds()
    if seg < 60:
        return "agora"
    if seg < 3600:
        return f"{int(seg // 60)} min"
    if seg < 86400:
        return f"{int(seg // 3600)} h"
    return f"{int(seg // 86400)} d"


def duracao(seg: float | None) -> str:
    if seg is None:
        return "—"
    seg = int(seg)
    d, resto = divmod(seg, 86400)
    h, resto = divmod(resto, 3600)
    m, s = divmod(resto, 60)
    return (f"{d}d " if d else "") + f"{h:02d}:{m:02d}:{s:02d}"


templates.env.filters["ha_quanto"] = ha_quanto
templates.env.filters["duracao"] = duracao


# ------------------------------------------------------------------ consultas
def _itens(s, u: dict, aba: str, busca: str, setor: str, etiqueta: str, agente: str) -> list[dict]:
    """Itens da lista à esquerda (um por paciente)."""
    termo = (busca or "").strip()
    if aba == "bot":
        q = (
            select(Conversa).join(Paciente)
            .where(Conversa.atendimento_humano.is_(False), Conversa.ultima_msg_paciente_em >= config.agora() - timedelta(hours=24))
            .order_by(Conversa.ultima_msg_paciente_em.desc()).limit(100)
        )
        if termo:
            q = q.where(or_(Paciente.nome.ilike(f"%{termo}%"), Paciente.nome_perfil.ilike(f"%{termo}%"), Paciente.telefone.contains(termo)))
        return [{"p": c.paciente, "at": None, "quando": c.ultima_msg_paciente_em, "estado": c.estado} for c in s.scalars(q)]

    q = select(Atendimento).join(Paciente)
    if aba == "fila":
        q = q.where(Atendimento.status == "fila").order_by(Atendimento.urgente.desc(), Atendimento.aberto_em)
    elif aba == "meus":
        q = q.where(Atendimento.status == "em_atendimento", Atendimento.assumido_por == u["login"]).order_by(Atendimento.ultima_msg_em.desc())
    elif aba == "finalizados":
        q = q.where(Atendimento.status == "finalizado").order_by(Atendimento.finalizado_em.desc())
    else:
        q = q.where(Atendimento.status == "em_atendimento").order_by(Atendimento.ultima_msg_em.desc())
    if int_ou_none(setor):
        q = q.where(Atendimento.setor_id == int(setor))
    if agente:
        q = q.where(Atendimento.assumido_por == agente)
    if int_ou_none(etiqueta):
        q = q.join(atendimento_etiqueta).where(atendimento_etiqueta.c.etiqueta_id == int(etiqueta))
    if termo:
        msgs = select(Mensagem.atendimento_id).where(Mensagem.conteudo.ilike(f"%{termo}%"))
        q = q.where(or_(Paciente.nome.ilike(f"%{termo}%"), Paciente.nome_perfil.ilike(f"%{termo}%"),
                        Paciente.telefone.contains(termo), Atendimento.id.in_(msgs)))
    return [{"p": a.paciente, "at": a, "quando": a.ultima_msg_em} for a in s.scalars(q.limit(150))]


def _ultima_msg(s, paciente_id: int) -> Mensagem | None:
    return s.scalar(select(Mensagem).where(Mensagem.paciente_id == paciente_id).order_by(Mensagem.id.desc()).limit(1))


def _contagens(s, u: dict) -> dict:
    c = dict(s.execute(select(Atendimento.status, func.count()).where(Atendimento.status != "finalizado").group_by(Atendimento.status)).all())
    meus = s.scalar(select(func.count(Atendimento.id)).where(Atendimento.status == "em_atendimento", Atendimento.assumido_por == u["login"]))
    return {"fila": c.get("fila", 0), "todos": c.get("em_atendimento", 0), "meus": meus or 0}


def _contexto_lista(s, u, aba, busca, setor, etiqueta, agente, selecionado) -> dict:
    itens = _itens(s, u, aba, busca, setor, etiqueta, agente)
    for it in itens:
        it["ultima"] = _ultima_msg(s, it["p"].id)
    return {"itens": itens, "aba": aba, "selecionado": selecionado}


def _contexto_chat(s, pid: int | None) -> dict:
    if not pid or not (p := s.get(Paciente, pid)):
        return {"cp": None}
    msgs = s.scalars(select(Mensagem).where(Mensagem.paciente_id == p.id).order_by(Mensagem.id.desc()).limit(200)).all()[::-1]
    at = A.aberto_do_paciente(s, p.id)
    if at and at.nao_lidas:
        at.nao_lidas = 0
    ultimo_at = at or s.scalar(select(Atendimento).where(Atendimento.paciente_id == p.id).order_by(Atendimento.id.desc()).limit(1))
    return {"cp": p, "msgs": msgs, "at": at, "ultimo_at": ultimo_at, "janela": A.janela_aberta(p.conversa),
            "prox_ags": [a for a in p.agendamentos if a.status in ("agendado", "confirmado") and a.vaga.inicio >= config.agora()]}


# ------------------------------------------------------------------ telas
@router.get("/atendimentos", response_class=HTMLResponse)
def caixa(request: Request, aba: str = "fila", busca: str = "", setor: str = "", etiqueta: str = "", agente: str = "",
          p: str = "", u=Depends(usuario)):
    aba = aba if aba in dict(ABAS) else "fila"
    pid = int_ou_none(p)
    with sessao() as s:
        if pid:
            registrar_acesso(s, u, "abriu conversa", pid)
        ctx = {
            **_contexto_lista(s, u, aba, busca, setor, etiqueta, agente, pid),
            **_contexto_chat(s, pid),
            "abas": ABAS, "contagens": _contagens(s, u), "busca": busca, "setor": setor, "etiqueta": etiqueta, "agente": agente,
            "setores": s.scalars(select(Setor).where(Setor.ativo).order_by(Setor.nome)).all(),
            "etiquetas": s.scalars(select(Etiqueta).order_by(Etiqueta.nome)).all(),
            "agentes": sorted(config.usuarios()),
            "filtros_ativos": sum(bool(x) for x in (setor, etiqueta, agente)),
        }
        return render(request, "atendimentos.html", **ctx)


@router.get("/atendimentos/_lista", response_class=HTMLResponse)
def fragmento_lista(request: Request, aba: str = "fila", busca: str = "", setor: str = "", etiqueta: str = "",
                    agente: str = "", p: str = "", u=Depends(usuario)):
    with sessao() as s:
        ctx = {**_contexto_lista(s, u, aba, busca, setor, etiqueta, agente, int_ou_none(p)), "contagens": _contagens(s, u),
               "busca": busca, "setor": setor, "etiqueta": etiqueta, "agente": agente}
        return templates.TemplateResponse(request, "_atend_lista.html", {"usuario": u, **ctx})


@router.get("/atendimentos/_mensagens/{pid}", response_class=HTMLResponse)
def fragmento_mensagens(request: Request, pid: int, u=Depends(usuario)):
    with sessao() as s:
        return templates.TemplateResponse(request, "_atend_mensagens.html", {"usuario": u, **_contexto_chat(s, pid)})


def _at(s, at_id: int) -> Atendimento:
    at = s.get(Atendimento, at_id)
    if not at:
        raise HTTPException(404)
    return at


def _volta(at: Atendimento, aba: str = "meus", **kw):
    return ir("/atendimentos", aba=aba, p=at.paciente_id, **kw)


@router.post("/atendimentos/proximo")
def pegar_proximo(setor: str = Form(""), u=Depends(usuario)):
    with sessao() as s:
        at = A.proximo_da_fila(s, u["login"], int_ou_none(setor))
        if not at:
            return ir("/atendimentos", aba="fila", msg="A fila está vazia. 🎉")
        return _volta(at)


@router.post("/atendimentos/{at_id}/assumir")
def assumir(at_id: int, u=Depends(usuario)):
    with sessao() as s:
        at = _at(s, at_id)
        A.assumir(at, u["login"])
        return _volta(at)


@router.post("/atendimentos/paciente/{pid}/abrir")
def abrir_para_paciente(pid: int, u=Depends(usuario)):
    """Atendente assume uma conversa que está com o bot, ou inicia contato com um paciente."""
    with sessao() as s:
        p = s.get(Paciente, pid)
        if not p or not p.telefone:
            return ir(f"/pacientes/{pid}", erro="Paciente sem WhatsApp cadastrado.")
        if not p.conversa:
            from ..fluxo import obter_paciente

            obter_paciente(s, p.telefone)
        at = A.abrir(s, p, f"Iniciado por {u['login']}", atendente=u["login"])
        registrar_acesso(s, u, "abriu atendimento", p.id)
        return _volta(at)


@router.post("/atendimentos/{at_id}/responder")
def responder(at_id: int, texto: str = Form(""), u=Depends(usuario)):
    with sessao() as s:
        at = _at(s, at_id)
        if not texto.strip():
            return _volta(at)
        try:
            A.responder(s, rotas.servico, at, u["login"], texto.strip()[:4000])
        except A.ForaDaJanela as e:
            return _volta(at, erro=str(e))
        return _volta(at)


@router.post("/atendimentos/{at_id}/modelo")
def modelo_contato(at_id: int, u=Depends(usuario)):
    with sessao() as s:
        at = _at(s, at_id)
        try:
            A.enviar_modelo_contato(s, rotas.servico, at, u["login"])
        except A.ForaDaJanela as e:
            return _volta(at, erro=str(e))
        return _volta(at, msg="Modelo enviado. Quando o paciente responder, a conversa reabre por 24h.")


@router.post("/atendimentos/{at_id}/transferir")
def transferir(at_id: int, setor_id: int = Form(...), u=Depends(usuario)):
    with sessao() as s:
        at = _at(s, at_id)
        A.transferir(at, setor_id)
        setor = s.get(Setor, setor_id)
        return _volta(at, aba="fila", msg=f"Transferido para {setor.nome if setor else 'outro setor'}.")


@router.post("/atendimentos/{at_id}/etiquetas")
async def etiquetas(request: Request, at_id: int, u=Depends(usuario)):
    ids = [int(x) for x in (await request.form()).getlist("etiquetas") if str(x).isdigit()]
    with sessao() as s:
        at = _at(s, at_id)
        at.etiquetas = list(s.scalars(select(Etiqueta).where(Etiqueta.id.in_(ids)))) if ids else []
        return _volta(at, aba="meus" if at.status == "em_atendimento" else at.status)


@router.post("/atendimentos/{at_id}/finalizar")
def finalizar(at_id: int, avisar: str = Form(""), u=Depends(usuario)):
    with sessao() as s:
        at = _at(s, at_id)
        A.finalizar(s, rotas.servico, at, u["login"], avisar=bool(avisar))
        return ir("/atendimentos", aba="meus", msg="Atendimento finalizado. O bot volta a responder este paciente.")


# ------------------------------------------------------------------ painel em tempo real
@router.get("/atendimentos/painel", response_class=HTMLResponse)
def painel_tempo_real(request: Request, u=Depends(usuario)):
    agora = config.agora()
    hoje = datetime.combine(agora.date(), time())
    with sessao() as s:
        setores = s.scalars(select(Setor).order_by(Setor.nome)).all()
        ats = s.scalars(select(Atendimento).where(or_(Atendimento.status != "finalizado", Atendimento.finalizado_em >= hoje))).all()

        def media(vals):
            vals = [v for v in vals if v is not None]
            return sum(vals) / len(vals) if vals else None

        def linha(grupo):
            return {
                "aguardando": sum(a.status == "fila" for a in grupo),
                "maior_espera": max(((agora - a.aberto_em).total_seconds() for a in grupo if a.status == "fila"), default=None),
                "tme": media([(a.assumido_em - a.aberto_em).total_seconds() for a in grupo if a.assumido_em and a.assumido_em >= hoje]),
                "em_atendimento": sum(a.status == "em_atendimento" for a in grupo),
                "tma": media([(a.finalizado_em - (a.assumido_em or a.aberto_em)).total_seconds() for a in grupo if a.finalizado_em]),
                "finalizados": sum(a.status == "finalizado" for a in grupo),
            }

        por_setor = [(st, linha([a for a in ats if a.setor_id == st.id])) for st in setores]
        sem_setor = [a for a in ats if a.setor_id is None]
        if sem_setor:
            por_setor.append((None, linha(sem_setor)))
        agentes = sorted({a.assumido_por for a in ats if a.assumido_por} | {a.finalizado_por for a in ats if a.finalizado_por})
        por_agente = [(ag, {
            "em_atendimento": sum(a.status == "em_atendimento" and a.assumido_por == ag for a in ats),
            "finalizados": sum(a.status == "finalizado" and a.finalizado_por == ag for a in ats),
            "tma": media([(a.finalizado_em - (a.assumido_em or a.aberto_em)).total_seconds() for a in ats if a.finalizado_em and a.finalizado_por == ag]),
        }) for ag in agentes]
        total = linha(ats)
        return render(request, "atend_painel.html", por_setor=por_setor, por_agente=por_agente, total=total, agora=agora)


# ------------------------------------------------------------------ configuração
@router.get("/atendimentos/config", response_class=HTMLResponse)
def config_atendimento(request: Request, u=Depends(coordenacao)):
    with sessao() as s:
        return render(request, "atend_config.html", setores=s.scalars(select(Setor).order_by(Setor.nome)).all(),
                      etiquetas=s.scalars(select(Etiqueta).order_by(Etiqueta.nome)).all())


@router.post("/atendimentos/config/setor")
def salvar_setor(nome: str = Form(...), cor: str = Form("#0f5c8c"), setor_id: str = Form(""), ativo: str = Form("1"),
                 padrao: str = Form(""), u=Depends(coordenacao)):
    with sessao() as s:
        st = s.get(Setor, int(setor_id)) if int_ou_none(setor_id) else Setor()
        st.nome, st.cor, st.ativo = nome.strip()[:60], cor, ativo == "1"
        if padrao:
            for outro in s.scalars(select(Setor)):
                outro.padrao = False
            st.padrao = True
        s.add(st)
    return ir("/atendimentos/config", msg="Setor salvo.")


@router.post("/atendimentos/config/etiqueta")
def salvar_etiqueta(nome: str = Form(...), cor: str = Form("#6b7280"), u=Depends(coordenacao)):
    with sessao() as s:
        if not s.scalar(select(Etiqueta).where(Etiqueta.nome == nome.strip())):
            s.add(Etiqueta(nome=nome.strip()[:40], cor=cor))
    return ir("/atendimentos/config", msg="Etiqueta criada.")


@router.post("/atendimentos/config/etiqueta/{eid}/excluir")
def excluir_etiqueta(eid: int, u=Depends(coordenacao)):
    with sessao() as s:
        if e := s.get(Etiqueta, eid):
            s.delete(e)
    return ir("/atendimentos/config", msg="Etiqueta excluída.")
