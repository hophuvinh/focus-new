# FocusFlow v2 — Backend + Bot

## Stack
- **FastAPI** — REST API
- **SQLite** — Database (persistent trên Railway volume)
- **python-telegram-bot** — Telegram bot
- **APScheduler** — Scheduled messages

## Railway Setup

### 1. Deploy
```bash
# Push lên GitHub repo, connect Railway
railway login
railway init
railway up
```

### 2. Environment Variables (Railway → Variables)
```
BOT_TOKEN=<token từ @BotFather>
CHAT_ID=<Telegram user ID của bạn — lấy từ @userinfobot>
API_BASE=http://localhost:8000
APP_URL=https://<your-domain>.railway.app
DB_PATH=/data/focusflow.db
```

### 3. Volume (Railway → Storage)
- Mount path: `/data`
- Để SQLite persist khi redeploy

## API Endpoints

| Method | Path | Mô tả |
|--------|------|-------|
| GET | /api/tasks | Lấy tất cả tasks |
| POST | /api/tasks | Tạo task mới |
| PATCH | /api/tasks/:id | Cập nhật task |
| DELETE | /api/tasks/:id | Xoá task |
| GET | /api/delegated | Lấy task đã giao |
| POST | /api/delegated | Giao việc mới |
| PATCH | /api/delegated/:id | Cập nhật trạng thái |
| GET | /api/summary | Tóm tắt cho bot |

## Bot Commands
```
/today     — task focus + reactive hôm nay
/reactive  — chỉ task reactive
/delegated — task đã giao + check hạn
/done      — tổng kết ngày
/add [tên] — thêm task nhanh → chọn slot
/finish    — đánh dấu xong
```

## Scheduled Messages (Asia/Ho_Chi_Minh)
```
07:30  ☀ Chào buổi sáng + task focus hôm nay
13:30  ⚡ Nhắc reactive + overdue
17:00  👀 Check task đã giao
21:00  🌙 Tổng kết ngày
```

## Web App
Cập nhật `API_BASE` trong focusflow-v4.html:
```js
const API_BASE = "https://<your-domain>.railway.app";
```
