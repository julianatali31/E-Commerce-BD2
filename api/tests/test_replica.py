"""
Fase 2: réplica de leitura do shard_a por streaming replication.

O teste de convergência espera o atraso configurado (10 s por padrão).
"""
import time

import psycopg
import pytest

from app import shards
from app.roteamento import shard_do_cliente


@pytest.fixture(autouse=True)
def exige_replica(exige_shards):
    if not shards.verificar("shard_a", replica=True)["online"]:
        pytest.skip("réplica fora do ar: rode `docker compose up -d` antes")


def cliente_do_shard(shard: str) -> int:
    return next(i for i in range(1, 100) if shard_do_cliente(i) == shard)


def test_replica_e_somente_leitura():
    with shards.conectar("shard_a", replica=True) as conn:
        with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
            conn.execute("UPDATE clientes SET cidade = 'X' WHERE id = 1")


def test_replica_mostra_dado_desatualizado_e_depois_converge(http):
    cliente_id = cliente_do_shard("shard_a")
    original = http.get(f"/clientes/{cliente_id}").json()["cliente"]["cidade"]
    nova = f"Cidade-{time.time_ns()}"

    http.patch(f"/clientes/{cliente_id}", json={"cidade": nova})
    try:
        # Logo depois da escrita: primário já mudou, réplica ainda não.
        r = http.get(f"/debug/replica/clientes/{cliente_id}").json()
        assert r["desatualizado"] is True
        assert r["primario"]["cidade"] == nova
        assert r["replica"]["cidade"] != nova

        # Consistência eventual: depois do atraso, a réplica alcança o primário.
        limite = time.monotonic() + 25
        while time.monotonic() < limite:
            r = http.get(f"/debug/replica/clientes/{cliente_id}").json()
            if not r["desatualizado"]:
                break
            time.sleep(1)
        assert r["desatualizado"] is False
        assert r["replica"]["cidade"] == nova
    finally:
        http.patch(f"/clientes/{cliente_id}", json={"cidade": original})


def test_cliente_de_shard_sem_replica_da_400(http):
    r = http.get(f"/debug/replica/clientes/{cliente_do_shard('shard_b')}")
    assert r.status_code == 400
