"""
Endpoints de diagnóstico (Fase 2). Não fazem parte da "loja"; existem para
MOSTRAR no seminário como os dados estão distribuídos e replicados.

    /debug/distribuicao             quantas linhas cada shard tem, tabela a tabela
    /debug/simular-chave            e se a chave de fragmentação fosse outra? (hot shard)
    /debug/replica                  estado da streaming replication do shard_a
    /debug/replica/clientes/{id}    mesmo cliente lido no primário e na réplica
"""
from typing import Literal

import psycopg
from fastapi import APIRouter, HTTPException

from app import shards
from app.roteamento import SHARDS, shard_do_cliente, shard_por_categoria

router = APIRouter(prefix="/debug", tags=["debug"])

REGRAS = {
    "produtos": "replicado: cópia completa em cada shard",
    "estoque": "hash(produto_id) % 2",
    "clientes": "hash(cliente_id) % 2",
    "pedidos": "hash(cliente_id) % 2 (mora junto do cliente)",
}

SQL_CONTAGEM = """
SELECT (SELECT count(*) FROM produtos) AS produtos,
       (SELECT count(*) FROM estoque)  AS estoque,
       (SELECT count(*) FROM clientes) AS clientes,
       (SELECT count(*) FROM pedidos)  AS pedidos
"""


def equilibrio(por_shard: dict[str, float]) -> dict:
    """Métricas de equilíbrio. Ideal com 2 shards: 50% / 50%, razão 1.0."""
    total = sum(por_shard.values())
    mais_cheio = max(por_shard, key=por_shard.get)
    menor = min(por_shard.values())
    return {
        "total": total,
        "percentual": {s: round(100 * n / total, 1) if total else 0 for s, n in por_shard.items()},
        "shard_mais_cheio": mais_cheio,
        # quantas vezes o shard mais cheio é maior que o mais vazio
        "razao_maior_menor": round(por_shard[mais_cheio] / menor, 2) if menor else None,
    }


def contar(shard: str, replica: bool = False) -> dict | None:
    try:
        with shards.conectar(shard, replica) as conn:
            return conn.execute(SQL_CONTAGEM).fetchone()
    except psycopg.OperationalError:
        return None  # shard fora: aparece como null, o resto continua


# --------------------------------------------------------------------------
# Distribuição real
# --------------------------------------------------------------------------
@router.get("/distribuicao")
def distribuicao():
    contagens = {s: contar(s) for s in SHARDS}

    tabelas = {}
    for tabela, regra in REGRAS.items():
        por_shard = {s: (c[tabela] if c else None) for s, c in contagens.items()}
        info = {"regra": regra, "por_shard": por_shard}
        # Para tabela replicada, "equilíbrio" não faz sentido: cada shard tem tudo.
        if tabela != "produtos" and None not in por_shard.values():
            info |= equilibrio(por_shard)
        tabelas[tabela] = info

    return {
        "shards_fora_do_ar": [s for s, c in contagens.items() if c is None],
        "tabelas": tabelas,
        # A réplica deve ter os mesmos números do shard_a (com até ATRASO_REPLICA de atraso).
        "replicas": {f"{s}_replica": contar(s, replica=True) for s in shards.REPLICA_DSN},
    }


# --------------------------------------------------------------------------
# Modo experimental: trocar a chave de fragmentação dos pedidos
# --------------------------------------------------------------------------
SQL_PEDIDOS_POR_CATEGORIA = """
SELECT pr.categoria, count(*) AS pedidos, sum(pe.valor_total) AS receita
  FROM pedidos pe
  JOIN produtos pr ON pr.id = pe.produto_id   -- JOIN local: o catálogo é replicado
 GROUP BY pr.categoria
"""


@router.get("/simular-chave")
def simular_chave(chave: Literal["cliente_id", "categoria"] = "categoria"):
    """Recalcula, sobre os pedidos REAIS, onde cada um moraria com outra chave.

    É uma simulação: nada é movido. Mover de verdade exigiria re-fragmentar
    (reshard) a tabela inteira, que é justamente a operação cara que se quer
    evitar escolhendo bem a chave desde o início.
    """
    # Coleta de cada shard: pedidos agrupados por categoria (um mini scatter-gather).
    linhas_por_shard = {}
    for shard in SHARDS:
        with shards.conectar_ou_503(shard) as conn:
            linhas_por_shard[shard] = conn.execute(SQL_PEDIDOS_POR_CATEGORIA).fetchall()

    pedidos = {s: 0 for s in SHARDS}
    receita = {s: 0.0 for s in SHARDS}
    por_categoria: dict[str, int] = {}
    longe_do_cliente = 0  # pedidos que deixariam de morar no shard do seu cliente

    for shard_atual, linhas in linhas_por_shard.items():
        for linha in linhas:
            # Hoje, todo pedido em shard_atual tem o cliente em shard_atual.
            destino = shard_atual if chave == "cliente_id" else shard_por_categoria(linha["categoria"])
            pedidos[destino] += linha["pedidos"]
            receita[destino] += float(linha["receita"])
            por_categoria[linha["categoria"]] = por_categoria.get(linha["categoria"], 0) + linha["pedidos"]
            if destino != shard_atual:
                longe_do_cliente += linha["pedidos"]

    resultado = {
        "simulacao": True,
        "chave": chave,
        "regra": f"hash({chave}) % {len(SHARDS)}",
        "pedidos_por_shard": pedidos,
        **equilibrio(pedidos),
        "receita_por_shard": {s: round(v, 2) for s, v in receita.items()},
        "valores_distintos_da_chave": len(por_categoria) if chave == "categoria" else "um por cliente",
        "pedidos_longe_do_cliente": longe_do_cliente,
    }

    if chave == "categoria":
        resultado["categorias"] = [
            {"categoria": c, "shard": shard_por_categoria(c), "pedidos": n}
            for c, n in sorted(por_categoria.items(), key=lambda item: -item[1])
        ]
        quente = resultado["shard_mais_cheio"]
        resultado["conclusao"] = (
            f"{quente} viraria HOT SHARD: {resultado['percentual'][quente]}% dos pedidos "
            f"({resultado['razao_maior_menor']}x o outro). Além disso, "
            f"{longe_do_cliente} pedidos deixariam de morar junto do cliente, e "
            "'listar pedidos do cliente' passaria a consultar todos os shards."
        )
    return resultado


# --------------------------------------------------------------------------
# Réplica de leitura (streaming replication)
# --------------------------------------------------------------------------
@router.get("/replica")
def estado_replica():
    """Visão dos dois lados da replicação."""
    primario = replica = None
    try:
        with shards.conectar("shard_a") as conn:
            # Visto pelo primário: quem está conectado recebendo WAL.
            primario = conn.execute(
                """SELECT client_addr::text, state, sent_lsn::text, replay_lsn::text,
                          replay_lag::text
                     FROM pg_stat_replication"""
            ).fetchall()
    except psycopg.OperationalError:
        pass
    try:
        with shards.conectar("shard_a", replica=True) as conn:
            # Visto pela réplica: quanto WAL já chegou e quanto já foi aplicado.
            replica = conn.execute(
                """SELECT pg_is_in_recovery() AS eh_replica,
                          current_setting('recovery_min_apply_delay') AS atraso_configurado,
                          pg_last_wal_receive_lsn()::text AS wal_recebido,
                          pg_last_wal_replay_lsn()::text  AS wal_aplicado,
                          pg_wal_lsn_diff(pg_last_wal_receive_lsn(), pg_last_wal_replay_lsn())
                              AS bytes_recebidos_ainda_nao_aplicados,
                          pg_last_xact_replay_timestamp() AS ultimo_commit_aplicado"""
            ).fetchone()
    except psycopg.OperationalError:
        pass
    return {"primario_shard_a": primario, "replica_shard_a": replica}


@router.get("/replica/clientes/{cliente_id}")
def comparar_primario_e_replica(cliente_id: int):
    """Lê o MESMO cliente no primário e na réplica e diz se a réplica está atrasada.

    Demo: PATCH /clientes/{id} mudando a cidade e chame este endpoint logo em
    seguida: o primário já mostra a cidade nova, a réplica ainda a antiga.
    """
    shard = shard_do_cliente(cliente_id)
    if shard not in shards.REPLICA_DSN:
        raise HTTPException(400, f"Cliente {cliente_id} mora em {shard}, que não tem réplica nesta demo. "
                                 "Use um cliente do shard_a.")

    sql = "SELECT * FROM clientes WHERE id = %s"
    with shards.conectar_ou_503(shard) as conn:
        no_primario = conn.execute(sql, [cliente_id]).fetchone()
    with shards.conectar_ou_503(shard, replica=True) as conn:
        na_replica = conn.execute(sql, [cliente_id]).fetchone()
        atraso = conn.execute("SHOW recovery_min_apply_delay").fetchone()["recovery_min_apply_delay"]

    if no_primario is None and na_replica is None:
        raise HTTPException(404, f"Cliente {cliente_id} não existe.")

    desatualizado = no_primario != na_replica
    return {
        "cliente_id": cliente_id,
        "shard": shard,
        "primario": no_primario,
        "replica": na_replica,
        "desatualizado": desatualizado,
        "explicacao": (
            f"A réplica aplica cada commit {atraso} depois do primário. Ler dela alivia "
            "o primário, mas a leitura é eventualmente consistente."
            if desatualizado else
            "Réplica em dia com o primário para este cliente."
        ),
    }
