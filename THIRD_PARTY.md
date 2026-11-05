# Componentes de terceiros

O Central Odonto é software proprietário (veja `LICENSE`), mas usa os componentes abaixo,
que continuam sob as suas próprias licenças:

| Componente | Uso | Licença |
|---|---|---|
| FastAPI, Starlette | servidor web | MIT / BSD-3 |
| Uvicorn | servidor HTTP | BSD-3 |
| SQLAlchemy | banco de dados | MIT |
| psycopg | conexão com PostgreSQL | LGPL-3.0 (usado como biblioteca, sem modificação) |
| httpx | chamadas à API do WhatsApp | BSD-3 |
| Jinja2, itsdangerous | telas e sessão de login | BSD-3 |
| python-multipart | envio de arquivos | Apache-2.0 |
| tzdata | fuso horário | Apache-2.0 |
| Atkinson Hyperlegible Next (fonte) | tipografia das telas | SIL Open Font License 1.1 — texto em `bot/app/static/fontes/OFL.txt` |
| PostgreSQL (imagem Docker) | banco de dados | PostgreSQL License |
| Chatwoot CE (opcional) | caixa de atendimento alternativa | MIT |
| Redis (opcional, com Chatwoot) | fila do Chatwoot | BSD-3 / RSALv2 |
| Cloudflared (opcional) | túnel para testes | Apache-2.0 |
