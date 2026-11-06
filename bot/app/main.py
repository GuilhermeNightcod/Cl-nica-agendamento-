"""Servidor web: webhooks (WhatsApp/Chatwoot) + sistema da clínica."""
import asyncio
import json
import logging
import secrets
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from starlette.middleware.sessions import SessionMiddleware

from . import config, dados
from .db import criar_tabelas, sessao
from .fila import FilaPorPaciente
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
        from .usuarios import criar_iniciais

        if n := criar_iniciais(s):
            log.info("Criados %s usuários iniciais a partir de USUARIOS do .env", n)
    tarefa = asyncio.create_task(_loop_tarefas())
    yield
    tarefa.cancel()


app = FastAPI(title="centralodonto", lifespan=ciclo_de_vida)
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")
app.add_middleware(SessionMiddleware, secret_key=config.CHAVE_SESSAO, max_age=12 * 3600, same_site="lax",
                   https_only=config.COOKIE_SEGURO)


@app.middleware("http")
async def cabecalhos_de_seguranca(request, call_next):
    resp = await call_next(request)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Referrer-Policy", "same-origin")
    if config.COOKIE_SEGURO:
        resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
    return resp


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


# Mensagens de um mesmo paciente são processadas em ordem; pacientes diferentes em paralelo.
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


# ------------------------------------------------------------------ Sistema da clínica
from .web import aluno_rotas, atendimento_rotas, professor_rotas, rotas, usuario_rotas  # noqa: E402

rotas.servico = servico
app.include_router(aluno_rotas.router)
app.include_router(professor_rotas.router)
app.include_router(usuario_rotas.router)
app.include_router(atendimento_rotas.router)
app.include_router(rotas.router)
