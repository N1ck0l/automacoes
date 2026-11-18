#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Testes do comportamento aprendido com as respostas reais das clínicas
(10 a 18/11/2026): tempo de resposta de robô, cortesia, pedido de e-mail,
cartão de contato da gestão, lead quente, backup e lista de números da ponte.

    python -m unittest test_inteligencia -v
"""

import argparse
import io
import json
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta
from pathlib import Path

import testes_seguros  # noqa: F401  (blindagem: ver testes_seguros.py)
import prospeccao.trava as trava
import prospeccao_whatsapp as pw
from test_ponte import PonteFalsa

_ISOLADO = Path(tempfile.mkdtemp())
trava.ARQUIVO_TRAVA = pw.ARQUIVO_TRAVA = _ISOLADO / ".envio.lock"
pw.ARQUIVO_BANCO = _ISOLADO / "prospeccao.db"
pw.PASTA_BACKUPS = _ISOLADO / "backups"
pw.ARQUIVO_NUMEROS_PONTE = _ISOLADO / "numeros_monitorados.json"

ENVIADA = ("Bom dia, tudo bem? Meu nome é Nickolas e desenvolvo automações para clínicas "
           "em Aracaju. Posso encaminhar uma breve apresentação para a Clínica Alfa?")


def _bolhas(*recebidas, envio=datetime(2026, 11, 18, 9, 28, 30)):
    """[(segundos depois do envio, texto)] -> bolhas no formato da leitura."""
    bolhas = [{"remetente": "eu", "quando": envio, "texto": ENVIADA}]
    for segundos, texto in recebidas:
        bolhas.append({"remetente": "Clínica", "quando": envio + timedelta(seconds=segundos),
                       "texto": texto})
    return bolhas, envio


class TestClassificadorComRespostasReais(unittest.TestCase):
    def _classe(self, *recebidas):
        bolhas, envio = _bolhas(*recebidas)
        return pw.classificar_resposta(bolhas, [ENVIADA], envio)

    def test_robo_responde_em_segundos_mesmo_virando_o_minuto(self):
        # Consultório odontológico: enviado 09:28:30, saudação automática às 09:28:35.
        self.assertEqual(self._classe((5, "Olá! Que bom receber seu contato! Sou Dra. Exemplo "
                                          "Neves. Me diga, em que posso te ajudar?")),
                         "resposta automatica")

    def test_pessoa_rapida_nao_vira_robo(self):
        # Uma clínica recusou em 50 s; outra respondeu "pode sim".
        self.assertEqual(self._classe((50, "pode sim")), "respondeu")

    def test_frases_de_robo_vistas_nas_clinicas(self):
        for texto in ("Bom dia *Nickolas*, em alguns instantes um atendente irá prosseguir "
                      "com seu atendimento.",
                      "*INFORMAÇÃO* Você foi transferido... Aguarde!",
                      "🤩 Como avalia o nosso atendimento? Sua opinião é importante para nós!",
                      "Encaminhei sua solicitação à equipe, que entrará em contato em breve"):
            self.assertEqual(self._classe((400, texto)), "resposta automatica", texto)

    def test_atendente_de_ia_em_25s(self):
        self.assertEqual(self._classe((25, "Olá, Nickolas. Por aqui posso ajudar com "
                                           "agendamento de exames e informações")),
                         "resposta automatica")

    def test_robo_sem_menu_de_atendente_recebe_identificacao(self):
        for texto in ("Olá! Seja bem-vindo(a) à Clínica Sorriso! Como podemos ajudar você hoje?",
                      "Vamos agendar sua avaliação? Me conte seu nome, qual tratamento procura",
                      "Escolha uma das opções abaixo: 1️⃣ Quero melhorar meu sorriso "
                      "2️⃣ Estou com dor 3️⃣ Quero agendar uma consulta"):
            self.assertEqual(pw.resposta_para_robo([texto]), "Nickolas", texto)
        self.assertEqual(pw.resposta_para_robo(["5. Falar com um atendente."]), "5")

    def test_cortesia(self):
        for texto in ("Disponha!", "Disponha, Nickolas. Tenha um ótimo dia",
                      "Tenha uma excelente semana!", "Obrigada", "ok"):
            self.assertTrue(pw.eh_cortesia(texto), texto)
        for texto in ("pode sim", "Sr. Joana Silva.", "Pode ser quinta às 14h?",
                      "o senhor poderia antecipar de qual assunto se trata?"):
            self.assertFalse(pw.eh_cortesia(texto), texto)

    def test_email_e_cartao_de_contato(self):
        self.assertEqual(pw.extrair_email(["Bom dia! Estarei te encaminhando o e-mail "
                                           "comercial dele;\ndr.exemplo@example.com"]),
                         "dr.exemplo@example.com")
        self.assertEqual(pw.extrair_email(["Pode enviar para o email\n"
                                           "Contato@clinica.example.com."]),
                         "contato@clinica.example.com")
        self.assertIsNone(pw.extrair_email(["Pode mandar por aqui mesmo"]))
        self.assertEqual(pw.extrair_contato_compartilhado(["[contato] Joana Gestão +557999000088"]),
                         ("Joana Gestão", "557999000088"))

    def test_nomes_e_telefone(self):
        self.assertEqual(pw.primeiro_nome("Joana Gestão"), "Joana")
        self.assertEqual(pw.primeiro_nome("Dra. Ana Lima"), "Dra. Ana")
        self.assertEqual(pw.primeiro_nome("Gestão Exemplo"), "")
        self.assertEqual(pw.formatar_telefone("5579981677954"), "(79) 98167-7954")


class BaseFluxo(unittest.TestCase):
    TEL = "5579999000001"

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self._orig = (pw.ARQUIVO_LOG, pw.PASTA_LOGS, pw.notificar_windows,
                      pw.criar_rascunho_gmail, pw.MOTOR)
        pw.ARQUIVO_LOG = self.dir / "historico.jsonl"
        pw.PASTA_LOGS = self.dir / "logs"
        self.alertas = []
        pw.notificar_windows = lambda titulo, texto: self.alertas.append((titulo, texto))
        self.rascunhos = []
        pw.criar_rascunho_gmail = lambda para, assunto, corpo, cfg=None: (
            self.rascunhos.append((para, assunto, corpo)) or False)
        self.planilha = pw.Planilha(self.dir / "prospeccao.db")
        self.contato = {c: "" for c in pw.COLUNAS} | {
            "clinica": "Clínica Alfa", "bairro": "Centro", "cidade": "Aracaju",
            "telefone": self.TEL, "status": "enviado", "resposta": "aguardando",
            "variante": "completa", "etapa": "apresentacao", "versao_textos": "x",
            "ultimo_envio": (datetime.now() - timedelta(minutes=30)).isoformat(timespec="seconds")}
        self.planilha.adicionar(self.contato)
        self.planilha.salvar()
        pw.ARQUIVO_LOG.write_text(json.dumps({
            "timestamp": self.contato["ultimo_envio"], "telefone": self.TEL,
            "clinica": "Clínica Alfa", "tipo": "inicial", "mensagem": ENVIADA}) + "\n",
            encoding="utf-8")
        self.args = argparse.Namespace(limite_dia=10, intervalo_min=0, intervalo_max=0,
                                       resumo_para="5579981677954")

    def tearDown(self):
        (pw.ARQUIVO_LOG, pw.PASTA_LOGS, pw.notificar_windows, pw.criar_rascunho_gmail,
         pw.MOTOR) = self._orig
        self._tmp.cleanup()

    def _ponte(self, *recebidas):
        base = datetime.fromisoformat(self.contato["ultimo_envio"])
        return PonteFalsa(mensagens=[
            {"de_mim": False, "quando": (base + timedelta(minutes=5 + i)).timestamp(),
             "texto": t, "nome": "Recepção"} for i, t in enumerate(recebidas)])

    def _processar(self, ponte, textos=None):
        with redirect_stdout(io.StringIO()):
            return pw.processar_vigia(self.planilha, self.args, pw.carregar_mensagens(),
                                      {self.TEL}, sessao=pw.SessaoAPI(ponte), textos=textos)


class TestPedidoDeEmail(BaseFluxo):
    def test_confirma_cria_texto_e_avisa(self):
        ponte = self._ponte("Bom dia! Pode enviar para o email\nContato@clinicaalfa.example.com")
        feitos = self._processar(ponte)
        self.assertTrue(any("e-mail" in f for f in feitos), feitos)
        para_clinica = [t for n, t in ponte.enviadas if n == self.TEL]
        self.assertEqual(len(para_clinica), 1)                # só a confirmação, sem o resumo
        self.assertIn("contato@clinicaalfa.example.com", para_clinica[0])
        self.assertNotIn("{", para_clinica[0])
        para, assunto, corpo = self.rascunhos[0]
        self.assertEqual(para, "contato@clinicaalfa.example.com")
        self.assertIn("Clínica Alfa", assunto)
        self.assertIn("n1ck0l.github.io", corpo)             # link da demonstração
        self.assertIn("(79) 98167-7954", corpo)              # assinatura com o WhatsApp
        self.assertNotIn("{", corpo)
        aviso = [t for n, t in ponte.enviadas if n == "5579981677954"]
        self.assertTrue(aviso and "Assunto:" in aviso[0])    # sem Gmail: texto pronto no aviso
        p = pw.carregar_planilha(self.planilha.caminho)
        self.assertEqual((p.contatos[0]["email"], p.contatos[0]["etapa"]),
                         ("contato@clinicaalfa.example.com", "email"))
        # Ler de novo não repete a ação
        ponte2 = self._ponte("Bom dia! Pode enviar para o email\nContato@clinicaalfa.example.com")
        self._processar(ponte2)
        self.assertEqual([t for n, t in ponte2.enviadas if n == self.TEL], [])


class TestEmailAutomatico(BaseFluxo):
    PEDIDO = "Bom dia! Pode enviar para o email\nContato@clinicaalfa.example.com"

    def setUp(self):
        super().setUp()
        self._orig_e = (pw.carregar_config, pw.email_configurado, pw.enviar_email)
        self.config = {"email_envio_automatico": True}
        pw.carregar_config = lambda *a, **k: dict(self.config)
        self.enviados = []
        self.credenciais = False
        pw.email_configurado = lambda cfg=None: self.credenciais
        pw.enviar_email = lambda para, assunto, corpo, cfg=None: (
            self.credenciais and not self.enviados.append((para, assunto, corpo)))

    def tearDown(self):
        pw.carregar_config, pw.email_configurado, pw.enviar_email = self._orig_e
        super().tearDown()

    def _estado(self):
        with redirect_stdout(io.StringIO()):
            return pw.carregar_planilha(self.planilha.caminho).contatos[0]

    def test_envia_na_hora_com_senha(self):
        self.credenciais = True
        ponte = self._ponte(self.PEDIDO)
        self._processar(ponte)
        self.assertEqual(self.enviados[0][0], "contato@clinicaalfa.example.com")
        self.assertEqual(self.rascunhos, [])                  # não cria rascunho
        self.assertNotIn(self._estado()["email_enviado"], ("", "pendente"))
        aviso = [t for n, t in ponte.enviadas if n == "5579981677954"][0]
        self.assertIn("já enviei", aviso)

    def test_sem_senha_fica_pendente_e_sai_depois(self):
        ponte = self._ponte(self.PEDIDO)
        self._processar(ponte)
        self.assertEqual(self.enviados, [])
        self.assertEqual(self._estado()["email_enviado"], "pendente")
        self.assertIn("assim que a senha", [t for n, t in ponte.enviadas
                                            if n == "5579981677954"][0])
        # Você cola a senha: na próxima rodada o e-mail sai, uma vez só.
        self.credenciais = True
        self.planilha.recarregar()
        avisos = pw.enviar_emails_pendentes(self.planilha, pw.carregar_mensagens())
        self.assertEqual(len(self.enviados), 1)
        self.assertIn("Proposta enviada", avisos[0])
        self.planilha.recarregar()
        self.assertEqual(pw.enviar_emails_pendentes(self.planilha, pw.carregar_mensagens()), [])
        self.assertEqual(len(self.enviados), 1)

    def test_sem_envio_automatico_continua_rascunho(self):
        self.config = {}
        self._processar(self._ponte(self.PEDIDO))
        self.assertEqual(self.enviados, [])
        self.assertEqual(len(self.rascunhos), 1)


class TestIndicacaoDaGestao(BaseFluxo):
    def test_agradece_e_apresenta_ao_gestor(self):
        ponte = self._ponte("Olá, segue o contato da nossa gestão",
                            "[contato] Joana Gestão +557999000088")
        self._processar(ponte)
        destinos = [n for n, _ in ponte.enviadas]
        self.assertIn(self.TEL, destinos)
        self.assertIn("557999000088", destinos)
        agradecimento = next(t for n, t in ponte.enviadas if n == self.TEL)
        self.assertIn("Joana", agradecimento)
        abertura = next(t for n, t in ponte.enviadas if n == "557999000088")
        self.assertTrue(abertura.startswith("Olá, Joana"), abertura)
        self.assertIn("Clínica Alfa", abertura)
        p = pw.carregar_planilha(self.planilha.caminho)
        gestor = next(c for c in p.contatos if c["telefone"] == "557999000088")
        self.assertEqual((gestor["status"], gestor["indicado_por"]), ("enviado", "Clínica Alfa"))
        self.assertEqual(p.contatos[0]["etapa"], "indicou")


class TestNaoAtropelaConversas(BaseFluxo):
    def test_robo_antigo_nao_gera_identificacao_depois_da_2a_etapa(self):
        # Clínicas que já receberam o resumo: mensagens antigas
        # (antes do último envio) não podem disparar "Não sou paciente...".
        self.contato.update(etapa="resumo")
        self.planilha.salvar()
        ponte = self._ponte("Olá! Seja bem-vindo(a)! Como podemos ajudar você hoje?")
        ponte.mensagens[0]["quando"] -= 3600 * 2  # chegou antes do último envio
        self._processar(ponte)
        self.assertEqual([n for n, _ in ponte.enviadas if n == self.TEL], [])

    def test_conversa_assumida_pelo_operador(self):
        # O robô da clínica respondeu, mas você já mandou a apresentação à mão.
        base = datetime.fromisoformat(self.contato["ultimo_envio"])
        ponte = PonteFalsa(mensagens=[
            {"de_mim": False, "quando": (base + timedelta(seconds=5)).timestamp(),
             "texto": "Olá! Me diga, em que posso te ajudar?", "nome": "Clínica"},
            {"de_mim": True, "quando": (base + timedelta(minutes=20)).timestamp(),
             "texto": "Segue uma breve apresentação do meu trabalho, escrita à mão.",
             "nome": ""}])
        self._processar(ponte)
        self.assertEqual([n for n, _ in ponte.enviadas if n == self.TEL], [])

    def test_sem_operador_o_robo_recebe_identificacao(self):
        base = datetime.fromisoformat(self.contato["ultimo_envio"])
        ponte = PonteFalsa(mensagens=[
            {"de_mim": False, "quando": (base + timedelta(seconds=4)).timestamp(),
             "texto": "Olá! Me diga, em que posso te ajudar?", "nome": "Robô"}])
        self._processar(ponte)
        enviadas = [t for n, t in ponte.enviadas if n == self.TEL]
        self.assertEqual(len(enviadas), 1)
        # As duas variantes de identificacoes_robo deixam claro que não é paciente.
        self.assertTrue("Não sou paciente" in enviadas[0]
                        or "não se trata de agendamento" in enviadas[0], enviadas[0])
        self.assertIn("gestão", enviadas[0])


class TestLeadQuente(BaseFluxo):
    def setUp(self):
        super().setUp()
        self.contato.update(resposta="respondeu", etapa="resumo")
        self.planilha.salvar()

    def test_avisa_quando_volta_a_escrever(self):
        ponte = self._ponte("Pode ser quinta às 14h?")
        self._processar(ponte, textos={self.TEL: ["Pode ser quinta às 14h?"]})
        aviso = [t for n, t in ponte.enviadas if n == "5579981677954"]
        self.assertTrue(aviso and "voltou a escrever" in aviso[0] and "quinta" in aviso[0])
        self.assertEqual([n for n, _ in ponte.enviadas if n == self.TEL], [])  # nada à clínica

    def test_cortesia_nao_gera_aviso(self):
        ponte = self._ponte("Disponha!")
        self._processar(ponte, textos={self.TEL: ["Disponha!"]})
        self.assertEqual(ponte.enviadas, [])


class TestClienteEsperando(BaseFluxo):
    """Ninguém fica esperando: um dentista esperou 4 h por resposta em 18/11."""

    def setUp(self):
        super().setUp()
        # Primeiro envio há 4 h: a conversa de cada teste vem depois dele.
        envio = (datetime.now() - timedelta(hours=4)).isoformat(timespec="seconds")
        self.contato.update(resposta="respondeu", etapa="resumo", ultimo_envio=envio)
        self.planilha.salvar()
        pw.ARQUIVO_LOG.write_text(json.dumps({
            "timestamp": envio, "telefone": self.TEL, "clinica": "Clínica Alfa",
            "tipo": "inicial", "mensagem": ENVIADA}) + "\n", encoding="utf-8")

    def _conversa(self, *bolhas, agora=None):
        # Hora fixa em segundos inteiros, como a ponte grava: a mesma mensagem
        # tem sempre a mesma hora de uma varredura para outra.
        agora = (agora or datetime.now()).replace(microsecond=0)
        return PonteFalsa(mensagens=[
            {"de_mim": de_mim, "quando": int((agora - timedelta(minutes=min_atras)).timestamp()),
             "texto": texto, "nome": "" if de_mim else "Recepção"}
            for min_atras, de_mim, texto in bolhas])

    def _varrer(self, ponte):
        with redirect_stdout(io.StringIO()):
            pw.varredura(self.planilha, self.args, pw.carregar_mensagens(),
                         sessao=pw.SessaoAPI(ponte))
        return [t for n, t in ponte.enviadas if n == "5579981677954"]

    def test_alerta_aos_30_min_uma_vez_e_insiste_as_2h(self):
        agora = datetime.now()
        conversa = ((60, True, "Segue o resumo."),
                    (40, False, "Qual seria o valor da implantação?"))
        avisos = self._varrer(self._conversa(*conversa, agora=agora))
        self.assertTrue(avisos and "esperando resposta há 40 min" in avisos[0], avisos)
        self.assertIn("valor da implantação", avisos[0])
        # Varredura seguinte: mesma mensagem, mesmo nível -> silêncio.
        self.assertEqual(self._varrer(self._conversa(*conversa, agora=agora)), [])
        # A MESMA mensagem, 90 min depois (2 h 10 min sem resposta): segundo alerta.
        orig_now = pw.datetime
        mais_tarde = agora + timedelta(minutes=90)

        class _Relogio(datetime):
            @classmethod
            def now(cls, tz=None):
                return mais_tarde
        pw.datetime = _Relogio
        try:
            avisos = self._varrer(self._conversa(*conversa, agora=agora))
        finally:
            pw.datetime = orig_now
        self.assertTrue(avisos and "2º alerta" in avisos[0], avisos)

    def test_sem_alerta_quando_nao_ha_ninguem_esperando(self):
        casos = [
            [(60, False, "Pode ser quinta?"), (50, True, "Pode sim, às 14h.")],  # respondemos
            [(60, True, "Segue o resumo."), (45, False, "Disponha!")],          # cortesia
            [(10, True, "Segue o resumo."), (5, False, "Qual o valor?")],       # ainda < 30 min
            [(90, True, "Bom dia!"), (90, False, "Em breve uma de nossas atendentes "
                                                 "irá entrar em contato.")],     # robô
        ]
        for bolhas in casos:
            self.contato["alerta_sla"] = ""
            self.planilha.salvar()
            self.assertEqual(self._varrer(self._conversa(*bolhas)), [], bolhas)


class TestPonteEBackup(BaseFluxo):
    def test_lista_de_numeros_da_ponte(self):
        self.assertTrue(pw.escrever_numeros_monitorados(self.planilha, ["5579981677954"]))
        dados = json.loads(pw.ARQUIVO_NUMEROS_PONTE.read_text(encoding="utf-8"))
        self.assertEqual(set(dados["numeros"]), {self.TEL, "5579981677954"})
        self.assertFalse(pw.escrever_numeros_monitorados(self.planilha, ["5579981677954"]))

    def test_backup_diario_e_limite(self):
        orig = pw.ARQUIVO_BANCO
        pw.ARQUIVO_BANCO = self.planilha.caminho
        try:
            hoje = datetime(2026, 11, 18, 10)
            self.assertIsNotNone(pw.fazer_backup_banco(hoje))
            self.assertIsNone(pw.fazer_backup_banco(hoje))    # 1x por dia
            for i in range(1, 35):
                pw.fazer_backup_banco(hoje + timedelta(days=i))
            copias = sorted(pw.PASTA_BACKUPS.glob("prospeccao_*.db"))
            self.assertEqual(len(copias), pw.BACKUPS_MANTIDOS)
            self.assertIn("2026-12-22", copias[-1].name)
            with redirect_stdout(io.StringIO()):
                copia = pw.carregar_planilha(copias[-1])
            self.assertEqual(copia.contatos[0]["clinica"], "Clínica Alfa")
        finally:
            pw.ARQUIVO_BANCO = orig

    def test_envio_do_dia_nao_roda_sem_ponte(self):
        pw.MOTOR = "api"
        orig = pw.SessaoAPI.healthcheck
        pw.SessaoAPI.healthcheck = lambda self, segundos=25: {"status": "deslogado"}
        try:
            args = argparse.Namespace(hora_inicio=0, hora_fim=24, atraso_max=0,
                                      fim_de_semana=True, limite_dia=2)
            with redirect_stdout(io.StringIO()):
                n = pw.rodar_automatico(self.planilha, args, pw.carregar_mensagens())
        finally:
            pw.SessaoAPI.healthcheck = orig
        self.assertEqual(n, 0)
        self.assertTrue(any("NÃO rodou" in t for t, _ in self.alertas))


if __name__ == "__main__":
    unittest.main()
