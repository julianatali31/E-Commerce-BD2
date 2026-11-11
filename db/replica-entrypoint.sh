#!/bin/sh
# Inicialização da réplica de leitura do shard_a (streaming replication REAL).
#
# No primeiro boot (volume vazio), clona o shard_a inteiro com pg_basebackup:
#   -R          escreve standby.signal + primary_conninfo: o Postgres sobe como
#               réplica (hot standby: aceita SELECT, recusa escrita) e passa a
#               receber o WAL do primário continuamente;
#   -X stream   copia também o WAL gerado durante o clone.
set -e
if [ ! -s "$PGDATA/PG_VERSION" ]; then
    echo "replica: clonando shard_a com pg_basebackup..."
    until pg_basebackup -h shard_a -U replicador -D "$PGDATA" -R -X stream; do
        echo "replica: shard_a ainda não aceita replicação; tentando de novo em 2s"
        rm -rf "${PGDATA:?}"/*
        sleep 2
    done
    chmod 0700 "$PGDATA"
fi

# recovery_min_apply_delay: a réplica RECEBE o WAL na hora, mas só APLICA cada
# commit depois desse atraso. Numa rede local a replicação leva milissegundos,
# rápido demais para ver a olho nu; com o atraso, o dado desatualizado fica
# visível durante a demo. É um recurso real do Postgres ("delayed standby",
# usado em produção como proteção contra um DELETE errado), não uma simulação.
exec postgres -c recovery_min_apply_delay="${ATRASO_REPLICA:-10s}"
