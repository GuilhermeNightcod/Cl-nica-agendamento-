"""Tipos de mensagem que o bot envia (independentes do WhatsApp)."""
from dataclasses import dataclass, field


@dataclass
class Texto:
    texto: str


@dataclass
class Botoes:
    """Até 3 botões de resposta rápida. opcoes = [(id, titulo)]."""

    texto: str
    opcoes: list[tuple[str, str]]


@dataclass
class Lista:
    """Menu em lista, até 10 itens. opcoes = [(id, titulo, descricao)]."""

    texto: str
    botao: str
    opcoes: list[tuple[str, str, str]]


@dataclass
class Modelo:
    """Template aprovado pela Meta (necessário fora da janela de 24h)."""

    nome: str
    parametros: list[str] = field(default_factory=list)
    texto_resumo: str = ""
    # payload de cada botão de resposta rápida do template (na ordem dos botões)
    payloads_botoes: list[str] = field(default_factory=list)


Resposta = Texto | Botoes | Lista | Modelo


@dataclass
class Entrada:
    """Mensagem recebida do paciente, já normalizada."""

    telefone: str
    texto: str = ""
    id_opcao: str | None = None  # id do botão/item escolhido
    tipo: str = "text"  # text | interactive | button | audio | image | ...
    nome_perfil: str | None = None
    wa_message_id: str | None = None


def resumo(r: Resposta) -> str:
    """Versão em texto puro (para histórico e Chatwoot)."""
    if isinstance(r, Texto):
        return r.texto
    if isinstance(r, Botoes):
        return r.texto + "\n" + " | ".join(f"[{t}]" for _, t in r.opcoes)
    if isinstance(r, Lista):
        return r.texto + "\n" + "\n".join(f"- {t}" for _, t, _ in r.opcoes)
    return f"[modelo {r.nome}] {r.texto_resumo}"
