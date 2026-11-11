"""
Testes de integração do /health: precisam dos shards rodando
(docker compose up). Se não houver shard acessível, são pulados.

A queda de um shard é simulada trocando o endereço dele por uma porta onde
nada escuta; o efeito para a API é o mesmo de um `docker stop`.
"""
import pytest
from fastapi.testclient import TestClient

from app import shards
from app.main import app
from app.roteamento import SHARDS, shard_do_produto

cliente_http = TestClient(app)
ENDERECO_MORTO = "postgresql://loja:loja@127.0.0.1:1/loja"  # porta 1: conexão recusada


@pytest.fixture(autouse=True)
def exige_shards():
    if not all(shards.verificar(s)["online"] for s in SHARDS):
        pytest.skip("shards fora do ar: rode `docker compose up -d` antes")


def test_health_com_tudo_de_pe():
    r = cliente_http.get("/health")
    assert r.status_code == 200
    corpo = r.json()
    assert corpo["status"] == "ok"
    assert all(corpo["shards"][s]["online"] for s in SHARDS)
    assert "indisponivel" not in corpo


def test_health_com_um_shard_fora(monkeypatch):
    monkeypatch.setitem(shards.DSN, "shard_b", ENDERECO_MORTO)

    r = cliente_http.get("/health")
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


def test_catalogo_replicado_sobrevive_a_queda_do_primeiro_shard(monkeypatch):
    monkeypatch.setitem(shards.DSN, "shard_a", ENDERECO_MORTO)

    r = cliente_http.get("/produtos")
    assert r.status_code == 200
    assert r.json()["lido_de"] == "shard_b"  # failover para a outra réplica
    assert r.json()["total"] == 50


def test_health_com_tudo_fora(monkeypatch):
    for s in SHARDS:
        monkeypatch.setitem(shards.DSN, s, ENDERECO_MORTO)
    r = cliente_http.get("/health")
    assert r.status_code == 503
    assert r.json()["status"] == "fora_do_ar"
