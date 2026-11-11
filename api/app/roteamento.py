"""
Roteamento: o ÚNICO lugar do sistema que decide em qual shard cada linha mora.

    clientes, pedidos  ->  hash(cliente_id) % 2
    estoque            ->  hash(produto_id) % 2
    produtos (catálogo)->  replicado em todos os shards (não passa por aqui)

Manter isso num módulo só tem dois motivos:
  1. Coerência: API, seed e testes usam exatamente a mesma regra. Se cada um
     calculasse o shard do seu jeito, um cliente poderia ser gravado no shard A
     e procurado no shard B.
  2. Didática: este arquivo cabe num slide.
"""
import hashlib

# A ordem importa: posição 0 = shard_a, posição 1 = shard_b.
SHARDS = ["shard_a", "shard_b"]


def hash_estavel(chave) -> int:
    """Transforma qualquer chave num inteiro grande, sempre do mesmo jeito.

    Por que não usar o hash() do Python?  Para strings ele muda a cada execução
    (PYTHONHASHSEED), e para inteiros ele é a identidade (hash(7) == 7), o que
    viraria um simples "par/ímpar". O MD5 aqui não é para segurança: só
    queremos um hash determinístico e bem espalhado.
    """
    digest = hashlib.md5(str(chave).encode()).digest()
    return int.from_bytes(digest[:8], "big")


def shard_por_hash(chave) -> str:
    """hash(chave) % N  ->  nome do shard."""
    return SHARDS[hash_estavel(chave) % len(SHARDS)]


def shard_do_cliente(cliente_id: int) -> str:
    """Shard de um cliente E de todos os pedidos dele (co-localização)."""
    return shard_por_hash(cliente_id)


def shard_do_produto(produto_id: int) -> str:
    """Shard onde está o estoque de um produto."""
    return shard_por_hash(produto_id)


# --------------------------------------------------------------------------
# EXPERIMENTAL (Fase 2): e se fragmentássemos pedidos pela CATEGORIA do produto?
# Usada só na simulação de /debug/simular-chave; nenhum dado é gravado assim.
#
# Problemas que a simulação expõe:
#  - Só 7 categorias: a chave tem cardinalidade baixa, então nunca daria para
#    usar mais de 7 shards, e o hash de 7 valores dificilmente fica 50/50.
#  - Categorias têm popularidades muito diferentes (mouse vende 10x mais que
#    PC): o shard que recebe as campeãs vira "hot shard".
#  - Quebra a co-localização: o pedido deixa de morar junto do cliente.
# --------------------------------------------------------------------------
def shard_por_categoria(categoria: str) -> str:
    return shard_por_hash(categoria)
