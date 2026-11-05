"""
Integração com o Chatwoot (caixa de atendimento humano, código aberto).

Como funciona:
  * Quando o bot passa o paciente para um humano, criamos (ou reabrimos) uma
    conversa no Chatwoot, numa caixa do tipo "API", com um resumo do caso.
  * Enquanto o paciente estiver com humano, cada mensagem dele é copiada para lá.
  * Quando o atendente responde no Chatwoot, o Chatwoot avisa o bot (webhook)
    e o bot envia a resposta pelo WhatsApp.
  * Quando o atendente marca a conversa como "Resolvida", o bot volta a atender.
"""
import logging

import httpx

from . import config
from .models import Paciente

log = logging.getLogger("chatwoot")


class ClienteChatwoot:
    def __init__(self) -> None:
        self.base = f"{config.CHATWOOT_URL}/api/v1/accounts/{config.CHATWOOT_ACCOUNT_ID}"
        self.headers = {"api_access_token": config.CHATWOOT_API_TOKEN}

    def _req(self, metodo: str, caminho: str, **kw) -> dict:
        r = httpx.request(metodo, self.base + caminho, headers=self.headers, timeout=15, **kw)
        if r.status_code >= 400:
            log.error("Chatwoot %s %s -> %s %s", metodo, caminho, r.status_code, r.text[:300])
            r.raise_for_status()
        return r.json() if r.content else {}

    def _contato(self, p: Paciente) -> tuple[int, str]:
        """Retorna (contact_id, source_id) do paciente na caixa de entrada."""
        busca = self._req("GET", "/contacts/search", params={"q": p.telefone})
        for c in busca.get("payload", []):
            if c.get("identifier") == p.telefone or (c.get("phone_number") or "").lstrip("+") == p.telefone:
                for ci in c.get("contact_inboxes", []):
                    if str(ci.get("inbox", {}).get("id")) == str(config.CHATWOOT_INBOX_ID):
                        return c["id"], ci["source_id"]
                ci = self._req(
                    "POST", f"/contacts/{c['id']}/contact_inboxes", json={"inbox_id": int(config.CHATWOOT_INBOX_ID)}
                )
                return c["id"], ci["source_id"]
        novo = self._req(
            "POST",
            "/contacts",
            json={
                "inbox_id": int(config.CHATWOOT_INBOX_ID),
                "name": p.nome or p.nome_perfil or p.telefone,
                "phone_number": f"+{p.telefone}",
                "identifier": p.telefone,
            },
        )
        contato = novo.get("payload", {}).get("contact", novo.get("payload", novo))
        return contato["id"], contato["contact_inboxes"][0]["source_id"]

    def abrir_conversa(self, p: Paciente, resumo: str) -> int:
        contact_id, source_id = self._contato(p)
        conv = self._req(
            "POST",
            "/conversations",
            json={
                "source_id": source_id,
                "inbox_id": int(config.CHATWOOT_INBOX_ID),
                "contact_id": contact_id,
                "status": "open",
            },
        )
        self.nota_privada(conv["id"], resumo)
        return conv["id"]

    def mensagem_do_paciente(self, conversa_id: int, texto: str) -> None:
        self._req(
            "POST", f"/conversations/{conversa_id}/messages", json={"content": texto, "message_type": "incoming"}
        )

    def nota_privada(self, conversa_id: int, texto: str) -> None:
        self._req(
            "POST",
            f"/conversations/{conversa_id}/messages",
            json={"content": texto, "message_type": "outgoing", "private": True},
        )
