import os, httpx, logging
from typing import Any

logger = logging.getLogger(__name__)

TURSO_URL   = os.environ.get("TURSO_URL", "")
TURSO_TOKEN = os.environ.get("TURSO_TOKEN", "")

def _http_url():
    # Convert libsql:// to https://
    url = TURSO_URL.replace("libsql://", "https://")
    return f"{url}/v2/pipeline"

async def execute(sql: str, params: list = []) -> list[dict]:
    """Execute SQL and return rows as list of dicts"""
    payload = {
        "requests": [
            {"type": "execute", "stmt": {"sql": sql, "args": [{"type":"text","value":str(p)} if p is not None else {"type":"null"} for p in params]}},
            {"type": "close"}
        ]
    }
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.post(
            _http_url(),
            json=payload,
            headers={"Authorization": f"Bearer {TURSO_TOKEN}"}
        )
        r.raise_for_status()
        data = r.json()
    
    result = data["results"][0]
    if result["type"] == "error":
        raise Exception(result["error"]["message"])
    
    rows_data = result["response"]["result"]
    cols = [c["name"] for c in rows_data["cols"]]
    rows = []
    for row in rows_data["rows"]:
        d = {}
        for i, col in enumerate(cols):
            v = row[i]
            d[col] = v["value"] if v["type"] != "null" else None
        rows.append(d)
    return rows

async def execute_write(sql: str, params: list = []) -> int:
    """Execute INSERT/UPDATE/DELETE, return last_insert_rowid"""
    payload = {
        "requests": [
            {"type": "execute", "stmt": {"sql": sql, "args": [{"type":"text","value":str(p)} if p is not None else {"type":"null"} for p in params]}},
            {"type": "close"}
        ]
    }
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.post(
            _http_url(),
            json=payload,
            headers={"Authorization": f"Bearer {TURSO_TOKEN}"}
        )
        r.raise_for_status()
        data = r.json()
    
    result = data["results"][0]
    if result["type"] == "error":
        raise Exception(result["error"]["message"])
    
    return result["response"]["result"].get("last_insert_rowid", 0)

async def init_db():
    await execute_write("""
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            grp TEXT DEFAULT 'kv',
            status TEXT DEFAULT 'todo',
            slot TEXT DEFAULT 'inbox',
            deadline TEXT,
            assigned_date TEXT,
            done INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)
    await execute_write("""
        CREATE TABLE IF NOT EXISTS delegated (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            who TEXT,
            grp TEXT DEFAULT 'kv',
            deadline TEXT,
            status TEXT DEFAULT 'watching',
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)
    logger.info("Turso DB initialized ✅")
