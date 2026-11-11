"""
API = coordenador. Ela não guarda dados; só sabe onde cada dado está
(roteamento.py) e conversa com os shards.

Fase 1: /health (estado de cada shard + o que ficou indisponível) e
/produtos (catálogo replicado, lido de qualquer shard que esteja de pé).
"""
import psycopg
from fastapi import FastAPI, HTTPException, Response

from app import shards
from app.roteamento import SHARDS, shard_do_produto

app = FastAPI(title="Loja distribuída - coordenador")


def ler_catalogo() -> tuple[str, list[dict]]:
    """Lê o catálogo da primeira réplica que responder (failover de leitura).

    Como o catálogo é replicado por completo, qualquer shard serve. Tentamos
    na ordem; se o primeiro estiver fora, o segundo responde.
    """
    for shard in SHARDS:
        try:
            with shards.conectar(shard) as conn:
                linhas = conn.execute(
                    "SELECT id, nome, categoria, preco FROM produtos ORDER BY id"
                ).fetchall()
            return shard, linhas
        except psycopg.OperationalError:
            continue
    raise HTTPException(503, "Nenhuma réplica do catálogo está disponível.")


def impacto_da_queda(shard: str, produtos: list[dict]) -> dict:
    """Descreve, em termos de NEGÓCIO, o que se perde quando um shard cai.

    Graças ao catálogo replicado, o coordenador consegue listar exatamente
    quais produtos estão sem estoque acessível, mesmo com o shard fora.
    """
    posicao = SHARDS.index(shard)
    return {
        "clientes_e_pedidos": (
            f"clientes com hash(cliente_id) % {len(SHARDS)} == {posicao} "
            "e todos os pedidos deles"
        ),
        "estoque_inacessivel": [
            {"id": p["id"], "nome": p["nome"]}
            for p in produtos
            if shard_do_produto(p["id"]) == shard
        ],
    }


@app.get("/health")
def health(response: Response):
    estado = {shard: shards.verificar(shard) for shard in SHARDS}
    online = [s for s in SHARDS if estado[s]["online"]]
    offline = [s for s in SHARDS if not estado[s]["online"]]

    if not offline:
        status = "ok"
    elif online:
        status = "degradado"  # API de pé, parte dos dados fora
    else:
        status = "fora_do_ar"
        response.status_code = 503  # nada pode ser atendido

    resultado = {"status": status, "shards": estado}

    if offline:
        lido_de, produtos = ler_catalogo() if online else (None, [])
        resultado["indisponivel"] = {s: impacto_da_queda(s, produtos) for s in offline}
        resultado["continua_disponivel"] = {
            "catalogo": f"sim, réplica em {lido_de}" if lido_de else "não",
            "clientes_e_pedidos": [f"os que moram em {s}" for s in online],
        }
    return resultado


@app.get("/produtos")
def listar_produtos():
    lido_de, produtos = ler_catalogo()
    return {"lido_de": lido_de, "total": len(produtos), "produtos": produtos}
