"""
Usuários do sistema: senha guardada com scrypt (nunca em texto), senha provisória
com troca obrigatória no primeiro acesso, bloqueio após tentativas erradas.
"""
import hashlib
import hmac
import re
import secrets
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import config
from .models import Usuario

PAPEIS = {"recepcao": "Recepção", "coordenacao": "Coordenação"}
TENTATIVAS_MAX = 5
BLOQUEIO = timedelta(minutes=15)
SENHA_MIN = 8


class ErroUsuario(Exception):
    pass


def gerar_hash(senha: str) -> str:
    sal = secrets.token_bytes(16)
    h = hashlib.scrypt(senha.encode(), salt=sal, n=2**14, r=8, p=1, dklen=32)
    return f"scrypt$16384$8$1${sal.hex()}${h.hex()}"


def conferir(senha: str, guardado: str) -> bool:
    try:
        _, n, r, p, sal, h = guardado.split("$")
        calc = hashlib.scrypt(senha.encode(), salt=bytes.fromhex(sal), n=int(n), r=int(r), p=int(p), dklen=len(h) // 2)
        return hmac.compare_digest(calc.hex(), h)
    except (ValueError, TypeError):
        return False


def senha_provisoria() -> str:
    """Fácil de ditar: 3 blocos sem letras parecidas (0/O, 1/l)."""
    alfabeto = "abcdefghjkmnpqrstuvwxyz23456789"
    return "-".join("".join(secrets.choice(alfabeto) for _ in range(4)) for _ in range(3))


def validar_senha(senha: str, login: str = "") -> None:
    if len(senha) < SENHA_MIN:
        raise ErroUsuario(f"A senha precisa ter pelo menos {SENHA_MIN} caracteres.")
    if login and login.lower() in senha.lower():
        raise ErroUsuario("A senha não pode conter o nome de usuário.")
    if senha.lower() in {"12345678", "123456789", "senha123", "odonto123", "clinica123", "password"}:
        raise ErroUsuario("Essa senha é fácil demais de adivinhar. Escolha outra.")


def normalizar_login(login: str) -> str:
    login = (login or "").strip().lower()
    if not re.fullmatch(r"[a-z0-9._-]{3,40}", login):
        raise ErroUsuario("Use de 3 a 40 letras minúsculas, números, ponto, hífen ou sublinhado no usuário (ex.: ana.souza).")
    return login


def criar(s: Session, login: str, nome: str, papel: str, senha: str | None = None, criado_por: str | None = None,
          trocar_senha: bool = True) -> tuple[Usuario, str]:
    login = normalizar_login(login)
    if s.scalar(select(Usuario).where(Usuario.login == login)):
        raise ErroUsuario(f"Já existe o usuário “{login}”.")
    if papel not in PAPEIS:
        raise ErroUsuario("Papel inválido.")
    if not nome.strip():
        raise ErroUsuario("Informe o nome da pessoa.")
    senha = senha or senha_provisoria()
    u = Usuario(login=login, nome=" ".join(nome.split())[:120], papel=papel, senha_hash=gerar_hash(senha),
                trocar_senha=trocar_senha, criado_por=criado_por, ativo=True, tentativas_falhas=0)
    s.add(u)
    s.flush()
    return u, senha


def coordenadores_ativos(s: Session) -> int:
    return s.scalar(select(func.count(Usuario.id)).where(Usuario.papel == "coordenacao", Usuario.ativo)) or 0


def autenticar(s: Session, login: str, senha: str) -> Usuario:
    agora = config.agora()
    u = s.scalar(select(Usuario).where(Usuario.login == (login or "").strip().lower()))
    if u and u.bloqueado_ate and u.bloqueado_ate > agora:
        minutos = int((u.bloqueado_ate - agora).total_seconds() // 60) + 1
        raise ErroUsuario(f"Muitas tentativas erradas. Tente de novo em {minutos} min ou peça à coordenação para redefinir a senha.")
    if not u or not conferir(senha, u.senha_hash):
        if u:
            u.tentativas_falhas = (u.tentativas_falhas or 0) + 1
            if u.tentativas_falhas >= TENTATIVAS_MAX:
                u.bloqueado_ate, u.tentativas_falhas = agora + BLOQUEIO, 0
        raise ErroUsuario("Usuário ou senha incorretos.")
    if not u.ativo:
        raise ErroUsuario("Este usuário foi desativado. Fale com a coordenação.")
    u.tentativas_falhas, u.bloqueado_ate, u.ultimo_acesso_em = 0, None, agora
    return u


def criar_iniciais(s: Session) -> int:
    """Primeira execução: cria os usuários do .env (USUARIOS), já pedindo troca de senha."""
    if s.scalar(select(func.count(Usuario.id))):
        return 0
    n = 0
    for login, (senha, papel) in config.usuarios().items():
        try:
            criar(s, login, login.capitalize(), papel if papel in PAPEIS else "recepcao", senha=senha, criado_por="instalação",
                  trocar_senha=config.TROCAR_SENHA_INICIAL)
            n += 1
        except ErroUsuario:
            continue
    return n
