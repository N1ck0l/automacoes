"""Notificações opcionais: Telegram, e-mail (alertas) e rascunhos no Gmail."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request


def eh_lead_quente(categoria: str, config: dict | None = None) -> bool:
    """Retorna True se a categoria deve disparar alerta imediato."""
    cats = (config or {}).get("telegram_categorias") or ["INTERESSE", "DUVIDA"]
    return str(categoria or "").upper() in {str(c).upper() for c in cats}


def notificar_telegram(
    titulo: str,
    texto: str,
    config: dict | None = None,
    timeout: float = 5.0,
) -> bool:
    """Envia alerta via Telegram Bot API se token e chat_id estiverem configurados.

    Nunca levanta exceção em caso de falha de rede ou configuração ausente.
    """
    cfg = config or {}
    token = str(cfg.get("telegram_bot_token") or os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
    chat_id = str(cfg.get("telegram_chat_id") or os.environ.get("TELEGRAM_CHAT_ID") or "").strip()
    if not token or not chat_id:
        return False

    corpo = f"{titulo}\n\n{texto}".strip() if texto else titulo
    payload = json.dumps({
        "chat_id": chat_id,
        "text": corpo[:4000],
        "disable_web_page_preview": True,
    }).encode("utf-8")

    req = urllib.request.Request(
        url=f"https://api.telegram.org/bot{token}/sendMessage",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return 200 <= getattr(resp, "status", 200) < 300
    except urllib.error.HTTPError as exc:
        exc.close()
        return False
    except (urllib.error.URLError, OSError, ValueError):
        return False



# --- E-mail (Gmail com senha de app) ------------------------------------------
#
# config.local.json:
#   "email_usuario":   conta Gmail que envia os alertas e guarda os rascunhos
#   "email_senha_app": senha de app de 16 letras (myaccount.google.com/apppasswords;
#                      exige verificação em duas etapas). NÃO é a senha da conta.
#   "email_alertas":   para onde vão os alertas (padrão: o próprio email_usuario)
# Sem usuário ou senha, as funções abaixo não fazem nada e retornam False.

def _credenciais_email(cfg: dict) -> tuple[str, str] | None:
    usuario = str(cfg.get("email_usuario") or "").strip()
    senha = str(cfg.get("email_senha_app") or os.environ.get("EMAIL_SENHA_APP") or "")
    senha = senha.replace(" ", "").strip()
    return (usuario, senha) if usuario and senha else None


def _montar_email(remetente: str, para: str, assunto: str, corpo: str):
    from email.message import EmailMessage
    from email.utils import formatdate, make_msgid
    msg = EmailMessage()
    msg["From"] = remetente
    msg["To"] = para
    msg["Subject"] = assunto
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid()
    msg.set_content(corpo)
    return msg


def enviar_email_alerta(titulo: str, texto: str, config: dict | None = None,
                        timeout: float = 15.0) -> bool:
    """Alerta por e-mail (canal que não depende do WhatsApp). Nunca levanta exceção."""
    cfg = config or {}
    cred = _credenciais_email(cfg)
    if not cred:
        return False
    usuario, senha = cred
    destino = str(cfg.get("email_alertas") or usuario).strip()
    try:
        import smtplib
        msg = _montar_email(usuario, destino, f"[Prospecção] {titulo}", texto or titulo)
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=timeout) as smtp:
            smtp.login(usuario, senha)
            smtp.send_message(msg)
        return True
    except Exception:  # noqa: BLE001 - alerta é melhor esforço
        return False


def criar_rascunho_gmail(para: str, assunto: str, corpo: str, config: dict | None = None,
                         timeout: float = 20.0) -> bool:
    """Cria um RASCUNHO no Gmail (não envia nada): você revisa e clica em Enviar.

    Usa IMAP (APPEND na pasta marcada como Drafts, qualquer que seja o idioma).
    """
    cfg = config or {}
    cred = _credenciais_email(cfg)
    if not cred:
        return False
    usuario, senha = cred
    try:
        import imaplib
        import re
        import time
        msg = _montar_email(usuario, para, assunto, corpo)
        with imaplib.IMAP4_SSL("imap.gmail.com", 993, timeout=timeout) as imap:
            imap.login(usuario, senha)
            pasta = None
            _, pastas = imap.list()
            for linha in pastas or []:
                texto = linha.decode("utf-8", "replace") if isinstance(linha, bytes) else str(linha)
                if r'\Drafts' in texto:
                    m = re.search(r'"([^"]+)"\s*$', texto) or re.search(r"(\S+)\s*$", texto)
                    pasta = m.group(1) if m else None
                    break
            if not pasta:
                return False
            status, _ = imap.append(f'"{pasta}"', r'\Draft',
                                    imaplib.Time2Internaldate(time.time()), msg.as_bytes())
            return status == "OK"
    except Exception:  # noqa: BLE001
        return False


def email_configurado(config: dict | None = None) -> bool:
    """Há conta Gmail e senha de app para enviar/criar rascunhos?"""
    return _credenciais_email(config or {}) is not None


def enviar_email(para: str, assunto: str, corpo: str, config: dict | None = None,
                 timeout: float = 20.0) -> bool:
    """Envia um e-mail pela conta configurada (Gmail guarda em Enviados).

    Retorna False sem credenciais ou em qualquer falha (nunca levanta exceção).
    """
    cfg = config or {}
    cred = _credenciais_email(cfg)
    if not cred or "@" not in (para or ""):
        return False
    usuario, senha = cred
    try:
        import smtplib
        msg = _montar_email(usuario, para, assunto, corpo)
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=timeout) as smtp:
            smtp.login(usuario, senha)
            smtp.send_message(msg)
        return True
    except Exception:  # noqa: BLE001
        return False
