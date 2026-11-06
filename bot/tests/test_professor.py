"""Área do professor: clínicas que supervisiona, pacientes do dia, presença e limites."""
import re
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import sessao
from app.main import app
from app.models import Agendamento, Paciente, SessaoClinica, Vaga


@pytest.fixture
def c():
    with TestClient(app) as cliente:
        yield cliente


def entrar(c, login, senha):
    c.cookies.clear()
    return c.post("/entrar", data={"login": login, "senha": senha}, follow_redirects=False)


def criar_professor(c, nome, nome_grade, login):
    entrar(c, "coord", "senha")
    r = c.post("/usuarios/novo", data={"nome": nome, "login": login, "papel": "professor", "nome_grade": nome_grade})
    senha = re.search(r'id="senha">([^<]+)<', r.text).group(1)
    entrar(c, login, senha)
    c.post("/minha-senha", data={"atual": senha, "nova": "senha do professor", "confirmar": "senha do professor"})


def agendar_paciente(c, turma, dia, nome):
    entrar(c, "coord", "senha")
    with sessao() as s:
        vid = s.scalar(select(Vaga.id).join(SessaoClinica).where(SessaoClinica.turma == turma, SessaoClinica.dia_semana == dia)
                       .order_by(Vaga.inicio))
    c.post(f"/agenda/vaga/{vid}/agendar", data={"novo_nome": nome, "novo_nascimento": "1990-01-01", "aluno": "Dupla Teste", "encaixe": "1"})
    with sessao() as s:
        return vid, s.scalar(select(Paciente.id).where(Paciente.nome == nome))


def test_professor_ve_suas_clinicas_e_marca_presenca(c):
    vid, pid = agendar_paciente(c, "8º semestre", 1, "Paciente Da Jhenifer")       # terça 8º: Jhenifer
    vid6, pid6 = agendar_paciente(c, "6º semestre", 2, "Paciente Da Quarta")        # quarta 6º: Jhenifer também
    _, pid_outro = agendar_paciente(c, "8º semestre", 4, "Paciente Do Rosemar")     # sexta 8º: Rosemar
    entrar(c, "coord", "senha")
    assert "Jhenifer Pinheiro" in c.get("/usuarios/novo").text  # nome vem da grade
    assert "Escolha o nome do professor" in c.post("/usuarios/novo", data={"nome": "X", "login": "prof.x", "papel": "professor"}).text
    criar_professor(c, "Jhenifer Pinheiro", "Jhenifer Pinheiro", "prof.jhenifer")

    assert c.get("/", follow_redirects=False).headers["location"] == "/professor"
    r = c.get("/professor")
    assert "8º semestre" in r.text and "6º semestre" in r.text  # supervisiona duas turmas
    r = c.get(f"/professor/vaga/{vid}")
    assert "Paciente Da Jhenifer" in r.text and "Dupla Teste" in r.text
    c.post(f"/professor/agendamento/{_ag(pid)}/status", data={"status": "compareceu"})
    with sessao() as s:
        assert s.get(Agendamento, _ag(pid)).status == "compareceu"
    assert c.get(f"/professor/paciente/{pid}").status_code == 200
    r = c.post(f"/pacientes/{pid}/odontograma", data={"dente": "11", "descricao": "Avaliado", "status": "finalizado"})
    assert "/professor/paciente/" in str(r.url)

    # limites
    assert c.get(f"/professor/paciente/{pid_outro}").status_code == 404
    with sessao() as s:
        vid_rosemar = s.scalar(select(Vaga.id).join(SessaoClinica).where(SessaoClinica.professor == "Rosemar"))
    assert c.get(f"/professor/vaga/{vid_rosemar}").status_code == 404
    for url in ["/agenda", "/pacientes", "/atendimentos", "/aluno"]:
        r = c.get(url, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/professor", url


def _ag(pid):
    with sessao() as s:
        return s.scalar(select(Agendamento.id).where(Agendamento.paciente_id == pid))
