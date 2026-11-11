"""
API = coordenador. Ela não guarda dados; só sabe onde cada dado está
(roteamento.py) e conversa com os shards.

Fase 1: /health (estado de cada shard + o que ficou indisponível) e
        /produtos (catálogo replicado, lido de qualquer shard que esteja de pé).
Fase 2: /clientes (criar, ler, atualizar, listar pedidos), sempre roteado
        por hash(cliente_id). Os endpoints de diagnóstico ficam em debug.py.
"""
import psycopg
from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel, Field

from app import debug, ids, shards
from app.roteamento import SHARDS, shard_do_cliente, shard_do_produto

app = FastAPI(title="Loja distribuída - coordenador")
app.include_router(debug.router)


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

    resultado = {
        "status": status,
        "shards": estado,
        # A réplica não entra no "status": a loja funciona sem ela.
        "replicas": {f"{s}_replica": shards.verificar(s, replica=True) for s in shards.REPLICA_DSN},
    }

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


# ==========================================================================
# Clientes (Fase 2). Padrão de TODOS os endpoints abaixo:
#   1. roteamento.py diz qual shard;  2. conversa só com aquele shard.
# Nenhuma dessas operações toca no outro shard: é isso que faz a
# fragmentação escalar.
# ==========================================================================
class NovoCliente(BaseModel):
    nome: str = Field(min_length=1)
    email: str = Field(min_length=3)
    cidade: str = Field(min_length=1)


class AlteracaoCliente(BaseModel):
    nome: str | None = None
    email: str | None = None
    cidade: str | None = None


@app.post("/clientes", status_code=201)
def criar_cliente(dados: NovoCliente):
    cliente_id, gerador = ids.proximo_id("seq_clientes")  # 1. id único global
    shard = shard_do_cliente(cliente_id)                    # 2. onde ele vai morar
    with shards.conectar_ou_503(shard) as conn:             # 3. grava só lá
        cliente = conn.execute(
            "INSERT INTO clientes (id, nome, email, cidade) VALUES (%s, %s, %s, %s) RETURNING *",
            [cliente_id, dados.nome, dados.email, dados.cidade],
        ).fetchone()
    return {"shard": shard, "id_gerado_por": gerador, "cliente": cliente}


@app.get("/clientes/{cliente_id}")
def ler_cliente(cliente_id: int):
    shard = shard_do_cliente(cliente_id)
    with shards.conectar_ou_503(shard) as conn:
        cliente = conn.execute("SELECT * FROM clientes WHERE id = %s", [cliente_id]).fetchone()
    if cliente is None:
        raise HTTPException(404, f"Cliente {cliente_id} não existe (procurado em {shard}).")
    return {"shard": shard, "cliente": cliente}


@app.patch("/clientes/{cliente_id}")
def alterar_cliente(cliente_id: int, dados: AlteracaoCliente):
    """Usado na demo da réplica: altere a cidade e leia da réplica logo em seguida."""
    shard = shard_do_cliente(cliente_id)
    with shards.conectar_ou_503(shard) as conn:
        cliente = conn.execute(
            """UPDATE clientes
                  SET nome   = COALESCE(%s, nome),
                      email  = COALESCE(%s, email),
                      cidade = COALESCE(%s, cidade)
                WHERE id = %s
            RETURNING *""",
            [dados.nome, dados.email, dados.cidade, cliente_id],
        ).fetchone()
    if cliente is None:
        raise HTTPException(404, f"Cliente {cliente_id} não existe (procurado em {shard}).")
    return {"shard": shard, "cliente": cliente}


@app.get("/clientes/{cliente_id}/pedidos")
def listar_pedidos(cliente_id: int):
    """Consulta 100% local, graças a duas decisões de design:
    - co-localização: os pedidos moram no mesmo shard do cliente;
    - replicação do catálogo: o JOIN com produtos também é local.
    """
    shard = shard_do_cliente(cliente_id)
    with shards.conectar_ou_503(shard) as conn:
        if conn.execute("SELECT 1 FROM clientes WHERE id = %s", [cliente_id]).fetchone() is None:
            raise HTTPException(404, f"Cliente {cliente_id} não existe (procurado em {shard}).")
        pedidos = conn.execute(
            """SELECT pe.id, pe.produto_id, pr.nome AS produto, pr.categoria,
                      pe.quantidade, pe.valor_total, pe.criado_em
                 FROM pedidos pe
                 JOIN produtos pr ON pr.id = pe.produto_id
                WHERE pe.cliente_id = %s
                ORDER BY pe.criado_em DESC""",
            [cliente_id],
        ).fetchall()
    return {"shard": shard, "cliente_id": cliente_id, "total": len(pedidos), "pedidos": pedidos}
