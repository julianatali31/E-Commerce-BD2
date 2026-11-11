"""Fixtures compartilhadas pelos testes de integração."""
import pytest
from fastapi.testclient import TestClient

from app import shards
from app.main import app
from app.roteamento import SHARDS, shard_do_cliente

# Porta 1 em localhost: nada escuta, a conexão é recusada na hora.
# Para a API, é o mesmo efeito de um `docker stop` no shard.
ENDERECO_MORTO = "postgresql://loja:loja@127.0.0.1:1/loja"


@pytest.fixture
def http():
    return TestClient(app)


@pytest.fixture
def exige_shards():
    if not all(shards.verificar(s)["online"] for s in SHARDS):
        pytest.skip("shards fora do ar: rode `docker compose up -d` antes")


@pytest.fixture
def clientes_criados():
    """Lista onde o teste anota ids que criou; apagados no fim (dados do seed intactos)."""
    criados: list[int] = []
    yield criados
    for cliente_id in criados:
        with shards.conectar(shard_do_cliente(cliente_id)) as conn:
            conn.execute("DELETE FROM clientes WHERE id = %s", [cliente_id])
