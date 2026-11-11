"""
Testes de integração do /health: precisam dos shards rodando
(docker compose up). Se não houver shard acessível, são pulados.

A queda de um shard é simulada trocando o endereço dele por uma porta onde
nada escuta; o efeito para a API é o mesmo de um `docker stop`.
"""
import pytest
from conftest import ENDERECO_MORTO

from app import shards
from app.roteamento import SHARDS, shard_do_produto

pytestmark = pytest.mark.usefixtures("exige_shards")


def test_health_com_tudo_de_pe(http):
    r = http.get("/health")
    assert r.status_code == 200
    corpo = r.json()
    assert corpo["status"] == "ok"
    assert all(corpo["shards"][s]["online"] for s in SHARDS)
    assert "indisponivel" not in corpo


def test_health_com_um_shard_fora(http, monkeypatch):
    monkeypatch.setitem(shards.DSN, "shard_b", ENDERECO_MORTO)

    r = http.get("/health")
    assert r.status_code == 200  # a API continua respondendo
    corpo = r.json()
    assert corpo["status"] == "degradado"
    assert corpo["shards"]["shard_a"]["online"] is True
    assert corpo["shards"]["shard_b"]["online"] is False

    # O que ficou indisponível é exatamente o estoque roteado para shard_b.
    perdidos = {p["id"] for p in corpo["indisponivel"]["shard_b"]["estoque_inacessivel"]}
    esperados = {pid for pid in range(1, 51) if shard_do_produto(pid) == "shard_b"}
    assert perdidos == esperados
    assert corpo["continua_disponivel"]["catalogo"] == "sim, réplica em shard_a"


def test_catalogo_replicado_sobrevive_a_queda_do_primeiro_shard(http, monkeypatch):
    monkeypatch.setitem(shards.DSN, "shard_a", ENDERECO_MORTO)

    r = http.get("/produtos")
    assert r.status_code == 200
    assert r.json()["lido_de"] == "shard_b"  # failover para a outra réplica
    assert r.json()["total"] == 50


def test_health_com_tudo_fora(http, monkeypatch):
    for s in SHARDS:
        monkeypatch.setitem(shards.DSN, s, ENDERECO_MORTO)
    r = http.get("/health")
    assert r.status_code == 503
    assert r.json()["status"] == "fora_do_ar"
