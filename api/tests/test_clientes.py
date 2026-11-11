"""Fase 2: roteamento por hash(cliente_id) e geração de IDs sem serviço central."""
import pytest
from conftest import ENDERECO_MORTO

from app import shards
from app.roteamento import SHARDS, shard_do_cliente

pytestmark = pytest.mark.usefixtures("exige_shards")

NOVO = {"nome": "Cliente de Teste", "email": "teste@exemplo.com", "cidade": "Teste"}


def onde_esta(cliente_id: int) -> list[str]:
    """Pergunta DIRETO aos bancos (sem passar pela API) onde o cliente está."""
    encontrado = []
    for s in SHARDS:
        with shards.conectar(s) as conn:
            if conn.execute("SELECT 1 FROM clientes WHERE id = %s", [cliente_id]).fetchone():
                encontrado.append(s)
    return encontrado


def test_cliente_novo_e_gravado_so_no_shard_do_hash(http, clientes_criados):
    r = http.post("/clientes", json=NOVO)
    assert r.status_code == 201
    cliente_id = r.json()["cliente"]["id"]
    clientes_criados.append(cliente_id)

    assert r.json()["shard"] == shard_do_cliente(cliente_id)
    assert onde_esta(cliente_id) == [shard_do_cliente(cliente_id)]  # em um shard, só um


def test_ids_sao_unicos_e_vem_da_sequencia_impar_do_shard_a(http, clientes_criados):
    respostas = [http.post("/clientes", json=NOVO).json() for _ in range(6)]
    novos = [r["cliente"]["id"] for r in respostas]
    clientes_criados.extend(novos)

    assert len(set(novos)) == 6
    assert all(r["id_gerado_por"] == "shard_a" for r in respostas)
    assert all(i % 2 == 1 for i in novos)  # shard_a gera ímpares
    # ...mas cada cliente vai para o shard que o HASH manda, não para quem gerou o id
    assert {r["shard"] for r in respostas} <= set(SHARDS)


def test_gerador_de_ids_faz_failover_quando_shard_a_cai(http, monkeypatch, clientes_criados):
    monkeypatch.setitem(shards.DSN, "shard_a", ENDERECO_MORTO)

    gravados = 0
    for _ in range(10):
        r = http.post("/clientes", json=NOVO)
        if r.status_code == 201:
            corpo = r.json()
            clientes_criados.append(corpo["cliente"]["id"])
            assert corpo["id_gerado_por"] == "shard_b"
            assert corpo["cliente"]["id"] % 2 == 0  # shard_b gera pares
            assert corpo["shard"] == "shard_b"
            gravados += 1
        else:
            # O id caiu (pelo hash) no shard_a, que está fora: recusa clara, não erro 500.
            assert r.status_code == 503
            assert "shard_a" in r.json()["detail"]
    assert gravados > 0


def test_ler_cliente_existente_e_inexistente(http):
    assert http.get("/clientes/1").json()["shard"] == shard_do_cliente(1)
    assert http.get("/clientes/999999999").status_code == 404


def test_listar_pedidos_bate_com_o_banco(http):
    cliente_id = 226  # tem 5 pedidos no seed padrão
    shard = shard_do_cliente(cliente_id)
    with shards.conectar(shard) as conn:
        esperado = conn.execute(
            "SELECT count(*) AS n FROM pedidos WHERE cliente_id = %s", [cliente_id]
        ).fetchone()["n"]

    corpo = http.get(f"/clientes/{cliente_id}/pedidos").json()
    assert corpo["shard"] == shard
    assert corpo["total"] == esperado > 0
    assert all("categoria" in p for p in corpo["pedidos"])  # JOIN local com o catálogo


def test_cliente_em_shard_fora_do_ar_retorna_503(http, monkeypatch):
    cliente_id = 1
    monkeypatch.setitem(shards.DSN, shard_do_cliente(cliente_id), ENDERECO_MORTO)
    r = http.get(f"/clientes/{cliente_id}/pedidos")
    assert r.status_code == 503
