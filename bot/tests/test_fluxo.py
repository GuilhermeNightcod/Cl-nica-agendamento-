from datetime import timedelta

from sqlalchemy import select

from app import config
from app.db import sessao
from app.mensagens import Botoes, Lista, Modelo, Texto
from app.models import Agendamento, Conversa, ListaEspera, Paciente, Vaga
from app.tarefas import enviar_lembretes, recuperar_abandonos


def ids(resp):
    return [o[0] for o in resp.opcoes]


def agendar_ate_horarios(bot, turno="turno:qualquer"):
    r = bot.diz("oi")
    assert isinstance(r[0], Texto) and isinstance(r[1], Botoes)  # boas-vindas + privacidade
    r = bot.diz(opcao="lgpd:sim")
    assert isinstance(r[0], Lista) and "menu:agendar" in ids(r[0])
    bot.diz(opcao="menu:agendar")
    bot.diz("Maria da Silva")
    r = bot.diz("25/03/1990")
    assert "motivo" in r[0].texto
    r = bot.diz("quero fazer uma limpeza")
    assert ids(r[0])[0].startswith("esp:")  # lista de especialidades
    assert "Triagem" in r[0].opcoes[0][1]  # triagem aparece primeiro
    r = bot.diz(opcao=r[0].opcoes[0][0])
    assert "turno:manha" in ids(r[0])
    return bot.diz(opcao=turno)


def test_agendamento_completo(bot):
    r = agendar_ate_horarios(bot)
    horarios = r[0]
    assert isinstance(horarios, Lista) and horarios.opcoes and len(horarios.opcoes) <= config.MAX_HORARIOS_OFERECIDOS
    r = bot.diz(opcao=horarios.opcoes[0][0])
    assert "Confirma" in r[0].texto
    r = bot.diz(opcao="confirmar:sim")
    assert "Agendado" in r[0].texto
    with sessao() as s:
        ag = s.scalar(select(Agendamento))
        assert ag.status == "agendado" and ag.queixa == "quero fazer uma limpeza"
        assert ag.vaga.ocupadas == 1
        assert ag.paciente.nome == "Maria Da Silva"


def test_escolha_por_numero_digitado(bot):
    bot.diz("oi")
    r = bot.diz("1")  # 1 = Concordo
    assert isinstance(r[0], Lista)
    r = bot.diz("1")  # 1 = Agendar
    assert "nome" in r[0].texto


def test_urgencia_chama_humano(bot):
    bot.diz("oi")
    r = bot.diz("estou com o rosto inchado e muita dor")
    assert "urgência" in r[0].texto
    assert bot.chatwoot.abertas and "URGÊNCIA" in bot.chatwoot.abertas[0][1]
    # a partir de agora o bot fica quieto e repassa ao Chatwoot
    r = bot.diz("alguém pode me ajudar?")
    assert r == [] and bot.chatwoot.mensagens == [(77, "alguém pode me ajudar?")]


def test_atendente_responde_e_encerra(bot):
    bot.diz("oi")
    bot.diz("quero falar com atendente")
    with sessao() as s:
        bot.servico_.evento_chatwoot(s, {"event": "message_created", "message_type": "outgoing", "private": False,
                                        "content": "Olá, sou a Ana da recepção", "conversation": {"id": 77}})
    assert bot.whatsapp.enviadas[-1][1].texto == "Olá, sou a Ana da recepção"
    with sessao() as s:
        bot.servico_.evento_chatwoot(s, {"event": "message_created", "message_type": "outgoing", "private": True,
                                        "content": "nota interna", "conversation": {"id": 77}})
    assert bot.whatsapp.enviadas[-1][1].texto != "nota interna"
    with sessao() as s:
        bot.servico_.evento_chatwoot(s, {"event": "conversation_status_changed", "id": 77, "status": "resolved"})
    r = bot.diz("oi")
    assert r, "bot deve voltar a responder após o atendimento ser resolvido"


def test_sem_vagas_vai_para_lista_de_espera(bot):
    with sessao() as s:
        for v in s.scalars(select(Vaga)):
            v.ocupadas = v.capacidade
    r = agendar_ate_horarios(bot)
    assert "lista de espera" in r[0].texto
    r = bot.diz(opcao="espera:sim")
    with sessao() as s:
        assert s.scalar(select(ListaEspera)).queixa == "quero fazer uma limpeza"


def test_cancelar_libera_vaga(bot):
    r = agendar_ate_horarios(bot)
    bot.diz(opcao=r[0].opcoes[0][0])
    bot.diz(opcao="confirmar:sim")
    bot.diz("menu")
    r = bot.diz(opcao="menu:meus")
    assert "Seus próximos" in r[0].texto
    r = bot.diz(opcao="cancelar")
    r = bot.diz(opcao=r[0].opcoes[0][0])
    with sessao() as s:
        ag = s.scalar(select(Agendamento))
        assert ag.status == "cancelado" and ag.vaga.ocupadas == 0


def test_lembrete_e_confirmacao(bot):
    r = agendar_ate_horarios(bot)
    bot.diz(opcao=r[0].opcoes[0][0])
    bot.diz(opcao="confirmar:sim")
    with sessao() as s:
        ag = s.scalar(select(Agendamento))
        ag.vaga.inicio = config.agora() + timedelta(hours=5)  # consulta daqui a pouco
    bot.whatsapp.enviadas.clear()
    with sessao() as s:
        assert enviar_lembretes(s, bot.servico_) == 1
        assert enviar_lembretes(s, bot.servico_) == 0  # não repete
    modelo = bot.whatsapp.enviadas[0][1]
    assert isinstance(modelo, Modelo) and modelo.payloads_botoes[0].startswith("confirma:")
    r = bot.diz("Confirmo", opcao=modelo.payloads_botoes[0], tipo="button")
    assert "confirmar" in r[0].texto
    with sessao() as s:
        assert s.scalar(select(Agendamento)).status == "confirmado"


def test_recuperacao_de_abandono(bot):
    bot.diz("oi")
    bot.diz(opcao="lgpd:sim")
    bot.diz(opcao="menu:agendar")
    bot.diz("João Pereira")  # parou na data de nascimento
    with sessao() as s:
        c = s.scalar(select(Conversa))
        c.ultima_msg_paciente_em = config.agora() - timedelta(hours=3)
    bot.whatsapp.enviadas.clear()
    with sessao() as s:
        assert recuperar_abandonos(s, bot.servico_) == 1
    assert "não terminou" in bot.whatsapp.enviadas[0][1].texto
    r = bot.diz(opcao="continuar")
    assert "nascimento" in r[0].texto
    r = bot.diz("01/02/1985")
    assert "motivo" in r[0].texto


def test_data_invalida_e_midia(bot):
    bot.diz("oi")
    bot.diz(opcao="lgpd:sim")
    bot.diz(opcao="menu:agendar")
    bot.diz("Ana Souza")
    r = bot.diz("ontem")
    assert "dia/mês/ano" in r[0].texto
    r = bot.diz(tipo="audio")
    assert "áudio" in r[0].texto


def test_nao_concordar_privacidade(bot):
    bot.diz("oi")
    r = bot.diz(opcao="lgpd:nao")
    with sessao() as s:
        assert s.scalar(select(Paciente)).aceitou_privacidade_em is None
    assert "Sem esses dados" in r[0].texto


def test_queixa_comum_nao_e_urgencia(bot):
    bot.diz("oi")
    bot.diz(opcao="lgpd:sim")
    bot.diz(opcao="menu:agendar")
    bot.diz("Fernanda Alves")
    bot.diz("12/04/1992")
    r = bot.diz("minha gengiva sangra ao escovar e está um pouco inchada")
    assert isinstance(r[0], Lista)  # segue para a escolha da especialidade
    assert not bot.chatwoot.abertas


def test_urgencia_com_palavras_no_meio():
    from app.fluxo import contem_expressao, normalizar
    assert contem_expressao(normalizar("Estou com o rosto MUITO inchado!"), "rosto inchado")
    assert contem_expressao(normalizar("uma dor muito forte"), "dor forte")
    assert not contem_expressao(normalizar("gengiva sangra ao escovar"), "sangrando muito")
    assert not contem_expressao(normalizar("o rosto dele no outro dia ficou inchado"), "rosto inchado")


def test_modo_triagem_vai_para_fila_da_asb(bot, monkeypatch):
    from app.models import Atendimento
    monkeypatch.setattr(config, "MODO_AGENDAMENTO_BOT", "triagem")
    bot.diz("oi")
    bot.diz(opcao="lgpd:sim")
    bot.diz(opcao="menu:agendar")
    bot.diz("Renata Alves")
    bot.diz("10/10/1985")
    r = bot.diz("quero fazer uma limpeza e ver um dente quebrado")
    turnos = [o[0] for o in r[0].opcoes]
    assert "turno:noite" in turnos and "turno:tarde" not in turnos  # a clínica não atende à tarde
    r = bot.diz(opcao="turno:noite")
    assert "Nossa equipe vai avaliar" in r[0].texto
    with sessao() as s:
        at = s.scalar(select(Atendimento))
        assert at.status == "fila" and at.setor.nome == "Triagem (ASB)"
        assert "limpeza" in at.motivo and " anos" in at.motivo and "noite" in at.motivo
        assert s.scalar(select(Agendamento)) is None  # quem agenda é a ASB
    assert bot.diz("ok, aguardo") == []  # depois disso quem responde é a recepção


def test_valores_e_endereco(bot):
    bot.diz("oi")
    bot.diz(opcao="lgpd:sim")
    r = bot.diz(opcao="menu:valores")
    textos = " ".join(getattr(x, "texto", "") for x in r)
    assert "R$ 50,00" in textos and "Valparaíso de Goiás" in textos and "18h às 21h30" in textos
