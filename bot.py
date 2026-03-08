import os, asyncio, logging, httpx, re
from datetime import datetime
from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.request import HTTPXRequest

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN    = os.environ["BOT_TOKEN"]
CHAT_ID  = int(os.environ["CHAT_ID"])
API_BASE = os.environ.get("API_BASE_INTERNAL", "http://localhost:8000")
APP_URL  = os.environ.get("APP_URL", "")
SLOT_LABEL = {"focus":"🎯 Focus","reactive":"⚡ Reactive","learn-today":"◎ Tonight","inbox":"📥 Inbox"}
STATUS_LABEL = {"todo":"Chưa làm","review":"Review","done":"✅ Xong"}

# ═══ API ═══
async def api_get(path):
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(f"{API_BASE}{path}"); return r.json()

async def api_post(path, data):
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.post(f"{API_BASE}{path}", json=data)
        result = r.json()
        logger.info(f"api_post {path} -> {result}")
        return result

async def api_patch(path, data):
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.patch(f"{API_BASE}{path}", json=data); return r.json()

def fmt_date(s):
    if not s: return ""
    d = datetime.strptime(s, "%Y-%m-%d"); return f"{d.day}/{d.month}"

def today_str(): return datetime.now().strftime("%Y-%m-%d")

def app_kb():
    if not APP_URL: return None
    return InlineKeyboardMarkup([[InlineKeyboardButton("📱 Mở FocusFlow", url=APP_URL)]])

# ═══ SCHEDULED ═══
async def morning_nudge(bot: Bot):
    now = datetime.now()
    day_vi = ["Thứ 2","Thứ 3","Thứ 4","Thứ 5","Thứ 6","Thứ 7","Chủ nhật"][now.weekday()]
    try:
        s = await api_get("/api/summary")
        focus = s.get("focus", [])
        msg = f"☀️ *Chào buổi sáng, Vinh!*\n_{day_vi}, {now.strftime('%d/%m/%Y')}_\n\n"
        msg += (f"🎯 *Focus hôm nay ({len(focus)}/3):*\n" + "".join(f"  • {t['name']}\n" for t in focus)) if focus else "🎯 Focus trống — vào app xếp task!\n"
        msg += "\n👉 Mở app bắt đầu ngày mới"
        await bot.send_message(CHAT_ID, msg, parse_mode="Markdown", reply_markup=app_kb())
    except Exception as e: logger.error(f"morning: {e}")

async def reactive_nudge(bot: Bot):
    try:
        s = await api_get("/api/summary")
        reactive = s.get("reactive", []); overdue = s.get("overdue", [])
        msg = "⚡ *Giờ Reactive — 13:30*\n\n"
        msg += (f"*Task cần xử lý ({len(reactive)}):*\n" + "".join(f"  • {t['name']}\n" for t in reactive)) if reactive else "Không có task reactive 🎉\n"
        if overdue: msg += "\n🔴 *Quá hạn:*\n" + "".join(f"  • {t['name']} _(hạn {fmt_date(t['deadline'])})_\n" for t in overdue)
        await bot.send_message(CHAT_ID, msg, parse_mode="Markdown", reply_markup=app_kb())
    except Exception as e: logger.error(f"reactive: {e}")

async def delegation_check(bot: Bot):
    try:
        s = await api_get("/api/summary")
        delegated = s.get("delegated", []); urgent = s.get("urgent_delegated", [])
        if not delegated: return
        msg = "👀 *Check task đã giao — 17:00*\n\n"
        if urgent: msg += "🔴 *Sắp đến hạn:*\n" + "".join(f"  • {t['name']} — {t['who']} _(hạn {fmt_date(t['deadline'])})_\n" for t in urgent) + "\n"
        uid = {t['id'] for t in urgent}
        watching = [t for t in delegated if t['id'] not in uid]
        if watching:
            msg += f"👁 *Đang theo dõi ({len(watching)}):*\n"
            for t in watching[:5]:
                msg += f"  • {t['name']} — {t['who']}" + (f" _(hạn {fmt_date(t['deadline'])})_" if t.get("deadline") else "") + "\n"
        await bot.send_message(CHAT_ID, msg, parse_mode="Markdown", reply_markup=app_kb())
    except Exception as e: logger.error(f"delegation: {e}")

async def eod_summary(bot: Bot):
    try:
        s = await api_get("/api/summary")
        done = s.get("done_today", []); focus = s.get("focus", []); reactive = s.get("reactive", [])
        msg = "🌙 *Tổng kết ngày*\n\n"
        msg += (f"✅ *Đã xong ({len(done)}):*\n" + "".join(f"  • {n}\n" for n in done)) if done else "Chưa đánh dấu xong task nào.\n"
        remaining = focus + reactive
        if remaining: msg += f"\n⏳ *Còn lại ({len(remaining)}):*\n" + "".join(f"  • {t['name']}\n" for t in remaining)
        msg += "\n_Nghỉ ngơi tốt nhé! 💤_"
        await bot.send_message(CHAT_ID, msg, parse_mode="Markdown", reply_markup=app_kb())
    except Exception as e: logger.error(f"eod: {e}")

# ═══ HANDLE UPDATE ═══
async def handle_update(bot: Bot, update_data: dict):
    try:
        msg = update_data.get("message") or update_data.get("callback_query", {}).get("message")
        
        # CALLBACK
        if "callback_query" in update_data:
            cq = update_data["callback_query"]
            cq_id = cq["id"]; d = cq["data"]
            await bot.answer_callback_query(cq_id)
            
            if d.startswith("task_done_"):
                task = await api_patch(f"/api/tasks/{d.split('_')[-1]}", {"done":True,"status":"done"})
                await bot.edit_message_text(f"✅ *{task['name']}* 🎉", cq["message"]["chat"]["id"], cq["message"]["message_id"], parse_mode="Markdown")
            elif d.startswith("slot_"):
                parts = d.split("_", 2); tid, slot = parts[1], parts[2]
                task = await api_patch(f"/api/tasks/{tid}", {"slot":slot,"assigned_date":today_str()})
                await bot.edit_message_text(f"✅ *#{task['id']}* {task['name']}\n→ {SLOT_LABEL.get(slot,slot)}", cq["message"]["chat"]["id"], cq["message"]["message_id"], parse_mode="Markdown")
            elif d.startswith("delg_done_"):
                await api_patch(f"/api/delegated/{d.split('_')[-1]}", {"status":"done"})
                await bot.edit_message_text("✅ Đánh dấu xong!", cq["message"]["chat"]["id"], cq["message"]["message_id"])
            return

        if not msg: return
        chat_id = msg["chat"]["id"]
        text = msg.get("text","").strip()
        if not text: return

        # COMMANDS
        if text.startswith("/start"):
            await bot.send_message(chat_id,
                "👋 *FocusFlow Bot*\n\nNhắn tên task để thêm.\n\n/today /reactive /delegated /done\n/add [tên] · /finish",
                parse_mode="Markdown", reply_markup=app_kb())

        elif text.startswith("/today"):
            s = await api_get("/api/summary")
            focus = s.get("focus",[]); reactive = s.get("reactive",[])
            m = f"📅 *{datetime.now().strftime('%d/%m')}*\n\n🎯 *Focus ({len(focus)}/3):*\n"
            m += "".join(f"  `#{t['id']}` {t['name']} — _{STATUS_LABEL.get(t['status'],'')}_\n" for t in focus) or "  _Trống_\n"
            m += f"\n⚡ *Reactive ({len(reactive)}):*\n"
            m += "".join(f"  `#{t['id']}` {t['name']}\n" for t in reactive) or "  _Trống_\n"
            await bot.send_message(chat_id, m, parse_mode="Markdown", reply_markup=app_kb())

        elif text.startswith("/reactive"):
            tasks = await api_get("/api/tasks")
            r = [t for t in tasks if t["slot"]=="reactive" and not t["done"]]
            m = f"⚡ *Reactive ({len(r)}):*\n\n" + "".join(f"`#{t['id']}` {t['name']}\n" for t in r) if r else "Không có task reactive"
            await bot.send_message(chat_id, m, parse_mode="Markdown")

        elif text.startswith("/delegated"):
            items = await api_get("/api/delegated")
            watching = [t for t in items if t["status"]=="watching"]
            if not watching:
                await bot.send_message(chat_id, "Không có task đang theo dõi"); return
            m = f"👀 *Đã giao ({len(watching)}):*\n\n"
            for t in watching:
                urgent = t.get("deadline","") <= today_str() if t.get("deadline") else False
                m += f"{'🔴 ' if urgent else ''}`#{t['id']}` {t['name']} — *{t.get('who','')}*\n"
            kb = InlineKeyboardMarkup([[InlineKeyboardButton(f"✓ #{t['id']} xong", callback_data=f"delg_done_{t['id']}")] for t in watching[:3]])
            await bot.send_message(chat_id, m, parse_mode="Markdown", reply_markup=kb)

        elif text.startswith("/done"):
            s = await api_get("/api/summary")
            done = s.get("done_today",[]); focus = s.get("focus",[]); reactive = s.get("reactive",[])
            m = f"🌙 *{datetime.now().strftime('%d/%m')}* — Xong: *{len(done)}* · Còn: *{len(focus)+len(reactive)}*\n"
            if done: m += "\n" + "".join(f"  ✅ {n}\n" for n in done[-5:])
            await bot.send_message(chat_id, m, parse_mode="Markdown")

        elif text.startswith("/add "):
            name = text[5:].strip()
            task = await api_post("/api/tasks", {"name": name, "slot": "inbox"})
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton("🎯", callback_data=f"slot_{task['id']}_focus"),
                InlineKeyboardButton("⚡", callback_data=f"slot_{task['id']}_reactive"),
                InlineKeyboardButton("◎", callback_data=f"slot_{task['id']}_learn-today")
            ]])
            await bot.send_message(chat_id, f"✅ *#{task['id']}* {task['name']}\n_Chọn slot:_", parse_mode="Markdown", reply_markup=kb)

        elif text.startswith("/finish"):
            parts = text.split()
            if len(parts) > 1:
                task = await api_patch(f"/api/tasks/{parts[1]}", {"done":True,"status":"done"})
                await bot.send_message(chat_id, f"✅ *{task['name']}* 🎉", parse_mode="Markdown")
            else:
                tasks = await api_get("/api/tasks")
                active = [t for t in tasks if not t["done"] and t["slot"] in ["focus","reactive"]]
                if not active: await bot.send_message(chat_id, "Không có task active"); return
                kb = InlineKeyboardMarkup([[InlineKeyboardButton(f"✓ #{t['id']} {t['name'][:35]}", callback_data=f"task_done_{t['id']}")] for t in active])
                await bot.send_message(chat_id, "Task nào xong?", reply_markup=kb)

        else:
            # free text — check "xong #5"
            m = re.match(r"(?:xong|done)\s+#?(\d+)", text, re.I)
            if m:
                task = await api_patch(f"/api/tasks/{m.group(1)}", {"done":True,"status":"done"})
                await bot.send_message(chat_id, f"✅ *{task['name']}* 🎉", parse_mode="Markdown")
            else:
                task = await api_post("/api/tasks", {"name": text, "slot": "inbox"})
                kb = InlineKeyboardMarkup([[
                    InlineKeyboardButton("🎯", callback_data=f"slot_{task['id']}_focus"),
                    InlineKeyboardButton("⚡", callback_data=f"slot_{task['id']}_reactive"),
                    InlineKeyboardButton("◎", callback_data=f"slot_{task['id']}_learn-today")
                ]])
                await bot.send_message(chat_id, f"✅ *#{task['id']}* {task['name']}\n_Chọn slot:_", parse_mode="Markdown", reply_markup=kb)

    except Exception as e:
        logger.error(f"handle_update error: {e}")
        try:
            await bot.send_message(chat_id, f"❌ Lỗi: {e}")
        except: pass

# ═══ SCHEDULER ═══
async def run_scheduler(bot: Bot):
    """Check every minute if it's time to send scheduled messages (VN time = UTC+7)"""
    sent = set()
    while True:
        now = datetime.utcnow()
        # Convert to VN time
        from datetime import timedelta
        vn = now + timedelta(hours=7)
        key = vn.strftime("%H:%M")
        
        if key == "07:30" and key not in sent:
            sent.add(key); asyncio.create_task(morning_nudge(bot))
        elif key == "13:30" and key not in sent:
            sent.add(key); asyncio.create_task(reactive_nudge(bot))
        elif key == "17:00" and key not in sent:
            sent.add(key); asyncio.create_task(delegation_check(bot))
        elif key == "21:00" and key not in sent:
            sent.add(key); asyncio.create_task(eod_summary(bot))
        
        # Reset sent at midnight
        if key == "00:00":
            sent.clear()
        
        await asyncio.sleep(30)

# ═══ POLLING ═══
async def run_polling(bot: Bot):
    offset = None
    logger.info("FocusFlow Bot polling started ✅")
    while True:
        try:
            params = {"timeout": 30, "allowed_updates": ["message","callback_query"]}
            if offset: params["offset"] = offset
            updates = await bot.get_updates(**params)
            for u in updates:
                offset = u.update_id + 1
                asyncio.create_task(handle_update(bot, u.to_dict()))
        except Exception as e:
            logger.error(f"polling error: {e}")
            await asyncio.sleep(5)

# ═══ MAIN ═══
async def main():
    request = HTTPXRequest(connection_pool_size=8)
    bot = Bot(token=TOKEN, request=request)
    me = await bot.get_me()
    logger.info(f"Bot: @{me.username} ✅")
    await asyncio.gather(
        run_polling(bot),
        run_scheduler(bot)
    )

if __name__ == "__main__":
    asyncio.run(main())
