#!/bin/sh
# Roda SÓ no shard_a, no primeiro boot (docker-entrypoint-initdb.d).
# Prepara o shard_a para ser primário de uma réplica por streaming replication:
#   1. um usuário com permissão REPLICATION (senha em texto puro: é só uma demo local);
#   2. uma linha no pg_hba.conf liberando conexões de replicação pela rede.
#      (a regra "host all all all" padrão da imagem NÃO cobre replicação)
# wal_level=replica e max_wal_senders=10 já são o padrão do PostgreSQL 16.
set -e
psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
     -c "CREATE ROLE replicador WITH REPLICATION LOGIN PASSWORD 'replicador';"
echo "host replication replicador all scram-sha-256" >> "$PGDATA/pg_hba.conf"
