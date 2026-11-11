-- =====================================================================
-- Esquema de UM shard. O mesmo arquivo roda em shard_a e shard_b.
--
-- Por que o mesmo DDL nos dois?  Fragmentação HORIZONTAL: cada shard tem
-- todas as colunas, mas só uma parte das linhas. Quem decide qual linha
-- vai para qual shard é o coordenador (api/app/roteamento.py), não o banco.
--
-- Este arquivo é montado em /docker-entrypoint-initdb.d e só roda no
-- PRIMEIRO boot do container (volume vazio). Para recriar: docker compose down -v
-- =====================================================================

-- ---------------------------------------------------------------------
-- produtos: catálogo REPLICADO (cópia completa em todos os shards).
-- Tabela pequena (~50 linhas), lida o tempo todo e quase nunca escrita:
-- o caso clássico para replicação total. Ganho: qualquer shard responde
-- sozinho "qual o nome/preço do produto X" e consegue ter FKs locais.
-- ---------------------------------------------------------------------
CREATE TABLE produtos (
    id         INTEGER       PRIMARY KEY,
    nome       TEXT          NOT NULL,
    categoria  TEXT          NOT NULL,
    preco      NUMERIC(10,2) NOT NULL CHECK (preco > 0)
);

-- ---------------------------------------------------------------------
-- estoque: FRAGMENTADO por hash(produto_id) % 2.
-- A FK para produtos funciona porque o catálogo existe localmente (réplica).
-- O CHECK (quantidade >= 0) é a última linha de defesa contra estoque
-- negativo: mesmo se o coordenador errar, o banco recusa (usado na Fase 4).
-- ---------------------------------------------------------------------
CREATE TABLE estoque (
    produto_id  INTEGER PRIMARY KEY REFERENCES produtos(id),
    quantidade  INTEGER NOT NULL CHECK (quantidade >= 0)
);

-- ---------------------------------------------------------------------
-- clientes: FRAGMENTADO por hash(cliente_id) % 2.
-- O id NÃO é SERIAL: se cada shard tivesse sua própria sequência, os dois
-- gerariam id=1, id=2... e haveria colisão. Quem atribui o id é o coordenador.
-- ---------------------------------------------------------------------
CREATE TABLE clientes (
    id         BIGINT      PRIMARY KEY,
    nome       TEXT        NOT NULL,
    email      TEXT        NOT NULL,
    cidade     TEXT        NOT NULL,
    criado_em  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------
-- pedidos: fragmentado pela MESMA chave do cliente (hash(cliente_id) % 2).
-- Isso é co-localização: o pedido mora no mesmo shard do seu cliente, então
-- "listar pedidos do cliente X" é uma consulta local, sem junção entre shards,
-- e a FK pedidos -> clientes pode existir dentro do shard.
--
-- Simplificação didática: 1 pedido = 1 produto (com quantidade). Assim um
-- pedido envolve no máximo 2 shards (o do cliente e o do estoque), o que
-- deixa o 2PC da Fase 4 fácil de acompanhar.
-- ---------------------------------------------------------------------
CREATE TABLE pedidos (
    id           BIGINT        PRIMARY KEY,
    cliente_id   BIGINT        NOT NULL REFERENCES clientes(id),
    produto_id   INTEGER       NOT NULL REFERENCES produtos(id),
    quantidade   INTEGER       NOT NULL CHECK (quantidade > 0),
    valor_total  NUMERIC(12,2) NOT NULL,
    criado_em    TIMESTAMPTZ   NOT NULL DEFAULT now()
);

CREATE INDEX idx_pedidos_cliente ON pedidos (cliente_id);
CREATE INDEX idx_pedidos_produto ON pedidos (produto_id);

-- ---------------------------------------------------------------------
-- Geradores de ID (Fase 2): uma sequência por shard, com passo 2.
-- O ponto de partida é diferente em cada shard (ímpares no shard_a, pares no
-- shard_b) e é ajustado pelo seed, que sabe quantos ids já foram usados.
-- Detalhes e o porquê em api/app/ids.py.
-- ---------------------------------------------------------------------
CREATE SEQUENCE seq_clientes INCREMENT BY 2;
CREATE SEQUENCE seq_pedidos  INCREMENT BY 2;
