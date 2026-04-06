#!/bin/sh
set -e

if [ -n "$DATABASE_URL" ]; then
    echo "Using PostgreSQL: $DATABASE_URL"
else
    # SQLite mode: ensure data directory and symlink
    mkdir -p /data
    if [ ! -e /app/agent_mailer.db ]; then
        ln -s /data/agent_mailer.db /app/agent_mailer.db
    elif [ ! -L /app/agent_mailer.db ]; then
        mv /app/agent_mailer.db /data/agent_mailer.db
        ln -s /data/agent_mailer.db /app/agent_mailer.db
    fi
fi

exec "$@"
