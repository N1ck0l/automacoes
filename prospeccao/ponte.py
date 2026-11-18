"""Cliente HTTP da ponte local do WhatsApp (ponte_whatsapp/ponte.js, Baileys).

Só fala com 127.0.0.1. Usa apenas a biblioteca padrão.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request

PORTA_PADRAO = int(os.environ.get("PONTE_PORTA", "8790"))


class PonteIndisponivel(Exception):
    """A ponte não está rodando (ou não respondeu)."""


class ErroPonte(Exception):
    """A ponte respondeu com erro. `codigo` é o status HTTP; `erro`, o motivo."""

    def __init__(self, codigo: int, erro: str) -> None:
        super().__init__(f"{codigo}: {erro}")
        self.codigo = codigo
        self.erro = erro


class ClientePonte:
    def __init__(self, porta: int = PORTA_PADRAO, timeout: float = 60.0) -> None:
        self.base = f"http://127.0.0.1:{porta}"
        self.timeout = timeout

    def _pedir(self, metodo: str, rota: str, corpo: dict | None = None,
               timeout: float | None = None) -> dict:
        dados = json.dumps(corpo).encode("utf-8") if corpo is not None else None
        req = urllib.request.Request(
            self.base + rota, data=dados, method=metodo,
            headers={"Content-Type": "application/json"} if dados else {})
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as exc:
            try:
                erro = json.loads(exc.read().decode("utf-8")).get("erro", "")
            except Exception:  # noqa: BLE001
                erro = ""
            raise ErroPonte(exc.code, erro or str(exc)) from exc
        except (urllib.error.URLError, ConnectionError, TimeoutError, OSError) as exc:
            raise PonteIndisponivel(str(exc)) from exc

    def status(self) -> dict:
        return self._pedir("GET", "/status", timeout=5)

    def verificar(self, numero: str) -> dict:
        return self._pedir("POST", "/verificar", {"numero": numero})

    def enviar(self, numero: str, texto: str, digitar: bool = True) -> dict:
        return self._pedir("POST", "/enviar", {"numero": numero, "texto": texto,
                                               "digitar": digitar})

    def enviar_arquivo(self, numero: str, caminho: str, legenda: str = "") -> dict:
        return self._pedir("POST", "/enviar-arquivo",
                           {"numero": numero, "caminho": caminho, "legenda": legenda},
                           timeout=120)

    def conversa(self, numero: str) -> dict:
        return self._pedir("GET", "/conversa?" + urllib.parse.urlencode({"numero": numero}))

    def eventos(self, apos: int = 0) -> dict:
        return self._pedir("GET", f"/eventos?apos={int(apos)}", timeout=10)
