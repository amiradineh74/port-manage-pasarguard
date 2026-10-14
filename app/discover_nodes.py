"""Read-only listing of PasarGuard node IDs and names, run inside the panel container.

Never print API keys, certificates, proxy URLs, or database credentials.
"""
import asyncio
import json
import sys

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from config import database_settings


async def main():
    engine = create_async_engine(database_settings.url, pool_size=1, max_overflow=0)
    try:
        async with engine.connect() as db:
            if db.dialect.name == "postgresql":
                await db.execute(text("SET TRANSACTION READ ONLY"))
            result = await db.execute(text("SELECT id, name FROM nodes ORDER BY id"))
            nodes = [{"id": int(row.id), "name": row.name} for row in result]
        print(json.dumps(nodes, ensure_ascii=False))
    finally:
        await engine.dispose()


try:
    asyncio.run(main())
except Exception:
    # Do not print original exceptions, which could contain database connection secrets.
    print("Node discovery failed", file=sys.stderr)
    sys.exit(1)
