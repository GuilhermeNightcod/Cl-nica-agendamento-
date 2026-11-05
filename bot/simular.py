"""
SIMULADOR — converse com o bot no terminal, sem WhatsApp.

    python simular.py

Digite as mensagens como se fosse o paciente. Para escolher um botão ou item
de lista, digite o NÚMERO da opção. Comandos especiais:
    /sair      encerra
    /reset     apaga o paciente de teste e começa do zero
    /tarefas   roda os lembretes e a recuperação agora
    /humano    simula o atendente encerrando o atendimento humano
"""
import os
import sys
import tempfile
from pathlib import Path

if "DATABASE_URL" not in os.environ:
    os.environ["DATABASE_URL"] = f"sqlite:///{Path(tempfile.gettempdir()) / 'simulador_odonto.db'}"

sys.path.insert(0, str(Path(__file__).parent))

from sqlalchemy import delete, select  # noqa: E402

from app import dados  # noqa: E402
from app.db import criar_tabelas, sessao  # noqa: E402
from app.mensagens import Botoes, Entrada, Lista, Modelo, Texto  # noqa: E402
from app.models import Agendamento, Conversa, ListaEspera, Mensagem, Paciente  # noqa: E402
from app.servico import Servico  # noqa: E402
from app.tarefas import enviar_lembretes, recuperar_abandonos  # noqa: E402

TELEFONE = "5511999990000"
AZUL, VERDE, CINZA, FIM = "\033[94m", "\033[92m", "\033[90m", "\033[0m"


class WhatsAppDeTela:
    def enviar(self, telefone, r):
        if isinstance(r, Texto):
            print(f"{VERDE}🤖 {r.texto}{FIM}\n")
        elif isinstance(r, Botoes):
            print(f"{VERDE}🤖 {r.texto}{FIM}")
            for i, (_, t) in enumerate(r.opcoes, 1):
                print(f"   {AZUL}[{i}] {t}{FIM}")
            print()
        elif isinstance(r, Lista):
            print(f"{VERDE}🤖 {r.texto}{FIM}")
            for i, (_, t, d) in enumerate(r.opcoes, 1):
                print(f"   {AZUL}{i}. {t}{FIM} {CINZA}{d}{FIM}")
            print()
        elif isinstance(r, Modelo):
            print(f"{VERDE}🤖 [TEMPLATE '{r.nome}'] {r.parametros}{FIM}")
            print(f"   {AZUL}[confirma] Confirmo   [remarca] Remarcar{FIM}  {CINZA}{r.payloads_botoes}{FIM}\n")


def resetar():
    with sessao() as s:
        p = s.scalar(select(Paciente).where(Paciente.telefone == TELEFONE))
        if p:
            for ag in s.scalars(select(Agendamento).where(Agendamento.paciente_id == p.id)):
                if ag.status in ("agendado", "confirmado"):
                    ag.vaga.ocupadas -= 1
            for modelo in (Agendamento, ListaEspera, Mensagem, Conversa):
                s.execute(delete(modelo).where(modelo.paciente_id == p.id))
            s.delete(p)


def main():
    criar_tabelas()
    with sessao() as s:
        dados.carregar(s)
    servico = Servico(whatsapp=WhatsAppDeTela())
    print(f"{CINZA}Simulador da Central Odonto. Digite 'oi' para começar. /sair para encerrar.{FIM}\n")
    while True:
        try:
            texto = input("🙂 Você: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if texto == "/sair":
            break
        if texto == "/reset":
            resetar()
            print(f"{CINZA}(paciente de teste apagado){FIM}\n")
            continue
        if texto == "/tarefas":
            with sessao() as s:
                print(f"{CINZA}lembretes: {enviar_lembretes(s, servico)}  recuperações: {recuperar_abandonos(s, servico)}{FIM}\n")
            continue
        if texto == "/humano":
            with sessao() as s:
                conv = s.scalar(select(Conversa).join(Paciente).where(Paciente.telefone == TELEFONE))
                if conv:
                    conv.chatwoot_conversa_id = conv.chatwoot_conversa_id or 1
                    servico.evento_chatwoot(s, {"event": "conversation_status_changed", "id": conv.chatwoot_conversa_id, "status": "resolved"})
            continue
        print()
        entrada = Entrada(telefone=TELEFONE, texto=texto, nome_perfil="Paciente Teste")
        if texto.startswith(("confirma:", "remarca:")):  # simula clique no botão do lembrete
            entrada = Entrada(telefone=TELEFONE, texto=texto, id_opcao=texto, tipo="button")
        with sessao() as s:
            res = servico.receber(s, entrada)
            if res.repassar_para_humano:
                print(f"{CINZA}(em atendimento humano: mensagem iria para o Chatwoot. Use /humano para encerrar){FIM}\n")


if __name__ == "__main__":
    main()
