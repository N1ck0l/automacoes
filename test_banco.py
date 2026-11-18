#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Testes do armazenamento em SQLite (prospeccao/banco.py e Planilha .db).

    python -m unittest test_banco -v
"""

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

import testes_seguros  # noqa: F401  (blindagem: ver testes_seguros.py)
import minerador_maps as mm
import prospeccao_whatsapp as pw


def _contato(nome, tel, **extra):
    return {c: "" for c in pw.COLUNAS} | {"clinica": nome, "bairro": "Centro",
                                          "cidade": "Aracaju", "telefone": tel,
                                          "status": "pendente"} | extra


class BaseBanco(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.db = self.dir / "prospeccao.db"
        self._orig = (pw.ARQUIVO_LOG, pw.ARQUIVO_BANCO, pw.CSV_LEGADO, pw.JSONL_LEGADO,
                      pw.PASTA_BACKUP_LEGADO)
        pw.ARQUIVO_LOG = pw.ARQUIVO_BANCO = self.db
        pw.CSV_LEGADO = self.dir / "prospeccao.csv"
        pw.JSONL_LEGADO = self.dir / "historico_envios.jsonl"
        pw.PASTA_BACKUP_LEGADO = self.dir / "backup_pre_sqlite"

    def tearDown(self):
        (pw.ARQUIVO_LOG, pw.ARQUIVO_BANCO, pw.CSV_LEGADO, pw.JSONL_LEGADO,
         pw.PASTA_BACKUP_LEGADO) = self._orig
        self._tmp.cleanup()

    def _criar(self, *contatos):
        planilha = pw.Planilha(self.db)
        for c in contatos:
            planilha.adicionar(c)
        planilha.salvar()
        return planilha

    def _carregar(self):
        with redirect_stdout(io.StringIO()):
            return pw.carregar_planilha(self.db)


class TestPlanilhaBanco(BaseBanco):
    def test_ida_e_volta(self):
        self._criar(_contato("Clínica Alfa", "5579999000001", horarios="seg 8-18"),
                    _contato("Clínica Beta", "5579999000002"))
        p = self._carregar()
        self.assertEqual([c["clinica"] for c in p.contatos], ["Clínica Alfa", "Clínica Beta"])
        self.assertEqual(p.contatos[0]["horarios"], "seg 8-18")

    def test_linhas_invalidas_ficam_guardadas_fora_da_fila(self):
        self._criar(_contato("Sem telefone", ""), _contato("Clínica Alfa", "5579999000001"),
                    _contato("Duplicada", "5579999000001"))
        p = self._carregar()
        self.assertEqual(len(p.linhas), 3)
        self.assertEqual([c["clinica"] for c in p.contatos], ["Clínica Alfa"])
        p.salvar()
        self.assertEqual(len(self._carregar().linhas), 3)

    def test_dois_processos_nao_apagam_o_trabalho_um_do_outro(self):
        self._criar(_contato("Clínica Alfa", "5579999000001"),
                    _contato("Clínica Beta", "5579999000002"))
        vigia, envio = self._carregar(), self._carregar()   # dois processos
        vigia.contatos[0]["resposta"] = "respondeu"          # mesma linha,
        envio.contatos[0]["etapa"] = "resumo"                # campos diferentes
        envio.contatos[1]["status"] = "enviado"              # outra linha
        vigia.salvar()
        envio.salvar()                                       # com o CSV, apagava o 'respondeu'
        final = self._carregar()
        self.assertEqual(final.contatos[0]["resposta"], "respondeu")
        self.assertEqual(final.contatos[0]["etapa"], "resumo")
        self.assertEqual(final.contatos[1]["status"], "enviado")

    def test_salvar_sem_mudanca_nao_grava_nada(self):
        self._criar(_contato("Clínica Alfa", "5579999000001"))
        p = self._carregar()
        p.salvar()
        outro = self._carregar()
        outro.contatos[0]["resposta"] = "respondeu"
        outro.salvar()
        p.salvar()  # p não mudou nada: não pode desfazer o 'respondeu'
        self.assertEqual(self._carregar().contatos[0]["resposta"], "respondeu")

    def test_recarregar_mantem_controle_de_alteracoes(self):
        self._criar(_contato("Clínica Alfa", "5579999000001"))
        p = self._carregar()
        outro = self._carregar()
        outro.contatos[0]["etapa"] = "resumo"
        outro.salvar()
        p.recarregar()
        self.assertEqual(p.contatos[0]["etapa"], "resumo")
        p.contatos[0]["resposta"] = "respondeu"
        p.salvar()
        final = self._carregar()
        self.assertEqual(len(final.linhas), 1)  # não duplicou a linha
        self.assertEqual((final.contatos[0]["etapa"], final.contatos[0]["resposta"]),
                         ("resumo", "respondeu"))

    def test_colunas_extras_preservadas(self):
        self._criar(_contato("Clínica Alfa", "5579999000001", observacao="ligar à tarde"))
        p = self._carregar()
        self.assertIn("observacao", p.colunas)
        self.assertEqual(p.contatos[0]["observacao"], "ligar à tarde")

    def test_exportar_csv(self):
        self._criar(_contato("Clínica Alfa", "5579999000001"))
        destino = self.dir / "export.csv"
        pw.exportar_csv(self._carregar(), destino)
        self.assertIn("Clínica Alfa", destino.read_text(encoding="utf-8"))


class TestHistoricoBanco(BaseBanco):
    def test_registra_e_le(self):
        c = _contato("Clínica Alfa", "5579999000001")
        pw.atualizar_historico(c, "Bom dia!", "automatico", "inicial", "curta")
        self.assertEqual(pw.ler_historico()[0]["mensagem"], "Bom dia!")
        self.assertTrue(pw.enviado_hoje("5579999000001"))
        self.assertEqual(pw.envios_hoje(), 1)
        pw.atualizar_historico(c, "Resumo", "automatico", "resumo")
        self.assertEqual([r["tipo"] for r in pw.ler_historico()], ["inicial", "resumo"])
        self.assertEqual(pw.envios_hoje(), 1)  # resumo não conta no limite


class TestMigracao(BaseBanco):
    def test_migra_uma_vez_e_guarda_originais(self):
        pw.salvar_contatos(pw.CSV_LEGADO, [_contato("Clínica Alfa", "5579999000001",
                                                    status="enviado", resposta="respondeu"),
                                           _contato("Sem telefone", "")])
        pw.JSONL_LEGADO.write_text(json.dumps({
            "timestamp": "2026-11-10T08:19:28", "clinica": "Clínica Alfa", "bairro": "Centro",
            "telefone": "5579999000001", "modo": "web", "tipo": "inicial",
            "mensagem": "Bom dia"}) + "\nlinha quebrada\n", encoding="utf-8")
        with redirect_stdout(io.StringIO()):
            pw.garantir_banco()
        p = self._carregar()
        self.assertEqual(len(p.linhas), 2)
        self.assertEqual(p.contatos[0]["resposta"], "respondeu")
        self.assertEqual(pw.ler_historico()[0]["mensagem"], "Bom dia")
        self.assertFalse(pw.CSV_LEGADO.exists())
        self.assertTrue((pw.PASTA_BACKUP_LEGADO / "prospeccao.csv").exists())
        self.assertTrue((pw.PASTA_BACKUP_LEGADO / "historico_envios.jsonl").exists())
        pw.salvar_contatos(pw.CSV_LEGADO, [_contato("Outra", "5579999000009")])
        pw.garantir_banco()  # banco já tem dados: não mexe
        self.assertEqual(len(self._carregar().linhas), 2)


class TestMineradorBanco(BaseBanco):
    def test_integra_no_banco_sem_duplicar(self):
        novo = _contato("Clínica Nova", "5579999000003")
        self.assertEqual(mm.integrar_csv([novo], self.db), (1, 0))
        self.assertEqual(mm.integrar_csv([dict(novo)], self.db), (0, 1))
        self.assertEqual(len(self._carregar().contatos), 1)


if __name__ == "__main__":
    unittest.main()
