import os, logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
import db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

APP_HTML = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.html")

@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.init_db()
    yield

app = FastAPI(lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

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
@app.get("/api/tasks")
async def get_tasks():
    rows = await db.execute("SELECT id,name,grp,status,slot,deadline,assigned_date,done,created_at FROM tasks ORDER BY id DESC")
    for r in rows:
        r["done"] = bool(int(r["done"] or 0))
        r["id"] = int(r["id"])
    return rows

@app.post("/api/tasks")
async def create_task(task: TaskCreate):
    lid = await db.execute_write(
        "INSERT INTO tasks (name,grp,status,slot,deadline,assigned_date,done) VALUES (?,?,?,?,?,?,?)",
        [task.name, task.grp, task.status, task.slot, task.deadline, task.assigned_date, 1 if task.done else 0]
    )
    rows = await db.execute("SELECT id,name,grp,status,slot,deadline,assigned_date,done,created_at FROM tasks WHERE id=?", [lid])
    r = rows[0]
    r["done"] = bool(int(r["done"] or 0))
    r["id"] = int(r["id"])
    return r

@app.patch("/api/tasks/{task_id}")
async def update_task(task_id: int, update: TaskUpdate):
    fields = {k: v for k, v in update.model_dump().items() if v is not None}
    if "done" in fields:
        fields["done"] = 1 if fields["done"] else 0
    if fields:
        sets = ", ".join(f"{k}=?" for k in fields)
        await db.execute_write(f"UPDATE tasks SET {sets} WHERE id=?", [*fields.values(), task_id])
    rows = await db.execute("SELECT id,name,grp,status,slot,deadline,assigned_date,done,created_at FROM tasks WHERE id=?", [task_id])
    if not rows: raise HTTPException(404, "Not found")
    r = rows[0]; r["done"] = bool(int(r["done"] or 0)); r["id"] = int(r["id"])
    return r

@app.delete("/api/tasks/{task_id}")
async def delete_task(task_id: int):
    await db.execute_write("DELETE FROM tasks WHERE id=?", [task_id])
    return {"ok": True}

# ═══ DELEGATED ═══
@app.get("/api/delegated")
async def get_delegated():
    rows = await db.execute("SELECT id,name,who,grp,deadline,status,created_at FROM delegated ORDER BY id DESC")
    for r in rows: r["id"] = int(r["id"])
    return rows

@app.post("/api/delegated")
async def create_delegated(item: DelegatedCreate):
    lid = await db.execute_write(
        "INSERT INTO delegated (name,who,grp,deadline,status) VALUES (?,?,?,?,?)",
        [item.name, item.who, item.grp, item.deadline, item.status]
    )
    rows = await db.execute("SELECT id,name,who,grp,deadline,status,created_at FROM delegated WHERE id=?", [lid])
    r = rows[0]; r["id"] = int(r["id"])
    return r

@app.patch("/api/delegated/{item_id}")
async def update_delegated(item_id: int, update: DelegatedUpdate):
    fields = {k: v for k, v in update.model_dump().items() if v is not None}
    if fields:
        sets = ", ".join(f"{k}=?" for k in fields)
        await db.execute_write(f"UPDATE delegated SET {sets} WHERE id=?", [*fields.values(), item_id])
    rows = await db.execute("SELECT id,name,who,grp,deadline,status,created_at FROM delegated WHERE id=?", [item_id])
    r = rows[0]; r["id"] = int(r["id"])
    return r

# ═══ SUMMARY ═══
@app.get("/api/summary")
async def get_summary():
    today = datetime.now().strftime("%Y-%m-%d")
    focus    = await db.execute("SELECT id,name,grp,status FROM tasks WHERE slot IN ('focus-am','focus-pm') AND done=0")
    reactive = await db.execute("SELECT id,name,grp,status FROM tasks WHERE slot IN ('reactive-am','reactive-pm') AND done=0")
    done_today = await db.execute("SELECT name FROM tasks WHERE done=1 AND (assigned_date=? OR deadline=?)", [today, today])
    overdue  = await db.execute("SELECT id,name,deadline FROM tasks WHERE done=0 AND deadline < ? AND slot NOT IN ('inbox','learn-today')", [today])
    delegated = await db.execute("SELECT id,name,who,deadline FROM delegated WHERE status='watching'")
    urgent_delegated = await db.execute("SELECT id,name,who,deadline FROM delegated WHERE status='watching' AND deadline <= ?", [today])
    for r in focus+reactive+overdue+delegated+urgent_delegated:
        r["id"] = int(r["id"])
    return {
        "focus": focus, "reactive": reactive,
        "done_today": [r["name"] for r in done_today],
        "overdue": overdue, "delegated": delegated,
        "urgent_delegated": urgent_delegated,
    }

# ═══ HEALTH + APP ═══
@app.get("/health")
async def health():
    return {"ok": True}

@app.get("/")
async def serve_app():
    try:
        with open(APP_HTML, "r", encoding="utf-8") as f:
            html = f.read()
        html = html.replace(
            "</head>",
            '<script src="https://telegram.org/js/telegram-web-app.js"></script>\n</head>'
        ).replace(
            "const API_BASE = localStorage.getItem('ff_api_base') || '';",
            "const API_BASE = window.location.origin;"
        )
        return HTMLResponse(content=html)
    except FileNotFoundError:
        return HTMLResponse(content="<h1>App not found</h1>", status_code=404)
