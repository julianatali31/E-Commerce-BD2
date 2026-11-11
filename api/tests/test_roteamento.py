"""Testes da função de fragmentação (não precisam de banco)."""
from collections import Counter

from app.roteamento import SHARDS, hash_estavel, shard_do_cliente, shard_do_produto


def test_hash_e_deterministico():
    # Mesmo valor -> mesmo hash, sempre (pré-requisito para achar o dado depois).
    assert hash_estavel(123) == hash_estavel(123)
    assert hash_estavel("123") == hash_estavel(123)  # chave é tratada como texto


def test_todo_cliente_cai_em_um_shard_valido():
    assert all(shard_do_cliente(cid) in SHARDS for cid in range(1, 1000))


def test_distribuicao_de_clientes_e_equilibrada():
    # Com 2.000 clientes, um hash bem espalhado deve dar ~50% para cada lado.
    contagem = Counter(shard_do_cliente(cid) for cid in range(1, 2001))
    for shard in SHARDS:
        assert 900 <= contagem[shard] <= 1100, contagem


def test_hash_nao_e_simplesmente_par_ou_impar():
    # Se fosse id % 2, todos os pares iriam para o mesmo shard.
    pares = {shard_do_cliente(cid) for cid in range(2, 200, 2)}
    assert pares == set(SHARDS)


def test_estoque_usa_os_dois_shards():
    # Com 50 produtos, os dois shards precisam ter algum estoque (senão não há 2PC).
    assert {shard_do_produto(pid) for pid in range(1, 51)} == set(SHARDS)
