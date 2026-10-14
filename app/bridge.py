"""Executed INSIDE the existing panel container via docker exec -i.
Only SQL SELECT (read-only transaction) and node GetStats(reset=False).
Never import panel NodeManager, never call start/stop, never change users.
"""
import asyncio
import json
import sys
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from config import database_settings
from PasarGuardNodeBridge import NodeType, create_node
from PasarGuardNodeBridge.common.service_pb2 import StatType

TARGET_IPS = set(sys.argv[1:])

async def poll_one(row):
    item = {"node_id": row["id"], "node_name": row["name"],
            "address": row["address"], "ports": [], "unknown_tags": 0}
    core = json.loads(row["core_json"]) if isinstance(row["core_json"], str) else row["core_json"]
    tag_to_port = {}
    used_ports = set()
    for inbound in core.get("inbounds", []):
        tag, port = inbound.get("tag"), inbound.get("port")
        if not tag or type(port) is not int or not 1 <= port <= 65535:
            continue
        if tag in tag_to_port or port in used_ports:
            raise ValueError("Ambiguous inbound tags or ports")
        tag_to_port[tag] = port
        used_ports.add(port)

    node = create_node(
        connection=NodeType(row["connection_type"]),
        address=row["address"], port=row["port"], api_port=row["api_port"],
        server_ca=row["server_ca"], api_key=row["api_key"],
        proxy=row["proxy_url"] or None,
    )
    try:
        response = await node.get_stats(stat_type=StatType.Inbounds, reset=False, timeout=12)
    finally:
        # Never use "async with node": __aexit__ calls node.stop()!
        if hasattr(node, "channel"):
            node.channel.close()
        else:
            await node._client.close()
            await node._json_client.close()

    if response is None or not response.stats:
        raise ValueError("No inbound counters received")
    values = {}
    for stat in response.stats:
        if stat.name not in tag_to_port:
            item["unknown_tags"] += 1
            continue
        if stat.type not in ("uplink", "downlink") or stat.value < 0:
            continue
        values.setdefault(stat.name, {})[stat.type] = int(stat.value)

    for tag, pair in values.items():
        item["ports"].append({
            "port": tag_to_port[tag], "tag": tag,
            "uplink": pair.get("uplink"), "downlink": pair.get("downlink"),
        })
    item["ports"].sort(key=lambda p: p["port"])
    return item

async def main():
    output = {"nodes": [], "errors": []}
    engine = create_async_engine(database_settings.url, pool_size=1, max_overflow=0)
    try:
        async with engine.connect() as db:
            if db.dialect.name == "postgresql":
                await db.execute(text("SET TRANSACTION READ ONLY"))
            result = await db.execute(text("""
                SELECT n.id, n.name, n.address, n.port, n.api_port,
                       n.server_ca, n.api_key, n.connection_type,
                       n.proxy_url, c.config AS core_json
                FROM nodes AS n
                JOIN core_configs AS c
                  ON c.id = COALESCE(n.core_config_id, 1)
                ORDER BY n.id
            """))
            rows = [dict(x) for x in result.mappings().all()]
    finally:
        await engine.dispose()

    rows = [r for r in rows if not TARGET_IPS or r["address"] in TARGET_IPS]
    if TARGET_IPS:
        for ip in TARGET_IPS:
            if not any(r["address"] == ip for r in rows):
                output["errors"].append("Configured node not found: " + ip)
    if not rows:
        output["errors"].append("No matching nodes")
    for row in rows:
        try:
            output["nodes"].append(await poll_one(row))
        except Exception as exc:
            # Never serialize secrets, credential-bearing URLs, or full exceptions.
            output["errors"].append("Node %s: %s" % (row["id"], type(exc).__name__))
    print(json.dumps(output, ensure_ascii=False, separators=(",", ":")))

try:
    asyncio.run(main())
except Exception as exc:
    print(json.dumps({"nodes": [], "errors": ["Bridge: " + type(exc).__name__]}))
    sys.exit(1)
