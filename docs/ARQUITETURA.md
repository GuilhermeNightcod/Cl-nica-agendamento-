# Arquitetura (para o programador)

## Visão geral

- **bot/**: Python 3.12, FastAPI, SQLAlchemy 2, PostgreSQL (SQLite em testes e no simulador).
- **WhatsApp**: integração direta com a **Cloud API** da Meta (`app/whatsapp.py`), sem BSP.
- **Atendimento humano**: Chatwoot CE, com uma caixa de entrada do tipo **API**. O bot é dono do
  número do WhatsApp e "espelha" a conversa no Chatwoot só durante o atendimento humano.
- **Rotinas**: loop asyncio dentro do processo (`app/tarefas.py`), executado a cada `INTERVALO_TAREFAS_MIN`.

```
app/
  main.py        rotas HTTP: /webhook (Meta), /chatwoot/webhook, /painel, /saude
  fila.py        filas por paciente (hash do telefone -> thread): ordem garantida por paciente
  servico.py     orquestra: fluxo -> envio WhatsApp -> Chatwoot
  fluxo.py       máquina de estados da conversa (função pura sobre a Session)
  textos.py      todas as mensagens (editável por não-programadores)
  mensagens.py   tipos neutros: Texto, Botoes, Lista, Modelo, Entrada
  whatsapp.py    payloads da Cloud API, verificação HMAC, parsing do webhook
  chatwoot.py    cliente da API do Chatwoot (contatos, conversas, mensagens)
  tarefas.py     lembretes (template) e recuperação (dentro da janela de 24h)
  dados.py       importa CSVs -> especialidades e vagas do semestre (idempotente)
  models.py      Paciente, Conversa, Especialidade, Vaga, Agendamento, ListaEspera, Mensagem
```

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
- **Vários processos**: a fila é por processo. Para escalar horizontalmente, usar Redis/RQ
  com particionamento por telefone, ou `SELECT ... FOR UPDATE` no paciente.
- **Token da Meta**: usar token de usuário do sistema e guardar em um gerenciador de segredos.
- **Multi-clínica (SaaS)**: adicionar `clinica_id` em todas as tabelas e roteamento por `phone_number_id`.
- **LGPD**: login individual no painel, log de acesso, política de retenção e exclusão a pedido.
- **Mídia**: transcrever áudio (Whisper) e encaminhar fotos ao humano.
- **Webhook de status** (entregue/lido/falhou) para medir a entrega dos lembretes.
