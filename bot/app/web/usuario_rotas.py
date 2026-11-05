"""Gestão de usuários (coordenação) e troca da própria senha (todos)."""
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select

from .. import config
from .. import usuarios as U
from ..db import sessao
from ..models import RegistroAcesso, Usuario
from .rotas import coordenacao, int_ou_none, ir, render, usuario

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
    return render(request, "usuario_form.html", alvo=None, papeis=U.PAPEIS, dados={})


@router.post("/usuarios/novo", response_class=HTMLResponse)
def criar(request: Request, nome: str = Form(""), login: str = Form(""), papel: str = Form("recepcao"), u=Depends(coordenacao)):
    with sessao() as s:
        try:
            novo, senha = U.criar(s, login, nome, papel, criado_por=u["login"])
        except U.ErroUsuario as e:
            return render(request, "usuario_form.html", alvo=None, papeis=U.PAPEIS, erro=str(e),
                          dados={"nome": nome, "login": login, "papel": papel})
        _registrar(s, u["login"], "criou usuário", f"{novo.login} ({novo.papel_nome})")
        # a senha provisória aparece UMA vez, nesta tela; não vai para a URL nem para o registro
        return render(request, "usuario_senha.html", alvo=novo, senha=senha, criado=True)


@router.get("/usuarios/{uid}", response_class=HTMLResponse)
def form_editar(request: Request, uid: int, u=Depends(coordenacao)):
    with sessao() as s:
        alvo = s.get(Usuario, uid)
        if not alvo:
            raise HTTPException(404)
        return render(request, "usuario_form.html", alvo=alvo, papeis=U.PAPEIS, dados={})


@router.post("/usuarios/{uid}")
def editar(uid: int, nome: str = Form(""), papel: str = Form("recepcao"), ativo: str = Form(""), u=Depends(coordenacao)):
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
        mudancas = []
        if alvo.papel != papel:
            mudancas.append(f"papel {alvo.papel_nome} → {U.PAPEIS[papel]}")
        if alvo.ativo != bool(ativo):
            mudancas.append("reativado" if ativo else "desativado")
        alvo.nome, alvo.papel, alvo.ativo = " ".join(nome.split())[:120], papel, bool(ativo)
        _registrar(s, u["login"], "editou usuário", f"{alvo.login}: {', '.join(mudancas) or 'nome'}")
    return ir("/usuarios", msg="Usuário salvo.")


@router.post("/usuarios/{uid}/redefinir-senha", response_class=HTMLResponse)
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
