"""Configurações lidas das variáveis de ambiente (arquivo .env)."""
import os
from datetime import date, datetime
from zoneinfo import ZoneInfo


def _env(nome: str, padrao: str = "") -> str:
    return os.getenv(nome, padrao).strip()


# --- Clínica ---------------------------------------------------------------
NOME_CLINICA = _env("NOME_CLINICA", "Clínica-Escola de Odontologia")
FUSO = ZoneInfo(_env("FUSO_HORARIO", "America/Sao_Paulo"))
SEMESTRE_INICIO = date.fromisoformat(_env("SEMESTRE_INICIO", "2026-08-03"))
SEMESTRE_FIM = date.fromisoformat(_env("SEMESTRE_FIM", "2026-12-11"))
DIAS_ANTECEDENCIA_MIN = int(_env("DIAS_ANTECEDENCIA_MIN", "1"))
MAX_HORARIOS_OFERECIDOS = int(_env("MAX_HORARIOS_OFERECIDOS", "5"))
# Como o bot trata quem quer agendar:
#   triagem -> coleta dados, motivo e turno e manda para a fila "Triagem" da recepção (a ASB agenda)
#   direto  -> o próprio paciente escolhe área e horário pelo WhatsApp
MODO_AGENDAMENTO_BOT = _env("MODO_AGENDAMENTO_BOT", "triagem").lower()
SETOR_TRIAGEM = _env("SETOR_TRIAGEM", "Triagem (ASB)")

# --- Banco de dados --------------------------------------------------------
DATABASE_URL = _env("DATABASE_URL", "sqlite:///./odonto.db")

# --- WhatsApp Cloud API (oficial da Meta) ----------------------------------
WHATSAPP_TOKEN = _env("WHATSAPP_TOKEN")
WHATSAPP_PHONE_NUMBER_ID = _env("WHATSAPP_PHONE_NUMBER_ID")
WHATSAPP_VERIFY_TOKEN = _env("WHATSAPP_VERIFY_TOKEN", "troque-este-token")
WHATSAPP_APP_SECRET = _env("WHATSAPP_APP_SECRET")
WHATSAPP_API_VERSION = _env("WHATSAPP_API_VERSION", "v23.0")

# Modelo de mensagem (template) aprovado na Meta para o lembrete.
TEMPLATE_LEMBRETE = _env("TEMPLATE_LEMBRETE", "lembrete_consulta")
TEMPLATE_IDIOMA = _env("TEMPLATE_IDIOMA", "pt_BR")
# Template opcional enviado quando a RECEPÇÃO agenda (fora da janela de 24h). Vazio = não envia.
TEMPLATE_AGENDAMENTO = _env("TEMPLATE_AGENDAMENTO")
# Template opcional para o ATENDENTE iniciar conversa fora da janela de 24h. Vazio = não envia.
TEMPLATE_CONTATO = _env("TEMPLATE_CONTATO")

# --- Rotinas automáticas ---------------------------------------------------
LEMBRETE_HORAS_ANTES = int(_env("LEMBRETE_HORAS_ANTES", "24"))
RECUPERACAO_APOS_HORAS = float(_env("RECUPERACAO_APOS_HORAS", "2"))
INTERVALO_TAREFAS_MIN = int(_env("INTERVALO_TAREFAS_MIN", "10"))

# --- Chatwoot (atendimento humano) - opcional ------------------------------
CHATWOOT_URL = _env("CHATWOOT_URL").rstrip("/")
CHATWOOT_API_TOKEN = _env("CHATWOOT_API_TOKEN")
CHATWOOT_ACCOUNT_ID = _env("CHATWOOT_ACCOUNT_ID", "1")
CHATWOOT_INBOX_ID = _env("CHATWOOT_INBOX_ID")
CHATWOOT_WEBHOOK_TOKEN = _env("CHATWOOT_WEBHOOK_TOKEN", "troque-este-token")

# --- Sistema da clínica (recepção / coordenação) ---------------------------
# Usuários no formato  login:senha:papel  separados por vírgula.
# Papéis: recepcao | coordenacao  (coordenação também configura as clínicas)
USUARIOS = _env("USUARIOS", "coordenacao:troque-esta-senha:coordenacao,recepcao:troque-esta-senha:recepcao")
CHAVE_SESSAO = _env("CHAVE_SESSAO", "troque-por-um-texto-aleatorio")
# Os usuários de USUARIOS só são usados na PRIMEIRA vez que o sistema liga; depois, a coordenação
# cria e gerencia os logins na tela "Usuários". No primeiro acesso cada um troca a senha.
TROCAR_SENHA_INICIAL = _env("TROCAR_SENHA_INICIAL", "sim").lower() not in ("nao", "não", "0", "false")
ARQUIVOS_DIR = _env("ARQUIVOS_DIR", "./arquivos")
# Endereço do sistema que aparece nos cartões de login dos alunos (ex.: odonto.suafaculdade.edu.br)
ENDERECO_SITE = _env("ENDERECO_SITE")
TAMANHO_MAX_ARQUIVO_MB = int(_env("TAMANHO_MAX_ARQUIVO_MB", "20"))


def usuarios() -> dict[str, tuple[str, str]]:
    """{login: (senha, papel)}"""
    res = {}
    for item in USUARIOS.split(","):
        partes = item.strip().split(":")
        if len(partes) >= 2 and partes[0]:
            res[partes[0]] = (partes[1], partes[2] if len(partes) > 2 else "recepcao")
    return res


def chatwoot_ativo() -> bool:
    return bool(CHATWOOT_URL and CHATWOOT_API_TOKEN and CHATWOOT_INBOX_ID)


def agora() -> datetime:
    """Data/hora local da clínica, sem fuso (o banco guarda horário local)."""
    return datetime.now(FUSO).replace(tzinfo=None, microsecond=0)
