import os, asyncio, logging, httpx, re
from datetime import datetime, timedelta
from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.request import HTTPXRequest

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN    = os.environ["BOT_TOKEN"]
CHAT_ID  = int(os.environ["CHAT_ID"])
PORT     = int(os.environ.get("PORT", "8000"))
API_BASE = f"http://localhost:{PORT}"
APP_URL  = os.environ.get("APP_URL", "")

def esc(text: str) -> str:
    """Escape _ and * for Telegram Markdown"""
    if not text: return ""
    return text.replace('_', r'\_').replace('*', r'\*').replace('[', r'\[').replace('`', r'\`')

SLOT_LABEL   = {"focus-am":"🎯 Focus sáng","focus-pm":"🎯 Focus chiều","reactive-am":"⚡ Reactive sáng","reactive-pm":"⚡ Reactive chiều","learn-today":"◎ Tonight","inbox":"📥 Inbox"}
STATUS_LABEL = {"todo":"Chưa làm","review":"Review","done":"✅ Xong"}

# ═══ API ═══
async def api_get(path):
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(f"{API_BASE}{path}")
        return r.json()

async def api_post(path, data):
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.post(f"{API_BASE}{path}", json=data)
        result = r.json()
        logger.info(f"POST {path} status={r.status_code} -> {result}")
        return result

async def api_patch(path, data):
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.patch(f"{API_BASE}{path}", json=data)
        return r.json()

def fmt_date(s):
    if not s: return ""
    return datetime.strptime(s, "%Y-%m-%d").strftime("%-d/%-m")

def today_str():
    return datetime.now().strftime("%Y-%m-%d")

def app_kb():
    if not APP_URL: return None
    return InlineKeyboardMarkup([[InlineKeyboardButton("📱 Mở FocusFlow", url=APP_URL)]])

def slot_kb(task_id):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🎯 Sáng",  callback_data=f"slot_{task_id}_focus-am"),
        InlineKeyboardButton("🎯 Chiều", callback_data=f"slot_{task_id}_focus-pm"),
        InlineKeyboardButton("⚡ Reactive", callback_data=f"slot_{task_id}_reactive-am"),
        InlineKeyboardButton("◎ Learn",     callback_data=f"slot_{task_id}_learn-today"),
    ]])

# ═══ SCHEDULED ═══
async def morning_nudge(bot: Bot):
    now = datetime.now()
    day_vi = ["Thứ 2","Thứ 3","Thứ 4","Thứ 5","Thứ 6","Thứ 7","Chủ nhật"][now.weekday()]
    try:
        s = await api_get("/api/summary")
        focus = s.get("focus", [])
        msg = f"☀️ *Chào buổi sáng, Vinh!*\n_{day_vi}, {now.strftime('%d/%m/%Y')}_\n\n"
        if focus:
            msg += f"🎯 *Focus hôm nay ({len(focus)}/3):*\n" + "".join(f"  • {t['name']}\n" for t in focus)
        else:
            msg += "🎯 Focus trống — vào app xếp task!\n"
        msg += "\n👉 Mở app bắt đầu ngày mới"
        await bot.send_message(CHAT_ID, msg, parse_mode="Markdown", reply_markup=app_kb())
    except Exception as e:
        logger.error(f"morning_nudge: {e}")

async def reactive_nudge(bot: Bot):
    try:
        s = await api_get("/api/summary")
        reactive = s.get("reactive", [])
        overdue  = s.get("overdue", [])
        msg = "⚡ *Reactive chiều — 16:00*\n\n"
        if reactive:
            msg += f"*Task cần xử lý ({len(reactive)}):*\n" + "".join(f"  • {t['name']}\n" for t in reactive)
        else:
            msg += "Không có task reactive 🎉\n"
        if overdue:
            msg += "\n🔴 *Quá hạn:*\n" + "".join(f"  • {t['name']} _(hạn {fmt_date(t['deadline'])})_\n" for t in overdue)
        await bot.send_message(CHAT_ID, msg, parse_mode="Markdown", reply_markup=app_kb())
    except Exception as e:
        logger.error(f"reactive_nudge: {e}")

async def delegation_check(bot: Bot):
    try:
        s = await api_get("/api/summary")
        delegated = s.get("delegated", [])
        urgent    = s.get("urgent_delegated", [])
        if not delegated: return
        msg = "👀 *Check task đã giao — 17:00*\n\n"
        if urgent:
            msg += "🔴 *Sắp đến hạn:*\n" + "".join(
                f"  • {t['name']} — {t['who']} _(hạn {fmt_date(t['deadline'])})_\n" for t in urgent) + "\n"
        uid = {t['id'] for t in urgent}
        watching = [t for t in delegated if t['id'] not in uid]
        if watching:
            msg += f"👁 *Đang theo dõi ({len(watching)}):*\n"
            for t in watching[:5]:
                dl = f" _(hạn {fmt_date(t['deadline'])})_" if t.get("deadline") else ""
                msg += f"  • {t['name']} — {t['who']}{dl}\n"
        await bot.send_message(CHAT_ID, msg, parse_mode="Markdown", reply_markup=app_kb())
    except Exception as e:
        logger.error(f"delegation_check: {e}")

async def eod_summary(bot: Bot):
    try:
        s = await api_get("/api/summary")
        done     = s.get("done_today", [])
        focus    = s.get("focus", [])
        reactive = s.get("reactive", [])
        msg = "🌙 *Tổng kết ngày*\n\n"
        if done:
            msg += f"✅ *Đã xong ({len(done)}):*\n" + "".join(f"  • {n}\n" for n in done)
        else:
            msg += "Chưa đánh dấu xong task nào.\n"
        remaining = focus + reactive
        if remaining:
            msg += f"\n⏳ *Còn lại ({len(remaining)}):*\n" + "".join(f"  • {t['name']}\n" for t in remaining)
        msg += "\n_Nghỉ ngơi tốt nhé! 💤_"
        await bot.send_message(CHAT_ID, msg, parse_mode="Markdown", reply_markup=app_kb())
    except Exception as e:
        logger.error(f"eod_summary: {e}")

# ═══ HANDLE UPDATE ═══
async def handle_update(bot: Bot, update_data: dict):
    chat_id = None
    try:
        # Extract chat_id early for error handling
        if "message" in update_data:
            chat_id = update_data["message"]["chat"]["id"]
        elif "callback_query" in update_data:
            chat_id = update_data["callback_query"]["message"]["chat"]["id"]

        # ── CALLBACK ──
        if "callback_query" in update_data:
            cq   = update_data["callback_query"]
            d    = cq["data"]
            mid  = cq["message"]["message_id"]
            await bot.answer_callback_query(cq["id"])

            if d.startswith("task_done_"):
                tid  = int(d.split("_")[-1])
                task = await api_patch(f"/api/tasks/{tid}", {"done": True, "status": "done"})
                await bot.edit_message_text(f"✅ {esc(task['name'])} 🎉", chat_id, mid, parse_mode="Markdown")

            elif d.startswith("slot_"):
                _, tid, slot = d.split("_", 2)
                if slot in ["focus-am","focus-pm"]:
                    tasks = await api_get("/api/tasks")
                    focus_count = sum(1 for t in tasks if t["slot"] in ["focus-am","focus-pm"] and not t["done"] and str(t["id"]) != tid)
                    if focus_count >= 3:
                        await bot.answer_callback_query(cq["id"], "⚠️ Tối đa 3 task Focus mỗi ngày!", show_alert=True)
                        return
                task = await api_patch(f"/api/tasks/{tid}", {"slot": slot, "assigned_date": today_str()})
                await bot.edit_message_text(
                    f"✅ *#{task['id']}* {esc(task['name'])}\n→ {SLOT_LABEL.get(slot, slot)}",
                    chat_id, mid, parse_mode="Markdown")

            elif d.startswith("delg_done_"):
                tid = int(d.split("_")[-1])
                await api_patch(f"/api/delegated/{tid}", {"status": "done"})
                await bot.edit_message_text("✅ Đánh dấu xong!", chat_id, mid)
            return

        # ── MESSAGE ──
        if "message" not in update_data: return
        msg  = update_data["message"]
        text = msg.get("text", "").strip()
        if not text: return

        if text.startswith("/start"):
            await bot.send_message(chat_id,
                "👋 *FocusFlow Bot*\n\nNhắn tên task để thêm.\n\n"
                "/today · /reactive · /delegated · /done\n/add [tên] · /finish",
                parse_mode="Markdown", reply_markup=app_kb())

        elif text.startswith("/today"):
            s = await api_get("/api/summary")
            focus    = s.get("focus", [])
            reactive = s.get("reactive", [])
            m  = f"📅 *Hôm nay — {datetime.now().strftime('%d/%m')}*\n\n"
            m += f"🎯 *Focus ({len(focus)}/3):*\n"
            m += "".join(f"  `#{t['id']}` {t['name']} — _{STATUS_LABEL.get(t['status'],'')}_\n" for t in focus) or "  _Trống_\n"
            m += f"\n⚡ *Reactive ({len(reactive)}):*\n"
            m += "".join(f"  `#{t['id']}` {t['name']}\n" for t in reactive) or "  _Trống_\n"
            await bot.send_message(chat_id, m, parse_mode="Markdown", reply_markup=app_kb())

        elif text.startswith("/reactive"):
            tasks = await api_get("/api/tasks")
            r = [t for t in tasks if t["slot"] in ["reactive-am","reactive-pm"] and not t["done"]]
            m = f"⚡ *Reactive ({len(r)}):*\n\n" + "".join(f"`#{t['id']}` {t['name']}\n" for t in r) if r else "Không có task reactive"
            await bot.send_message(chat_id, m, parse_mode="Markdown")

        elif text.startswith("/delegated"):
            items    = await api_get("/api/delegated")
            watching = [t for t in items if t["status"] == "watching"]
            if not watching:
                await bot.send_message(chat_id, "Không có task đang theo dõi"); return
            m = f"👀 *Đã giao ({len(watching)}):*\n\n"
            for t in watching:
                urgent = t.get("deadline", "") <= today_str() if t.get("deadline") else False
                dl = f" · hạn {fmt_date(t['deadline'])}" if t.get("deadline") else ""
                m += f"{'🔴 ' if urgent else ''}`#{t['id']}` {t['name']} — *{t.get('who','')}*{dl}\n"
            kb = InlineKeyboardMarkup([[InlineKeyboardButton(f"✓ #{t['id']} xong", callback_data=f"delg_done_{t['id']}")] for t in watching[:3]])
            await bot.send_message(chat_id, m, parse_mode="Markdown", reply_markup=kb)

        elif text.startswith("/done"):
            s = await api_get("/api/summary")
            done     = s.get("done_today", [])
            focus    = s.get("focus", [])
            reactive = s.get("reactive", [])
            m = f"🌙 *{datetime.now().strftime('%d/%m')}* — Xong: *{len(done)}* · Còn: *{len(focus)+len(reactive)}*\n"
            if done: m += "\n" + "".join(f"  ✅ {n}\n" for n in done[-5:])
            await bot.send_message(chat_id, m, parse_mode="Markdown")

        elif text.lower().startswith("/add"):
            name = text[4:].strip()
            if not name:
                await bot.send_message(chat_id, "Cú pháp: `/add tên task`", parse_mode="Markdown"); return
            task = await api_post("/api/tasks", {"name": name, "slot": "inbox"})
            if "id" not in task:
                await bot.send_message(chat_id, f"❌ Lỗi tạo task: {task}"); return
            await bot.send_message(chat_id, f"✅ *#{task['id']}* {esc(task['name'])}\n_Chọn slot:_",
                parse_mode="Markdown", reply_markup=slot_kb(task['id']))

        elif text.lower().startswith("/finish"):
            parts = text.split()
            if len(parts) > 1 and parts[1].isdigit():
                task = await api_patch(f"/api/tasks/{parts[1]}", {"done": True, "status": "done"})
                await bot.send_message(chat_id, f"✅ {esc(task['name'])} 🎉", parse_mode="Markdown")
            else:
                tasks  = await api_get("/api/tasks")
                active = [t for t in tasks if not t["done"] and t["slot"] in ["focus-am","focus-pm","reactive-am","reactive-pm"]]
                if not active:
                    await bot.send_message(chat_id, "Không có task đang active"); return
                kb = InlineKeyboardMarkup([[InlineKeyboardButton(f"✓ #{t['id']} {t['name'][:35]}", callback_data=f"task_done_{t['id']}")] for t in active])
                await bot.send_message(chat_id, "Task nào xong?", reply_markup=kb)

        else:
            # "xong #5" hoặc "done 5"
            match = re.match(r"(?:xong|done)\s+#?(\d+)", text, re.I)
            if match:
                task = await api_patch(f"/api/tasks/{match.group(1)}", {"done": True, "status": "done"})
                await bot.send_message(chat_id, f"✅ {esc(task['name'])} 🎉", parse_mode="Markdown")
            else:
                # free text = new task
                task = await api_post("/api/tasks", {"name": text, "slot": "inbox"})
                if "id" not in task:
                    await bot.send_message(chat_id, f"❌ Lỗi tạo task: {task}"); return
                await bot.send_message(chat_id, f"✅ *#{task['id']}* {esc(task['name'])}\n_Chọn slot:_",
                    parse_mode="Markdown", reply_markup=slot_kb(task['id']))

    except Exception as e:
        logger.error(f"handle_update error: {e}", exc_info=True)
        if chat_id:
            try: await bot.send_message(chat_id, f"❌ Lỗi: {e}")
            except: pass

# ═══ SCHEDULER ═══
async def run_scheduler(bot: Bot):
    sent = set()
    while True:
        vn_now = datetime.utcnow() + timedelta(hours=7)
        key    = vn_now.strftime("%H:%M")
        if key == "00:00": sent.clear()

        jobs = {"08:20": morning_nudge, "16:00": reactive_nudge,
                "17:00": delegation_check, "21:00": eod_summary}
        if key in jobs and key not in sent:
            sent.add(key)
            asyncio.create_task(jobs[key](bot))

        await asyncio.sleep(30)

# ═══ POLLING ═══
async def run_polling(bot: Bot):
    offset = None
    logger.info("FocusFlow Bot polling started ✅")
    while True:
        try:
            params = {"timeout": 30, "allowed_updates": ["message", "callback_query"]}
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
    # Wait for API to be ready
    for _ in range(10):
        try:
            async with httpx.AsyncClient(timeout=3) as c:
                await c.get(f"{API_BASE}/health")
            logger.info(f"API ready at {API_BASE} ✅")
            break
        except:
            logger.info("Waiting for API...")
            await asyncio.sleep(2)

    request = HTTPXRequest(connection_pool_size=8)
    bot     = Bot(token=TOKEN, request=request)
    me      = await bot.get_me()
    logger.info(f"Bot: @{me.username} ✅")
    await asyncio.gather(run_polling(bot), run_scheduler(bot))

if __name__ == "__main__":
    asyncio.run(main())
