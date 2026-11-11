"""
Acesso aos shards: endereço de cada um e como abrir conexão.

Decisão: uma conexão nova por operação, sem pool. Custa alguns milissegundos,
mas deixa o código óbvio e faz com que um shard que caiu e voltou seja
percebido na próxima requisição, sem conexões "zumbis" num pool.
"""
import os
import time

import psycopg
from psycopg.rows import dict_row

from app.roteamento import SHARDS

# Endereços vêm de variáveis de ambiente (o docker-compose define).
# Os padrões apontam para as portas publicadas no host, para rodar testes fora do Docker.
DSN = {
    "shard_a": os.getenv("SHARD_A_DSN", "postgresql://loja:loja@localhost:5433/loja"),
    "shard_b": os.getenv("SHARD_B_DSN", "postgresql://loja:loja@localhost:5434/loja"),
}
assert set(DSN) == set(SHARDS), "DSN e roteamento.SHARDS precisam listar os mesmos shards"

# Sem timeout, um shard "pendurado" (rede caiu, container pausado) travaria a
# requisição inteira. Com 2 s, o coordenador desiste e segue com os demais.
TIMEOUT_CONEXAO_S = 2


def conectar(shard: str) -> psycopg.Connection:
    """Abre conexão com um shard; linhas voltam como dict."""
    return psycopg.connect(DSN[shard], connect_timeout=TIMEOUT_CONEXAO_S, row_factory=dict_row)


def verificar(shard: str) -> dict:
    """Testa um shard e devolve seu estado (nunca lança exceção)."""
    inicio = time.perf_counter()
    try:
        with conectar(shard) as conn:
            versao = conn.execute("SHOW server_version").fetchone()["server_version"]
        return {
            "online": True,
            "latencia_ms": round((time.perf_counter() - inicio) * 1000, 1),
            "postgres": versao,
        }
    except psycopg.OperationalError as erro:
        # Primeira linha da mensagem basta (ex.: "connection refused", "could not translate host name").
        return {"online": False, "erro": str(erro).strip().splitlines()[0]}
