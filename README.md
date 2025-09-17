Stock MCPilot (Bilingual Documentation) / 中英文文档
====================================================

---

# 1. Overview (EN)

Stock MCPilot is a cross‑platform desktop application (macOS/Windows via Tauri) that fetches multi‑market stock data (US / HK / CN) and produces structured analytical summaries & investment insights using either local or cloud LLMs. Data is cached locally (SQLite / Parquet) to reduce redundant requests. Current status: early scaffold with incremental features being added.

> DISCLAIMER: Outputs are for educational & research purposes only and DO NOT constitute investment advice.

## 1.1 Features (Current Scaffold)
- Single symbol query for US / HK / A‑share markets
- Data sources: yfinance (US/HK/crypto) + AKShare (CN markets, to extend)
- Local or cloud LLM selection (Ollama local inference; cloud via future LiteLLM routing)
- Basic statistical summary (return, volatility, max drawdown, average volume)
- Close price line chart with:
  - Adaptive date X‑axis tick density
  - Brush for adjustable visible range (draggable window)
  - Visible range label
- Earnings panel (right side):
  - Last ~2 years EPS Estimate / Actual / Surprise (+ Surprise%)
  - Next earnings date (if available)
  - Graceful fallback per market (US best; HK/CN best‑effort)
  - Compact, scrollable card with expand/collapse
- Recent News panel (below chart):
  - Up to 10 recent headlines (pure text, concise)
  - Scrollable inside fixed area; does not expand page layout
  - Local cache with FIFO eviction (keep latest 10 per symbol/market)
  - Sources: yfinance Ticker.news; fallback to Yahoo Finance RSS
- Intraday behavior for “today”:
  - If trading day and market open → show current price (auto‑refreshed on query)
  - If market closed → show official close (overwrites prior intraday cache)
  - SQLite upsert keeps latest for the day
- Settings page (mode, API key, local model)
- Caching daily prices into SQLite
- Tauri minimal configuration

Additional recently added features (2025‑09):
- Movers page: gainers / losers with strict market symbol filtering & percent normalization
- Upcoming Earnings page: forward US earnings dates (subset) with graceful empty HK/CN
- Local LLM analysis robustness: extended timeouts, fallback generate endpoint, reasoning tag cleanup
- Global i18n (EN / ZH) applied to new navigation & Upcoming/Movers pages
- Improved brush logic (fixed previous data slicing bug; stable range label)
- Route hardening (regex + ordering) to prevent 404/422 on `/stocks/upcoming_earnings`

Planned (Roadmap excerpt):
- Technical indicators (MA / RSI / MACD / ATR)
- ECharts candlestick + overlayed indicators
- LangChain agent/tool integration & backtesting MCP tools
- Cloud LLM via LiteLLM (OpenAI / Claude / Gemini)
- Secure storage (encrypted API keys)
- Testing (pytest, Vitest), CI pipeline, release bundles

## 1.2 Tech Stack
| Layer | Tech |
|-------|------|
| Desktop Shell | Tauri 2.x |
| Frontend | React + Vite + TypeScript + TailwindCSS + Zustand |
| Backend API | FastAPI (Python) |
| LLM Layer | LangChain (planned) + custom providers (local/cloud) |
| Data Sources | yfinance, AKShare |
| Storage/Cache | SQLite (SQLAlchemy) + potential Parquet extension |

## 1.3 Repository Structure
```
StockMCPilot
├── frontend/            # React + Vite + TS + Tailwind + Zustand
│   ├── src/components/  # UI components
│   │   └── EarningsCard.tsx  # Earnings panel (EPS, next earnings date)
│   │   └── NewsList.tsx      # Recent news panel (scrollable, max 10)
│   ├── src/pages/       # Pages (Home / Settings)
│   ├── src/store/       # Global state (Zustand)
│   ├── src/api/         # API client wrappers
│   ├── src/charts/      # Charts (Recharts / future ECharts)
│   └── src/hooks/       # Custom hooks
├── backend/             # FastAPI service & LLM/data integration
│   ├── routers/         # API routes (stocks / analysis / settings)
│   │   └── stocks.py     # + /stocks/{symbol}/earnings endpoint
│   ├── schemas/         # Pydantic models
│   ├── providers/       # LLM providers (local / cloud)
│   ├── agents/          # LangChain agents (stubs)
│   ├── storage/         # SQLite logic & caching
│   │   └── db.py         # + news table (cached headlines)
│   └── main.py          # App entry
├── src-tauri/           # Tauri (Rust) config
└── README.md
```

## 1.4 Prerequisites (Local Dev)
| Component | Requirement |
|-----------|-------------|
| Python | 3.10+ (3.11 recommended) |
| Node.js | 18+ LTS (or 20+) |
| Rust | Latest stable (for Tauri) |
| Ollama (optional) | For local LLM inference (mac / linux) |
| Git | Repo management |

Optional utilities: `curl`, `jq`.

## 1.5 Environment Variables
Backend (`.env` in project root):
```
LLM_MODE=local            # or cloud
LLM_API_KEY=              # required if cloud
LLM_LOCAL_MODEL=llama3    # local model (Ollama model name)
DATABASE_URL=sqlite:///./backend/storage/stock_cache.db
OLLAMA_ENDPOINT=http://localhost:11434
```
Frontend (`frontend/.env` or `.env.local`):
```
VITE_API_BASE=http://127.0.0.1:8000
```
> NOTE: Restart the Vite dev server after changing env vars.

## 1.6 Step-by-Step Setup

### 1. Clone
```bash
git clone https://github.com/<your-org>/stock-mcpilot.git
cd stock-mcpilot
```

### 2. Python Virtual Environment & Dependencies
```bash
python3 -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
python -m pip install --upgrade pip
pip install -r backend/requirements.txt
```

### 3. (Optional) Pull Local Model via Ollama
```bash
ollama pull llama3
# or another model name you will set in LLM_LOCAL_MODEL
```

### 4. Backend Run
```bash
uvicorn backend.main:app --reload
```
Test:
```bash
curl http://127.0.0.1:8000/health
```

### 5. Frontend Install & Dev Server
```bash
cd frontend
cp .env.example .env  # adjust VITE_API_BASE if needed
npm install
npm run dev
```
Open: http://127.0.0.1:5173

### 6. Desktop (Tauri) Dev (optional)
In another terminal (backend still running):
```bash
cd src-tauri
cargo tauri dev
```

### 7. Build (Preview Examples)
Frontend build:
```bash
cd frontend && npm run build
```
Tauri production build (later once integrated fully):
```bash
cargo tauri build
```

## 1.7 Usage Flow
1. Open frontend (Vite) or Tauri window.
2. Enter symbol (e.g., AAPL) + select market.
3. Query fetches historical data (cached if repeated). If today is a trading day:
  - During market hours, the latest intraday price is saved/updated for today.
  - After close, the official close overwrites any prior intraday cache.
4. Left: Close price line chart (adjustable range). Below the chart: Recent News (up to 10, scrollable).
5. Right: Earnings panel shows recent EPS Estimate/Actual/Surprise and the next earnings date (if available).
6. (Optional) Enter a question -> LLM analysis (local Ollama or future cloud).

## 1.8 Data & Caching Notes
- yfinance data normalized to lowercase columns (open/high/low/close/volume)
- SQLite primary key (symbol, market, date)
- Download attempts fill gaps; simplistic gap heuristic now (future improvement: trading calendar)
- Intraday update flow:
  - During session: upsert today's row using yfinance fast_info/1m history (open/high/low/close/volume)
  - Post‑close: fetch daily history and ensure today's close exists/overwrites prior intraday value
  - End date fetch includes +1 day to account for yfinance's right‑open interval

### 1.8.1 REST Endpoints (selection)
- GET `/health`: service health probe
- GET `/stocks/{symbol}`: daily rows + summary
- GET `/stocks/{symbol}/earnings`: earnings dates with EPS and next earnings date
- GET `/stocks/{symbol}/news`: up to 10 recent text headlines (cached, FIFO)
- GET `/stocks/movers?market=US|HK|CN&type=gainers|losers&count=10`: top movers (normalized pct change)
- GET `/stocks/upcoming_earnings?market=US|HK|CN&days=14&limit=50`: upcoming earnings (US implemented)
- POST `/analysis`: model analysis (local LLM currently)
- GET `/settings`: retrieve saved settings
- POST `/settings`: update settings

### 1.8.2 News Caching & Sources
- Cache: SQLite `news` table, primary key (symbol, market, published_at)
- Each query writes fresh items then trims to the latest 10
- Sources: yfinance `Ticker.news` first; fallback to Yahoo Finance RSS feed

## 1.9 Contributing (Short)
1. Fork & branch (`feat/xyz`)
2. Add/adjust code & tests
3. Submit PR with concise description

## 1.10 Roadmap (Detailed)
1. Technical indicators & enriched summary
2. LangChain tools (data summary, indicator calc, backtest stub)
3. Streaming analysis (server-sent or WebSocket)
4. Cloud LLM via LiteLLM router
5. ECharts candlestick with overlay indicators
6. Secure secrets (keychain / OS secure storage)
7. Test suite & CI/CD (lint, type, test, package)
8. Cross‑platform binary release (Tauri bundle)
9. Strategy backtesting MCP server
10. Multi-symbol comparison view

## 1.11 License & Disclaimer
MIT License (see `LICENSE`).

> Again: No investment advice. Use at your own risk.

---

# 2. 概述 (ZH)

Stock MCPilot 是一个跨平台 (macOS/Windows) 桌面应用，通过本地或云端 LLM 对美股 / 港股 / A 股的单只股票进行数据抓取、统计摘要与结构化智能分析，并利用本地缓存减少重复请求。当前处于早期脚手架阶段，功能逐步完善。

> 免责声明：所有输出仅用于学习 / 研究，不构成投资建议。

## 2.1 已有功能
- 单只股票查询（美股 / 港股 / A 股）
- 数据源：yfinance（美股/港股/加密）+ AKShare（A 股等，待扩展）
- 本地 / 云端 LLM 模式切换（本地 Ollama；云端后续通过 LiteLLM）
- 基础统计摘要（收益、波动率、最大回撤、均量等）
- 收盘价趋势图（改进）：
  - 横轴日期自适配刻度密度
  - 支持拖拽选择可见区间（Brush）
  - 顶部显示当前可见区间
- 财报信息卡片（右侧）：
  - 近两年 EPS 估值/实际/意外（含 Surprise%）
  - 下一次财报日期（若可得）
  - 不同市场覆盖度不同（美股较完整），缺失即不显示具体条目
  - 卡片高度受控、可滚动，支持“展开/收起”
- 近期资讯（图表下方）：
  - 最多 10 条纯文本标题，简短展示
  - 固定高度，内部滚动；不撑大页面
  - 本地缓存（每只股票最新 10 条，FIFO 逐出最早）
  - 数据来源：优先 yfinance Ticker.news，兜底 Yahoo Finance RSS
- 当日展示策略：
  - 若为交易日且开市中：展示并缓存“当前价格”，多次查询自动刷新
  - 若已收盘：展示官方收盘价，并覆盖先前的盘中缓存
  - SQLite upsert 保存当日最新数据
- 设置页（模式 / API Key / 本地模型）
- 日线数据 SQLite 缓存
- Tauri 最小配置

近期新增功能（2025‑09）：
- 涨跌榜页面：按市场展示涨幅榜 / 跌幅榜，严格过滤跨市场代码并规范化涨跌幅
- 即将披露财报页面：抓取美股部分标的未来财报日期，港/沪深暂为空占位
- 本地 LLM 分析增强：延长超时、增加 fallback generate、清理思维标签
- 全局中英文切换覆盖新页面（涨跌榜 / 即将财报）
- 图表 Brush 逻辑修复与区间标签稳定
- 路由与正则加固，避免 `/stocks/upcoming_earnings` 被动态捕获导致 404/422

计划（路线图摘录）：
- 技术指标 (MA / RSI / MACD / ATR)
- ECharts K 线 + 指标叠加
- LangChain Agent & 工具 + 回测 MCP 工具
- 云端 LLM (LiteLLM: OpenAI / Claude / Gemini)
- 安全存储（API Key 加密）
- 测试与 CI/CD，打包发布

## 2.2 技术栈
| 层 | 技术 |
|----|------|
| 桌面壳 | Tauri 2.x |
| 前端 | React + Vite + TypeScript + TailwindCSS + Zustand |
| 后端 | FastAPI |
| LLM 层 | LangChain(规划) + 自定义 Provider |
| 数据源 | yfinance, AKShare |
| 存储缓存 | SQLite (SQLAlchemy) + 预留 Parquet |

## 2.3 目录结构
同上英文段落，参见结构树。

## 2.4 本地开发前置
| 组件 | 要求 |
|------|------|
| Python | 3.10+ (推荐 3.11) |
| Node.js | 18+ LTS (或 20+) |
| Rust | 最新 stable |
| Ollama (可选) | 本地推理 |
| Git | 版本管理 |

## 2.5 环境变量
后端 (`.env` 根目录)：
```
LLM_MODE=local
LLM_API_KEY=
LLM_LOCAL_MODEL=llama3
DATABASE_URL=sqlite:///./backend/storage/stock_cache.db
OLLAMA_ENDPOINT=http://localhost:11434
```
前端 (`frontend/.env`)：
```
VITE_API_BASE=http://127.0.0.1:8000
```

## 2.6 搭建步骤
1. 克隆仓库：
  ```bash
  git clone https://github.com/<your-org>/stock-mcpilot.git
  cd stock-mcpilot
  ```
2. 创建虚拟环境并安装依赖：
  ```bash
  python3 -m venv .venv
  source .venv/bin/activate
  python -m pip install --upgrade pip
  pip install -r backend/requirements.txt
  ```
3. (可选) 下载本地模型：
  ```bash
  ollama pull llama3
  ```
4. 启动后端：
  ```bash
  uvicorn backend.main:app --reload
  ```
  健康检查：`curl http://127.0.0.1:8000/health`
5. 前端安装与启动：
  ```bash
  cd frontend
  cp .env.example .env
  npm install
  npm run dev
  ```
  打开 http://127.0.0.1:5173
6. (可选) Tauri 桌面开发：
  ```bash
  cd src-tauri
  cargo tauri dev
  ```
7. 构建：
  - 前端：`npm run build`
  - Tauri 生产（后续完善后再执行）：`cargo tauri build`

## 2.7 使用流程
1. 打开前端或桌面窗口
2. 输入代码与市场并查询
3. 若当天为交易日：
  - 开市中：缓存并展示最新盘中价格；
  - 收盘后：用当日收盘价更新/覆盖；
4. 左侧：收盘价趋势图（可调整区间）下方显示“近期资讯”（最多 10 条，可滚动）。
5. 右侧：财报卡片显示近两年 EPS（估值/实际/意外）与下次财报日（如有）。
6. 可输入问题调用 LLM 分析（本地或未来云端）。

## 2.8 缓存说明
- yfinance 数据列标准化为小写
- SQLite 主键 (symbol, market, date)
- 简单缺口填充策略（未来可结合交易日历精准化）
- 盘中与收盘更新：
  - 开市：基于 yfinance fast_info/1m 刷新当日 open/high/low/close/volume；
  - 收盘：以日线数据补全/覆盖当日收盘；
  - 拉取时 end 向后 +1 天以适配 yfinance 右开区间；

### 2.8.1 REST 接口（节选）
- GET `/health`：健康检查
- GET `/stocks/{symbol}`：日线与统计摘要
- GET `/stocks/{symbol}/earnings`：财报日期、EPS 及下一次财报日（尽力）
- GET `/stocks/{symbol}/news`：最多 10 条纯文本新闻（缓存 FIFO）
- GET `/stocks/movers?market=US|HK|CN&type=gainers|losers&count=10`：涨跌榜（规范化涨跌幅）
- GET `/stocks/upcoming_earnings?market=US|HK|CN&days=14&limit=50`：即将财报（当前仅美股实现）
- POST `/analysis`：模型分析（本地 LLM）
- GET `/settings`：获取设置
- POST `/settings`：更新设置

### 2.8.2 资讯缓存与数据源
- 缓存：SQLite `news` 表，主键 (symbol, market, published_at)
- 每次查询写入新项并仅保留最新 10 条
- 数据源：优先 yfinance `Ticker.news`；兜底 Yahoo Finance RSS 源

## 2.9 贡献方式
1. Fork & 建立分支 (feat/xxx)
2. 编写/调整代码与测试
3. 提交 PR，描述变更

## 2.10 路线图（详细）
1. 技术指标 & 摘要增强
2. LangChain 工具 / 回测接口
3. 流式输出 (SSE / WebSocket)
4. 云端 LLM (LiteLLM)
5. K 线 + 指标叠加
6. 密钥安全存储
7. 测试 & CI/CD
8. 跨平台打包分发
9. 策略回测 MCP Server
10. 多标的比较视图

## 2.11 许可证 & 免责声明
MIT (参见 `LICENSE`).

> 再次提示：不构成投资建议，风险自担。

---

欢迎提交 Issue / PR 一起完善 Stock MCPilot。

---

## 3. 更新日志 / Changelog (excerpt)

### 2025-09-16
- Added Movers endpoint & page (strict market filtering, pct normalization)
- Added Upcoming Earnings endpoint & page (US subset forward dates)
- Strengthened routing to prevent dynamic path capture (404 → 200 for upcoming)
- Implemented EN/ZH i18n across new pages
- Hardened local LLM provider (timeouts, fallback, reasoning tag strip)
- Fixed brush slicing bug; added visible range label stability

### 2025-09-10
- Earnings panel refinement & scrolling layout
- News caching with RSS fallback

### 2025-09-05
- Intraday live update logic

### 2025-09-01
- Initial scaffold (price fetch, summary stats, basic analysis, settings)
