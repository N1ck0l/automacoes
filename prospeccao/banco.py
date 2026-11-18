"""Armazenamento em SQLite (prospeccao.db): contatos e histórico de envios.

Substitui o prospeccao.csv e o historico_envios.jsonl. Vários processos (envio
diário, vigia, minerador, dashboard) usam o mesmo arquivo ao mesmo tempo:

- modo WAL + busy_timeout: leitores não bloqueiam quem grava, e quem grava
  espera a vez em vez de falhar;
- `salvar_alteracoes` grava SÓ os campos que mudaram em cada linha, dentro de
  uma transação. Dois processos que mexem em contatos (ou campos) diferentes
  não apagam o trabalho um do outro, como acontecia ao regravar o CSV inteiro.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

CAMPOS_HISTORICO = ("timestamp", "telefone", "clinica", "bairro", "modo", "tipo",
                    "variante", "mensagem")


def eh_banco(caminho) -> bool:
    return Path(caminho).suffix.lower() in (".db", ".sqlite", ".sqlite3")


def conectar(caminho) -> sqlite3.Connection:
    con = sqlite3.connect(str(caminho), timeout=30, isolation_level=None)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=30000")
    con.execute("PRAGMA foreign_keys=ON")
    return con


def garantir_esquema(con: sqlite3.Connection, colunas: list[str]) -> None:
    con.execute("CREATE TABLE IF NOT EXISTS contatos ("
                "id INTEGER PRIMARY KEY, extras TEXT NOT NULL DEFAULT '{}')")
    existentes = {r["name"] for r in con.execute("PRAGMA table_info(contatos)")}
    for coluna in colunas:  # COLUNAS novas no código viram colunas novas no banco
        if coluna not in existentes:
            con.execute(f'ALTER TABLE contatos ADD COLUMN "{coluna}" TEXT NOT NULL DEFAULT \'\'')
    con.execute("CREATE TABLE IF NOT EXISTS historico ("
                "id INTEGER PRIMARY KEY, "
                + ", ".join(f"{c} TEXT NOT NULL DEFAULT ''" for c in CAMPOS_HISTORICO)
                + ", extras TEXT NOT NULL DEFAULT '{}')")
    con.execute("CREATE INDEX IF NOT EXISTS ix_hist_tel ON historico(telefone)")
    con.execute("CREATE INDEX IF NOT EXISTS ix_hist_ts ON historico(timestamp)")
    con.execute("CREATE INDEX IF NOT EXISTS ix_cont_tel ON contatos(telefone)")


# ------------------------------------------------------------------ contatos ---

def carregar_contatos(caminho, colunas: list[str]) -> tuple[list[tuple[int, dict]], list[str]]:
    """[(id, registro)] na ordem de inserção, e as colunas extras encontradas."""
    con = conectar(caminho)
    try:
        garantir_esquema(con, colunas)
        linhas, extras_vistas = [], []
        for r in con.execute("SELECT * FROM contatos ORDER BY id"):
            registro = {c: (r[c] or "") for c in colunas}
            for chave, valor in json.loads(r["extras"] or "{}").items():
                registro[chave] = "" if valor is None else str(valor)
                if chave not in extras_vistas:
                    extras_vistas.append(chave)
            linhas.append((r["id"], registro))
        return linhas, extras_vistas
    finally:
        con.close()


def salvar_alteracoes(caminho, colunas: list[str],
                      itens: list[tuple[int | None, dict, dict | None]]) -> list[int]:
    """Grava inserções e alterações campo a campo, numa transação só.

    `itens`: (id, registro atual, registro como foi carregado). id None =
    linha nova. Retorna o id de cada item, na mesma ordem.
    """
    con = conectar(caminho)
    try:
        garantir_esquema(con, colunas)
        con.execute("BEGIN IMMEDIATE")
        ids: list[int] = []
        for id_, atual, original in itens:
            base = {c: str(atual.get(c, "") or "") for c in colunas}
            extras = {k: str(v) for k, v in atual.items() if k not in colunas and v not in (None, "")}
            if id_ is None:
                nomes = ", ".join(f'"{c}"' for c in colunas)
                marcas = ", ".join("?" for _ in colunas)
                cur = con.execute(f"INSERT INTO contatos ({nomes}, extras) VALUES ({marcas}, ?)",
                                  [base[c] for c in colunas] + [json.dumps(extras, ensure_ascii=False)])
                ids.append(cur.lastrowid)
                continue
            original = original or {}
            mudou = [c for c in colunas if base[c] != str(original.get(c, "") or "")]
            if mudou:
                atribuicoes = ", ".join(f'"{c}" = ?' for c in mudou)
                con.execute(f"UPDATE contatos SET {atribuicoes} WHERE id = ?",
                            [base[c] for c in mudou] + [id_])
            extras_orig = {k: str(v) for k, v in original.items()
                           if k not in colunas and v not in (None, "")}
            if extras != extras_orig:
                linha = con.execute("SELECT extras FROM contatos WHERE id = ?", [id_]).fetchone()
                no_banco = json.loads(linha["extras"] or "{}") if linha else {}
                for k in set(extras_orig) | set(extras):
                    if extras.get(k) != extras_orig.get(k):
                        if k in extras:
                            no_banco[k] = extras[k]
                        else:
                            no_banco.pop(k, None)
                con.execute("UPDATE contatos SET extras = ? WHERE id = ?",
                            [json.dumps(no_banco, ensure_ascii=False), id_])
            ids.append(id_)
        con.execute("COMMIT")
        return ids
    except BaseException:
        if con.in_transaction:
            con.execute("ROLLBACK")
        raise
    finally:
        con.close()


# ----------------------------------------------------------------- histórico ---

_CACHE: dict[str, tuple[tuple, list[dict]]] = {}


def ler_historico(caminho, colunas: list[str]) -> list[dict]:
    """Registros do histórico (mais antigo primeiro), com cache.

    O histórico só recebe inserções: (quantidade, maior id) muda sempre que
    alguém grava, inclusive outro processo.
    """
    if not Path(caminho).exists():
        return []
    con = conectar(caminho)
    try:
        garantir_esquema(con, colunas)
        assinatura = tuple(con.execute("SELECT COUNT(*), MAX(id) FROM historico").fetchone())
        chave = str(Path(caminho).resolve())
        em_cache = _CACHE.get(chave)
        if em_cache and em_cache[0] == assinatura:
            return list(em_cache[1])
        registros = []
        for r in con.execute("SELECT * FROM historico ORDER BY id"):
            registro = {c: r[c] for c in CAMPOS_HISTORICO}
            registro.update(json.loads(r["extras"] or "{}"))
            registros.append(registro)
        _CACHE[chave] = (assinatura, registros)
        return list(registros)
    finally:
        con.close()


def registrar_historico(caminho, colunas: list[str], registro: dict) -> None:
    con = conectar(caminho)
    try:
        garantir_esquema(con, colunas)
        extras = {k: v for k, v in registro.items() if k not in CAMPOS_HISTORICO}
        con.execute(f"INSERT INTO historico ({', '.join(CAMPOS_HISTORICO)}, extras) "
                    f"VALUES ({', '.join('?' for _ in CAMPOS_HISTORICO)}, ?)",
                    [str(registro.get(c, "") or "") for c in CAMPOS_HISTORICO]
                    + [json.dumps(extras, ensure_ascii=False)])
    finally:
        con.close()
    _CACHE.pop(str(Path(caminho).resolve()), None)


# ------------------------------------------------------------------ migração ---

def vazio(caminho, colunas: list[str]) -> bool:
    if not Path(caminho).exists():
        return True
    con = conectar(caminho)
    try:
        garantir_esquema(con, colunas)
        return not (con.execute("SELECT 1 FROM contatos LIMIT 1").fetchone()
                    or con.execute("SELECT 1 FROM historico LIMIT 1").fetchone())
    finally:
        con.close()


def migrar(linhas_csv: list[dict], registros_jsonl: list[dict], destino,
           colunas: list[str]) -> tuple[int, int]:
    """Copia as linhas do CSV (todas, inclusive inválidas) e o histórico para
    um banco VAZIO. Retorna (contatos, envios)."""
    if not vazio(destino, colunas):
        raise RuntimeError(f"{Path(destino).name} já tem dados; migração não refeita.")
    salvar_alteracoes(destino, colunas, [(None, linha, None) for linha in linhas_csv])
    con = conectar(destino)
    try:
        con.execute("BEGIN IMMEDIATE")
        for registro in registros_jsonl:
            extras = {k: v for k, v in registro.items() if k not in CAMPOS_HISTORICO}
            con.execute(f"INSERT INTO historico ({', '.join(CAMPOS_HISTORICO)}, extras) "
                        f"VALUES ({', '.join('?' for _ in CAMPOS_HISTORICO)}, ?)",
                        [str(registro.get(c, "") or "") for c in CAMPOS_HISTORICO]
                        + [json.dumps(extras, ensure_ascii=False)])
        con.execute("COMMIT")
    except BaseException:
        if con.in_transaction:
            con.execute("ROLLBACK")
        raise
    finally:
        con.close()
    return len(linhas_csv), len(registros_jsonl)
