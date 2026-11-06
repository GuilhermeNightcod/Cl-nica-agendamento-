"""Telas da recepção/coordenação."""
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import sessao
from app.main import app
from app.models import Agendamento, Documento, Paciente, RegistroAcesso, SessaoClinica, Vaga


@pytest.fixture
def cliente():
    with TestClient(app) as c:
        yield c


def entrar(c, login="recep", senha="senha2"):
    r = c.post("/entrar", data={"login": login, "senha": senha}, follow_redirects=False)
    assert r.status_code == 303 and "erro" not in r.headers["location"]


def vaga_de(clinica_nome):
    with sessao() as s:
        return s.scalar(select(Vaga).join(SessaoClinica).where(SessaoClinica.nome.contains(clinica_nome)).order_by(Vaga.inicio)).id


def test_login_obrigatorio_e_senha_errada(cliente):
    assert cliente.get("/agenda", follow_redirects=False).status_code == 303
    r = cliente.post("/entrar", data={"login": "recep", "senha": "x"}, follow_redirects=False)
    assert "erro" in r.headers["location"]


def test_sessoes_do_8_semestre_importadas(cliente):
    with sessao() as s:
        terca = s.scalar(select(SessaoClinica).where(SessaoClinica.turma == "8º semestre", SessaoClinica.dia_semana == 1))
        assert terca.professor == "Jhenifer Pinheiro"
        assert (terca.hora_inicio.strftime("%H:%M"), terca.hora_fim.strftime("%H:%M")) == ("18:00", "21:30")  # noturno
        assert terca.alunos == 13 and terca.duplas == 7 and terca.vagas == 7  # 8º: 13 alunos, 1 paciente por dupla
        assert {e.codigo for e in terca.especialidades} == {"triagem", "endodontia"}
        hebiatria = s.scalar(select(SessaoClinica).where(SessaoClinica.turma == "8º semestre", SessaoClinica.dia_semana == 2))
        assert (hebiatria.idade_min, hebiatria.idade_max) == (10, 19)
        assert s.scalar(select(Vaga).where(Vaga.sessao_id == terca.id)) is not None
        # segunda do 8º é pré-clínica (sem pacientes): não pode existir clínica
        assert s.scalar(select(SessaoClinica).where(SessaoClinica.turma == "8º semestre", SessaoClinica.dia_semana == 0)) is None
        idoso = s.scalar(select(SessaoClinica).where(SessaoClinica.nome.contains("Idoso")))
        assert idoso.idade_min == 60 and idoso.turma == "10º semestre"


def test_agenda_semana_mostra_clinicas(cliente):
    entrar(cliente)
    r = cliente.get("/agenda")
    assert r.status_code == 200 and "8º semestre" in r.text


def test_recepcao_cadastra_e_agenda_novo_paciente(cliente):
    entrar(cliente)
    vid = vaga_de("Assistência Odontológica III")
    r = cliente.post(f"/agenda/vaga/{vid}/agendar", data={
        "novo_nome": "joana prado", "novo_telefone": "(11) 97777-1234", "novo_nascimento": "1985-06-01",
        "procedimento": "", "aluno": "Guilherme", "avisar": "1",
    })
    assert r.status_code == 200 and "Agendado" in r.text and "Joana Prado" in r.text
    with sessao() as s:
        ag = s.scalar(select(Agendamento))
        assert ag.origem == "recepcao" and ag.aluno == "Guilherme" and ag.criado_por == "recep"
        assert ag.paciente.telefone == "5511977771234"
        assert ag.vaga.ocupadas == 1
    r = cliente.get(f"/agenda/vaga/{vid}")
    assert "Joana Prado" in r.text


def test_faixa_etaria_e_encaixe(cliente):
    entrar(cliente)
    with sessao() as s:
        p = Paciente(nome="Adulto Teste", data_nascimento=date(1980, 1, 1))
        s.add(p)
        s.flush()
        pid = p.id
    vid = vaga_de("Adolescente")
    r = cliente.post(f"/agenda/vaga/{vid}/agendar", data={"paciente_id": pid})
    assert "fora da faixa etária" in r.text
    r = cliente.post(f"/agenda/vaga/{vid}/agendar", data={"paciente_id": pid, "encaixe": "1"})
    assert "Agendado" in r.text
    # paciente NOVO recusado pela idade não fica cadastrado pela metade
    dados = {"novo_nome": "Roberto Dias", "novo_telefone": "11 98776-5544", "novo_nascimento": "1975-05-05"}
    assert "fora da faixa" in cliente.post(f"/agenda/vaga/{vid}/agendar", data=dados).text
    with sessao() as s:
        assert s.scalar(select(Paciente).where(Paciente.nome == "Roberto Dias")) is None
    assert "Agendado" in cliente.post(f"/agenda/vaga/{vid}/agendar", data={**dados, "encaixe": "1"}).text


def test_encontrar_horario_filtra_por_idade(cliente):
    entrar(cliente)
    with sessao() as s:
        crianca = Paciente(nome="Criança Teste", data_nascimento=date.today() - timedelta(days=365 * 7))
        adulto = Paciente(nome="Adulto Dois", data_nascimento=date(1970, 5, 5))
        s.add_all([crianca, adulto])
        s.flush()
        ids = crianca.id, adulto.id
        from app.models import Especialidade
        ped = s.scalar(select(Especialidade).where(Especialidade.codigo == "odontopediatria")).id
    r = cliente.get(f"/agendar?paciente_id={ids[0]}&procedimento=esp:{ped}")
    assert "Agendar aqui" in r.text
    r = cliente.get(f"/agendar?paciente_id={ids[1]}&procedimento=esp:{ped}")
    assert "Agendar aqui" not in r.text and "Nenhum horário livre" in r.text


def test_bloquear_dia_tira_do_bot(cliente):
    from app.agenda import vagas_disponiveis
    entrar(cliente)
    vid = vaga_de("Assistência Odontológica III")
    cliente.post(f"/agenda/vaga/{vid}/bloqueio", data={"acao": "bloquear", "motivo": "Professora em congresso"})
    with sessao() as s:
        assert s.get(Vaga, vid).bloqueada
        assert vid not in [v.id for v in vagas_disponiveis(s, a_partir=None)]


def test_prontuario_upload_visualizacao_e_registro(cliente):
    entrar(cliente)
    cliente.post("/pacientes/novo", data={"nome": "Paulo Reis", "numero_prontuario": "2024-0153"})
    with sessao() as s:
        pid = s.scalar(select(Paciente).where(Paciente.numero_prontuario == "2024-0153")).id
    jpg = b"\xff\xd8\xff\xe0" + b"0" * 100
    r = cliente.post(f"/pacientes/{pid}/documentos", data={"tipo": "anamnese", "data_documento": "2025-03-10"},
                     files=[("arquivos", ("folha1.jpg", jpg, "image/jpeg")), ("arquivos", ("virus.exe", b"MZ\x90", "image/jpeg"))])
    assert "1 arquivo(s) anexado" in r.text and "virus.exe" in r.text
    with sessao() as s:
        d = s.scalar(select(Documento))
        assert d.tipo == "anamnese" and d.enviado_por == "recep"
    r = cliente.get(f"/documentos/{d.id}")
    assert r.status_code == 200 and r.content == jpg
    # busca pelo nº do prontuário físico
    assert "Paulo Reis" in cliente.get("/pacientes?busca=2024-0153").text
    # recepção não pode excluir documentos; coordenação pode
    assert cliente.post(f"/documentos/{d.id}/excluir").status_code == 403
    with sessao() as s:
        acoes = {r.acao for r in s.scalars(select(RegistroAcesso))}
    assert {"cadastrou paciente", "anexou documentos", "viu documento"} <= acoes


def test_coordenacao_configura_clinica(cliente):
    entrar(cliente)
    assert cliente.get("/clinicas").status_code == 403  # recepção não configura
    entrar(cliente, "coord", "senha")
    with sessao() as s:
        from app.models import Especialidade
        endo = s.scalar(select(Especialidade).where(Especialidade.codigo == "endodontia")).id
    r = cliente.post("/clinicas/nova", data={
        "turma": "10º semestre", "nome": "Endo X", "professor": "Prof. Teste", "dia_semana": "2",
        "hora_inicio": "19:00", "hora_fim": "22:00", "vagas": "6", "areas": [str(endo)], "ativa": "1",
    })
    assert r.status_code == 200 and "datas criadas" in r.text
    with sessao() as s:
        se = s.scalar(select(SessaoClinica).where(SessaoClinica.nome == "Endo X"))
        vagas = s.scalars(select(Vaga).where(Vaga.sessao_id == se.id)).all()
        assert vagas and all(v.inicio.weekday() == 2 and v.inicio.hour == 19 and v.capacidade == 6 for v in vagas)
        sid = se.id
    # mudar para quinta: datas antigas vazias somem, novas são criadas
    cliente.post(f"/clinicas/{sid}", data={
        "turma": "10º semestre", "nome": "Endo X", "dia_semana": "3", "hora_inicio": "19:00", "hora_fim": "22:00",
        "vagas": "6", "areas": [str(endo)], "ativa": "1",
    })
    with sessao() as s:
        assert all(v.inicio.weekday() == 3 for v in s.scalars(select(Vaga).where(Vaga.sessao_id == sid)))
    assert cliente.get("/clinicas/nova").status_code == 200
    assert "Endo X" in cliente.get("/clinicas").text
    assert cliente.get("/acessos").status_code == 200


def test_todas_as_telas_abrem(cliente):
    entrar(cliente, "coord", "senha")
    for url in ["/agenda", "/agenda?turma=8º semestre", "/agendar", "/agendar?busca=a", "/pacientes", "/pacientes/novo",
                "/espera", "/painel", "/clinicas", "/acessos"]:
        assert cliente.get(url).status_code == 200, url


def test_duplas_boxes_e_turmas_na_mesma_clinica(cliente):
    from app.agenda import uso_de_boxes
    from app.models import EspacoClinico
    entrar(cliente, "coord", "senha")
    with sessao() as s:
        esp = s.scalar(select(EspacoClinico))
        sid = s.scalar(select(SessaoClinica.id).where(SessaoClinica.turma == "8º semestre", SessaoClinica.dia_semana == 1))
        esp_id, esp_nome = esp.id, esp.nome
    cliente.post("/clinicas/espaco", data={"espaco_id": esp_id, "nome": esp_nome, "boxes": "20"})
    with sessao() as s:
        se = s.get(SessaoClinica, sid)
        areas = [str(e.id) for e in se.especialidades]
        dados = {"turma": se.turma, "nome": se.nome, "professor": se.professor, "dia_semana": "1", "hora_inicio": "19:00",
                 "hora_fim": "22:00", "vagas": "99", "alunos": "25", "pacientes_por_dupla": "1", "espaco": esp_nome,
                 "areas": areas, "ativa": "1"}
    cliente.post(f"/clinicas/{sid}", data=dados)  # 25 alunos -> 13 duplas -> 13 vagas (ignora o 99)
    with sessao() as s:
        se = s.get(SessaoClinica, sid)
        assert se.duplas == 13 and se.vagas == 13
        assert all(v.capacidade == 13 for v in s.scalars(select(Vaga).where(Vaga.sessao_id == sid)))
        # 10º semestre também atende terça no mesmo horário e na mesma clínica física
        dez = s.scalar(select(SessaoClinica).where(SessaoClinica.turma == "10º semestre", SessaoClinica.dia_semana == 1))
        dez.alunos = 16  # 8 duplas -> 13 + 8 = 21 > 20 boxes
        terca = [u for u in uso_de_boxes(list(s.scalars(select(SessaoClinica)))) if u["dia"] == 1][0]
        assert terca["duplas"] == 21 and terca["excede"] and terca["turmas"] == ["8º semestre", "10º semestre"]
    assert "falta 1 box" in cliente.get("/clinicas").text or "Uso de boxes" in cliente.get("/clinicas").text


def test_trio_na_cirurgia_do_6(cliente):
    from app.agenda import uso_de_boxes
    with sessao() as s:
        cir = s.scalar(select(SessaoClinica).where(SessaoClinica.turma == "6º semestre", SessaoClinica.dia_semana == 3))
        assert cir.alunos_por_box == 3 and cir.duplas == 8 and cir.vagas == 8 and cir.rotulo_equipes == "8 trios"
        quinta = [u for u in uso_de_boxes(list(s.scalars(select(SessaoClinica)))) if u["dia"] == 3][0]
        assert quinta["duplas"] == 8 + 7 and not quinta["excede"]  # 15 de 15 boxes
    with sessao() as s:
        logins = {u.login: u.papel for u in s.scalars(select(__import__("app.models", fromlist=["Usuario"]).Usuario))}
    assert logins.get("larissa") == "recepcao" and logins.get("herika") == "recepcao"
