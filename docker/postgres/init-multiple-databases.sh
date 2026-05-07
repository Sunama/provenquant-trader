#!/bin/bash
# Creates databases defined in DB_CONFIGS env var.
# Format: "db1:user1:pass1, db2:user2:pass2"
set -e

create_db() {
    local database=$1
    local username=$2
    local password=$3
    echo "Creating database '$database' with user '$username'"
    psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" <<-EOSQL
        CREATE USER $username WITH PASSWORD '$password';
        CREATE DATABASE $database;
        GRANT ALL PRIVILEGES ON DATABASE $database TO $username;
        \c $database
        GRANT ALL ON SCHEMA public TO $username;
        CREATE EXTENSION IF NOT EXISTS pgcrypto;
EOSQL
}

if [ -n "$DB_CONFIGS" ]; then
    IFS=',' read -ra ENTRIES <<< "$DB_CONFIGS"
    for entry in "${ENTRIES[@]}"; do
        entry=$(echo "$entry" | xargs)
        IFS=':' read -ra PARTS <<< "$entry"
        create_db "${PARTS[0]}" "${PARTS[1]}" "${PARTS[2]}"
    done
fi
