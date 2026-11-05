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

# --- Painel ----------------------------------------------------------------
PAINEL_USUARIO = _env("PAINEL_USUARIO", "coordenacao")
PAINEL_SENHA = _env("PAINEL_SENHA", "troque-esta-senha")


def chatwoot_ativo() -> bool:
    return bool(CHATWOOT_URL and CHATWOOT_API_TOKEN and CHATWOOT_INBOX_ID)


def agora() -> datetime:
    """Data/hora local da clínica, sem fuso (o banco guarda horário local)."""
    return datetime.now(FUSO).replace(tzinfo=None, microsecond=0)
