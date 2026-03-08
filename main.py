import os, asyncio, logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse
import aiosqlite
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DB = os.environ.get("DB_PATH", "focusflow.db")
APP_HTML = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.html")

# ═══ DB INIT ═══
async def init_db():
    async with aiosqlite.connect(DB) as db:
        await db.execute("""
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
        await db.execute("""
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
        await db.commit()

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    logger.info("DB initialized")
    yield

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ═══ MODELS ═══
class TaskCreate(BaseModel):
    name: str
    grp: Optional[str] = "kv"
    status: Optional[str] = "todo"
    slot: Optional[str] = "inbox"
    deadline: Optional[str] = None
    assigned_date: Optional[str] = None
    done: Optional[bool] = False

class TaskUpdate(BaseModel):
    name: Optional[str] = None
    grp: Optional[str] = None
    status: Optional[str] = None
    slot: Optional[str] = None
    deadline: Optional[str] = None
    assigned_date: Optional[str] = None
    done: Optional[bool] = None

class DelegatedCreate(BaseModel):
    name: str
    who: Optional[str] = None
    grp: Optional[str] = "kv"
    deadline: Optional[str] = None
    status: Optional[str] = "watching"

class DelegatedUpdate(BaseModel):
    status: Optional[str] = None
    deadline: Optional[str] = None

# ═══ TASKS ═══
def row_to_task(row):
    keys = ["id","name","grp","status","slot","deadline","assigned_date","done","created_at"]
    d = dict(zip(keys, row))
    d["done"] = bool(d["done"])
    return d

def row_to_delegated(row):
    keys = ["id","name","who","grp","deadline","status","created_at"]
    return dict(zip(keys, row))

@app.get("/api/tasks")
async def get_tasks():
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute("SELECT id,name,grp,status,slot,deadline,assigned_date,done,created_at FROM tasks ORDER BY id DESC")
        rows = await cur.fetchall()
    return [row_to_task(r) for r in rows]

@app.post("/api/tasks")
async def create_task(task: TaskCreate):
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute(
            "INSERT INTO tasks (name,grp,status,slot,deadline,assigned_date,done) VALUES (?,?,?,?,?,?,?)",
            (task.name, task.grp, task.status, task.slot, task.deadline,
             task.assigned_date, 1 if task.done else 0)
        )
        await db.commit()
        row = await (await db.execute("SELECT id,name,grp,status,slot,deadline,assigned_date,done,created_at FROM tasks WHERE id=?", (cur.lastrowid,))).fetchone()
    return row_to_task(row)

@app.patch("/api/tasks/{task_id}")
async def update_task(task_id: int, update: TaskUpdate):
    async with aiosqlite.connect(DB) as db:
        row = await (await db.execute("SELECT id FROM tasks WHERE id=?", (task_id,))).fetchone()
        if not row:
            raise HTTPException(404, "Task not found")
        fields = {k: v for k, v in update.model_dump().items() if v is not None}
        if "done" in fields:
            fields["done"] = 1 if fields["done"] else 0
        if fields:
            sets = ", ".join(f"{k}=?" for k in fields)
            await db.execute(f"UPDATE tasks SET {sets} WHERE id=?", (*fields.values(), task_id))
            await db.commit()
        row = await (await db.execute("SELECT id,name,grp,status,slot,deadline,assigned_date,done,created_at FROM tasks WHERE id=?", (task_id,))).fetchone()
    return row_to_task(row)

@app.delete("/api/tasks/{task_id}")
async def delete_task(task_id: int):
    async with aiosqlite.connect(DB) as db:
        await db.execute("DELETE FROM tasks WHERE id=?", (task_id,))
        await db.commit()
    return {"ok": True}

# ═══ DELEGATED ═══
@app.get("/api/delegated")
async def get_delegated():
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute("SELECT id,name,who,grp,deadline,status,created_at FROM delegated ORDER BY id DESC")
        rows = await cur.fetchall()
    return [row_to_delegated(r) for r in rows]

@app.post("/api/delegated")
async def create_delegated(item: DelegatedCreate):
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute(
            "INSERT INTO delegated (name,who,grp,deadline,status) VALUES (?,?,?,?,?)",
            (item.name, item.who, item.grp, item.deadline, item.status)
        )
        await db.commit()
        row = await (await db.execute("SELECT id,name,who,grp,deadline,status,created_at FROM delegated WHERE id=?", (cur.lastrowid,))).fetchone()
    return row_to_delegated(row)

@app.patch("/api/delegated/{item_id}")
async def update_delegated(item_id: int, update: DelegatedUpdate):
    async with aiosqlite.connect(DB) as db:
        fields = {k: v for k, v in update.model_dump().items() if v is not None}
        if fields:
            sets = ", ".join(f"{k}=?" for k in fields)
            await db.execute(f"UPDATE delegated SET {sets} WHERE id=?", (*fields.values(), item_id))
            await db.commit()
        row = await (await db.execute("SELECT id,name,who,grp,deadline,status,created_at FROM delegated WHERE id=?", (item_id,))).fetchone()
    return row_to_delegated(row)

# ═══ SUMMARY (for bot) ═══
@app.get("/api/summary")
async def get_summary():
    today = datetime.now().strftime("%Y-%m-%d")
    async with aiosqlite.connect(DB) as db:
        focus = await (await db.execute(
            "SELECT id,name,grp,status FROM tasks WHERE slot='focus' AND done=0")).fetchall()
        reactive = await (await db.execute(
            "SELECT id,name,grp,status FROM tasks WHERE slot='reactive' AND done=0")).fetchall()
        done_today = await (await db.execute(
            "SELECT name FROM tasks WHERE done=1 AND (assigned_date=? OR deadline=?)")).fetchall()
        overdue = await (await db.execute(
            "SELECT id,name,deadline FROM tasks WHERE done=0 AND deadline < ? AND slot!='inbox'",
            (today,))).fetchall()
        delegated = await (await db.execute(
            "SELECT id,name,who,deadline FROM delegated WHERE status='watching'")).fetchall()
        urgent_delegated = await (await db.execute(
            "SELECT id,name,who,deadline FROM delegated WHERE status='watching' AND deadline <= ?",
            (today,))).fetchall()

    return {
        "focus": [{"id":r[0],"name":r[1],"grp":r[2],"status":r[3]} for r in focus],
        "reactive": [{"id":r[0],"name":r[1],"grp":r[2],"status":r[3]} for r in reactive],
        "done_today": [r[0] for r in done_today],
        "overdue": [{"id":r[0],"name":r[1],"deadline":r[2]} for r in overdue],
        "delegated": [{"id":r[0],"name":r[1],"who":r[2],"deadline":r[3]} for r in delegated],
        "urgent_delegated": [{"id":r[0],"name":r[1],"who":r[2],"deadline":r[3]} for r in urgent_delegated],
    }

@app.get("/health")
async def health():
    return {"ok": True}

@app.get("/")
async def serve_app():
    try:
        with open(APP_HTML, "r", encoding="utf-8") as f:
            html = f.read()
        # Inject Telegram WebApp script and set API_BASE
        html = html.replace(
            "</head>",
            '<script src="https://telegram.org/js/telegram-web-app.js"></script>\n</head>'
        ).replace(
            "const API_BASE = localStorage.getItem(\'ff_api_base\') || \'\';",
            f"const API_BASE = window.location.origin;"
        )
        return HTMLResponse(content=html)
    except FileNotFoundError:
        return HTMLResponse(content="<h1>App not found</h1>", status_code=404)
