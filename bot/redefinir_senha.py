"""
Gera uma senha provisória para um usuário (uso no servidor, quando ninguém da coordenação consegue entrar).
    docker compose exec bot python redefinir_senha.py coordenacao
"""
import sys

from sqlalchemy import select

from app.db import sessao
from app.models import RegistroAcesso, Usuario
from app.usuarios import gerar_hash, senha_provisoria

if len(sys.argv) != 2:
    sys.exit("Uso: python redefinir_senha.py LOGIN")
with sessao() as s:
    u = s.scalar(select(Usuario).where(Usuario.login == sys.argv[1].strip().lower()))
    if not u:
        sys.exit(f"Usuário '{sys.argv[1]}' não encontrado.")
    senha = senha_provisoria()
    u.senha_hash, u.trocar_senha, u.ativo, u.tentativas_falhas, u.bloqueado_ate = gerar_hash(senha), True, True, 0, None
    s.add(RegistroAcesso(usuario="servidor", acao="redefiniu senha pelo terminal", detalhe=u.login))
print(f"Senha provisória de {u.login}: {senha}  (o sistema pede para trocar no primeiro acesso)")
