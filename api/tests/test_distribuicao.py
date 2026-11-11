"""Fase 2: contagem por shard e o experimento da chave "categoria" (hot shard)."""
import pytest

from app.roteamento import SHARDS, shard_por_categoria

pytestmark = pytest.mark.usefixtures("exige_shards")


def test_distribuicao_por_tabela(http):
    tabelas = http.get("/debug/distribuicao").json()["tabelas"]

    # Replicada: cada shard tem a cópia completa.
    assert all(tabelas["produtos"]["por_shard"][s] == 50 for s in SHARDS)
    # Fragmentadas: as partes somam o todo, e nenhum shard fica vazio.
    for tabela in ("estoque", "clientes", "pedidos"):
        info = tabelas[tabela]
        assert sum(info["por_shard"].values()) == info["total"]
        assert all(n > 0 for n in info["por_shard"].values())
    assert tabelas["estoque"]["total"] == 50


def test_chave_categoria_cria_hot_shard(http):
    por_cliente = http.get("/debug/simular-chave", params={"chave": "cliente_id"}).json()
    por_categoria = http.get("/debug/simular-chave", params={"chave": "categoria"}).json()

    # Os mesmos pedidos, só redistribuídos.
    assert por_categoria["total"] == por_cliente["total"]
    # Hash do cliente: quase 50/50. Hash da categoria: bem mais desequilibrado.
    assert por_cliente["razao_maior_menor"] < 1.2
    assert por_categoria["razao_maior_menor"] > 1.5
    assert por_categoria["valores_distintos_da_chave"] == 7
    # Com a chave atual nenhum pedido mora longe do cliente; com categoria, muitos.
    assert por_cliente["pedidos_longe_do_cliente"] == 0
    assert por_categoria["pedidos_longe_do_cliente"] > 0
    for item in por_categoria["categorias"]:
        assert item["shard"] == shard_por_categoria(item["categoria"])
