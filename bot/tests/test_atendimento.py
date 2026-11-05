"""Central de atendimentos (WhatsApp humano) e odontograma."""
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import config
from app.db import sessao
from app.main import app, fila, servico
from app.mensagens import Entrada
from app.models import Atendimento, Conversa, Mensagem, Paciente, RegistroDente, Setor
from tests.conftest import WhatsAppFalso

TEL = "5511955554444"


@pytest.fixture
def c():
    servico.whatsapp = WhatsAppFalso()
    servico._chatwoot = None
    with TestClient(app) as cliente:
        yield cliente


def entrar(c, login="recep", senha="senha2"):
    c.post("/entrar", data={"login": login, "senha": senha})


def paciente_diz(texto):
    with sessao() as s:
        servico.receber(s, Entrada(telefone=TEL, texto=texto, nome_perfil="Bruna"))


def test_urgencia_vai_para_fila_de_urgencia(c):
    paciente_diz("oi")
    paciente_diz("meu rosto está muito inchado")
    paciente_diz("estou esperando")
    with sessao() as s:
        at = s.scalar(select(Atendimento))
        assert at.status == "fila" and at.urgente and at.setor.nome == "Urgência"
        assert at.nao_lidas == 1
        assert s.scalar(select(Mensagem).where(Mensagem.conteudo == "estou esperando")).atendimento_id == at.id
    entrar(c)
    r = c.get("/atendimentos?aba=fila")
    assert "Bruna" in r.text and "Pegar próximo da fila" in r.text


def test_pegar_responder_etiquetar_finalizar(c):
    paciente_diz("oi")
    paciente_diz("quero falar com atendente")
    entrar(c)
    r = c.post("/atendimentos/proximo")
    assert "Em atendimento com <b>recep</b>" in r.text
    with sessao() as s:
        at = s.scalar(select(Atendimento))
        assert at.status == "em_atendimento" and at.assumido_por == "recep" and at.setor.nome.startswith("Recepção")
        at_id = at.id
    servico.whatsapp.enviadas.clear()
    c.post(f"/atendimentos/{at_id}/responder", data={"texto": "Olá Bruna, aqui é a recepção!"})
    assert servico.whatsapp.enviadas[-1][1].texto == "Olá Bruna, aqui é a recepção!"
    with sessao() as s:
        m = s.scalar(select(Mensagem).where(Mensagem.conteudo.like("Olá Bruna%")))
        assert m.autor == "recep" and m.direcao == "saida"
    from app.models import Etiqueta
    with sessao() as s:
        eid = s.scalar(select(Etiqueta.id).where(Etiqueta.nome == "Retorno"))
    c.post(f"/atendimentos/{at_id}/etiquetas", data={"etiquetas": [str(eid)]})
    assert "Retorno" in c.get(f"/atendimentos?aba=meus&p={_pid()}").text
    # fragmentos usados pela atualização automática
    assert "Olá Bruna" in c.get(f"/atendimentos/_mensagens/{_pid()}").text
    assert "Bruna" in c.get("/atendimentos/_lista?aba=meus").text
    c.post(f"/atendimentos/{at_id}/finalizar", data={"avisar": "1"})
    with sessao() as s:
        assert s.get(Atendimento, at_id).status == "finalizado"
        assert s.scalar(select(Conversa)).atendimento_humano is False
    servico.whatsapp.enviadas.clear()
    paciente_diz("oi de novo")
    assert servico.whatsapp.enviadas, "o bot volta a responder depois de finalizado"


def _pid():
    with sessao() as s:
        return s.scalar(select(Paciente.id).where(Paciente.telefone == TEL))


def test_fora_da_janela_de_24h_bloqueia_texto(c):
    paciente_diz("oi")
    paciente_diz("atendente por favor")
    with sessao() as s:
        s.scalar(select(Conversa)).ultima_msg_paciente_em = config.agora() - timedelta(hours=30)
        at_id = s.scalar(select(Atendimento.id))
    entrar(c)
    r = c.post(f"/atendimentos/{at_id}/responder", data={"texto": "oi"})
    assert "24h" in r.text and "modelo" in r.text


def test_atendente_assume_conversa_do_bot_e_transfere(c):
    paciente_diz("oi")
    entrar(c)
    r = c.get("/atendimentos?aba=bot")
    assert "Bruna" in r.text
    r = c.post(f"/atendimentos/paciente/{_pid()}/abrir")
    assert "Em atendimento com <b>recep</b>" in r.text
    with sessao() as s:
        at = s.scalar(select(Atendimento))
        urg = s.scalar(select(Setor.id).where(Setor.nome == "Urgência"))
    c.post(f"/atendimentos/{at.id}/transferir", data={"setor_id": urg})
    with sessao() as s:
        at = s.get(Atendimento, at.id)
        assert at.status == "fila" and at.setor_id == urg and at.assumido_por is None


def test_painel_tempo_real_e_config(c):
    paciente_diz("oi")
    paciente_diz("quero falar com atendente")
    entrar(c)
    c.post("/atendimentos/proximo")
    r = c.get("/atendimentos/painel")
    assert r.status_code == 200 and "TME" in r.text and "Recepção" in r.text
    assert c.get("/atendimentos/config").status_code == 403
    entrar(c, "coord", "senha")
    c.post("/atendimentos/config/etiqueta", data={"nome": "Biópsia", "cor": "#123456"})
    assert "Biópsia" in c.get("/atendimentos/config").text


def test_odontograma(c):
    entrar(c)
    c.post("/pacientes/novo", data={"nome": "Tiago Melo"})
    with sessao() as s:
        pid = s.scalar(select(Paciente.id).where(Paciente.nome == "Tiago Melo"))
    r = c.post(f"/pacientes/{pid}/odontograma", data={"dente": "99", "descricao": "x"})
    assert "Escolha um dente" in r.text
    r = c.post(f"/pacientes/{pid}/odontograma", data={"dente": "16", "faces": ["O", "M"], "descricao": "Restauração em resina",
                                                       "status": "aberto", "anotacao": "sensibilidade ao frio", "aluno": "Guilherme"})
    assert r.status_code == 200 and "Restauração em resina" in r.text
    c.post(f"/pacientes/{pid}/odontograma", data={"dente": "arcada_sup", "descricao": "Prótese total", "status": "aberto"})
    c.post(f"/pacientes/{pid}/odontograma", data={"dente": "38", "status": "ausente"})
    with sessao() as s:
        regs = {r.dente: r for r in s.scalars(select(RegistroDente))}
        assert regs["16"].faces == "MO" and regs["16"].criado_por == "recep"
        assert regs["38"].descricao == "Ausente"
        rid = regs["16"].id
    c.post(f"/odontograma/{rid}/status", data={"status": "finalizado"})
    with sessao() as s:
        assert s.get(RegistroDente, rid).status == "finalizado"
    ficha = c.get(f"/pacientes/{pid}").text
    assert 'data-dente="16"' in ficha and "Arcada superior · 1" in ficha
    # outro usuário (recepção não autora) não exclui; coordenação exclui
    entrar(c, "coord", "senha")
    assert c.post(f"/odontograma/{rid}/excluir").status_code == 200


def test_agenda_grade_semana_dia_e_professor(c):
    entrar(c)
    assert "Jhenifer Pinheiro" in c.get("/agenda").text
    r = c.get("/agenda?professor=Thaynara Lima&visao=dia")
    assert r.status_code == 200 and "Dia" in r.text
