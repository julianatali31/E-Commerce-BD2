"""
Seed: gera dados fictícios e os DISTRIBUI entre os shards.

Por que o seed é Python e não um .sql?  Porque a distribuição tem de seguir
exatamente a mesma regra da API (roteamento.py). Um seed em SQL teria que
reimplementar o hash e poderia divergir.

Uso (dentro do container da API):
    python -m scripts.seed                       # só popula se estiver vazio
    python -m scripts.seed --reset               # apaga tudo e popula de novo
    python -m scripts.seed --reset --pedidos 200000   # volume maior (Fase 3)

Os dados são determinísticos (random.seed fixo): os números dos slides se repetem.
"""
import argparse
import random
from datetime import datetime, timedelta, timezone

from app import shards
from app.roteamento import SHARDS, shard_do_cliente, shard_do_produto

# --------------------------------------------------------------------------
# Catálogo: 50 produtos em 7 categorias.
# --------------------------------------------------------------------------
CATALOGO = {
    "mouse": [
        ("Mouse Óptico Básico USB", 39.90), ("Mouse Sem Fio Slim", 79.90),
        ("Mouse Gamer 7200 DPI", 129.90), ("Mouse Gamer RGB 16000 DPI", 249.90),
        ("Mouse Vertical Ergonômico", 159.90), ("Mouse Bluetooth Silencioso", 99.90),
        ("Mouse Gamer Ultraleve 59g", 349.90), ("Mouse Trackball", 289.90),
    ],
    "teclado": [
        ("Teclado ABNT2 Básico", 59.90), ("Teclado Sem Fio Compacto", 119.90),
        ("Teclado Mecânico Switch Azul", 229.90), ("Teclado Mecânico Switch Vermelho", 239.90),
        ("Teclado Mecânico 60%", 279.90), ("Teclado Mecânico TKL RGB", 349.90),
        ("Teclado Low Profile Bluetooth", 299.90), ("Teclado Ergonômico Dividido", 549.90),
    ],
    "headset": [
        ("Headset P2 Básico", 69.90), ("Headset USB com Microfone", 149.90),
        ("Headset Gamer 7.1", 299.90), ("Headset Gamer Sem Fio", 599.90),
        ("Headset Home Office", 189.90), ("Headset Gamer Leve", 229.90),
        ("Headset Bluetooth com Cancelamento", 749.90),
    ],
    "fone": [
        ("Fone Intra-auricular com Fio", 29.90), ("Fone Bluetooth TWS", 119.90),
        ("Fone Over-ear Bluetooth", 349.90), ("Fone Esportivo à Prova d'Água", 179.90),
        ("Fone com Cancelamento de Ruído", 899.90), ("Fone Monitor de Estúdio", 459.90),
        ("Fone Infantil Volume Limitado", 89.90),
    ],
    "monitor": [
        ('Monitor 21,5" Full HD', 549.90), ('Monitor 24" IPS 75Hz', 799.90),
        ('Monitor Gamer 24" 165Hz', 1099.90), ('Monitor 27" QHD', 1499.90),
        ('Monitor Gamer 27" 240Hz', 2299.90), ('Monitor Ultrawide 34"', 2799.90),
        ('Monitor 4K 28"', 1999.90),
    ],
    "pc": [
        ("PC Escritório i3 8GB", 2299.00), ("PC Home Office Ryzen 5", 3199.00),
        ("PC Gamer Entrada", 3999.00), ("PC Gamer Intermediário", 5999.00),
        ("PC Gamer Avançado", 8999.00), ("Mini PC Compacto", 1899.00),
    ],
    "memoria_ram": [
        ("Memória RAM 8GB DDR4 2666MHz", 129.90), ("Memória RAM 16GB DDR4 3200MHz", 239.90),
        ("Kit RAM 2x8GB DDR4 3200MHz", 269.90), ("Kit RAM 2x16GB DDR4 3600MHz", 499.90),
        ("Memória RAM 16GB DDR5 5600MHz", 349.90), ("Kit RAM 2x16GB DDR5 6000MHz", 749.90),
        ("Memória RAM Notebook 8GB DDR4", 139.90),
    ],
}

# Popularidade relativa das categorias nos pedidos. Uma loja real não vende
# tudo igual: periféricos baratos saem muito mais que PCs. Isso vai importar
# na Fase 2, quando fragmentarmos por categoria e aparecer um "hot shard".
POPULARIDADE = {
    "mouse": 30, "teclado": 20, "headset": 15, "fone": 15,
    "monitor": 10, "memoria_ram": 7, "pc": 3,
}

NOMES = ["Ana", "Bruno", "Carla", "Diego", "Eduarda", "Felipe", "Gabriela", "Heitor",
         "Isabela", "João", "Larissa", "Marcos", "Natália", "Otávio", "Paula", "Rafael",
         "Sofia", "Thiago", "Valéria", "Yuri"]
SOBRENOMES = ["Silva", "Santos", "Oliveira", "Souza", "Lima", "Pereira", "Costa",
              "Ferreira", "Almeida", "Ribeiro", "Carvalho", "Gomes", "Martins", "Rocha"]
CIDADES = ["São Paulo", "Rio de Janeiro", "Belo Horizonte", "Curitiba", "Porto Alegre",
           "Salvador", "Recife", "Fortaleza", "Brasília", "Goiânia", "Manaus", "Florianópolis"]


def gerar_produtos() -> list[tuple]:
    produtos, pid = [], 1
    for categoria, itens in CATALOGO.items():
        for nome, preco in itens:
            produtos.append((pid, nome, categoria, preco))
            pid += 1
    return produtos


def gerar_clientes(n: int, rng: random.Random) -> list[tuple]:
    inicio = datetime(2025, 1, 1, tzinfo=timezone.utc)
    clientes = []
    for cid in range(1, n + 1):
        nome = f"{rng.choice(NOMES)} {rng.choice(SOBRENOMES)}"
        email = f"cliente{cid}@exemplo.com"
        criado = inicio + timedelta(minutes=rng.randint(0, 365 * 24 * 60))
        clientes.append((cid, nome, email, rng.choice(CIDADES), criado))
    return clientes


def gerar_pedidos(n: int, n_clientes: int, produtos: list[tuple], rng: random.Random) -> list[tuple]:
    por_categoria: dict[str, list[tuple]] = {}
    for p in produtos:
        por_categoria.setdefault(p[2], []).append(p)
    categorias = list(POPULARIDADE)
    pesos = [POPULARIDADE[c] for c in categorias]

    inicio = datetime(2025, 6, 1, tzinfo=timezone.utc)
    pedidos = []
    for pedido_id in range(1, n + 1):
        categoria = rng.choices(categorias, weights=pesos)[0]
        produto_id, _, _, preco = rng.choice(por_categoria[categoria])
        qtd = rng.choices([1, 2, 3], weights=[80, 15, 5])[0]
        cliente_id = rng.randint(1, n_clientes)
        criado = inicio + timedelta(minutes=rng.randint(0, 150 * 24 * 60))
        pedidos.append((pedido_id, cliente_id, produto_id, qtd, round(preco * qtd, 2), criado))
    return pedidos


def copiar(conn, tabela: str, colunas: str, linhas: list[tuple]) -> None:
    """COPY é o carregamento em massa do Postgres: muito mais rápido que N INSERTs
    (200k pedidos em segundos), o que importa para o benchmark da Fase 3."""
    with conn.cursor().copy(f"COPY {tabela} ({colunas}) FROM STDIN") as copy:
        for linha in linhas:
            copy.write_row(linha)


def main() -> None:
    parser = argparse.ArgumentParser(description="Popula os shards com dados fictícios.")
    parser.add_argument("--clientes", type=int, default=2000)
    parser.add_argument("--pedidos", type=int, default=2000)
    parser.add_argument("--reset", action="store_true", help="apaga os dados existentes antes")
    args = parser.parse_args()

    conexoes = {s: shards.conectar(s) for s in SHARDS}  # o seed exige os dois shards de pé

    ja_populado = all(
        c.execute("SELECT count(*) AS n FROM produtos").fetchone()["n"] > 0
        for c in conexoes.values()
    )
    if ja_populado and not args.reset:
        print("Shards já populados; nada a fazer (use --reset para recriar).")
        for conn in conexoes.values():
            conn.close()
        return

    rng = random.Random(42)
    produtos = gerar_produtos()
    clientes = gerar_clientes(args.clientes, rng)
    pedidos = gerar_pedidos(args.pedidos, args.clientes, produtos, rng)

    # Distribui cada linha segundo roteamento.py.
    destino = {s: {"produtos": [], "estoque": [], "clientes": [], "pedidos": []} for s in SHARDS}
    for p in produtos:
        for s in SHARDS:  # replicação total: o catálogo vai para TODOS os shards
            destino[s]["produtos"].append(p)
        destino[shard_do_produto(p[0])]["estoque"].append((p[0], rng.randint(5, 200)))
    for c in clientes:
        destino[shard_do_cliente(c[0])]["clientes"].append(c)
    for p in pedidos:  # o pedido vai para o shard do CLIENTE (co-localização)
        destino[shard_do_cliente(p[1])]["pedidos"].append(p)

    # Uma transação por shard: TRUNCATE + COPY + ANALYZE e um COMMIT no fim.
    # (O psycopg já abriu a transação no SELECT acima; nada é gravado sem o commit.)
    # Não é atômico ENTRE shards (isso é assunto da Fase 4, 2PC); para um seed,
    # rodar de novo com --reset resolve qualquer falha no meio do caminho.
    for shard, conn in conexoes.items():
        conn.execute("TRUNCATE pedidos, clientes, estoque, produtos")
        copiar(conn, "produtos", "id, nome, categoria, preco", destino[shard]["produtos"])
        copiar(conn, "estoque", "produto_id, quantidade", destino[shard]["estoque"])
        copiar(conn, "clientes", "id, nome, email, cidade, criado_em", destino[shard]["clientes"])
        copiar(conn, "pedidos", "id, cliente_id, produto_id, quantidade, valor_total, criado_em",
               destino[shard]["pedidos"])
        conn.execute("ANALYZE")  # estatísticas frescas para o planejador (EXPLAIN da Fase 3)
        conn.commit()
        conn.close()
        resumo = ", ".join(f"{t}={len(l)}" for t, l in destino[shard].items())
        print(f"{shard}: {resumo}")


if __name__ == "__main__":
    main()
