#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Testes do motor 'api' (ponte Baileys) e do modo vigia, com uma ponte falsa.

    python -m unittest test_ponte -v
"""

import argparse
import io
import json
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from datetime import datetime
from pathlib import Path

import testes_seguros  # noqa: F401  (blindagem: ver testes_seguros.py)
import prospeccao.trava as trava
import prospeccao_whatsapp as pw
from prospeccao.ponte import ErroPonte, PonteIndisponivel

# Nada de arquivos reais: trava, banco, backups e lista de números da ponte.
_ISOLADO = Path(tempfile.mkdtemp())
trava.ARQUIVO_TRAVA = pw.ARQUIVO_TRAVA = _ISOLADO / ".envio.lock"
pw.ARQUIVO_BANCO = _ISOLADO / "prospeccao.db"
pw.PASTA_BACKUPS = _ISOLADO / "backups"
pw.ARQUIVO_NUMEROS_PONTE = _ISOLADO / "numeros_monitorados.json"


class PonteFalsa:
    def __init__(self, conectado=True, existe=True, falha_envio=None, mensagens=None,
                 eventos=None):
        self.conectado, self.existe = conectado, existe
        self.falha_envio = falha_envio
        self.mensagens = mensagens or []
        self.lotes = list(eventos or [])
        self.enviadas: list[tuple[str, str]] = []
        self.arquivos: list[tuple[str, str]] = []

    def status(self):
        if self.conectado is None:
            raise PonteIndisponivel("connection refused")
        return {"conectado": self.conectado, "inicio": "a"}

    def verificar(self, numero):
        return {"existe": self.existe}

    def enviar(self, numero, texto, digitar=True):
        if self.falha_envio:
            raise self.falha_envio
        self.enviadas.append((numero, texto))
        return {"ok": True, "id": "X"}

    def enviar_arquivo(self, numero, caminho, legenda=""):
        self.arquivos.append((numero, Path(caminho).name))
        return {"ok": True}

    def conversa(self, numero):
        return {"jid": f"{numero}@s.whatsapp.net", "mensagens": self.mensagens}

    def eventos(self, apos=0):
        lote = self.lotes.pop(0) if self.lotes else []
        return {"inicio": "a", "seq": 0, "eventos": [e for e in lote if e["seq"] > apos]}


CONTATO = {"clinica": "Clínica Alfa", "bairro": "Centro", "cidade": "Aracaju",
           "telefone": "557999000001"}


class BaseApi(unittest.TestCase):
    def setUp(self):
        self._orig = (pw.ARQUIVO_LOG, pw.MOTOR)
        self._tmp = tempfile.TemporaryDirectory()
        self.tmpdir = Path(self._tmp.name)
        pw.ARQUIVO_LOG = self.tmpdir / "historico.jsonl"

    def tearDown(self):
        pw.ARQUIVO_LOG, pw.MOTOR = self._orig
        self._tmp.cleanup()

    def _enviar(self, ponte, **kw):
        sessao = pw.SessaoAPI(ponte)
        with redirect_stdout(io.StringIO()):
            ok = sessao.enviar(dict(CONTATO), "Bom dia! Mensagem de teste.",
                               confirmar=False, **kw)
        return ok, sessao


class TestSessaoAPI(BaseApi):
    def test_envio_confirmado(self):
        ponte = PonteFalsa()
        ok, sessao = self._enviar(ponte)
        self.assertTrue(ok)
        self.assertTrue(sessao.confirmado)
        self.assertIsNone(sessao.ultimo_erro)
        self.assertEqual(ponte.enviadas, [("557999000001", "Bom dia! Mensagem de teste.")])
        self.assertTrue(sessao.enviar_arquivo(Path(pw.__file__)))
        self.assertEqual(ponte.arquivos[0][0], "557999000001")

    def test_sem_whatsapp_nao_envia(self):
        ponte = PonteFalsa(existe=False)
        ok, sessao = self._enviar(ponte)
        self.assertFalse(ok)
        self.assertEqual(sessao.ultimo_erro, pw.SessaoAPI.SEM_WHATSAPP)
        self.assertEqual(ponte.enviadas, [])

    def test_ponte_parada_ou_deslogada(self):
        ok, sessao = self._enviar(PonteFalsa(conectado=None))
        self.assertEqual((ok, sessao.ultimo_erro), (False, pw.SessaoAPI.TECNICO))
        ok, sessao = self._enviar(PonteFalsa(conectado=False))
        self.assertEqual((ok, sessao.ultimo_erro), (False, pw.SessaoAPI.DESLOGADO))

    def test_sem_resposta_apos_envio_conta_como_enviada(self):
        # Pode ter saído: nunca reenviar por engano.
        ok, sessao = self._enviar(PonteFalsa(falha_envio=PonteIndisponivel("timeout")))
        self.assertTrue(ok)
        self.assertFalse(sessao.confirmado)
        self.assertEqual(sessao.ultimo_erro, pw.SessaoAPI.NAO_CONFIRMADO)

    def test_recusa_da_ponte_nao_conta_como_enviada(self):
        ok, sessao = self._enviar(PonteFalsa(falha_envio=ErroPonte(500, "falhou")))
        self.assertEqual((ok, sessao.ultimo_erro), (False, pw.SessaoAPI.TECNICO))

    def test_bloqueia_segundo_envio_no_dia(self):
        pw.atualizar_historico(dict(CONTATO), "já foi", "automatico", "novo")
        ponte = PonteFalsa()
        ok, sessao = self._enviar(ponte)
        self.assertEqual((ok, sessao.ultimo_erro), (False, pw.SessaoAPI.BLOQUEADO))
        self.assertEqual(ponte.enviadas, [])

    def test_conversa_inclui_o_que_enviamos_pelo_navegador(self):
        enviada = "Bom dia! Meu nome é Nickolas e desenvolvo automações."
        pw.ARQUIVO_LOG.write_text(json.dumps({
            "timestamp": "2026-11-18T09:30:00", "telefone": "557999000001",
            "mensagem": enviada}) + "\n", encoding="utf-8")
        resposta = datetime(2026, 11, 18, 9, 41).timestamp()
        ponte = PonteFalsa(mensagens=[{"de_mim": False, "quando": resposta,
                                       "texto": "Irei direcionar para o setor responsável",
                                       "nome": "Ana"}])
        bolhas = pw.ler_conversa(pw.SessaoAPI(ponte), "557999000001")
        self.assertEqual([b["remetente"] for b in bolhas], ["eu", "Ana"])
        self.assertEqual(
            pw.classificar_resposta(bolhas, [enviada], datetime(2026, 11, 18, 9, 30)),
            "respondeu")


class TestChaveNumero(unittest.TestCase):
    def test_nono_digito(self):
        self.assertEqual(pw.chave_numero("557999000088"), pw.chave_numero("5579999000088"))
        self.assertNotEqual(pw.chave_numero("557999000088"), pw.chave_numero("557999000089"))
        self.assertEqual(pw.chave_numero("+55 (79) 99900-0088"), "557999000088")


class TestVigia(BaseApi):
    def setUp(self):
        super().setUp()
        self._orig_v = (pw.processar_vigia, pw.dia_util, pw.PASTA_LOGS, pw.notificar_windows,
                        pw.varredura)
        self.varreduras = []
        pw.varredura = lambda planilha, args, msgs, sessao=None: self.varreduras.append(1) or []
        pw.PASTA_LOGS = self.tmpdir / "logs"
        pw.dia_util = lambda agora=None: True
        pw.notificar_windows = lambda *a: None
        self.processados: list[set] = []
        pw.processar_vigia = lambda planilha, args, msgs, tels, sessao=None, textos=None: (
            self.processados.append(set(tels)) or ["ok"])
        self.planilha = pw.Planilha(self.tmpdir / "prospeccao.csv")
        for i, (nome, status) in enumerate([("Clínica Alfa", "enviado"),
                                            ("Clínica Beta", "pendente")]):
            self.planilha.adicionar({c: "" for c in pw.COLUNAS} | {
                "clinica": nome, "bairro": "Centro", "cidade": "Aracaju",
                "telefone": f"55799900000{i + 1}", "status": status})
        self.planilha.salvar()
        self.args = argparse.Namespace(hora_inicio=0, hora_fim=24, espera_min=0,
                                       espera_max=0, resumo_para=None)

    def tearDown(self):
        (pw.processar_vigia, pw.dia_util, pw.PASTA_LOGS, pw.notificar_windows,
         pw.varredura) = self._orig_v
        super().tearDown()

    def _rodar(self, lotes, ciclos=2):
        with redirect_stdout(io.StringIO()):
            pw.rodar_vigia(self.planilha, self.args, {}, cliente=PonteFalsa(eventos=lotes),
                           max_ciclos=ciclos, pausa=0)

    def test_responde_so_clinica_abordada_e_com_nono_digito(self):
        agora = time.time()
        self._rodar([[
            # mesmo número da Alfa, mas com o 9º dígito (como o WhatsApp devolve)
            {"seq": 1, "numero": "5579999000001", "quando": agora, "texto": "Oi"},
            {"seq": 2, "numero": "557999000002", "quando": agora, "texto": "Beta"},  # não abordada
            {"seq": 3, "numero": "5511988887777", "quando": agora, "texto": "pessoal"},
        ]])
        self.assertEqual(self.processados, [{"557999000001"}])

    def test_varredura_roda_ao_abrir_e_nao_a_cada_ciclo(self):
        self._rodar([[], [], []], ciclos=3)
        self.assertEqual(len(self.varreduras), 1)  # próxima só daqui a 15 min

    def test_fora_da_janela_so_acumula(self):
        self.args.hora_inicio, self.args.hora_fim = 0, 0
        self._rodar([[{"seq": 1, "numero": "557999000001", "quando": time.time(),
                       "texto": "Oi"}]])
        self.assertEqual(self.processados, [])

    def test_espera_antes_de_responder(self):
        self.args.espera_min = self.args.espera_max = 3600
        self._rodar([[{"seq": 1, "numero": "557999000001", "quando": time.time(),
                       "texto": "Oi"}]])
        self.assertEqual(self.processados, [])


class TestMotor(unittest.TestCase):
    def test_fabrica_respeita_motor(self):
        original = pw.MOTOR
        try:
            pw.MOTOR = "api"
            self.assertIsInstance(pw.nova_sessao(), pw.SessaoAPI)
            pw.MOTOR = "web"
            self.assertIsInstance(pw.nova_sessao(), pw.SessaoWeb)
        finally:
            pw.MOTOR = original


if __name__ == "__main__":
    unittest.main()
