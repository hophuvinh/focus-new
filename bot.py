import os, asyncio, logging, httpx, re
from datetime import datetime, time
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (Application, CommandHandler, MessageHandler,
                           CallbackQueryHandler, filters, ContextTypes)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN    = os.environ["BOT_TOKEN"]
CHAT_ID  = int(os.environ["CHAT_ID"])
API_BASE = os.environ.get("API_BASE", "http://localhost:8000")
APP_URL  = os.environ.get("APP_URL", "")

SLOT_LABEL = {"focus":"🎯 Focus","reactive":"⚡ Reactive","learn-today":"◎ Tonight","inbox":"📥 Inbox"}
STATUS_LABEL = {"todo":"Chưa làm","review":"Review","done":"✅ Xong","delegated":"Đã giao"}

async def api_get(path):
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(f"{API_BASE}{path}"); return r.json()

async def api_post(path, data):
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.post(f"{API_BASE}{path}", json=data); return r.json()

async def api_patch(path, data):
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.patch(f"{API_BASE}{path}", json=data); return r.json()

def fmt_date(s):
    if not s: return ""
    d = datetime.strptime(s, "%Y-%m-%d"); return f"{d.day}/{d.month}"

def today_str(): return datetime.now().strftime("%Y-%m-%d")

def app_btn():
    if not APP_URL: return []
    return [[InlineKeyboardButton("📱 Mở FocusFlow", url=APP_URL)]]

# ═══ SCHEDULED ═══
async def morning_nudge(ctx):
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
        kb = app_btn()
        await ctx.bot.send_message(CHAT_ID, msg, parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(kb) if kb else None)
    except Exception as e: logger.error(f"morning: {e}")

async def reactive_nudge(ctx):
    try:
        s = await api_get("/api/summary")
        reactive = s.get("reactive", []); overdue = s.get("overdue", [])
        msg = "⚡ *Giờ Reactive — 13:30*\n\n"
        if reactive:
            msg += f"*Task cần xử lý ({len(reactive)}):*\n" + "".join(f"  • {t['name']} — _{STATUS_LABEL.get(t['status'],'')}_\n" for t in reactive)
        else: msg += "Không có task reactive 🎉\n"
        if overdue:
            msg += f"\n🔴 *Quá hạn:*\n" + "".join(f"  • {t['name']} _(hạn {fmt_date(t['deadline'])})_\n" for t in overdue)
        kb = app_btn()
        await ctx.bot.send_message(CHAT_ID, msg, parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(kb) if kb else None)
    except Exception as e: logger.error(f"reactive: {e}")

async def delegation_check(ctx):
    try:
        s = await api_get("/api/summary")
        delegated = s.get("delegated", []); urgent = s.get("urgent_delegated", [])
        if not delegated: return
        msg = "👀 *Check task đã giao — 17:00*\n\n"
        if urgent:
            msg += f"🔴 *Sắp đến hạn:*\n" + "".join(f"  • {t['name']} — {t['who']} _(hạn {fmt_date(t['deadline'])})_\n" for t in urgent) + "\n"
        uid = {t['id'] for t in urgent}
        watching = [t for t in delegated if t['id'] not in uid]
        if watching:
            msg += f"👁 *Đang theo dõi ({len(watching)}):*\n"
            for t in watching[:5]:
                dl = f" _(hạn {fmt_date(t['deadline'])})_" if t.get("deadline") else ""
                msg += f"  • {t['name']} — {t['who']}{dl}\n"
        kb = app_btn()
        await ctx.bot.send_message(CHAT_ID, msg, parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(kb) if kb else None)
    except Exception as e: logger.error(f"delegation: {e}")

async def eod_summary(ctx):
    try:
        s = await api_get("/api/summary")
        done = s.get("done_today", []); focus = s.get("focus", []); reactive = s.get("reactive", [])
        msg = "🌙 *Tổng kết ngày*\n\n"
        if done:
            msg += f"✅ *Đã xong ({len(done)}):*\n" + "".join(f"  • {n}\n" for n in done)
        else: msg += "Chưa đánh dấu xong task nào.\n"
        remaining = focus + reactive
        if remaining:
            msg += f"\n⏳ *Còn lại ({len(remaining)}):*\n" + "".join(f"  • {t['name']}\n" for t in remaining)
        msg += "\n_Nghỉ ngơi tốt nhé! 💤_"
        kb = app_btn()
        await ctx.bot.send_message(CHAT_ID, msg, parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(kb) if kb else None)
    except Exception as e: logger.error(f"eod: {e}")

# ═══ COMMANDS ═══
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    kb = app_btn()
    await update.message.reply_text(
        "👋 *FocusFlow Bot*\n\nNhắn tên task bất kỳ để thêm.\n\n"
        "/today /reactive /delegated /done\n/add [tên] · /finish",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb) if kb else None)

async def cmd_today(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        s = await api_get("/api/summary")
        focus = s.get("focus", []); reactive = s.get("reactive", [])
        msg = f"📅 *Hôm nay — {datetime.now().strftime('%d/%m')}*\n\n🎯 *Focus ({len(focus)}/3):*\n"
        msg += "".join(f"  `#{t['id']}` {t['name']} — _{STATUS_LABEL.get(t['status'],'')}_\n" for t in focus) or "  _Trống_\n"
        msg += f"\n⚡ *Reactive ({len(reactive)}):*\n"
        msg += "".join(f"  `#{t['id']}` {t['name']}\n" for t in reactive) or "  _Trống_\n"
        kb = app_btn()
        await update.message.reply_text(msg, parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(kb) if kb else None)
    except Exception as e: await update.message.reply_text(f"❌ {e}")

async def cmd_reactive(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        tasks = await api_get("/api/tasks")
        r = [t for t in tasks if t["slot"]=="reactive" and not t["done"]]
        if not r: await update.message.reply_text("⚡ Không có task reactive"); return
        msg = f"⚡ *Reactive ({len(r)}):*\n\n" + "".join(f"`#{t['id']}` {t['name']}\n" for t in r)
        await update.message.reply_text(msg, parse_mode="Markdown")
    except Exception as e: await update.message.reply_text(f"❌ {e}")

async def cmd_delegated(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        items = await api_get("/api/delegated")
        watching = [t for t in items if t["status"]=="watching"]
        if not watching: await update.message.reply_text("👀 Không có task đang theo dõi"); return
        msg = f"👀 *Đã giao ({len(watching)}):*\n\n"
        for t in watching:
            urgent = t.get("deadline","") <= today_str() if t.get("deadline") else False
            dl = f" · hạn {fmt_date(t['deadline'])}" if t.get("deadline") else ""
            msg += f"{'🔴 ' if urgent else ''}`#{t['id']}` {t['name']} — *{t['who']}*{dl}\n"
        kb = [[InlineKeyboardButton(f"✓ #{t['id']} xong", callback_data=f"delg_done_{t['id']}")] for t in watching[:3]]
        await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))
    except Exception as e: await update.message.reply_text(f"❌ {e}")

async def cmd_done(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        s = await api_get("/api/summary")
        done = s.get("done_today",[]); focus = s.get("focus",[]); reactive = s.get("reactive",[])
        msg = f"🌙 *{datetime.now().strftime('%d/%m')}* — Xong: *{len(done)}* · Còn: *{len(focus)+len(reactive)}*\n"
        if done: msg += "\n" + "".join(f"  ✅ {n}\n" for n in done[-5:])
        await update.message.reply_text(msg, parse_mode="Markdown")
    except Exception as e: await update.message.reply_text(f"❌ {e}")

async def cmd_add(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    name = " ".join(ctx.args).strip()
    if not name: await update.message.reply_text("Cú pháp: `/add tên task`", parse_mode="Markdown"); return
    try:
        task = await api_post("/api/tasks", {"name": name, "slot": "inbox"})
        kb = [[InlineKeyboardButton("🎯 Focus", callback_data=f"slot_{task['id']}_focus"),
               InlineKeyboardButton("⚡ Reactive", callback_data=f"slot_{task['id']}_reactive"),
               InlineKeyboardButton("◎ Learn", callback_data=f"slot_{task['id']}_learn-today")]]
        await update.message.reply_text(f"✅ *#{task['id']}* {task['name']}\n_Chọn slot:_",
            parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))
    except Exception as e: await update.message.reply_text(f"❌ {e}")

async def cmd_finish(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if ctx.args:
        try:
            task = await api_patch(f"/api/tasks/{int(ctx.args[0])}", {"done": True, "status": "done"})
            await update.message.reply_text(f"✅ *{task['name']}* 🎉", parse_mode="Markdown"); return
        except Exception as e: await update.message.reply_text(f"❌ {e}"); return
    try:
        tasks = await api_get("/api/tasks")
        active = [t for t in tasks if not t["done"] and t["slot"] in ["focus","reactive"]]
        if not active: await update.message.reply_text("Không có task active"); return
        kb = [[InlineKeyboardButton(f"✓ #{t['id']} {t['name'][:35]}", callback_data=f"task_done_{t['id']}")] for t in active]
        await update.message.reply_text("Task nào xong?", reply_markup=InlineKeyboardMarkup(kb))
    except Exception as e: await update.message.reply_text(f"❌ {e}")

# ═══ CALLBACKS ═══
async def handle_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer(); d = q.data
    try:
        if d.startswith("task_done_"):
            task = await api_patch(f"/api/tasks/{int(d.split('_')[-1])}", {"done":True,"status":"done"})
            await q.edit_message_text(f"✅ *{task['name']}* 🎉", parse_mode="Markdown")
        elif d.startswith("slot_"):
            parts = d.split("_", 2); tid, slot = int(parts[1]), parts[2]
            task = await api_patch(f"/api/tasks/{tid}", {"slot":slot,"assigned_date":today_str()})
            await q.edit_message_text(f"✅ *#{task['id']}* {task['name']}\n→ {SLOT_LABEL.get(slot,slot)}", parse_mode="Markdown")
        elif d.startswith("delg_done_"):
            await api_patch(f"/api/delegated/{int(d.split('_')[-1])}", {"status":"done"})
            await q.edit_message_text("✅ Đã đánh dấu xong!")
    except Exception as e: await q.edit_message_text(f"❌ {e}")

# ═══ FREE TEXT ═══
async def handle_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    m = re.match(r"(?:xong|done)\s+#?(\d+)", text, re.I)
    if m:
        try:
            task = await api_patch(f"/api/tasks/{int(m.group(1))}", {"done":True,"status":"done"})
            await update.message.reply_text(f"✅ *{task['name']}* 🎉", parse_mode="Markdown")
        except: await update.message.reply_text(f"❌ Không tìm thấy")
        return
    try:
        task = await api_post("/api/tasks", {"name": text, "slot": "inbox"})
        kb = [[InlineKeyboardButton("🎯 Focus", callback_data=f"slot_{task['id']}_focus"),
               InlineKeyboardButton("⚡ Reactive", callback_data=f"slot_{task['id']}_reactive"),
               InlineKeyboardButton("◎ Learn", callback_data=f"slot_{task['id']}_learn-today")]]
        await update.message.reply_text(f"✅ *#{task['id']}* {task['name']}\n_Chọn slot:_",
            parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))
    except Exception as e: await update.message.reply_text(f"❌ {e}")

# ═══ MAIN ═══
def main():
    app = Application.builder().token(TOKEN).build()
    for cmd, fn in [("start",cmd_start),("today",cmd_today),("reactive",cmd_reactive),
                    ("delegated",cmd_delegated),("done",cmd_done),("add",cmd_add),("finish",cmd_finish)]:
        app.add_handler(CommandHandler(cmd, fn))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    # Scheduled jobs (UTC times = VN time - 7h)
    jq = app.job_queue
    jq.run_daily(morning_nudge,    time=time(0, 30))   # 07:30 VN
    jq.run_daily(reactive_nudge,   time=time(6, 30))   # 13:30 VN
    jq.run_daily(delegation_check, time=time(10, 0))   # 17:00 VN
    jq.run_daily(eod_summary,      time=time(14, 0))   # 21:00 VN

    logger.info("FocusFlow Bot started ✅")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
