# Arquitetura (para o programador)

## Visão geral

- **bot/**: Python 3.12, FastAPI, SQLAlchemy 2, PostgreSQL (SQLite em testes e no simulador).
- **WhatsApp**: integração direta com a **Cloud API** da Meta (`app/whatsapp.py`), sem BSP.
- **Atendimento humano**: nativo (`app/atendimentos.py` + `app/web/atendimento_rotas.py`): tickets com
  status fila → em_atendimento → finalizado, setores, etiquetas, TME/TMA. A tela faz polling de fragmentos
  HTML a cada 5 s. O Chatwoot continua suportado como espelho **opcional** (profile `chatwoot` no compose).
- **Rotinas**: loop asyncio dentro do processo (`app/tarefas.py`), executado a cada `INTERVALO_TAREFAS_MIN`.
- **Sistema da clínica**: telas server-side (Jinja2) em `app/web/rotas.py`, login por cookie de sessão
  (Starlette `SessionMiddleware`), usuários e papéis vindos de `USUARIOS` no `.env`.

```
app/
  main.py        app FastAPI, webhooks (/webhook Meta, /chatwoot/webhook), /saude
  web/rotas.py   telas: agenda, agendar, pacientes + prontuário, espera, painel, clínicas, acessos
  atendimentos.py regras do atendimento humano (fila, assumir, responder, janela de 24h, finalizar)
  web/atendimento_rotas.py  caixa de entrada, painel tempo real, setores/etiquetas
  agenda.py      regras da agenda (gerar datas, vagas disponíveis, agendar, cancelar) — usada pelo bot e pela web
  fila.py        filas por paciente (hash do telefone -> thread): ordem garantida por paciente
  servico.py     orquestra: fluxo -> envio WhatsApp -> Chatwoot
  fluxo.py       máquina de estados da conversa (função pura sobre a Session)
  textos.py      todas as mensagens (editável por não-programadores)
  mensagens.py   tipos neutros: Texto, Botoes, Lista, Modelo, Entrada
  whatsapp.py    payloads da Cloud API, verificação HMAC, parsing do webhook
  chatwoot.py    cliente da API do Chatwoot (contatos, conversas, mensagens)
  tarefas.py     lembretes (template) e recuperação (dentro da janela de 24h)
  dados.py       importa CSVs (especialidades, procedimentos, grade inicial, feriados) e gera as vagas
  models.py      tabelas (ver abaixo)
  templates/     HTML das telas
```

## Modelo de dados

```
Especialidade 1─N Procedimento
SessaoClinica N─N Especialidade        (turma, dia_semana, hora_inicio/fim, professor, vagas, idade_min/max)
SessaoClinica N─1 EspacoClinico        (clínica física com nº de boxes; turmas simultâneas somam duplas)
SessaoClinica 1─N Vaga                 (uma data concreta; capacidade, ocupadas, bloqueada)
Vaga          1─N Agendamento N─1 Paciente   (especialidade, procedimento, aluno, origem bot|recepcao, status)
Paciente      1─N Documento            (prontuário digitalizado: arquivo no disco em ARQUIVOS_DIR)
Paciente      1─1 Conversa             (estado do bot)
Paciente      1─N RegistroDente        (odontograma: dente FDI ou região, faces MODVL, status, aluno, anotação)
Paciente      1─N Atendimento N─1 Setor, N─N Etiqueta   (atendimento humano do WhatsApp)
Mensagem      N─1 Atendimento          (autor: bot | login do atendente | None = paciente)
Agendamento.hora                       (horário de chegada do paciente dentro da clínica)
RegistroAcesso                         (LGPD: usuário, ação, paciente, quando)
```

- `gerar_vagas` é idempotente: cria as datas que faltam, atualiza horário e capacidade, apaga datas
  futuras sem agendamentos e **bloqueia** (nunca apaga) datas com agendamentos que deixaram de existir.
  Esses pacientes aparecem em Indicadores → "remarcar".
- A grade de `sessoes_clinica.csv` só é importada com a tabela vazia. Depois a fonte da verdade é a tela Clínicas.
- Upload: o tipo do arquivo é validado pelos primeiros bytes (JPG/PNG/PDF), não pela extensão. Os arquivos
  recebem nome aleatório e só são servidos por rota autenticada, com registro de acesso.

## Visual

- Estilos em `app/static/estilo.css` (tokens no topo). Fonte Atkinson Hyperlegible Next servida localmente
  (`app/static/fontes`, licença OFL), sem chamar o Google na hora do uso.
- Paleta: verde campo cirúrgico `#1f4f47`, rosa gengiva `#c24d6b` (destaque), esmalte `#f5f8f7`, tinta `#1b2826`.
- Turmas com cores de papel articular (carbono): azul `#3557c9`, verde `#2e8a6e`, ameixa `#8e3f82`.
- Ocupação mostrada como fileira de boxes (`.boxes`): um quadrado por vaga; rosa = encaixe acima do limite.

## Decisões e por quê

| Decisão | Motivo |
|---|---|
| Bot fala direto com a Cloud API (o Chatwoot não é o dono do número) | Controle total sobre os botões e listas interativos, templates com payload e deduplicação. O Chatwoot entra só como caixa de entrada humana |
| Fluxo determinístico (botões e listas), sem LLM | Previsível, auditável e sem risco de "conselho clínico". A IA pode entrar depois só para classificar texto livre |
| Escolha aceita id do botão, número digitado ou o texto do título | Funciona no simulador e quando o paciente digita em vez de tocar |
| `Mensagem.wa_message_id` único | A Meta reenvia webhooks; é a deduplicação |
| Fila por paciente | Mensagens rápidas em sequência eram processadas fora de ordem com BackgroundTasks |
| Recuperação só dentro de 24h | Mensagem de sessão é grátis e não precisa de template; fora disso, o paciente fica no painel |
| Payload `confirma:<id>` / `remarca:<id>` nos botões do template | Liga a resposta ao agendamento certo sem depender de estado |
| Horários guardados em hora local, sem fuso | Uma clínica = um fuso. Se virar SaaS multi-região, migrar para UTC + fuso por clínica |

## Estados da conversa

`inicio → privacidade → menu → nome → nascimento → queixa → especialidade → turno → horario → confirmar`
mais `sem_vaga`, `meus`, `cancelar`, `recuperacao` e `humano`.
Atalhos que valem em qualquer estado: palavras de urgência, pedido de atendente, "menu"/"oi"
e as respostas aos botões do lembrete.

## Integração com o Chatwoot

1. Handoff: `POST /contacts` (ou search) → `POST /conversations` → nota privada com resumo e histórico.
2. Paciente em modo humano: `POST /conversations/{id}/messages` com `message_type=incoming`.
3. Webhook `message_created` (outgoing, não privada) → envia pelo WhatsApp.
4. Webhook `conversation_status_changed` com `resolved` → devolve o paciente ao bot.

Os ids de conversa do Chatwoot são o `display_id` (é o que a API e os webhooks expõem).

## Testes

```bash
cd bot
pip install -r requirements-dev.txt
pytest
```
Cobrem o fluxo completo, urgência e handoff, eventos do Chatwoot, lista de espera, cancelamento,
lembrete e confirmação, recuperação, validação de datas, webhook (assinatura, verificação,
deduplicação, ordem) e os limites de tamanho do WhatsApp.

## Dívidas técnicas / próximos passos

- **Migrações**: hoje usa `create_all`. Adotar **Alembic** antes de ir para produção.
- **Usuários**: tabela `usuarios`, senha com scrypt (stdlib), senha provisória com troca obrigatória,
  bloqueio de 15 min após 5 erros, usuário desativado perde a sessão na hora (conferido a cada requisição).
  Falta: recuperação de senha por e-mail e autenticação em dois fatores.
- **Armazenamento**: arquivos no disco local. Para várias máquinas ou backup fácil, usar S3/MinIO com criptografia.
- **Prontuário com valor legal**: assinatura ICP-Brasil (Lei 13.787/2018) se a faculdade quiser descartar o papel.
- **Vários processos**: a fila é por processo. Para escalar horizontalmente, usar Redis/RQ
  com particionamento por telefone, ou `SELECT ... FOR UPDATE` no paciente.
- **Token da Meta**: usar token de usuário do sistema e guardar em um gerenciador de segredos.
- **Multi-clínica (SaaS)**: adicionar `clinica_id` em todas as tabelas e roteamento por `phone_number_id`.
- **LGPD**: login individual no painel, log de acesso, política de retenção e exclusão a pedido.
- **Mídia**: transcrever áudio (Whisper) e encaminhar fotos ao humano.
- **Webhook de status** (entregue/lido/falhou) para medir a entrega dos lembretes.
