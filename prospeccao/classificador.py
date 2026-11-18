"""Classificação de respostas do WhatsApp Web (humano, robô, opt-out, recusa) e conferência."""

from __future__ import annotations

import re
from datetime import datetime

from .telefones import _sem_acentos

_RE_PRE = re.compile(r"\[(\d{1,2}):(\d{2}), (\d{1,2})/(\d{1,2})/(\d{4})\]\s*(.*?):\s*$")


def _norm(texto: str) -> str:
    return _sem_acentos((texto or "").lower()).strip()


FRASES_BOT = (
    "seja bem-vindo", "seja bem vindo", "bem-vindo a", "bem vindo a",
    "seja muito bem-vindo", "seja muito bem vindo", "bem-vindo(a)", "bem vindo(a)",
    "agradece seu contato", "agradece o seu contato",
    "obrigado pelo contato", "obrigada pelo contato", "estamos ausentes",
    "escolha uma das opcoes", "escolha uma opcao", "selecione uma opcao",
    "digite o numero", "digite a opcao", "clique no botao",
    "retornaremos", "horario de atendimento", "fora do horario",
    "nosso expediente", "mensagem automatica", "atendimento automatico",
    "atendimento virtual", "assistente virtual", "menu principal",
    "menu de opcoes", "para agilizar seu atendimento", "aguarde um momento",
    "ja vamos te atender", "em instantes", "assim que possivel", "em breve",
    "numero de protocolo", "protocolo de atendimento",
    # Vistos nas respostas reais (10 a 18/11/2026):
    "em alguns instantes", "um atendente ira", "uma de nossas atendentes",
    "voce foi transferido", "sera atendido", "entraremos em contato",
    "estamos indisponiveis", "agradece seu contato", "agradece o contato",
    "como avalia o nosso atendimento", "sua opiniao e importante",
    "conversa sera encerrada", "faz um tempinho que nao recebemos",
    "por aqui posso ajudar", "por aqui consigo ajudar", "encaminhei sua solicitacao",
    "responda apenas com o numero", "aviso sobre a lgpd",
)

# Cortesia de encerramento ("Disponha!", "Tenha uma excelente semana!"): é
# gente, mas não pede nada. Não vira aviso de lead quente.
_RE_CORTESIA = re.compile(
    r"^\W*(?:(?:bom\s+dia|boa\s+tarde|boa\s+noite|ola|oi)\W*)?"
    r"(?:disponha|de\s+nada|por\s+nada|obrigad[oa]s?|muito\s+obrigad[oa]|agradeco|"
    r"agradecemos|ok|okay|certo|combinado|amem|tmj|valeu|"
    r"(?:tenha|tenham)\s+(?:um|uma)\s+(?:otim[oa]|excelente|boa|bom)\s+\w+)"
    r"(?:[\s,.!]+(?:nickolas|tambem|igualmente|pra\s+voce|para\s+voce|"
    r"(?:tenha|tenham)\s+(?:um|uma)\s+(?:otim[oa]|excelente|boa|bom)\s+\w+))*\W*$")

_RE_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


def eh_cortesia(texto: str) -> bool:
    return bool(_RE_CORTESIA.match(_norm(texto)))


def extrair_email(textos: list[str]) -> str | None:
    """Primeiro e-mail citado nas mensagens (ex.: "Pode enviar para o email X")."""
    for texto in textos:
        m = _RE_EMAIL.search(texto or "")
        if m:
            return m.group(0).rstrip(".").lower()
    return None


def extrair_contato_compartilhado(textos: list[str]) -> tuple[str, str] | None:
    """(nome, telefone) de um cartão de contato repassado pela clínica.

    A ponte transforma o cartão em "[contato] Nome +5579..." (ver ponte.js).
    """
    for texto in textos:
        m = re.search(r"\[contato\]\s*(.*?)\s*\+?(\d{10,13})\b", texto or "")
        if m:
            return m.group(1).strip(" :-") or "Contato", m.group(2)
    return None

PADROES_OPTOUT = (
    r"\bn[aã]o\s+(?:tenho|temos|ha)\s+interesse", r"\bsem\s+interesse\b",
    r"\bn[aã]o\s+nos\s+interessa", r"\bn[aã]o\s+quero\b",
    r"\bpare(?:\s+de\s+(?:mandar|enviar))?\b", r"\bremov", r"\bdescadastr",
    r"\b(?:retire|tire)\s+(?:o\s+)?meu\s+n[uú]mero",
    r"\bn[aã]o\s+(?:me\s+)?(?:envie|mande)", r"\bn[aã]o\s+entre\s+em\s+contato",
    r"\bn[aã]o\s+insist",
    r"\bn[ãa]o\s+(?:[ée]|seria|[ée]\s+do\s+nosso|faz)\s+(?:relevante|interesse|necess[áa]rio|sentido)",
    r"\bn[ãa]o\s+(?:precisamos|estamos\s+precisando|temos\s+necessidade)",
)

PADROES_NEGATIVA = (
    r"^\W*nao\b",
    r"\bja\s+(?:temos|usamos|tem|utilizamos|possuimos|contratamos|fazemos|contamos\s+com)\b",
    r"\b(?:agora|no\s+momento|por\s+enquanto)\s+nao\b",
    r"\bnao\s+(?:no\s+momento|agora|estamos\s+contratando)\b",
    r"\b(?:talvez|fica\s+para)\s+(?:depois|outro\s+momento|mais\s+tarde)\b",
    r"\bsem\s+(?:demanda|orcamento|verba|previsao)\b",
    r"\bobrigad[oa],?\s+mas\b", r"\bagradec[oa],?\s+mas\b",
)

_RE_MENU_PRIMARIO = re.compile(
    r"(?im)^[\s*_~\[\(]*(?:op[cç][aã]o\s+|digite\s+)?(\d{1,2})[\ufe0f\u20e3\s*_~\]\)]*"
    r"[-–—.:•]?\s*(?:para\s+)?"
    r"(?:falar|conversar|atendimento)?\s*(?:(?:com|na|no|em)\s+(?:um|uma|o|a|nossa|nosso)?\s*)?"
    r"(?:atendente|recepcionista|secretari[oa]|humano|pessoa|equipe|recepcao)\b"
)

_RE_MENU_SECUNDARIO = re.compile(
    r"(?im)^[\s*_~\[\(]*(?:op[cç][aã]o\s+|digite\s+)?(\d{1,2})[\ufe0f\u20e3\s*_~\]\)]*"
    r"[-–—.:•]?\s*(?:outros?\s+assuntos?|outras?\s+(?:duvidas?|informacoes?)|"
    r"assuntos?\s+administrativos?|administrativo|financeiro|gestao|parcerias?|fornecedores?)\b"
)

# Robô pedindo identificação: nome e/ou motivo do contato. Ex. (consultório
# odontológico, 18/11/2026): "Para agilizar seu atendimento, por favor informe:
# 👉 Nome e sobrenome ... 👉 Motivo do contato".
_PADROES_PEDE_NOME = (
    r"\bqual\s+(?:e\s+)?(?:o\s+)?seu\s+nome\b",
    r"\bsaber\s+(?:o\s+)?seu\s+nome\b",
    r"\bcomo\s+posso\s+(?:te\s+|lhe\s+)?chamar\b",
    r"\b(?:informe|digite|envie)\s+(?:o\s+)?seu\s+nome\b",
    r"\bnome\s+(?:e\s+sobrenome|completo)\b",
    r"\bmotivo\s+d[oa]\s+(?:seu\s+)?(?:contato|atendimento|mensagem)\b",
    r"\b(?:me\s+)?(?:conte|diga|informe|envie|mande)\s+(?:o\s+)?seu\s+nome\b",
    r"\bseu\s+nome\s+completo\b",
)


def texto_confere(texto_na_caixa: str, mensagem: str) -> bool:
    """A caixa contém exatamente a mensagem (nem a mais, nem a menos)?

    Compara só letras e números: o WhatsApp Web renderiza emoji como imagem
    e pode mexer em espaços/quebras, mas texto duplicado ou faltando aparece.
    """
    def nucleo(s: str) -> str:
        return re.sub(r"[\W_]+", "", s or "").lower()
    return bool(nucleo(mensagem)) and nucleo(texto_na_caixa) == nucleo(mensagem)


def resposta_negativa(textos: list[str]) -> bool:
    """True se alguma resposta da pessoa soa como recusa (sem ser opt-out)."""
    return any(re.search(p, _norm(t)) for t in textos for p in PADROES_NEGATIVA)


def interpretar_bolha(pre: str, texto: str) -> dict:
    """Converte o atributo data-pre-plain-text ('[08:25, 10/11/2026] Nome: ')."""
    m = _RE_PRE.match(pre or "")
    quando = None
    remetente = ""
    if m:
        hh, mi, dd, mm, aaaa, remetente = m.groups()
        try:
            quando = datetime(int(aaaa), int(mm), int(dd), int(hh), int(mi))
        except ValueError:
            quando = None
    return {"remetente": remetente.strip(), "quando": quando, "texto": texto or ""}


def classificar_resposta(bolhas: list[dict], enviadas: list[str],
                         desde: datetime) -> str | None:
    """Classifica o que a clínica respondeu depois do nosso envio.

    Retorna "sem interesse" | "respondeu" | "resposta automatica" | None (nada).
    """
    eu = next((b["remetente"] for b in bolhas
               if any(texto_confere(b["texto"], e) for e in enviadas)), None)
    if eu is None:
        return None
    inicio = desde.replace(second=0, microsecond=0)
    recebidas = [b for b in bolhas
                 if b["remetente"] != eu and b["quando"] and b["quando"] >= inicio]
    if not recebidas:
        return None
    texto_todo = " ".join(_norm(b["texto"]) for b in recebidas)
    if any(re.search(p, texto_todo) for p in PADROES_OPTOUT):
        return "sem interesse"

    def automatica(b: dict) -> bool:
        # Medido nas respostas reais: robôs respondem em 2 a 5 s (um atendente
        # de IA levou 25 s); pessoas, de 50 s em diante. Até 2 min, só texto
        # longo (boas-vindas com menu) ainda conta como robô.
        # Conta do instante exato do envio (`desde`), não do início do minuto:
        # com o minuto, um robô que respondeu em 5 s parecia ter levado 35 s.
        segundos = max(0.0, (b["quando"] - desde).total_seconds())
        # Bolhas do WhatsApp Web só têm minuto: dá a folga de um minuto.
        limite = 90 if b["quando"].second == 0 and b["quando"].microsecond == 0 else 30
        norm = _norm(b["texto"])
        return (segundos <= limite or any(f in norm for f in FRASES_BOT)
                or (segundos <= 120 and len(norm) > 300))

    return "respondeu" if any(not automatica(b) for b in recebidas) else "resposta automatica"


def resultado_entrega(bolhas: list[dict], mensagem: str, enviado_em: datetime) -> str:
    """"ok" | "duplicada" | "ausente" | "inconclusivo"."""
    vezes = sum(1 for b in bolhas if texto_confere(b["texto"], mensagem))
    if vezes == 1:
        return "ok"
    if vezes > 1:
        return "duplicada"
    minuto_envio = enviado_em.replace(second=0, microsecond=0)
    if any(b["quando"] and b["quando"] < minuto_envio for b in bolhas):
        return "ausente"
    return "inconclusivo"


def opcao_atendente(textos: list[str]) -> str | None:
    """Número da opção "falar com atendente" (ou fallback administrativo/outros) num menu de robô."""
    for regex in (_RE_MENU_PRIMARIO, _RE_MENU_SECUNDARIO):
        for texto in textos:
            m = regex.search(_norm(texto))
            if m:
                return m.group(1)
    return None


def resposta_para_robo(textos: list[str], nome_remetente: str = "Nickolas") -> str | None:
    """Decide o que responder a outro robô: o dígito da opção "falar com
    atendente" do menu, ou `nome_remetente`, que quem chama troca por uma
    identificação completa (montar_identificacao: quem sou, que não sou
    paciente e que procuro a gestão).

    Nas respostas reais, quase nenhum robô tem opção de atendente: pedem
    nome, oferecem consulta ("Como posso te ajudar?", "Deseja agendar?") ou
    avisam que vão retornar. Em todos esses casos a identificação serve, e a
    pessoa que assumir a conversa já entende o assunto. (O antigo "Assunto
    administrativo…" é que saía solto; a identificação explica.)
    """
    digito = opcao_atendente(textos)
    if digito:
        return digito
    if any((t or "").strip() for t in textos):
        return nome_remetente
    return None


def pede_nome(textos: list[str]) -> bool:
    """O robô pediu nome/motivo do contato (para os testes e o log)."""
    junto = " ".join(_norm(t) for t in textos)
    return any(re.search(p, junto) for p in _PADROES_PEDE_NOME)


def mensagens_recebidas(bolhas: list[dict], enviadas: list[str],
                        desde: datetime) -> list[dict]:
    """Bolhas da clínica (não são nossas) a partir de `desde`."""
    inicio = desde.replace(second=0, microsecond=0)
    nossas = [b for b in bolhas if any(texto_confere(b["texto"], e) for e in enviadas)]
    eu = nossas[0]["remetente"] if nossas else None
    return [b for b in bolhas
            if b["quando"] and b["quando"] >= inicio
            and (b["remetente"] != eu if eu else
                 not any(texto_confere(b["texto"], e) for e in enviadas))]
