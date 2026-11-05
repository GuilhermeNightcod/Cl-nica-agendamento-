"""Gestão de usuários (coordenação) e troca da própria senha (todos)."""
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select

from .. import config
from .. import usuarios as U
from ..db import sessao
from ..models import RegistroAcesso, Usuario
from .rotas import coordenacao, int_ou_none, ir, render, turmas, usuario
from ..models import SessaoClinica


def professores(s) -> list[str]:
    return sorted({p for p in s.scalars(select(SessaoClinica.professor).distinct()) if p and not p.upper().startswith(("A DEFINIR", "EXEMPLO"))})

router = APIRouter()


def _registrar(s, autor: str, acao: str, detalhe: str) -> None:
    s.add(RegistroAcesso(usuario=autor, acao=acao, detalhe=detalhe[:300]))


@router.get("/usuarios", response_class=HTMLResponse)
def lista(request: Request, u=Depends(coordenacao)):
    with sessao() as s:
        todos = s.scalars(select(Usuario).order_by(Usuario.ativo.desc(), Usuario.nome)).all()
        return render(request, "usuarios.html", todos=todos, papeis=U.PAPEIS, now=config.agora())


@router.get("/usuarios/novo", response_class=HTMLResponse)
def form_novo(request: Request, u=Depends(coordenacao)):
    with sessao() as s:
        return render(request, "usuario_form.html", alvo=None, papeis=U.PAPEIS, dados={}, turmas=turmas(s), professores=professores(s))


@router.post("/usuarios/novo", response_class=HTMLResponse)
def criar(request: Request, nome: str = Form(""), login: str = Form(""), papel: str = Form("recepcao"), turma: str = Form(""),
          nome_grade: str = Form(""), u=Depends(coordenacao)):
    with sessao() as s:
        try:
            novo, senha = U.criar(s, login, nome, papel, criado_por=u["login"], turma=turma, nome_grade=nome_grade)
        except U.ErroUsuario as e:
            return render(request, "usuario_form.html", alvo=None, papeis=U.PAPEIS, erro=str(e), turmas=turmas(s),
                          professores=professores(s),
                          dados={"nome": nome, "login": login, "papel": papel, "turma": turma, "nome_grade": nome_grade})
        _registrar(s, u["login"], "criou usuário", f"{novo.login} ({novo.papel_nome})")
        # a senha provisória aparece UMA vez, nesta tela; não vai para a URL nem para o registro
        return render(request, "usuario_senha.html", alvo=novo, senha=senha, criado=True)


@router.get("/usuarios/{uid:int}", response_class=HTMLResponse)
def form_editar(request: Request, uid: int, u=Depends(coordenacao)):
    with sessao() as s:
        alvo = s.get(Usuario, uid)
        if not alvo:
            raise HTTPException(404)
        return render(request, "usuario_form.html", alvo=alvo, papeis=U.PAPEIS, dados={}, turmas=turmas(s), professores=professores(s))


@router.post("/usuarios/{uid:int}")
def editar(uid: int, nome: str = Form(""), papel: str = Form("recepcao"), ativo: str = Form(""), turma: str = Form(""),
           nome_grade: str = Form(""), u=Depends(coordenacao)):
    with sessao() as s:
        alvo = s.get(Usuario, uid)
        if not alvo:
            raise HTTPException(404)
        perde_coordenacao = alvo.papel == "coordenacao" and alvo.ativo and (papel != "coordenacao" or not ativo)
        if perde_coordenacao and U.coordenadores_ativos(s) <= 1:
            return ir(f"/usuarios/{uid}", erro="Precisa existir pelo menos um usuário ativo da coordenação.")
        if alvo.login == u["login"] and not ativo:
            return ir(f"/usuarios/{uid}", erro="Você não pode desativar o seu próprio usuário.")
        if papel not in U.PAPEIS or not nome.strip():
            return ir(f"/usuarios/{uid}", erro="Preencha o nome e o papel.")
        if papel == "aluno" and not turma.strip():
            return ir(f"/usuarios/{uid}", erro="Informe a turma do aluno.")
        if papel == "professor" and not nome_grade.strip():
            return ir(f"/usuarios/{uid}", erro="Escolha o nome do professor como aparece na grade.")
        alvo.turma = turma.strip() if papel == "aluno" else None
        alvo.nome_grade = nome_grade.strip() if papel == "professor" else None
        mudancas = []
        if alvo.papel != papel:
            mudancas.append(f"papel {alvo.papel_nome} → {U.PAPEIS[papel]}")
        if alvo.ativo != bool(ativo):
            mudancas.append("reativado" if ativo else "desativado")
        alvo.nome, alvo.papel, alvo.ativo = " ".join(nome.split())[:120], papel, bool(ativo)
        _registrar(s, u["login"], "editou usuário", f"{alvo.login}: {', '.join(mudancas) or 'nome'}")
    return ir("/usuarios", msg="Usuário salvo.")


@router.post("/usuarios/{uid:int}/redefinir-senha", response_class=HTMLResponse)
def redefinir(request: Request, uid: int, u=Depends(coordenacao)):
    with sessao() as s:
        alvo = s.get(Usuario, uid)
        if not alvo:
            raise HTTPException(404)
        senha = U.senha_provisoria()
        alvo.senha_hash, alvo.trocar_senha = U.gerar_hash(senha), True
        alvo.tentativas_falhas, alvo.bloqueado_ate = 0, None
        _registrar(s, u["login"], "redefiniu senha", alvo.login)
        return render(request, "usuario_senha.html", alvo=alvo, senha=senha, criado=False)


@router.get("/minha-senha", response_class=HTMLResponse)
def tela_minha_senha(request: Request, u=Depends(usuario)):
    return render(request, "minha_senha.html", obrigatoria=u.get("trocar_senha"))


@router.post("/minha-senha", response_class=HTMLResponse)
def trocar_minha_senha(request: Request, atual: str = Form(""), nova: str = Form(""), confirmar: str = Form(""), u=Depends(usuario)):
    with sessao() as s:
        eu = s.scalar(select(Usuario).where(Usuario.login == u["login"]))
        try:
            if not U.conferir(atual, eu.senha_hash):
                raise U.ErroUsuario("A senha atual não confere.")
            if nova != confirmar:
                raise U.ErroUsuario("A nova senha e a confirmação estão diferentes.")
            if nova == atual:
                raise U.ErroUsuario("Escolha uma senha diferente da atual.")
            U.validar_senha(nova, eu.login)
        except U.ErroUsuario as e:
            return render(request, "minha_senha.html", obrigatoria=u.get("trocar_senha"), erro=str(e))
        eu.senha_hash, eu.trocar_senha = U.gerar_hash(nova), False
        _registrar(s, eu.login, "trocou a própria senha", eu.login)
    request.session["usuario"] = {**u, "trocar_senha": False}
    return ir("/agenda", msg="Senha alterada.")


# ------------------------------------------------------------------ cadastro de turma inteira
@router.get("/usuarios/importar", response_class=HTMLResponse)
def tela_importar(request: Request, u=Depends(coordenacao)):
    with sessao() as s:
        return render(request, "usuarios_importar.html", turmas=turmas(s), criados=None)


@router.post("/usuarios/importar", response_class=HTMLResponse)
def importar(request: Request, turma: str = Form(""), nomes: str = Form(""), u=Depends(coordenacao)):
    with sessao() as s:
        lista_turmas = turmas(s)
        if turma not in lista_turmas:
            return render(request, "usuarios_importar.html", turmas=lista_turmas, criados=None, erro="Escolha a turma.", nomes=nomes)
        criados, pulados = [], []
        for linha in nomes.splitlines():
            nome = " ".join(linha.replace(";", " ").replace("\t", " ").split())
            if len(nome) < 3:
                continue
            if s.scalar(select(Usuario).where(Usuario.nome == nome.title(), Usuario.papel == "aluno", Usuario.turma == turma)):
                pulados.append(nome)
                continue
            novo, senha = U.criar(s, U.login_sugerido(s, nome), nome.title(), "aluno", criado_por=u["login"], turma=turma)
            criados.append((novo, senha))
        _registrar(s, u["login"], "cadastrou alunos", f"{len(criados)} em {turma}")
        return render(request, "usuarios_importar.html", turmas=lista_turmas, criados=criados, pulados=pulados, turma=turma)
