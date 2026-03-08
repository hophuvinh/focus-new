import os, asyncio, logging, httpx
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (Application, CommandHandler, MessageHandler,
                           CallbackQueryHandler, filters, ContextTypes)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN    = os.environ["BOT_TOKEN"]
CHAT_ID  = os.environ["CHAT_ID"]          # your Telegram user ID
API_BASE = os.environ.get("API_BASE", "http://localhost:8000")
APP_URL  = os.environ.get("APP_URL", "")  # https://yourapp.railway.app

GL = {"kv":"KV/Branding","uiux":"UI/UX","internal":"Internal",
      "editorial":"Editorial","reactive":"Reactive","learn":"Learn"}
SLOT_LABEL = {"focus":"🎯 Focus","reactive":"⚡ Reactive",
              "learn-today":"◎ Learn tonight","inbox":"📥 Inbox"}
STATUS_LABEL = {"todo":"Chưa làm","review":"Review","done":"✅ Xong","delegated":"Đã giao"}

# ═══ API HELPERS ═══
async def api_get(path):
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(f"{API_BASE}{path}")
        return r.json()

async def api_post(path, data):
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.post(f"{API_BASE}{path}", json=data)
        return r.json()

async def api_patch(path, data):
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.patch(f"{API_BASE}{path}", json=data)
        return r.json()

async def api_delete(path):
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.delete(f"{API_BASE}{path}")
        return r.json()

def fmt_date(s):
    if not s: return ""
    d = datetime.strptime(s, "%Y-%m-%d")
    return f"{d.day}/{d.month}"

def today_str():
    return datetime.now().strftime("%Y-%m-%d")

def app_btn():
    if not APP_URL: return []
    return [[InlineKeyboardButton("📱 Mở FocusFlow", url=APP_URL)]]

# ═══ SCHEDULED MESSAGES ═══
async def morning_nudge(bot):
    """07:30 — nhắc mở app"""
    now = datetime.now()
    day_vi = ["Thứ 2","Thứ 3","Thứ 4","Thứ 5","Thứ 6","Thứ 7","Chủ nhật"][now.weekday()]
    try:
        summary = await api_get("/api/summary")
        focus = summary["focus"]
        msg = (
            f"☀️ *Chào buổi sáng, Vinh!*\n"
            f"_{day_vi}, {now.strftime('%d/%m/%Y')}_\n\n"
        )
        if focus:
            msg += f"🎯 *Focus hôm nay ({len(focus)}/3):*\n"
            for t in focus:
                msg += f"  • {t['name']}\n"
        else:
            msg += "🎯 Focus slot trống — vào app xếp task đi!\n"
        msg += f"\n👉 Mở app để bắt đầu ngày mới"
        kb = app_btn()
        await bot.send_message(CHAT_ID, msg, parse_mode="Markdown",
                               reply_markup=InlineKeyboardMarkup(kb) if kb else None)
    except Exception as e:
        logger.error(f"morning_nudge error: {e}")

async def reactive_nudge(bot):
    """13:30 — list task reactive"""
    try:
        summary = await api_get("/api/summary")
        reactive = summary["reactive"]
        overdue  = summary["overdue"]
        msg = "⚡ *Giờ Reactive — 13:30*\n\n"
        if reactive:
            msg += f"*Task cần xử lý ({len(reactive)}):*\n"
            for t in reactive:
                s = STATUS_LABEL.get(t["status"],"")
                msg += f"  • {t['name']} — _{s}_\n"
        else:
            msg += "Không có task reactive hôm nay 🎉\n"
        if overdue:
            msg += f"\n🔴 *Quá hạn ({len(overdue)}):*\n"
            for t in overdue:
                msg += f"  • {t['name']} _(hạn {fmt_date(t['deadline'])})_\n"
        kb = app_btn()
        await bot.send_message(CHAT_ID, msg, parse_mode="Markdown",
                               reply_markup=InlineKeyboardMarkup(kb) if kb else None)
    except Exception as e:
        logger.error(f"reactive_nudge error: {e}")

async def delegation_check(bot):
    """17:00 — check tiến độ task đã giao"""
    try:
        summary = await api_get("/api/summary")
        delegated = summary["delegated"]
        urgent    = summary["urgent_delegated"]
        if not delegated:
            return  # im lặng nếu không có gì
        msg = "👀 *Check task đã giao — 17:00*\n\n"
        if urgent:
            msg += f"🔴 *Sắp đến hạn ({len(urgent)}):*\n"
            for t in urgent:
                msg += f"  • {t['name']} — {t['who']} _(hạn {fmt_date(t['deadline'])})_\n"
            msg += "\n"
        watching = [t for t in delegated if t not in urgent]
        if watching:
            msg += f"👁 *Đang theo dõi ({len(watching)}):*\n"
            for t in watching[:5]:
                dl = f" _(hạn {fmt_date(t['deadline'])})_" if t.get("deadline") else ""
                msg += f"  • {t['name']} — {t['who']}{dl}\n"
        kb = app_btn()
        await bot.send_message(CHAT_ID, msg, parse_mode="Markdown",
                               reply_markup=InlineKeyboardMarkup(kb) if kb else None)
    except Exception as e:
        logger.error(f"delegation_check error: {e}")

async def eod_summary(bot):
    """21:00 — tổng kết ngày"""
    try:
        summary = await api_get("/api/summary")
        done      = summary["done_today"]
        focus     = summary["focus"]
        reactive  = summary["reactive"]
        remaining = focus + reactive
        msg = "🌙 *Tổng kết ngày*\n\n"
        if done:
            msg += f"✅ *Đã xong ({len(done)}):*\n"
            for name in done:
                msg += f"  • {name}\n"
        else:
            msg += "Hôm nay chưa đánh dấu xong task nào.\n"
        if remaining:
            msg += f"\n⏳ *Còn lại ({len(remaining)}):*\n"
            for t in remaining:
                msg += f"  • {t['name']} _{SLOT_LABEL.get(t.get('slot',''),'')} · {STATUS_LABEL.get(t['status'],'')}_\n"
        msg += "\n_Nghỉ ngơi tốt nhé! 💤_"
        kb = app_btn()
        await bot.send_message(CHAT_ID, msg, parse_mode="Markdown",
                               reply_markup=InlineKeyboardMarkup(kb) if kb else None)
    except Exception as e:
        logger.error(f"eod_summary error: {e}")

# ═══ COMMAND HANDLERS ═══
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    kb = app_btn()
    await update.message.reply_text(
        "👋 *FocusFlow Bot*\n\n"
        "Lệnh:\n"
        "/today — task hôm nay\n"
        "/reactive — task reactive\n"
        "/delegated — task đã giao\n"
        "/done — tổng kết\n"
        "/add [tên] — thêm task nhanh\n"
        "/finish [id] — đánh dấu xong\n",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb) if kb else None
    )

async def cmd_today(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        summary = await api_get("/api/summary")
        focus   = summary["focus"]
        reactive = summary["reactive"]
        msg = f"📅 *Hôm nay — {datetime.now().strftime('%d/%m')}*\n\n"
        msg += f"🎯 *Focus ({len(focus)}/3):*\n"
        for t in focus:
            s = STATUS_LABEL.get(t["status"],"")
            msg += f"  `#{t['id']}` {t['name']} — _{s}_\n"
        if not focus: msg += "  _Trống_\n"
        msg += f"\n⚡ *Reactive ({len(reactive)}):*\n"
        for t in reactive:
            s = STATUS_LABEL.get(t["status"],"")
            msg += f"  `#{t['id']}` {t['name']} — _{s}_\n"
        if not reactive: msg += "  _Trống_\n"
        kb = app_btn()
        await update.message.reply_text(msg, parse_mode="Markdown",
                                        reply_markup=InlineKeyboardMarkup(kb) if kb else None)
    except Exception as e:
        await update.message.reply_text(f"❌ Lỗi: {e}")

async def cmd_reactive(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        tasks = await api_get("/api/tasks")
        reactive = [t for t in tasks if t["slot"]=="reactive" and not t["done"]]
        if not reactive:
            await update.message.reply_text("⚡ Không có task reactive"); return
        msg = f"⚡ *Reactive ({len(reactive)}):*\n\n"
        for t in reactive:
            dl = f" · hạn {fmt_date(t['deadline'])}" if t.get("deadline") else ""
            msg += f"`#{t['id']}` {t['name']}{dl}\n"
        await update.message.reply_text(msg, parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ {e}")

async def cmd_delegated(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        items = await api_get("/api/delegated")
        watching = [t for t in items if t["status"]=="watching"]
        if not watching:
            await update.message.reply_text("👀 Không có task đã giao đang theo dõi"); return
        today = today_str()
        msg = f"👀 *Đã giao ({len(watching)}):*\n\n"
        for t in watching:
            urgent = t.get("deadline","") <= today if t.get("deadline") else False
            dl = f" · hạn {fmt_date(t['deadline'])}" if t.get("deadline") else ""
            prefix = "🔴 " if urgent else ""
            msg += f"{prefix}`#{t['id']}` {t['name']} — *{t['who']}*{dl}\n"
        kb = [[InlineKeyboardButton(f"✓ #{t['id']} xong", callback_data=f"delg_done_{t['id']}") for t in watching[:3]]]
        await update.message.reply_text(msg, parse_mode="Markdown",
                                        reply_markup=InlineKeyboardMarkup(kb))
    except Exception as e:
        await update.message.reply_text(f"❌ {e}")

async def cmd_done(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        summary = await api_get("/api/summary")
        done    = summary["done_today"]
        focus   = summary["focus"]
        reactive = summary["reactive"]
        remaining = len(focus) + len(reactive)
        msg = f"🌙 *Hôm nay — {datetime.now().strftime('%d/%m')}*\n\n"
        msg += f"✅ Xong: *{len(done)}* task\n"
        msg += f"⏳ Còn lại: *{remaining}* task\n"
        if done:
            msg += "\n*Đã hoàn thành:*\n"
            for name in done[-5:]:
                msg += f"  • {name}\n"
        await update.message.reply_text(msg, parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ {e}")

async def cmd_add(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    name = " ".join(ctx.args).strip()
    if not name:
        await update.message.reply_text("Cú pháp: `/add tên task`", parse_mode="Markdown"); return
    try:
        task = await api_post("/api/tasks", {"name": name, "slot": "inbox"})
        kb = [
            [InlineKeyboardButton("🎯 Focus", callback_data=f"slot_{task['id']}_focus"),
             InlineKeyboardButton("⚡ Reactive", callback_data=f"slot_{task['id']}_reactive"),
             InlineKeyboardButton("◎ Learn", callback_data=f"slot_{task['id']}_learn-today")]
        ]
        await update.message.reply_text(
            f"✅ *#{task['id']}* {task['name']}\n_Chọn slot:_",
            parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))
    except Exception as e:
        await update.message.reply_text(f"❌ {e}")

async def cmd_finish(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        # show list of active tasks
        try:
            tasks = await api_get("/api/tasks")
            active = [t for t in tasks if not t["done"] and t["slot"] in ["focus","reactive"]]
            if not active:
                await update.message.reply_text("Không có task đang active"); return
            kb = [[InlineKeyboardButton(f"✓ #{t['id']} {t['name'][:35]}", callback_data=f"task_done_{t['id']}")] for t in active]
            await update.message.reply_text("Task nào xong?", reply_markup=InlineKeyboardMarkup(kb))
        except Exception as e:
            await update.message.reply_text(f"❌ {e}")
        return
    try:
        tid = int(ctx.args[0])
        task = await api_patch(f"/api/tasks/{tid}", {"done": True, "status": "done"})
        await update.message.reply_text(f"✅ Xong! *{task['name']}* 🎉", parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ {e}")

# ═══ CALLBACKS ═══
async def handle_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    d = q.data

    if d.startswith("task_done_"):
        tid = int(d.split("_")[-1])
        try:
            task = await api_patch(f"/api/tasks/{tid}", {"done": True, "status": "done"})
            await q.edit_message_text(f"✅ Xong! *{task['name']}* 🎉", parse_mode="Markdown")
        except Exception as e:
            await q.edit_message_text(f"❌ {e}")

    elif d.startswith("slot_"):
        _, tid, slot = d.split("_", 2)
        try:
            task = await api_patch(f"/api/tasks/{tid}",
                                   {"slot": slot, "assigned_date": today_str()})
            await q.edit_message_text(
                f"✅ *#{task['id']}* {task['name']}\n→ {SLOT_LABEL.get(slot,slot)}",
                parse_mode="Markdown")
        except Exception as e:
            await q.edit_message_text(f"❌ {e}")

    elif d.startswith("delg_done_"):
        tid = int(d.split("_")[-1])
        try:
            await api_patch(f"/api/delegated/{tid}", {"status": "done"})
            await q.edit_message_text("✅ Đã đánh dấu xong!")
        except Exception as e:
            await q.edit_message_text(f"❌ {e}")

# ═══ FREE TEXT ═══
async def handle_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    # Quick: "xong #5" or "done 5"
    import re
    m = re.match(r"(?:xong|done)\s+#?(\d+)", text, re.I)
    if m:
        tid = int(m.group(1))
        try:
            task = await api_patch(f"/api/tasks/{tid}", {"done": True, "status": "done"})
            await update.message.reply_text(f"✅ Xong! *{task['name']}* 🎉", parse_mode="Markdown")
        except:
            await update.message.reply_text(f"❌ Không tìm thấy #{tid}")
        return
    # Otherwise: treat as new task name
    try:
        task = await api_post("/api/tasks", {"name": text, "slot": "inbox"})
        kb = [
            [InlineKeyboardButton("🎯 Focus", callback_data=f"slot_{task['id']}_focus"),
             InlineKeyboardButton("⚡ Reactive", callback_data=f"slot_{task['id']}_reactive"),
             InlineKeyboardButton("◎ Learn", callback_data=f"slot_{task['id']}_learn-today")]
        ]
        await update.message.reply_text(
            f"✅ *#{task['id']}* {task['name']}\n_Chọn slot:_",
            parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))
    except Exception as e:
        await update.message.reply_text(f"❌ {e}")

# ═══ MAIN ═══
def main():
    app = Application.builder().token(TOKEN).build()

    # commands
    for cmd, fn in [("start", cmd_start), ("today", cmd_today),
                    ("reactive", cmd_reactive), ("delegated", cmd_delegated),
                    ("done", cmd_done), ("add", cmd_add), ("finish", cmd_finish)]:
        app.add_handler(CommandHandler(cmd, fn))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    # scheduler
    scheduler = AsyncIOScheduler(timezone="Asia/Ho_Chi_Minh")
    bot = app.bot

    scheduler.add_job(lambda: asyncio.create_task(morning_nudge(bot)),
                      CronTrigger(hour=7, minute=30))
    scheduler.add_job(lambda: asyncio.create_task(reactive_nudge(bot)),
                      CronTrigger(hour=13, minute=30))
    scheduler.add_job(lambda: asyncio.create_task(delegation_check(bot)),
                      CronTrigger(hour=17, minute=0))
    scheduler.add_job(lambda: asyncio.create_task(eod_summary(bot)),
                      CronTrigger(hour=21, minute=0))
    scheduler.start()

    logger.info("FocusFlow Bot started ✅")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
