"""
TEXTOS DO BOT  ✏️  — você pode editar este arquivo sem saber programar.

Regras:
  * Mude só o que está ENTRE as aspas.
  * Não apague as palavras entre chaves, como {nome} ou {clinica}: o sistema
    troca elas pelo valor certo na hora de enviar.
  * *texto* = negrito no WhatsApp.  _texto_ = itálico.
  * Títulos de botão: no máximo 20 caracteres (limite do WhatsApp).
"""

BOAS_VINDAS = (
    "Olá{nome}! 👋 Aqui é o atendimento automático da *{clinica}*.\n\n"
    "Posso te ajudar a agendar uma avaliação, tirar dúvidas sobre as "
    "especialidades ou chamar alguém da nossa equipe."
)

AVISO_PRIVACIDADE = (
    "🔒 Antes de continuar: para organizar seu atendimento vamos guardar seu nome, "
    "data de nascimento, telefone e o motivo da consulta. Esses dados são usados "
    "somente pela clínica, conforme a LGPD.\n\nVocê concorda?"
)
BOTAO_CONCORDO = "Concordo"
BOTAO_NAO_CONCORDO = "Não concordo"
SEM_CONSENTIMENTO = (
    "Tudo bem! Sem esses dados não conseguimos agendar pelo WhatsApp. "
    "Se mudar de ideia, é só mandar uma mensagem. Você também pode ir até a clínica pessoalmente."
)

MENU_TEXTO = "Como posso te ajudar? Escolha uma opção:"
MENU_BOTAO = "Ver opções"
MENU_AGENDAR = "Agendar avaliação"
MENU_INFO = "Especialidades"
MENU_MEUS = "Meus agendamentos"
MENU_HUMANO = "Falar com atendente"
MENU_VALORES = "Valores e endereço"

PERGUNTA_NOME = "Para começar, qual é o seu *nome completo*?"
NOME_INVALIDO = "Não entendi 🤔. Pode me dizer seu nome completo?"
PERGUNTA_NASCIMENTO = "Obrigado, {nome}! Qual a sua *data de nascimento*? (ex.: 25/03/1990)"
NASCIMENTO_INVALIDO = "Não consegui entender a data. Escreva assim: *dia/mês/ano*, por exemplo 25/03/1990."
PERGUNTA_QUEIXA = (
    "Agora me conte em poucas palavras: *qual o motivo da consulta?*\n"
    "(ex.: dor de dente, limpeza, dente quebrado, prótese, aparelho...)"
)
PERGUNTA_ESPECIALIDADE = (
    "Qual atendimento você procura? Se não souber, escolha *Triagem* que nossa "
    "equipe avalia e encaminha para a especialidade certa."
)
PERGUNTA_TURNO = "Qual turno fica melhor para você?"
TURNO_MANHA = "Manhã"
TURNO_TARDE = "Tarde"
TURNO_NOITE = "Noite"
TURNO_QUALQUER = "Qualquer turno"

HORARIOS_DISPONIVEIS = "Estes são os próximos horários disponíveis para *{especialidade}*:"
HORARIOS_BOTAO = "Ver horários"

SEM_HORARIOS = (
    "No momento não temos horários livres para *{especialidade}* nesse turno. 😕\n\n"
    "Posso colocar você na *lista de espera*? Avisamos assim que abrir uma vaga."
)
BOTAO_LISTA_ESPERA = "Entrar na lista"
BOTAO_OUTRO_TURNO = "Outro turno"
LISTA_ESPERA_OK = (
    "Pronto! Você está na lista de espera de *{especialidade}*. "
    "Vamos te chamar aqui pelo WhatsApp quando surgir uma vaga. 🙏"
)

CONFIRMAR_AGENDAMENTO = (
    "Confirma o agendamento?\n\n"
    "🦷 *{especialidade}*\n📅 {data}\n🕐 {hora}"
)
BOTAO_SIM = "Sim, confirmar"
BOTAO_NAO = "Escolher outro"

AGENDAMENTO_OK = (
    "✅ Agendado!\n\n🦷 *{especialidade}*\n📅 {data}\n🕐 {hora}\n\n"
    "📍 Chegue com 15 minutos de antecedência e traga um documento com foto.\n"
    "Vamos te mandar um lembrete antes da consulta."
)
VAGA_ACABOU = "Poxa, esse horário acabou de ser preenchido. Veja as outras opções:"

SEM_AGENDAMENTOS = "Você não tem agendamentos futuros conosco."
LISTA_AGENDAMENTOS = "Seus próximos agendamentos:\n\n{lista}"
BOTAO_CANCELAR = "Cancelar consulta"
BOTAO_MENU = "Voltar ao menu"
CANCELAR_QUAL = "Qual agendamento você quer cancelar?"
CANCELADO_OK = "Agendamento cancelado. Se quiser marcar outro horário, é só escolher *Agendar avaliação* no menu."

INFO_ESPECIALIDADES = "Estas são as especialidades atendidas na clínica-escola:\n\n{lista}"
INFO_GERAL = (
    "ℹ️ Os atendimentos são realizados por alunos sob supervisão de professores. "
    "As consultas acontecem durante o semestre letivo."
)

# ---- Modo triagem (a recepção/ASB agenda depois de avaliar) ----
PERGUNTA_TURNO_TRIAGEM = "Qual turno fica melhor para você vir à clínica?"
TRIAGEM_OK = (
    "Obrigado, {nome}! 🙏 Recebemos seus dados e o motivo da consulta.\n\n"
    "Nossa equipe vai avaliar e te chamar *aqui pelo WhatsApp* para combinar o dia e o horário "
    "com a turma que atende o seu caso."
)

# ---- Valores, endereço e horários (edite quando mudar) ----
VALORES = (
    "💲 *Tabela de valores (taxa social)*\n\n"
    "• Avaliação + limpeza: R$ 30,00 (toda avaliação já inclui a limpeza)\n"
    "• Restauração: R$ 30,00\n"
    "• Tratamento de canal: R$ 30,00\n"
    "• Atendimento infantil: R$ 30,00\n"
    "• Prótese dentária: R$ 30,00 (custos de laboratório cobrados à parte, conforme o serviço)\n"
    "• Extração / cirurgia: R$ 50,00\n"
    "• Raio-X: R$ 5,00 por dente\n\n"
    "Atendemos crianças, adolescentes, adultos e pessoas com necessidades especiais. "
    "Os procedimentos são feitos por alunos com supervisão de professores."
)
ENDERECO = (
    "📍 *Endereço*\n"
    "Quadra 05, Lotes 1, 2 e 3, Sala 01, Parque Rio Branco\n"
    "Q. Dois, L. 01, Loja 07, Parque Rio Branco\n"
    "Valparaíso de Goiás - GO, CEP 72870-105\n\n"
    "🕐 *Horários de atendimento*\n"
    "Noite: 18h às 21h30\n"
    "Manhã: 8h30 às 12h"
)

HUMANO_ENCAMINHADO = (
    "Certo! Vou chamar alguém da nossa equipe. 🙋 "
    "Assim que possível uma pessoa vai continuar a conversa por aqui."
)
HUMANO_FORA_DE_HORARIO_DICA = "(Atendimento humano em horário de expediente.)"
URGENCIA = (
    "⚠️ Entendi que pode ser uma *urgência*. Vou chamar nossa equipe agora.\n\n"
    "Se houver inchaço no rosto, febre, sangramento que não para ou dificuldade "
    "para respirar ou engolir, procure imediatamente um pronto-socorro (UPA) ou ligue 192."
)
ATENDIMENTO_ENCERRADO = "Atendimento encerrado. Se precisar de algo, é só mandar uma mensagem! 😊"

NAO_ENTENDI = "Desculpe, não entendi. 🤔 Escolha uma das opções abaixo, por favor."
MIDIA_NAO_SUPORTADA = (
    "Ainda não consigo ouvir áudios nem ver fotos. 🙏 Pode escrever sua mensagem? "
    "Se preferir, escolha *Falar com atendente*."
)

RECUPERACAO = (
    "Oi{nome}! Vi que você começou o agendamento mas não terminou. "
    "Quer continuar de onde parou?"
)
BOTAO_CONTINUAR = "Continuar"

LEMBRETE_CONFIRMADO = "Obrigado por confirmar! Te esperamos. 😊"
LEMBRETE_REMARCAR = "Sem problemas, cancelei esse horário. Vamos escolher outro?"
BOTAO_CONFIRMO = "Confirmo"
BOTAO_REMARCAR = "Remarcar"

# Palavras que fazem o bot chamar um humano imediatamente (urgência)
PALAVRAS_URGENCIA = [
    # ⚠️ Revise esta lista com os professores/coordenação clínica.
    # Use expressões específicas: "sangrando" sozinho pegaria "gengiva sangra ao escovar".
    "dor forte", "dor insuportavel", "muita dor", "dor muito forte",
    "rosto inchado", "inchaco no rosto", "cara inchada", "bochecha inchada", "face inchada", "olho inchado",
    "nao para de sangrar", "sangramento que nao para", "sangrando muito", "muito sangue",
    "febre", "urgente", "urgencia", "emergencia", "acidente", "trauma", "dente caiu", "dente saiu",
    "nao consigo engolir", "dificuldade para engolir", "dificuldade para respirar", "nao consigo abrir a boca",
]
# Palavras que fazem o bot chamar um humano a pedido do paciente
PALAVRAS_HUMANO = ["atendente", "humano", "falar com alguem", "recepcao", "funcionario"]
# Palavras que voltam ao menu
PALAVRAS_MENU = ["menu", "inicio", "voltar", "oi", "ola", "bom dia", "boa tarde", "boa noite"]
