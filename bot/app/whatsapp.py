"""Comunicação com a WhatsApp Cloud API (API oficial da Meta)."""
import hashlib
import hmac
import logging

import httpx

from . import config
from .mensagens import Botoes, Entrada, Lista, Modelo, Resposta, Texto

log = logging.getLogger("whatsapp")


def _corta(texto: str, limite: int) -> str:
    return texto if len(texto) <= limite else texto[: limite - 1] + "…"


def montar_payload(telefone: str, r: Resposta) -> dict:
    base = {"messaging_product": "whatsapp", "recipient_type": "individual", "to": telefone}
    if isinstance(r, Texto):
        return {**base, "type": "text", "text": {"body": r.texto, "preview_url": False}}
    if isinstance(r, Botoes):
        return {
            **base,
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {"text": _corta(r.texto, 1024)},
                "action": {
                    "buttons": [
                        {"type": "reply", "reply": {"id": i, "title": _corta(t, 20)}}
                        for i, t in r.opcoes[:3]
                    ]
                },
            },
        }
    if isinstance(r, Lista):
        return {
            **base,
            "type": "interactive",
            "interactive": {
                "type": "list",
                "body": {"text": _corta(r.texto, 4096)},
                "action": {
                    "button": _corta(r.botao, 20),
                    "sections": [
                        {
                            "title": "Opções",
                            "rows": [
                                {"id": i, "title": _corta(t, 24), "description": _corta(d, 72)}
                                for i, t, d in r.opcoes[:10]
                            ],
                        }
                    ],
                },
            },
        }
    if isinstance(r, Modelo):
        tpl: dict = {"name": r.nome, "language": {"code": config.TEMPLATE_IDIOMA}}
        componentes: list[dict] = []
        if r.parametros:
            componentes.append(
                {"type": "body", "parameters": [{"type": "text", "text": p} for p in r.parametros]}
            )
        for i, payload in enumerate(r.payloads_botoes):
            componentes.append(
                {
                    "type": "button",
                    "sub_type": "quick_reply",
                    "index": str(i),
                    "parameters": [{"type": "payload", "payload": payload}],
                }
            )
        if componentes:
            tpl["components"] = componentes
        return {**base, "type": "template", "template": tpl}
    raise TypeError(f"Tipo de mensagem desconhecido: {r!r}")


class ClienteWhatsApp:
    def enviar(self, telefone: str, r: Resposta) -> None:
        if not (config.WHATSAPP_TOKEN and config.WHATSAPP_PHONE_NUMBER_ID):
            log.warning("WhatsApp não configurado; mensagem não enviada para %s", telefone)
            return
        url = (
            f"https://graph.facebook.com/{config.WHATSAPP_API_VERSION}/"
            f"{config.WHATSAPP_PHONE_NUMBER_ID}/messages"
        )
        resp = httpx.post(
            url,
            json=montar_payload(telefone, r),
            headers={"Authorization": f"Bearer {config.WHATSAPP_TOKEN}"},
            timeout=15,
        )
        if resp.status_code >= 400:
            log.error("Erro ao enviar para %s: %s %s", telefone, resp.status_code, resp.text)
            resp.raise_for_status()


def assinatura_valida(corpo: bytes, cabecalho: str | None) -> bool:
    """Confere se a requisição veio mesmo da Meta (cabeçalho X-Hub-Signature-256)."""
    if not config.WHATSAPP_APP_SECRET:
        return True  # sem segredo configurado (modo de teste)
    if not cabecalho or not cabecalho.startswith("sha256="):
        return False
    esperado = hmac.new(config.WHATSAPP_APP_SECRET.encode(), corpo, hashlib.sha256).hexdigest()
    return hmac.compare_digest(esperado, cabecalho.removeprefix("sha256="))


def extrair_entradas(payload: dict) -> list[Entrada]:
    """Transforma o JSON do webhook da Meta em uma lista de Entrada."""
    entradas: list[Entrada] = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            valor = change.get("value", {})
            nomes = {
                c.get("wa_id"): c.get("profile", {}).get("name") for c in valor.get("contacts", [])
            }
            for m in valor.get("messages", []):
                tipo = m.get("type", "")
                e = Entrada(
                    telefone=m.get("from", ""),
                    tipo=tipo,
                    nome_perfil=nomes.get(m.get("from")),
                    wa_message_id=m.get("id"),
                )
                if tipo == "text":
                    e.texto = m.get("text", {}).get("body", "")
                elif tipo == "interactive":
                    inter = m.get("interactive", {})
                    escolha = inter.get("button_reply") or inter.get("list_reply") or {}
                    e.id_opcao = escolha.get("id")
                    e.texto = escolha.get("title", "")
                elif tipo == "button":  # botão de resposta rápida de um template
                    e.texto = m.get("button", {}).get("text", "")
                    e.id_opcao = m.get("button", {}).get("payload") or None
                entradas.append(e)
    return entradas
