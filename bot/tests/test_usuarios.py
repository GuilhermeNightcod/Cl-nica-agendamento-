"""Login, criação de usuários pela coordenação, senha provisória e bloqueios."""
import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import sessao
from app.main import app
from app.models import RegistroAcesso, Usuario
from app.usuarios import conferir, gerar_hash


@pytest.fixture
def c():
    with TestClient(app) as cliente:
        yield cliente


def entrar(c, login, senha):
    return c.post("/entrar", data={"login": login, "senha": senha}, follow_redirects=False)


def test_senha_guardada_com_hash(c):
    h = gerar_hash("minha senha boa")
    assert "minha senha boa" not in h and h.startswith("scrypt$")
    assert conferir("minha senha boa", h) and not conferir("outra", h)
    with sessao() as s:
        u = s.scalar(select(Usuario).where(Usuario.login == "coord"))
        assert u.papel == "coordenacao" and u.senha_hash.startswith("scrypt$")


def test_coordenacao_cria_usuario_que_troca_senha_no_primeiro_acesso(c):
    entrar(c, "coord", "senha")
    r = c.post("/usuarios/novo", data={"nome": "ana souza", "login": "Ana.Souza", "papel": "recepcao"})
    assert "Usuário criado" in r.text
    senha = re.search(r'id="senha">([^<]+)<', r.text).group(1)
    assert senha not in str(r.url)
    with sessao() as s:
        assert "ana.souza" in {x.login for x in s.scalars(select(Usuario))}
        assert all(senha not in (x.detalhe or "") for x in s.scalars(select(RegistroAcesso)))
    # usuário repetido
    assert "Já existe" in c.post("/usuarios/novo", data={"nome": "Outra", "login": "ana.souza", "papel": "recepcao"}).text

    c.cookies.clear()
    assert entrar(c, "ana.souza", senha).status_code == 303
    r = c.get("/agenda", follow_redirects=False)
    assert r.headers["location"] == "/minha-senha"  # obrigada a trocar
    r = c.post("/minha-senha", data={"atual": senha, "nova": "123", "confirmar": "123"})
    assert "pelo menos 8" in r.text
    r = c.post("/minha-senha", data={"atual": senha, "nova": "sorriso da clinica", "confirmar": "sorriso da clinica"})
    assert r.status_code == 200 and "Senha alterada" in r.text
    assert c.get("/agenda").status_code == 200
    assert c.get("/usuarios").status_code == 403  # recepção não gerencia usuários
    c.cookies.clear()
    assert "erro" in entrar(c, "ana.souza", senha).headers["location"]  # provisória não vale mais


def test_desativar_derruba_sessao_e_impede_login(c):
    entrar(c, "recep", "senha2")
    assert c.get("/agenda").status_code == 200
    admin = TestClient(app)
    entrar(admin, "coord", "senha")
    with sessao() as s:
        uid = s.scalar(select(Usuario.id).where(Usuario.login == "recep"))
    admin.post(f"/usuarios/{uid}", data={"nome": "Recepção", "papel": "recepcao"})  # sem "ativo" = desativa
    r = c.get("/agenda", follow_redirects=False)
    assert r.status_code == 303 and "/entrar" in r.headers["location"]
    assert "desativado" in c.post("/entrar", data={"login": "recep", "senha": "senha2"}).text


def test_bloqueio_apos_tentativas_e_redefinicao(c):
    for _ in range(5):
        entrar(c, "recep", "errada")
    r = c.post("/entrar", data={"login": "recep", "senha": "senha2"})
    assert "Muitas tentativas" in r.text
    entrar(c, "coord", "senha")
    with sessao() as s:
        uid = s.scalar(select(Usuario.id).where(Usuario.login == "recep"))
    r = c.post(f"/usuarios/{uid}/redefinir-senha")
    nova = re.search(r'id="senha">([^<]+)<', r.text).group(1)
    c.cookies.clear()
    assert entrar(c, "recep", nova).status_code == 303 and "erro" not in entrar(c, "recep", nova).headers["location"]


def test_sempre_sobra_um_coordenador(c):
    entrar(c, "coord", "senha")
    with sessao() as s:
        for outro in s.scalars(select(Usuario).where(Usuario.papel == "coordenacao", Usuario.login != "coord")):
            outro.ativo = False
        uid = s.scalar(select(Usuario.id).where(Usuario.login == "coord"))
    r = c.post(f"/usuarios/{uid}", data={"nome": "Coord", "papel": "recepcao", "ativo": "1"})
    assert "pelo menos um usuário ativo da coordenação" in r.text
    assert c.get("/usuarios").status_code == 200 and c.get("/usuarios/novo").status_code == 200


def test_lista_inicial_e_cartoes_de_primeiro_acesso(c):
    with sessao() as s:
        por_login = {u.login: u for u in s.scalars(select(Usuario))}
        assert por_login["jhenifer"].papel == "professor" and por_login["jhenifer"].nome_grade == "Jhenifer Pinheiro"
        assert por_login["jhenifer.coord"].papel == "coordenacao" and por_login["keylla.melo"].papel == "coordenacao"
        assert por_login["rosemar"].trocar_senha
        ids = [por_login[l].id for l in ("jhenifer", "keylla.melo")]
    entrar(c, "coord", "senha")
    r = c.get("/usuarios/primeiro-acesso")
    assert "Keylla Melo" in r.text and "Thaynara Lima" in r.text
    r = c.post("/usuarios/primeiro-acesso", data={"ids": [str(i) for i in ids]})
    cartoes = dict(re.findall(r"<dt>Usuário</dt><dd>([^<]+)</dd><dt>Senha</dt><dd>([^<]+)</dd>", r.text))
    assert set(cartoes) == {"jhenifer", "keylla.melo"}
    c.cookies.clear()
    r = entrar(c, "jhenifer", cartoes["jhenifer"])
    assert r.status_code == 303 and "erro" not in r.headers["location"]
    assert c.get("/agenda", follow_redirects=False).headers["location"] == "/minha-senha"
