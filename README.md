# 🦷 Central Inteligente de Atendimento Odontológico

Atendimento automático pelo **WhatsApp (API oficial da Meta)**, agenda centralizada,
lembretes, recuperação de pacientes, atendimento humano e painel para a coordenação,
feito para **clínicas-escola de Odontologia**.

> Este README foi escrito para quem **não programa**. A parte técnica para o
> programador está em [`docs/ARQUITETURA.md`](docs/ARQUITETURA.md).

---

## O que já funciona

| Função | Como funciona |
|---|---|
| **Resposta imediata** | O bot responde na hora com boas-vindas e menu |
| **Aviso de privacidade (LGPD)** | O paciente precisa concordar antes de informar dados |
| **Cadastro** | Pergunta nome, data de nascimento e motivo da consulta |
| **Agendamento** | Paciente escolhe especialidade → turno → horário livre → confirma |
| **Lista de espera** | Se não houver vaga, oferece entrar na lista |
| **Meus agendamentos** | Paciente vê e cancela as próprias consultas (a vaga é liberada) |
| **Urgência** | Palavras como "inchaço", "sangramento" e "muita dor" chamam um humano na hora |
| **Atendimento humano** | O paciente vai para o **Chatwoot**, onde a recepção responde |
| **Lembrete** | Mensagem automática 24h antes, com botões **Confirmo** / **Remarcar** |
| **Recuperação** | Quem parou no meio do agendamento recebe um "quer continuar?" |
| **Painel** | Indicadores, próximos agendamentos, faltas, lista de espera e pendentes |
| **Exportar para Excel** | Botão no painel baixa todos os agendamentos |

---

## Como as peças se conectam

```
 Paciente no WhatsApp
        │
        ▼
 Meta (WhatsApp Cloud API oficial)
        │  webhook
        ▼
 ┌───────────────────────┐       ┌──────────────────────────┐
 │  BOT  (pasta bot/)    │◄─────►│  CHATWOOT                │
 │  fluxo da conversa    │       │  recepção responde aqui  │
 │  agenda e vagas       │       └──────────────────────────┘
 │  lembretes            │
 │  painel /painel       │──► PostgreSQL (banco de dados)
 └───────────────────────┘
```

Todos os programas usados são de **código aberto**:

| Programa | Para quê | Licença |
|---|---|---|
| Python + FastAPI | o bot e o painel | MIT/BSD ✅ |
| PostgreSQL | banco de dados | PostgreSQL (livre) ✅ |
| Chatwoot (edição *Community*) | caixa de atendimento humano | MIT ✅ |
| Redis | fila interna do Chatwoot | BSD/RSAL (uso interno ok) ✅ |
| Cloudflared | endereço público temporário para testes | Apache 2.0 ✅ |

---

## Mudar o bot sem programar ✏️

| Quero mudar... | Arquivo | Como |
|---|---|---|
| **As mensagens do bot** | `bot/app/textos.py` | Edite o texto entre aspas. Não apague `{nome}`, `{clinica}` etc. |
| **As especialidades** | `bot/dados/especialidades.csv` | Abre no Excel. Coluna `ativa` = sim/nao |
| **Dias, horários e vagas** | `bot/dados/grade_horarios.csv` | Uma linha por horário: especialidade; dia (seg, ter...); hora; vagas |
| **Feriados** | `bot/dados/feriados.csv` | Data e descrição. Nesses dias não abre vaga |
| **Datas do semestre, senhas** | `.env` | Veja o passo 2 |

Depois de mudar as planilhas, clique em **"Recarregar agenda"** no painel.
Depois de mudar `textos.py`, reinicie o bot com `docker compose restart bot`.

> 💡 Ao salvar o CSV no Excel, escolha **"CSV UTF-8 (separado por vírgulas)"** para os acentos não quebrarem.

---

## Passo a passo para colocar no ar

### Passo 0: o que você precisa
- Um computador ou servidor com **Docker** instalado ([docker.com](https://www.docker.com/products/docker-desktop/)).
- Uma conta no **Meta for Developers** ([developers.facebook.com](https://developers.facebook.com)).

### Passo 1: testar sem WhatsApp (simulador)
Você conversa com o bot direto no terminal:
```bash
cd bot
pip install -r requirements.txt
python simular.py
```
Digite `oi` e responda com os **números** das opções. Comandos: `/reset` (começar de novo),
`/tarefas` (roda lembretes e recuperação), `/sair`.

### Passo 2: configurar
```bash
cp .env.example .env
```
Abra o `.env` e preencha pelo menos: `POSTGRES_PASSWORD`, `CHATWOOT_SECRET_KEY_BASE`,
`PAINEL_SENHA`, `SEMESTRE_INICIO` e `SEMESTRE_FIM`.

### Passo 3: subir tudo
```bash
docker compose up -d
```
- Painel do bot: <http://localhost:8000/painel> (usuário e senha do `.env`)
- Chatwoot: <http://localhost:3000> (na primeira vez ele pede para criar o usuário administrador; demora cerca de 1 minuto para abrir)

### Passo 4: ligar o Chatwoot ao bot
1. No Chatwoot: **Configurações → Caixas de entrada → Adicionar → API**.
   - Nome: `WhatsApp Clínica`
   - **URL do Webhook:** `http://bot:8000/chatwoot/webhook?token=SEU_CHATWOOT_WEBHOOK_TOKEN`
2. Adicione os atendentes (recepção) à caixa.
3. Anote o **número da caixa**, que aparece no endereço da página (`.../inboxes/`**`1`**`/settings`), e coloque em `CHATWOOT_INBOX_ID`.
4. No seu perfil (canto inferior esquerdo): **Configurações do perfil → Token de acesso**. Copie para `CHATWOOT_API_TOKEN`.
5. Em **Configurações → Integrações → Webhooks**, adicione a mesma URL do item 1 marcando **"Status da conversa alterado"**. É isso que devolve o paciente ao bot quando a recepção clica em **Resolver**.
6. Reinicie o bot: `docker compose restart bot`.

### Passo 5: conectar o WhatsApp (número de teste grátis da Meta)
1. Em [developers.facebook.com](https://developers.facebook.com): **Meus apps → Criar app → tipo Empresa → adicionar o produto WhatsApp**.
2. Em **WhatsApp → Configuração da API**, copie:
   - o **Token de acesso temporário** → `WHATSAPP_TOKEN`
   - a **Identificação do número de telefone** → `WHATSAPP_PHONE_NUMBER_ID`
3. Em **Configurações do app → Básico**, copie a **Chave secreta do aplicativo** → `WHATSAPP_APP_SECRET`.
4. Cadastre o seu celular no campo **"Para"** (até 5 números de teste).
5. Ligue o endereço público temporário e pegue a URL:
   ```bash
   docker compose --profile tunel up -d
   ```
   ```bash
   docker compose logs tunel | grep trycloudflare
   ```
6. Em **WhatsApp → Configuração → Webhook**:
   - **URL de callback:** `https://ENDERECO-QUE-APARECEU.trycloudflare.com/webhook`
   - **Token de verificação:** o mesmo `WHATSAPP_VERIFY_TOKEN` do `.env`
   - Clique em **Verificar e salvar** e depois **assine o campo `messages`**.
7. Reinicie o bot (`docker compose restart bot`) e mande **"oi"** do seu celular para o número de teste. 🎉

> ⚠️ O endereço `trycloudflare.com` muda toda vez que reinicia e serve **só para teste**.
> Em produção, use um servidor com domínio próprio e HTTPS.

> ⚠️ O token temporário expira em 24h. Para uso contínuo, crie um **usuário do sistema**
> no Meta Business (Configurações do negócio → Usuários do sistema) e gere um token permanente.

### Passo 6: criar o modelo de lembrete na Meta
Lembretes são enviados fora da janela de 24h, então precisam de um **modelo aprovado**.
No **Gerenciador do WhatsApp → Modelos de mensagem → Criar**:

- **Nome:** `lembrete_consulta` · **Categoria:** Utilidade · **Idioma:** Português (BR)
- **Corpo:**
  ```
  Olá {{1}}! Lembrete da sua consulta de {{2}} na clínica-escola: {{3}} às {{4}}. Você confirma sua presença?
  ```
- **Botões** (resposta rápida, nesta ordem): `Confirmo` e `Remarcar`

Depois que for aprovado, o bot passa a enviá-lo sozinho.

---

## Painel da coordenação

Endereço: `/painel`. Mostra:
- novos contatos, agendamentos, **% de contatos que agendaram** e **taxa de faltas**;
- próximos agendamentos, com botões **Compareceu**, **Faltou** e **Cancelar** (a recepção marca no dia);
- ocupação das vagas por especialidade nas próximas 4 semanas;
- lista de espera;
- quem está aguardando atendente e quem abandonou o agendamento.

---

## Comandos úteis

| Para... | Comando |
|---|---|
| Ver se está tudo rodando | `docker compose ps` |
| Ver o que o bot está fazendo | `docker compose logs -f bot` |
| Reiniciar o bot | `docker compose restart bot` |
| Desligar tudo | `docker compose down` |
| Rodar os testes automáticos | `cd bot && pip install -r requirements-dev.txt && pytest` |

## Problemas comuns

- **A Meta não verifica o webhook:** confira se o `WHATSAPP_VERIFY_TOKEN` é igual nos dois lugares e se o túnel está ligado.
- **O bot recebe mas não responde:** veja `docker compose logs bot`. Geralmente é o token expirado (24h).
- **Erro "recipient not in allowed list":** cadastre o número no campo "Para". Com números do Brasil, às vezes é preciso cadastrar **sem o 9** depois do DDD.
- **O Chatwoot não recebe os pacientes:** confira `CHATWOOT_API_TOKEN` e `CHATWOOT_INBOX_ID` no `.env` e reinicie o bot.

---

## Próximos passos sugeridos

- [ ] Painel para a recepção **editar vagas** sem mexer em planilha
- [ ] Avisar automaticamente quem está na **lista de espera** quando abrir vaga
- [ ] Ligar a **triagem** às disciplinas e turmas do semestre
- [ ] IA para entender mensagens livres ("meu dente quebrou" → especialidade certa)
- [ ] Login individual por funcionário no painel e registro de acessos (LGPD)
- [ ] Hospedagem em servidor com domínio e HTTPS + backup diário do banco
