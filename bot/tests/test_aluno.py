"""Área do aluno: agenda da turma, agendar/alterar pacientes da dupla e limites de acesso."""
import re
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import sessao
from app.main import app
from app.models import Agendamento, Paciente, SessaoClinica, Usuario, Vaga


@pytest.fixture
def c():
    with TestClient(app) as cliente:
        yield cliente


def entrar(c, login, senha):
    c.cookies.clear()
    return c.post("/entrar", data={"login": login, "senha": senha}, follow_redirects=False)


def cadastrar_turma(c, turma, nomes):
    entrar(c, "coord", "senha")
    r = c.post("/usuarios/importar", data={"turma": turma, "nomes": "\n".join(nomes)})
    assert f"{len(nomes)} alunos cadastrados" in r.text or "aluno cadastrado" in r.text
    return dict(re.findall(r"<dt>Usuário</dt><dd>([^<]+)</dd><dt>Senha</dt><dd>([^<]+)</dd>", r.text))


def primeiro_acesso(c, login, senha):
    entrar(c, login, senha)
    c.post("/minha-senha", data={"atual": senha, "nova": "minha senha nova", "confirmar": "minha senha nova"})


def vaga(turma, dia_semana):
    with sessao() as s:
        return s.scalar(select(Vaga).join(SessaoClinica).where(SessaoClinica.turma == turma, SessaoClinica.dia_semana == dia_semana)
                        .order_by(Vaga.inicio)).id


def test_fluxo_completo_do_aluno(c):
    logins = cadastrar_turma(c, "8º semestre", ["Guilherme Silva", "Ana Beatriz Souza", "Rafael Lima"])
    assert set(logins) == {"guilherme.silva", "ana.souza", "rafael.lima"}
    # mesmo nome de novo: ignorado
    entrar(c, "coord", "senha")
    assert "Já tinham login" in c.post("/usuarios/importar", data={"turma": "8º semestre", "nomes": "Guilherme Silva"}).text

    primeiro_acesso(c, "ana.souza", logins["ana.souza"])
    primeiro_acesso(c, "guilherme.silva", logins["guilherme.silva"])
    assert c.get("/", follow_redirects=False).headers["location"] == "/aluno"
    r = c.get("/aluno")
    assert "Olá, Guilherme" in r.text and "Próximas clínicas" in r.text
    assert "Assistência Odontológica III" in r.text and "Reabilitação Oral" in r.text  # clínicas do 8º
    assert "Propedêutica" not in r.text  # 6º semestre não aparece

    with sessao() as s:
        ana = s.scalar(select(Usuario.id).where(Usuario.login == "ana.souza"))
    r = c.post("/aluno/dupla", data={"dupla_id": ana})
    assert "Dupla formada com Ana Beatriz Souza" in r.text

    vid = vaga("8º semestre", 1)
    r = c.post(f"/aluno/vaga/{vid}/agendar", data={"novo_nome": "joão pedro", "novo_telefone": "11 91111-2222",
                                                   "novo_nascimento": "1990-01-01", "hora": "19:30", "avisar": "1"})
    assert "Agendado" in r.text and "João Pedro" in r.text
    with sessao() as s:
        ag = s.scalar(select(Agendamento))
        assert ag.origem == "aluno" and ag.criado_por == "guilherme.silva" and ag.aluno == "Guilherme Silva e Ana Beatriz Souza"
        assert ag.hora.strftime("%H:%M") == "19:30"
        ag_id, pid = ag.id, ag.paciente_id

    # a colega de dupla vê, altera e marca presença
    entrar(c, "ana.souza", "minha senha nova")
    assert "João Pedro" in c.get("/aluno").text
    c.post(f"/aluno/agendamento/{ag_id}", data={"hora": "20:00", "observacao": "trazer radiografia"})
    assert "trazer radiografia" in c.get(f"/aluno/agendamento/{ag_id}").text
    assert "João Pedro" in c.get("/aluno/pacientes").text
    r = c.get(f"/aluno/paciente/{pid}")
    assert r.status_code == 200 and "Odontograma" in r.text
    r = c.post(f"/pacientes/{pid}/odontograma", data={"dente": "46", "descricao": "Acesso endodôntico", "status": "aberto"})
    assert r.status_code == 200 and f"/aluno/paciente/{pid}" in str(r.url)

    # remarcar para outra terça da turma
    with sessao() as s:
        outra = s.scalars(select(Vaga).where(Vaga.sessao_id == s.get(Vaga, vid).sessao_id).order_by(Vaga.inicio)).all()[1].id
    r = c.post(f"/aluno/agendamento/{ag_id}/remarcar", data={"vaga_id": outra})
    assert "Remarcado" in r.text
    with sessao() as s:
        assert s.get(Agendamento, ag_id).status == "cancelado"
        novo = s.scalar(select(Agendamento).where(Agendamento.vaga_id == outra))
        assert novo.aluno1_id and novo.observacao == "trazer radiografia"
        assert s.get(Vaga, vid).ocupadas == 0 and s.get(Vaga, outra).ocupadas == 1


def test_limites_do_aluno(c):
    logins = cadastrar_turma(c, "8º semestre", ["Carla Dias", "Pedro Alves"])
    primeiro_acesso(c, "carla.dias", logins["carla.dias"])
    # telas da equipe: redireciona para a área do aluno
    for url in ["/agenda", "/pacientes", "/atendimentos", "/painel", "/agendar"]:
        r = c.get(url, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/aluno", url
    assert c.get("/clinicas").status_code == 403 and c.get("/usuarios").status_code == 403
    # dia de outra turma
    assert c.get(f"/aluno/vaga/{vaga('6º semestre', 0)}").status_code == 404
    # paciente que não é da dupla
    with sessao() as s:
        p = Paciente(nome="Paciente Alheio", data_nascimento=date(1980, 1, 1))
        s.add(p)
        s.flush()
        pid = p.id
    assert c.get(f"/aluno/paciente/{pid}").status_code == 404
    assert c.post(f"/pacientes/{pid}/odontograma", data={"dente": "11", "descricao": "x"}).status_code == 404
    # faixa etária: adulto na clínica do adolescente (quarta do 8º)
    r = c.post(f"/aluno/vaga/{vaga('8º semestre', 2)}/agendar", data={"paciente_id": pid})
    assert "fora da faixa etária" in r.text
    # sem vaga: aluno não faz encaixe
    vid = vaga("8º semestre", 1)
    with sessao() as s:
        v = s.get(Vaga, vid)
        v.ocupadas = v.capacidade
    r = c.post(f"/aluno/vaga/{vid}/agendar", data={"novo_nome": "Fulano Tal"})
    assert "fale com a recepção" in r.text
    with sessao() as s:
        assert s.scalar(select(Paciente).where(Paciente.nome == "Fulano Tal")) is None
    # agendamento de outra dupla
    entrar(c, "coord", "senha")
    with sessao() as s:
        livre = s.scalar(select(Vaga).join(SessaoClinica).where(SessaoClinica.turma == "8º semestre", Vaga.ocupadas == 0)).id
    c.post(f"/agenda/vaga/{livre}/agendar", data={"paciente_id": pid, "encaixe": "1"})
    with sessao() as s:
        ag_id = s.scalar(select(Agendamento.id).where(Agendamento.paciente_id == pid))
    entrar(c, "carla.dias", "minha senha nova")
    assert c.get(f"/aluno/agendamento/{ag_id}").status_code == 404


def test_coordenacao_cria_aluno_com_turma(c):
    entrar(c, "coord", "senha")
    assert "Informe a turma" in c.post("/usuarios/novo", data={"nome": "Sem Turma", "login": "sem.turma", "papel": "aluno"}).text
    r = c.post("/usuarios/novo", data={"nome": "Com Turma", "login": "com.turma", "papel": "aluno", "turma": "10º semestre"})
    assert "Usuário criado" in r.text
    assert "10º semestre" in c.get("/usuarios").text
