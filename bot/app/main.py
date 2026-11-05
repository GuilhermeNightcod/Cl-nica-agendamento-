"""Servidor web do bot (FastAPI)."""
import asyncio
import csv
import io
import json
import logging
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import Depends, FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select

from . import config, dados
from .db import criar_tabelas, sessao
from .fila import FilaPorPaciente
from .fluxo import ESTADOS_AGENDAMENTO, cancelar_agendamento
from .models import Agendamento, Conversa, Especialidade, ListaEspera, Paciente, Vaga
from .servico import Servico
from .tarefas import rodar_tudo
from .whatsapp import assinatura_valida, extrair_entradas

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("main")
servico = Servico()


async def _loop_tarefas():
    while True:
        await asyncio.to_thread(rodar_tudo, servico)
        await asyncio.sleep(config.INTERVALO_TAREFAS_MIN * 60)


@asynccontextmanager
async def ciclo_de_vida(app: FastAPI):
    criar_tabelas()
    with sessao() as s:
        log.info("Dados carregados: %s", dados.carregar(s))
    tarefa = asyncio.create_task(_loop_tarefas())
    yield
    tarefa.cancel()


app = FastAPI(title="Central Odonto", lifespan=ciclo_de_vida)
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
basic = HTTPBasic()


@app.get("/saude")
def saude():
    return {"ok": True, "whatsapp_configurado": bool(config.WHATSAPP_TOKEN), "chatwoot": config.chatwoot_ativo()}


# ------------------------------------------------------------------ WhatsApp (Meta)
@app.get("/webhook")
def verificar_webhook(
    modo: str = Query("", alias="hub.mode"),
    token: str = Query("", alias="hub.verify_token"),
    desafio: str = Query("", alias="hub.challenge"),
):
    """A Meta chama este endereço uma vez para confirmar que o webhook é seu."""
    if modo == "subscribe" and secrets.compare_digest(token, config.WHATSAPP_VERIFY_TOKEN):
        return PlainTextResponse(desafio)
    raise HTTPException(403, "Token de verificação inválido")


def _processar_entrada(entrada) -> None:
    try:
        with sessao() as s:
            servico.receber(s, entrada)
    except Exception:
        log.exception("Erro ao processar mensagem de %s", entrada.telefone)


# Filas: as mensagens de um mesmo paciente são sempre processadas em ordem,
# uma de cada vez; pacientes diferentes são atendidos em paralelo.
fila = FilaPorPaciente(_processar_entrada, trabalhadores=4)


@app.post("/webhook")
async def receber_webhook(request: Request):
    corpo = await request.body()
    if not assinatura_valida(corpo, request.headers.get("X-Hub-Signature-256")):
        raise HTTPException(401, "Assinatura inválida")
    for entrada in extrair_entradas(json.loads(corpo or b"{}")):
        fila.adicionar(entrada.telefone, entrada)
    return {"ok": True}  # responder rápido; a Meta reenvia se demorar


# ------------------------------------------------------------------ Chatwoot
@app.post("/chatwoot/webhook")
async def webhook_chatwoot(request: Request, token: str = ""):
    if not secrets.compare_digest(token, config.CHATWOOT_WEBHOOK_TOKEN):
        raise HTTPException(403)
    evento = await request.json()
    with sessao() as s:
        servico.evento_chatwoot(s, evento)
    return {"ok": True}


# ------------------------------------------------------------------ Painel
def autenticar(cred: HTTPBasicCredentials = Depends(basic)) -> str:
    ok = secrets.compare_digest(cred.username, config.PAINEL_USUARIO) and secrets.compare_digest(
        cred.password, config.PAINEL_SENHA
    )
    if not ok:
        raise HTTPException(401, headers={"WWW-Authenticate": "Basic"})
    return cred.username


def _indicadores(s) -> dict:
    agora = config.agora()
    d7, d30 = agora - timedelta(days=7), agora - timedelta(days=30)
    novos30 = s.scalar(select(func.count(Paciente.id)).where(Paciente.criado_em >= d30)) or 0
    com_ag30 = s.scalar(
        select(func.count(func.distinct(Agendamento.paciente_id)))
        .join(Paciente)
        .where(Paciente.criado_em >= d30)
    ) or 0
    passados = s.execute(
        select(Agendamento.status, func.count())
        .join(Vaga)
        .where(Vaga.inicio >= d30, Vaga.inicio < agora, Agendamento.status.in_(["compareceu", "faltou"]))
        .group_by(Agendamento.status)
    ).all()
    contagem = dict(passados)
    total_passados = sum(contagem.values())
    ocupacao = s.execute(
        select(Especialidade.nome, func.sum(Vaga.ocupadas), func.sum(Vaga.capacidade))
        .join(Vaga)
        .where(Vaga.inicio >= agora, Vaga.inicio < agora + timedelta(days=28))
        .group_by(Especialidade.nome)
        .order_by(Especialidade.nome)
    ).all()
    espera = s.execute(
        select(Especialidade.nome, func.count(ListaEspera.id))
        .join(ListaEspera)
        .where(ListaEspera.status == "aguardando")
        .group_by(Especialidade.nome)
    ).all()
    return {
        "contatos_7": s.scalar(select(func.count(Paciente.id)).where(Paciente.criado_em >= d7)) or 0,
        "contatos_30": novos30,
        "agendamentos_7": s.scalar(select(func.count(Agendamento.id)).where(Agendamento.criado_em >= d7)) or 0,
        "conversao": round(100 * com_ag30 / novos30) if novos30 else 0,
        "faltas_pct": round(100 * contagem.get("faltou", 0) / total_passados) if total_passados else 0,
        "faltas": contagem.get("faltou", 0),
        "ocupacao": [(n, int(o or 0), int(c or 0)) for n, o, c in ocupacao],
        "espera": espera,
    }


@app.get("/painel", response_class=HTMLResponse)
def painel(request: Request, _: str = Depends(autenticar)):
    agora = config.agora()
    with sessao() as s:
        prox = s.scalars(
            select(Agendamento)
            .join(Vaga)
            .where(Vaga.inicio >= agora - timedelta(days=2), Agendamento.status != "cancelado")
            .order_by(Vaga.inicio)
            .limit(100)
        ).all()
        humanos = s.scalars(select(Conversa).where(Conversa.atendimento_humano)).all()
        abandonos = s.scalars(
            select(Conversa)
            .where(Conversa.estado.in_(ESTADOS_AGENDAMENTO | {"recuperacao"}), Conversa.atendimento_humano.is_(False))
            .order_by(Conversa.atualizado_em.desc())
            .limit(50)
        ).all()
        espera = s.scalars(
            select(ListaEspera).where(ListaEspera.status == "aguardando").order_by(ListaEspera.criado_em).limit(100)
        ).all()
        return templates.TemplateResponse(
            request,
            "painel.html",
            {
                "ind": _indicadores(s),
                "prox": prox,
                "humanos": humanos,
                "abandonos": abandonos,
                "espera": espera,
                "agora": agora,
                "clinica": config.NOME_CLINICA,
            },
        )


@app.post("/painel/agendamento/{ag_id}")
def mudar_status(ag_id: int, status: str = Form(...), _: str = Depends(autenticar)):
    if status not in ("compareceu", "faltou", "cancelado", "confirmado"):
        raise HTTPException(400)
    with sessao() as s:
        ag = s.get(Agendamento, ag_id)
        if not ag:
            raise HTTPException(404)
        if status == "cancelado":
            cancelar_agendamento(ag)
        else:
            ag.status = status
    return RedirectResponse("/painel", status_code=303)


@app.post("/painel/espera/{item_id}")
def espera_atendido(item_id: int, _: str = Depends(autenticar)):
    with sessao() as s:
        item = s.get(ListaEspera, item_id)
        if item:
            item.status = "atendido"
    return RedirectResponse("/painel", status_code=303)


@app.post("/painel/recarregar-agenda")
def recarregar(_: str = Depends(autenticar)):
    with sessao() as s:
        log.info("Agenda recarregada: %s", dados.carregar(s))
    return RedirectResponse("/painel", status_code=303)


@app.get("/painel/agendamentos.csv")
def exportar(_: str = Depends(autenticar)):
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["data", "hora", "especialidade", "paciente", "telefone", "nascimento", "queixa", "status"])
    with sessao() as s:
        for a in s.scalars(select(Agendamento).join(Vaga).order_by(Vaga.inicio)):
            p, v = a.paciente, a.vaga
            w.writerow([
                f"{v.inicio:%d/%m/%Y}", f"{v.inicio:%H:%M}", v.especialidade.nome, p.nome, p.telefone,
                f"{p.data_nascimento:%d/%m/%Y}" if p.data_nascimento else "", a.queixa or "", a.status,
            ])
    return Response(
        "﻿" + buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename=agendamentos_{datetime.now():%Y%m%d}.csv"},
    )
