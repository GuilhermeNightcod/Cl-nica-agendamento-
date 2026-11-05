import hashlib
import hmac
import json

from fastapi.testclient import TestClient

from app.main import app, fila
from app.whatsapp import extrair_entradas, montar_payload
from app.mensagens import Botoes, Lista


def payload_texto(texto, msg_id="wamid.1"):
    return {"object": "whatsapp_business_account", "entry": [{"changes": [{"value": {
        "messaging_product": "whatsapp",
        "contacts": [{"wa_id": "5511912345678", "profile": {"name": "Carlos"}}],
        "messages": [{"from": "5511912345678", "id": msg_id, "type": "text", "text": {"body": texto}}],
    }}]}]}


def assinar(corpo: bytes) -> str:
    return "sha256=" + hmac.new(b"segredo", corpo, hashlib.sha256).hexdigest()


def test_verificacao_webhook():
    with TestClient(app) as c:
        r = c.get("/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "verifica123", "hub.challenge": "42"})
        assert r.status_code == 200 and r.text == "42"
        assert c.get("/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "x", "hub.challenge": "1"}).status_code == 403


def test_webhook_assinatura_e_processamento():
    corpo = json.dumps(payload_texto("oi")).encode()
    with TestClient(app) as c:
        assert c.post("/webhook", content=corpo, headers={"X-Hub-Signature-256": "sha256=errado"}).status_code == 401
        r = c.post("/webhook", content=corpo, headers={"X-Hub-Signature-256": assinar(corpo), "Content-Type": "application/json"})
        assert r.status_code == 200
        # mesma mensagem reenviada pela Meta não é processada duas vezes
        c.post("/webhook", content=corpo, headers={"X-Hub-Signature-256": assinar(corpo), "Content-Type": "application/json"})
        fila.aguardar()
        painel = c.get("/painel", auth=("coord", "senha"))
        assert painel.status_code == 200 and "Novos contatos" in painel.text
        assert c.get("/painel").status_code == 401
        assert c.get("/painel/agendamentos.csv", auth=("coord", "senha")).status_code == 200
    from sqlalchemy import func, select
    from app.db import sessao
    from app.models import Mensagem
    with sessao() as s:
        assert s.scalar(select(func.count()).select_from(Mensagem).where(Mensagem.direcao == "entrada")) == 1


def test_extrair_interativo():
    p = {"entry": [{"changes": [{"value": {"messages": [
        {"from": "55", "id": "a", "type": "interactive", "interactive": {"type": "list_reply", "list_reply": {"id": "menu:agendar", "title": "Agendar"}}},
        {"from": "55", "id": "b", "type": "button", "button": {"text": "Confirmo", "payload": "confirma:3"}},
    ]}}]}]}
    a, b = extrair_entradas(p)
    assert a.id_opcao == "menu:agendar" and b.id_opcao == "confirma:3"


def test_limites_do_whatsapp():
    pb = montar_payload("55", Botoes("x", [("a", "Um título muito comprido demais"), ("b", "b"), ("c", "c"), ("d", "d")]))
    botoes = pb["interactive"]["action"]["buttons"]
    assert len(botoes) == 3 and len(botoes[0]["reply"]["title"]) <= 20
    pl = montar_payload("55", Lista("x", "Ver", [(str(i), "t" * 30, "d" * 100) for i in range(12)]))
    rows = pl["interactive"]["action"]["sections"][0]["rows"]
    assert len(rows) == 10 and len(rows[0]["title"]) <= 24 and len(rows[0]["description"]) <= 72


def test_mensagens_rapidas_ficam_em_ordem():
    """Várias mensagens seguidas do mesmo paciente são processadas na ordem certa."""
    def ev(i, texto=None, opcao=None):
        m = {"from": "5511900001111", "id": f"wamid.ordem{i}"}
        if opcao:
            m |= {"type": "interactive", "interactive": {"type": "button_reply", "button_reply": {"id": opcao, "title": "x"}}}
        else:
            m |= {"type": "text", "text": {"body": texto}}
        corpo = json.dumps({"entry": [{"changes": [{"value": {"messages": [m]}}]}]}).encode()
        return corpo
    passos = [("oi", None), (None, "lgpd:sim"), (None, "menu:agendar"), ("Ana Lima", None), ("01/01/1990", None), ("canal", None)]
    with TestClient(app) as c:
        for i, (t, o) in enumerate(passos):
            corpo = ev(i, t, o)
            c.post("/webhook", content=corpo, headers={"X-Hub-Signature-256": assinar(corpo)})
        fila.aguardar()
    from sqlalchemy import select
    from app.db import sessao
    from app.models import Conversa
    with sessao() as s:
        conv = s.scalar(select(Conversa))
        assert conv.estado == "especialidade" and conv.contexto["queixa"] == "canal"
