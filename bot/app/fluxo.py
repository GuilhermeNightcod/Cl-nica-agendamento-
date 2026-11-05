"""
O FLUXO DA CONVERSA — o "cérebro" do bot.

Cada paciente tem uma Conversa com um `estado` (em que passo ele está).
A função `processar` recebe a mensagem do paciente, olha o estado atual,
decide o que responder e qual será o próximo estado.

    inicio ─► privacidade ─► menu ─┬─► agendar: nome ─► nascimento ─► queixa
                                   │        ─► especialidade ─► turno ─► horario ─► confirmar
                                   ├─► especialidades (informações)
                                   ├─► meus agendamentos ─► cancelar
                                   └─► atendente humano
"""
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import config, textos as T
from .mensagens import Botoes, Entrada, Lista, Resposta, Texto, resumo
from .agenda import VagaIndisponivel, agendamentos_futuros, agendar, cancelar as cancelar_agendamento, especialidades_atendidas, vagas_disponiveis
from .models import Agendamento, Conversa, Especialidade, ListaEspera, Mensagem, Paciente, Vaga

DIAS = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]
DIAS_LONGOS = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo"]
TIPOS_MIDIA = {"audio", "image", "video", "document", "sticker", "location", "contacts"}


@dataclass
class Resultado:
    respostas: list[Resposta] = field(default_factory=list)
    chamar_humano: str | None = None  # motivo, quando o bot passou para um humano agora
    repassar_para_humano: bool = False  # paciente já está com humano: só repassar a mensagem
    duplicada: bool = False


# --------------------------------------------------------------------------- utilidades
def normalizar(texto: str) -> str:
    t = unicodedata.normalize("NFKD", texto or "")
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    t = re.sub(r"[^\w\s/]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def contem_expressao(texto_normalizado: str, expressao: str) -> bool:
    """
    Procura a expressão aceitando até 2 palavras no meio:
    "rosto inchado" encontra "rosto muito inchado" e "rosto todo bem inchado".
    """
    palavras = [re.escape(p) for p in normalizar(expressao).split()]
    padrao = r"\b" + r"\s+(?:\w+\s+){0,2}".join(palavras) + r"\b"
    return re.search(padrao, texto_normalizado) is not None


def fmt_data(d: datetime) -> str:
    return f"{DIAS_LONGOS[d.weekday()]}, {d:%d/%m/%Y}"


def fmt_hora(d: datetime) -> str:
    return f"{d:%H:%M}"


def primeiro_nome(p: Paciente) -> str:
    nome = p.nome or p.nome_perfil or ""
    return nome.split()[0].capitalize() if nome.strip() else ""


def _ctx(conv: Conversa, **novos) -> None:
    """Atualiza o contexto (reatribui para o SQLAlchemy perceber a mudança)."""
    conv.contexto = {**(conv.contexto or {}), **novos}


def _escolha(e: Entrada, conv: Conversa) -> str | None:
    """Descobre qual opção o paciente escolheu: botão, número digitado ou texto igual ao título."""
    if e.id_opcao:
        return e.id_opcao
    opcoes = (conv.contexto or {}).get("opcoes", [])
    t = normalizar(e.texto)
    if t.isdigit() and 1 <= int(t) <= len(opcoes):
        return opcoes[int(t) - 1][0]
    for id_, titulo in opcoes:
        if t and t == normalizar(titulo):
            return id_
    return None


# --------------------------------------------------------------------------- telas
def menu() -> Lista:
    return Lista(
        T.MENU_TEXTO,
        T.MENU_BOTAO,
        [
            ("menu:agendar", T.MENU_AGENDAR, "Marque sua consulta"),
            ("menu:info", T.MENU_INFO, "Conheça os atendimentos"),
            ("menu:meus", T.MENU_MEUS, "Ver ou cancelar consultas"),
            ("menu:humano", T.MENU_HUMANO, "Fale com a recepção"),
        ],
    )


def tela_privacidade() -> Botoes:
    return Botoes(T.AVISO_PRIVACIDADE, [("lgpd:sim", T.BOTAO_CONCORDO), ("lgpd:nao", T.BOTAO_NAO_CONCORDO)])


def tela_especialidades(s: Session, p: Paciente) -> Lista:
    esps = especialidades_atendidas(s, idade=p.idade(), so_bot=True)
    return Lista(
        T.PERGUNTA_ESPECIALIDADE,
        T.MENU_BOTAO,
        [(f"esp:{e.id}", e.nome, e.descricao) for e in esps[:10]],
    )


def tela_turno() -> Lista:
    return Lista(
        T.PERGUNTA_TURNO,
        T.MENU_BOTAO,
        [
            ("turno:manha", T.TURNO_MANHA, "Até 12h"),
            ("turno:tarde", T.TURNO_TARDE, "12h às 18h"),
            ("turno:noite", T.TURNO_NOITE, "Depois das 18h"),
            ("turno:qualquer", T.TURNO_QUALQUER, "O primeiro horário livre"),
        ],
    )


def tela_horarios(s: Session, conv: Conversa) -> Resposta:
    ctx = conv.contexto
    esp = s.get(Especialidade, ctx["especialidade_id"])
    vagas = vagas_disponiveis(
        s, esp.id, ctx.get("turno", "qualquer"), idade=conv.paciente.idade(), limite=config.MAX_HORARIOS_OFERECIDOS
    )
    if not vagas:
        conv.estado = "sem_vaga"
        return Botoes(
            T.SEM_HORARIOS.format(especialidade=esp.nome),
            [("espera:sim", T.BOTAO_LISTA_ESPERA), ("espera:turno", T.BOTAO_OUTRO_TURNO), ("menu", T.BOTAO_MENU)],
        )
    conv.estado = "horario"
    return Lista(
        T.HORARIOS_DISPONIVEIS.format(especialidade=esp.nome),
        T.HORARIOS_BOTAO,
        [
            (f"vaga:{v.id}", f"{DIAS[v.inicio.weekday()]} {v.inicio:%d/%m} às {v.inicio:%H:%M}", DIAS_LONGOS[v.inicio.weekday()])
            for v in vagas
        ],
    )


# --------------------------------------------------------------------------- ações
def _passar_para_humano(conv: Conversa, motivo: str, texto: str) -> Resultado:
    conv.atendimento_humano = True
    conv.motivo_humano = motivo
    conv.estado = "humano"
    return Resultado([Texto(texto)], chamar_humano=motivo)


def _iniciar_agendamento(p: Paciente, conv: Conversa) -> list[Resposta]:
    _ctx(conv, queixa=None, especialidade_id=None, turno=None, vaga_id=None)
    if not p.nome:
        conv.estado = "nome"
        return [Texto(T.PERGUNTA_NOME)]
    if not p.data_nascimento:
        conv.estado = "nascimento"
        return [Texto(T.PERGUNTA_NASCIMENTO.format(nome=primeiro_nome(p)))]
    conv.estado = "queixa"
    return [Texto(T.PERGUNTA_QUEIXA)]


def _ir_menu(conv: Conversa, antes: list[Resposta] | None = None) -> list[Resposta]:
    conv.estado = "menu"
    return [*(antes or []), menu()]


def _parse_data(texto: str) -> date | None:
    m = re.search(r"(\d{1,2})\s*[/\-.]\s*(\d{1,2})\s*[/\-.]\s*(\d{2,4})", texto)
    if not m:
        return None
    d, mes, a = (int(x) for x in m.groups())
    if a < 100:
        a += 2000 if a <= config.agora().year % 100 else 1900
    try:
        nasc = date(a, mes, d)
    except ValueError:
        return None
    return nasc if date(1900, 1, 1) < nasc <= config.agora().date() else None


# --------------------------------------------------------------------------- principal
def obter_paciente(s: Session, telefone: str, nome_perfil: str | None = None) -> tuple[Paciente, Conversa]:
    p = s.scalar(select(Paciente).where(Paciente.telefone == telefone))
    if not p:
        p = Paciente(telefone=telefone, nome_perfil=nome_perfil)
        s.add(p)
        s.flush()
    elif nome_perfil:
        p.nome_perfil = nome_perfil
    if not p.conversa:
        p.conversa = Conversa(paciente_id=p.id, estado="inicio", contexto={})
        s.flush()
    return p, p.conversa


def registrar(s: Session, p: Paciente, direcao: str, conteudo: str, wa_id: str | None = None) -> None:
    s.add(Mensagem(paciente_id=p.id, direcao=direcao, conteudo=conteudo, wa_message_id=wa_id))


def processar(s: Session, e: Entrada) -> Resultado:
    if e.wa_message_id and s.scalar(select(Mensagem.id).where(Mensagem.wa_message_id == e.wa_message_id)):
        return Resultado(duplicada=True)  # a Meta às vezes reenvia o mesmo webhook

    p, conv = obter_paciente(s, e.telefone, e.nome_perfil)
    registrar(s, p, "entrada", e.texto or f"[{e.tipo}]", e.wa_message_id)
    conv.ultima_msg_paciente_em = config.agora()
    conv.atualizado_em = config.agora()
    conv.recuperacao_enviada_em = None

    if conv.atendimento_humano:
        return Resultado(repassar_para_humano=True)

    res = _decidir(s, e, p, conv)

    # guarda as opções mostradas, para aceitar "1", "2"... ou o texto do botão
    ultimas = [r for r in res.respostas if isinstance(r, (Botoes, Lista))]
    if ultimas:
        _ctx(conv, opcoes=[[o[0], o[1]] for o in ultimas[-1].opcoes])
    for r in res.respostas:
        registrar(s, p, "saida", resumo(r))
    return res


def _decidir(s: Session, e: Entrada, p: Paciente, conv: Conversa) -> Resultado:
    t = normalizar(e.texto)
    escolha = _escolha(e, conv)

    # 1) urgência e pedido de humano valem em qualquer etapa
    if t and any(contem_expressao(t, x) for x in T.PALAVRAS_URGENCIA):
        return _passar_para_humano(conv, f"URGÊNCIA: {e.texto[:150]}", T.URGENCIA)
    if escolha == "menu:humano" or (t and any(re.search(rf"\b{re.escape(x)}\b", t) for x in T.PALAVRAS_HUMANO)):
        return _passar_para_humano(conv, "Paciente pediu atendente", T.HUMANO_ENCAMINHADO)

    # 2) respostas aos botões do lembrete (template)
    if escolha and escolha.split(":")[0] in ("confirma", "remarca"):
        return _resposta_lembrete(s, p, conv, escolha)

    # 3) áudio, foto etc.
    if e.tipo in TIPOS_MIDIA:
        return Resultado([Texto(T.MIDIA_NAO_SUPORTADA), menu()] if p.aceitou_privacidade_em else [Texto(T.MIDIA_NAO_SUPORTADA)])

    # 4) "menu", "oi"... reinicia
    if escolha == "menu" and p.aceitou_privacidade_em:
        return Resultado(_ir_menu(conv))
    if t in [normalizar(x) for x in T.PALAVRAS_MENU] and conv.estado not in ("inicio", "privacidade"):
        conv.estado = "inicio"

    handler = ESTADOS.get(conv.estado, _estado_inicio)
    return Resultado(handler(s, e, p, conv, escolha))


# --------------------------------------------------------------------------- estados
def _estado_inicio(s, e, p, conv, escolha):
    nome = primeiro_nome(p)
    boas_vindas = Texto(T.BOAS_VINDAS.format(nome=f", {nome}" if nome else "", clinica=config.NOME_CLINICA))
    if not p.aceitou_privacidade_em:
        conv.estado = "privacidade"
        return [boas_vindas, tela_privacidade()]
    return _ir_menu(conv, [boas_vindas])


def _estado_privacidade(s, e, p, conv, escolha):
    if escolha == "lgpd:sim":
        p.aceitou_privacidade_em = config.agora()
        return _ir_menu(conv)
    if escolha == "lgpd:nao":
        conv.estado = "inicio"
        return [Texto(T.SEM_CONSENTIMENTO)]
    return [Texto(T.NAO_ENTENDI), tela_privacidade()]


def _estado_menu(s, e, p, conv, escolha):
    if escolha == "menu:agendar":
        return _iniciar_agendamento(p, conv)
    if escolha == "menu:info":
        esps = especialidades_atendidas(s, so_bot=True)
        lista = "\n".join(f"🦷 *{x.nome}* — {x.descricao}" for x in esps)
        return _ir_menu(conv, [Texto(T.INFO_ESPECIALIDADES.format(lista=lista)), Texto(T.INFO_GERAL)])
    if escolha == "menu:meus":
        ags = agendamentos_futuros(s, p)
        if not ags:
            return _ir_menu(conv, [Texto(T.SEM_AGENDAMENTOS)])
        lista = "\n".join(
            f"🦷 *{a.descricao}* — {fmt_data(a.vaga.inicio)} às {fmt_hora(a.vaga.inicio)}" for a in ags
        )
        conv.estado = "meus"
        return [Botoes(T.LISTA_AGENDAMENTOS.format(lista=lista), [("cancelar", T.BOTAO_CANCELAR), ("menu", T.BOTAO_MENU)])]
    return [Texto(T.NAO_ENTENDI), menu()]


def _estado_meus(s, e, p, conv, escolha):
    if escolha == "cancelar":
        ags = agendamentos_futuros(s, p)
        conv.estado = "cancelar"
        return [
            Lista(
                T.CANCELAR_QUAL,
                T.MENU_BOTAO,
                [(f"cancelar:{a.id}", f"{DIAS[a.vaga.inicio.weekday()]} {a.vaga.inicio:%d/%m %H:%M}", a.descricao[:72]) for a in ags],
            )
        ]
    return _ir_menu(conv)


def _estado_cancelar(s, e, p, conv, escolha):
    if escolha and escolha.startswith("cancelar:"):
        ag = s.get(Agendamento, int(escolha.split(":")[1]))
        if ag and ag.paciente_id == p.id:
            cancelar_agendamento(ag)
            return _ir_menu(conv, [Texto(T.CANCELADO_OK)])
    return _ir_menu(conv, [Texto(T.NAO_ENTENDI)])


def _estado_nome(s, e, p, conv, escolha):
    nome = " ".join(e.texto.split())
    if len(nome) < 3 or any(c.isdigit() for c in nome) or not re.search(r"[a-zA-ZÀ-ÿ]{2}", nome):
        return [Texto(T.NOME_INVALIDO)]
    p.nome = nome.title()[:120]
    conv.estado = "nascimento"
    return [Texto(T.PERGUNTA_NASCIMENTO.format(nome=primeiro_nome(p)))]


def _estado_nascimento(s, e, p, conv, escolha):
    nasc = _parse_data(e.texto)
    if not nasc:
        return [Texto(T.NASCIMENTO_INVALIDO)]
    p.data_nascimento = nasc
    conv.estado = "queixa"
    return [Texto(T.PERGUNTA_QUEIXA)]


def _estado_queixa(s, e, p, conv, escolha):
    if len(e.texto.strip()) < 2:
        return [Texto(T.PERGUNTA_QUEIXA)]
    _ctx(conv, queixa=e.texto.strip()[:500])
    conv.estado = "especialidade"
    return [tela_especialidades(s, p)]


def _estado_especialidade(s, e, p, conv, escolha):
    if escolha and escolha.startswith("esp:"):
        _ctx(conv, especialidade_id=int(escolha.split(":")[1]))
        conv.estado = "turno"
        return [tela_turno()]
    return [Texto(T.NAO_ENTENDI), tela_especialidades(s, p)]


def _estado_turno(s, e, p, conv, escolha):
    if escolha and escolha.startswith("turno:"):
        _ctx(conv, turno=escolha.split(":")[1])
        return [tela_horarios(s, conv)]
    return [Texto(T.NAO_ENTENDI), tela_turno()]


def _estado_sem_vaga(s, e, p, conv, escolha):
    ctx = conv.contexto
    if escolha == "espera:sim":
        esp = s.get(Especialidade, ctx["especialidade_id"])
        s.add(ListaEspera(paciente_id=p.id, especialidade_id=esp.id, turno=ctx.get("turno"), queixa=ctx.get("queixa")))
        conv.estado = "inicio"
        return [Texto(T.LISTA_ESPERA_OK.format(especialidade=esp.nome))]
    if escolha == "espera:turno":
        conv.estado = "turno"
        return [tela_turno()]
    return _ir_menu(conv)


def _estado_horario(s, e, p, conv, escolha):
    if escolha and escolha.startswith("vaga:"):
        v = s.get(Vaga, int(escolha.split(":")[1]))
        if v:
            esp = s.get(Especialidade, conv.contexto["especialidade_id"])
            _ctx(conv, vaga_id=v.id)
            conv.estado = "confirmar"
            return [
                Botoes(
                    T.CONFIRMAR_AGENDAMENTO.format(especialidade=esp.nome, data=fmt_data(v.inicio), hora=fmt_hora(v.inicio)),
                    [("confirmar:sim", T.BOTAO_SIM), ("confirmar:nao", T.BOTAO_NAO)],
                )
            ]
    return [Texto(T.NAO_ENTENDI), tela_horarios(s, conv)]


def _estado_confirmar(s, e, p, conv, escolha):
    if escolha == "confirmar:sim":
        ctx = conv.contexto
        try:
            ag = agendar(s, p, ctx["vaga_id"], especialidade_id=ctx.get("especialidade_id"), queixa=ctx.get("queixa"), origem="bot")
        except VagaIndisponivel:
            return [Texto(T.VAGA_ACABOU), tela_horarios(s, conv)]
        conv.estado = "inicio"
        conv.contexto = {}
        v = ag.vaga
        return [Texto(T.AGENDAMENTO_OK.format(especialidade=ag.especialidade.nome, data=fmt_data(v.inicio), hora=fmt_hora(v.inicio)))]
    if escolha == "confirmar:nao":
        conv.estado = "turno"
        return [tela_turno()]
    return [Texto(T.NAO_ENTENDI)]


def _resposta_lembrete(s, p, conv, escolha) -> Resultado:
    acao, _, id_ = escolha.partition(":")
    ag = s.get(Agendamento, int(id_)) if id_.isdigit() else None
    if not ag or ag.paciente_id != p.id:
        return Resultado(_ir_menu(conv))
    if acao == "confirma":
        if ag.status == "agendado":
            ag.status = "confirmado"
        conv.estado = "inicio"
        return Resultado([Texto(T.LEMBRETE_CONFIRMADO)])
    cancelar_agendamento(ag)
    _ctx(conv, queixa=ag.queixa, especialidade_id=ag.especialidade_id or ag.vaga.sessao.especialidades[0].id)
    conv.estado = "turno"
    return Resultado([Texto(T.LEMBRETE_REMARCAR), tela_turno()])


def _estado_recuperacao(s, e, p, conv, escolha):
    """Paciente respondeu à mensagem de recuperação."""
    anterior = (conv.contexto or {}).get("estado_anterior", "inicio")
    conv.estado = anterior
    if escolha != "continuar":
        # respondeu outra coisa: trata como resposta à etapa em que tinha parado
        return ESTADOS.get(anterior, _estado_inicio)(s, e, p, conv, escolha)
    if anterior == "nome":
        return [Texto(T.PERGUNTA_NOME)]
    if anterior == "nascimento":
        return [Texto(T.PERGUNTA_NASCIMENTO.format(nome=primeiro_nome(p)))]
    if anterior == "queixa":
        return [Texto(T.PERGUNTA_QUEIXA)]
    if anterior == "especialidade":
        return [tela_especialidades(s, p)]
    if anterior == "turno":
        return [tela_turno()]
    if anterior in ("horario", "confirmar", "sem_vaga"):
        return [tela_horarios(s, conv)]
    return _estado_inicio(s, e, p, conv, escolha)


ESTADOS = {
    "recuperacao": _estado_recuperacao,
    "inicio": _estado_inicio,
    "privacidade": _estado_privacidade,
    "menu": _estado_menu,
    "meus": _estado_meus,
    "cancelar": _estado_cancelar,
    "nome": _estado_nome,
    "nascimento": _estado_nascimento,
    "queixa": _estado_queixa,
    "especialidade": _estado_especialidade,
    "turno": _estado_turno,
    "sem_vaga": _estado_sem_vaga,
    "horario": _estado_horario,
    "confirmar": _estado_confirmar,
}

# estados "no meio do agendamento" (usados pela recuperação de pacientes)
ESTADOS_AGENDAMENTO = {"nome", "nascimento", "queixa", "especialidade", "turno", "horario", "confirmar", "sem_vaga"}
