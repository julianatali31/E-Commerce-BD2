"""
Geração de IDs únicos sem serviço central ("ticket servers", como o Flickr fazia).

Cada shard tem a sua sequência, todas com INCREMENT BY 2, mas começando em
pontos diferentes (o seed configura):

    shard_a -> 2001, 2003, 2005, ...   (ímpares)
    shard_b -> 2002, 2004, 2006, ...   (pares)

(valores com o seed padrão de 2.000 clientes.) Os conjuntos nunca se cruzam, então nenhum ID se repete, sem que os shards
precisem conversar. Se o shard_a cair, o shard_b continua gerando IDs.

ATENÇÃO: quem GERA o id não é quem GUARDA a linha. O id sai de qualquer
shard disponível; depois, roteamento.py (hash do id) decide onde o cliente mora.
Assim a distribuição continua equilibrada pelo hash, e não por quem gerou.

nextval() não é transacional: se o INSERT falhar, aquele número se perde.
Buracos na numeração são normais e inofensivos.
"""
import psycopg
from fastapi import HTTPException

from app import shards
from app.roteamento import SHARDS


def proximo_id(sequencia: str) -> tuple[int, str]:
    """Devolve (novo_id, shard_que_gerou). Tenta os shards na ordem (failover)."""
    for shard in SHARDS:
        try:
            with shards.conectar(shard) as conn:
                novo = conn.execute("SELECT nextval(%s) AS id", [sequencia]).fetchone()["id"]
            return novo, shard
        except psycopg.OperationalError:
            continue
    raise HTTPException(503, "Nenhum shard disponível para gerar IDs.")
