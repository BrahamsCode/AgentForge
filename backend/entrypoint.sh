#!/usr/bin/env bash
# Espera a Postgres, aplica migraciones y arranca el proceso indicado.
set -euo pipefail

echo "Esperando a Postgres…"
until python -c "
import asyncio, asyncpg, os, urllib.parse as u
url = os.environ['DATABASE_URL'].replace('+asyncpg', '')
p = u.urlparse(url)
async def check():
    conn = await asyncpg.connect(host=p.hostname, port=p.port or 5432,
        user=p.username, password=p.password, database=p.path.lstrip('/'))
    await conn.close()
asyncio.run(check())
" 2>/dev/null; do
  sleep 1
done

if [ "${RUN_MIGRATIONS:-0}" = "1" ]; then
  echo "Aplicando migraciones…"
  alembic upgrade head
fi

exec "$@"
