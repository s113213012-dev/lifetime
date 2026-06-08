# Livetime 部署指引

完整的本地開發 → 公開部署流程。

---

## 目錄

1. [快速啟動（本地）](#1-快速啟動本地)
2. [用 ngrok 讓 Claude / 外部裝置連線](#2-用-ngrok-讓-claude--外部裝置連線)
3. [GitHub Pages 靜態部署](#3-github-pages-靜態部署)
4. [架構總覽](#4-架構總覽)

---

## 1. 快速啟動（本地）

### 安裝依賴

```bash
cd backend
pip install fastmcp fastapi uvicorn anthropic
```

### 初始化資料庫

```bash
python seed.py
# ✓ Database seeded at .../livetime.db
```

### 啟動 REST API

```bash
python api_server.py          # 預設 http://127.0.0.1:8080
# 或指定 port：
python api_server.py --port 3001
```

確認可用：

```bash
curl http://127.0.0.1:8080/api/stats
# → {"total_events":10,"by_category":[...],...}
```

互動式文件：`http://127.0.0.1:8080/docs`

### 啟動 AI 功能（選用）

```bash
export ANTHROPIC_API_KEY=sk-ant-...
# API Server 會自動偵測，/api/analyze、/api/export、/api/chat 才會啟用
```

### 開啟前端

直接用瀏覽器開啟：

```
frontend/index.html
```

或起一個靜態伺服器（避免 CORS 問題）：

```bash
cd frontend
python -m http.server 5500
# 開啟 http://localhost:5500
```

前端預設連接 `http://127.0.0.1:8080`。若需更改，在瀏覽器 Console 執行：

```js
setApiUrl("http://127.0.0.1:3001")  // 重新整理後生效
```

---

## 2. 用 ngrok 讓 Claude / 外部裝置連線

當你需要讓外部 AI Agent、手機、或 Claude MCP Client 連到你的本地後端，
用 ngrok 建立安全的公開隧道。

### 安裝 ngrok

```bash
# macOS
brew install ngrok/ngrok/ngrok

# Linux
curl -sSL https://ngrok-agent.s3.amazonaws.com/ngrok.asc | \
  sudo tee /etc/apt/trusted.gpg.d/ngrok.asc >/dev/null && \
  echo "deb https://ngrok-agent.s3.amazonaws.com buster main" | \
  sudo tee /etc/apt/sources.list.d/ngrok.list && \
  sudo apt update && sudo apt install ngrok

# 或直接下載：https://ngrok.com/download
```

登入（免費帳號即可）：

```bash
ngrok config add-authtoken <YOUR_NGROK_TOKEN>
```

### 建立隧道

確保 API Server 已在 8080 運行，然後：

```bash
ngrok http 8080
```

輸出範例：

```
Forwarding   https://a1b2c3d4.ngrok-free.app -> http://localhost:8080
```

複製 `https://...ngrok-free.app` 這個 URL。

### 讓前端使用 ngrok URL

在瀏覽器 Console 貼上：

```js
setApiUrl("https://a1b2c3d4.ngrok-free.app")
```

頁面重新整理後，前端即透過 ngrok 呼叫你的本地後端。

### 讓 Claude Desktop 連接 MCP Server

在 `~/.config/claude/claude_desktop_config.json`（macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`）加入：

```json
{
  "mcpServers": {
    "livetime": {
      "command": "python",
      "args": ["/絕對路徑/lifetime/backend/mcp_server.py", "--stdio"],
      "env": {
        "ANTHROPIC_API_KEY": "sk-ant-..."
      }
    }
  }
}
```

重啟 Claude Desktop，側邊欄會出現 livetime 工具。

### ngrok 使用注意

| 項目 | 說明 |
|------|------|
| 免費方案限制 | 每月 1 GB 流量，隧道會在重啟後換 URL |
| 固定 URL | 升級 ngrok 付費方案，或使用 `--domain` 旗標 |
| 安全性 | ngrok URL 對全網路公開；不要在後端存放真實個人敏感資料 |
| 替代方案 | Cloudflare Tunnel（免費且固定）、Tailscale、localtunnel |

---

## 3. GitHub Pages 靜態部署

前端 `frontend/index.html` 是一個純靜態頁面，可直接部署到 GitHub Pages，
網址形式：`https://你的帳號.github.io/lifetime`

### 步驟一：確認 repo 設定

```bash
# 確認目前在正確的 branch
git branch
# * claude/vibrant-curie-CfHfc

# 確認 frontend/ 已提交
git status
```

### 步驟二：建立 gh-pages 分支

```bash
# 從 main 建立專屬的靜態部署分支
git checkout main
git checkout -b gh-pages

# 只保留 frontend/ 的內容在根目錄
git checkout claude/vibrant-curie-CfHfc -- frontend/
cp frontend/index.html index.html
git add index.html
git commit -m "deploy: GitHub Pages static frontend"
git push -u origin gh-pages
```

> **更簡單的方式**：直接把 `frontend/index.html` 複製到 repo 根目錄的 `docs/` 資料夾，然後在 GitHub Pages 設定中選擇「從 docs/ 資料夾部署」。

### 步驟三：開啟 GitHub Pages

1. 前往 GitHub repo 頁面 → **Settings** → **Pages**
2. **Source**：選 `Deploy from a branch`
3. **Branch**：選 `gh-pages`，資料夾選 `/ (root)`
4. 點 **Save**

幾分鐘後，GitHub 會給你一個網址：
`https://你的帳號.github.io/lifetime`

### 步驟四：設定前端指向後端

部署後的靜態頁面需要知道後端在哪裡。有三種方法：

**方法 A：ngrok（最簡單）**

把 `frontend/index.html` 中的這行改成你的 ngrok URL：

```js
// 找到這行：
const API = (localStorage.getItem("livetime_api") || "http://127.0.0.1:8080")
// 改成：
const API = (localStorage.getItem("livetime_api") || "https://你的ngrok網址.ngrok-free.app")
```

提交、推送後 GitHub Pages 自動更新。

**方法 B：瀏覽器 Console 動態設定（不用改程式碼）**

開啟已部署的頁面，在 Console 執行：

```js
setApiUrl("https://你的ngrok網址.ngrok-free.app")
```

設定儲存在 localStorage，只需設定一次。

**方法 C：部署後端到雲端（永久方案）**

推薦 [Railway](https://railway.app) 或 [Render](https://render.com)（均有免費方案）：

```bash
# Railway 一鍵部署（需安裝 railway CLI）
cd backend
railway login
railway init
railway up
# → 取得固定的 https://livetime-api.up.railway.app
```

然後把 API URL 改成雲端位址即可。

### 自動部署（選用）

在 `.github/workflows/pages.yml` 建立 Action，每次推送到 `main` 自動更新 Pages：

```yaml
name: Deploy Pages
on:
  push:
    branches: [main]
    paths: [frontend/**]
jobs:
  deploy:
    runs-on: ubuntu-latest
    permissions:
      contents: write
    steps:
      - uses: actions/checkout@v4
      - name: Copy to docs/
        run: |
          mkdir -p docs
          cp frontend/index.html docs/index.html
      - uses: stefanzweifel/git-auto-commit-action@v5
        with:
          commit_message: "chore: sync Pages from frontend/"
          branch: main
```

---

## 4. 架構總覽

```
┌─────────────────────────────────────────────────────┐
│                     使用者瀏覽器                        │
│         frontend/index.html (GitHub Pages)           │
│                        │                             │
│            Fetch API ──┤                             │
└───────────────────────│─────────────────────────────┘
                         │  HTTP (ngrok / 雲端)
┌───────────────────────▼─────────────────────────────┐
│              本地 / 雲端 後端                           │
│                                                     │
│   api_server.py  (:8080)  ← FastAPI REST            │
│         │                                           │
│         ├── GET  /api/events                        │
│         ├── GET  /api/stats                         │
│         ├── GET  /api/mood-series                   │
│         ├── GET  /api/skills                        │
│         ├── POST /api/analyze  ──┐                  │
│         ├── POST /api/export   ──┤→ agent.py        │
│         └── POST /api/chat    ──┘       │           │
│                                         ▼           │
│                              Anthropic Claude API   │
│         │                                           │
│         └── seed.py / livetime.db  (SQLite)         │
│                                                     │
│   mcp_server.py  (:8000/sse)  ← Claude Desktop MCP │
└─────────────────────────────────────────────────────┘
```

| 元件 | 技術 | 用途 |
|------|------|------|
| `frontend/index.html` | 純 HTML/CSS/JS | 時間軸 UI、儀表板、AI 對話介面 |
| `api_server.py` | FastAPI + uvicorn | REST 橋接，供前端 Fetch 呼叫 |
| `mcp_server.py` | FastMCP | 供 Claude Desktop 工具呼叫 |
| `agent.py` | Anthropic SDK | 斜線指令解析 + AI 報告生成 |
| `livetime.db` | SQLite | 所有時間軸資料 |
