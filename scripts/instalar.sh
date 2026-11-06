#!/usr/bin/env bash
# Instala/atualiza a Central Odonto no servidor (Ubuntu com Docker).
# Uso:  sudo bash scripts/instalar.sh centralodonto.tech
set -euo pipefail
cd "$(dirname "$0")/.."
DOMINIO="${1:-}"

if ! command -v docker >/dev/null; then
  echo "Instalando Docker..."; curl -fsSL https://get.docker.com | sh
fi

if [ ! -f .env ]; then
  [ -n "$DOMINIO" ] || { echo "Informe o domínio: sudo bash scripts/instalar.sh seudominio.com.br"; exit 1; }
  senha_coord="$(openssl rand -base64 18 | tr -dc 'a-zA-Z0-9' | head -c 16)"
  cp .env.example .env
  sed -i \
    -e "s|^DOMINIO=.*|DOMINIO=${DOMINIO}|" \
    -e "s|^ENDERECO_SITE=.*|ENDERECO_SITE=${DOMINIO}|" \
    -e "s|^COOKIE_SEGURO=.*|COOKIE_SEGURO=sim|" \
    -e "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$(openssl rand -hex 24)|" \
    -e "s|^CHAVE_SESSAO=.*|CHAVE_SESSAO=$(openssl rand -hex 32)|" \
    -e "s|^CHATWOOT_SECRET_KEY_BASE=.*|CHATWOOT_SECRET_KEY_BASE=$(openssl rand -hex 64)|" \
    -e "s|^WHATSAPP_VERIFY_TOKEN=.*|WHATSAPP_VERIFY_TOKEN=$(openssl rand -hex 16)|" \
    -e "s|^CHATWOOT_WEBHOOK_TOKEN=.*|CHATWOOT_WEBHOOK_TOKEN=$(openssl rand -hex 16)|" \
    -e "s|^USUARIOS=.*|USUARIOS=coordenacao:${senha_coord}:coordenacao|" \
    .env
  chmod 600 .env
  echo
  echo "================================================================"
  echo " .env criado. PRIMEIRO LOGIN (anote e guarde em lugar seguro):"
  echo "   usuário: coordenacao    senha provisória: ${senha_coord}"
  echo " No primeiro acesso o sistema pede para trocar a senha."
  echo " Revise as datas do semestre e o NOME_CLINICA em .env"
  echo "================================================================"
  echo
fi

docker compose --profile producao up -d --build
echo "Pronto. Acesse https://$(grep '^DOMINIO=' .env | cut -d= -f2)  (o certificado HTTPS pode levar 1 minuto)."
