import os
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

_db = Path(tempfile.mkdtemp()) / "teste.db"
os.environ.update(
    DATABASE_URL=f"sqlite:///{_db}",
    SEMESTRE_INICIO=date.today().isoformat(),
    SEMESTRE_FIM=(date.today() + timedelta(days=60)).isoformat(),
    WHATSAPP_VERIFY_TOKEN="verifica123",
    WHATSAPP_APP_SECRET="segredo",
    WHATSAPP_TOKEN="",
    CHATWOOT_WEBHOOK_TOKEN="cw123",
    USUARIOS="coord:senha:coordenacao,recep:senha2:recepcao",
    TROCAR_SENHA_INICIAL="nao",
    MODO_AGENDAMENTO_BOT="direto",  # testes do fluxo completo; o modo triagem tem teste próprio
    ARQUIVOS_DIR=str(Path(tempfile.mkdtemp()) / "arquivos"),
)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

from app import dados  # noqa: E402
from app.db import Base, engine, sessao  # noqa: E402
from app.mensagens import Entrada  # noqa: E402
from app.servico import Servico  # noqa: E402


class WhatsAppFalso:
    def __init__(self):
        self.enviadas = []

    def enviar(self, telefone, r):
        self.enviadas.append((telefone, r))


class ChatwootFalso:
    def __init__(self):
        self.abertas, self.mensagens = [], []

    def abrir_conversa(self, p, resumo):
        self.abertas.append((p.telefone, resumo))
        return 77

    def mensagem_do_paciente(self, conv_id, texto):
        self.mensagens.append((conv_id, texto))


@pytest.fixture(autouse=True)
def banco():
    from app import models  # noqa: F401

    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with sessao() as s:
        dados.carregar(s)
    yield


@pytest.fixture
def bot():
    wa, cw = WhatsAppFalso(), ChatwootFalso()
    servico = Servico(whatsapp=wa, chatwoot=cw)

    class Bot:
        whatsapp, chatwoot = wa, cw

        def diz(self, texto="", opcao=None, telefone="5511988887777", tipo="text"):
            wa.enviadas.clear()
            with sessao() as s:
                servico.receber(s, Entrada(telefone=telefone, texto=texto, id_opcao=opcao, tipo=tipo))
            return [r for _, r in wa.enviadas]

        servico_ = servico

    return Bot()
