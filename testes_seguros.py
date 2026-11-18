"""Blindagem dos testes: importe ANTES de qualquer teste (todos os test_*.py fazem).

Os testes nunca podem usar o que é real na máquina do operador:
- config.local.json (senha de app, envio automático de e-mail, motor 'api');
- e-mail (SMTP/IMAP), Telegram e notificações do sistema;
- trava de envio, banco, backups e lista de números da ponte.

Em 18/11/2026, com a senha de app recém-configurada, um teste leu o
config.local.json real e tentou mandar a proposta para o e-mail fictício do
teste. Daqui em diante, qualquer tentativa de envio real em teste levanta erro.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import prospeccao.trava as trava
import prospeccao_whatsapp as pw
from prospeccao import notificacoes
from prospeccao.config import CONFIG_PADRAO


class EnvioRealEmTeste(AssertionError):
    """Um teste tentou falar com o mundo real (e-mail/Telegram/notificação)."""


def _proibido(nome):
    def bloqueio(*_a, **_k):
        raise EnvioRealEmTeste(f"teste tentou usar {nome} de verdade")
    return bloqueio


ISOLADO = Path(tempfile.mkdtemp(prefix="testes_prospeccao_"))


def config_de_teste(*_a, **_k) -> dict:
    """Configuração padrão, sem credenciais e sem envio automático."""
    return dict(CONFIG_PADRAO)


# Configuração: nada do config.local.json real.
pw.carregar_config = config_de_teste
pw.MOTOR = "web"

# Canais externos. Envio de proposta e rascunho: erro se um teste chegar a
# usar o de verdade (quem testa isso substitui pela versão falsa). Alerta:
# silencioso (vários fluxos alertam; sem credenciais ele já não faria nada).
for _nome in ("enviar_email", "criar_rascunho_gmail"):
    setattr(pw, _nome, _proibido(_nome))
    setattr(notificacoes, _nome, _proibido(_nome))
pw.enviar_email_alerta = lambda *_a, **_k: False
notificacoes.enviar_email_alerta = lambda *_a, **_k: False
pw.email_configurado = lambda *_a, **_k: False
pw.notificar_telegram = lambda *_a, **_k: False
pw.notificar_sistema = lambda *_a, **_k: None

# Arquivos reais.
trava.ARQUIVO_TRAVA = pw.ARQUIVO_TRAVA = ISOLADO / ".envio.lock"
pw.ARQUIVO_BANCO = ISOLADO / "prospeccao.db"
pw.PASTA_BACKUPS = ISOLADO / "backups"
pw.ARQUIVO_NUMEROS_PONTE = ISOLADO / "numeros_monitorados.json"
pw.PASTA_LOGS = ISOLADO / "logs"
