# Stock MCPilot 中文说明

English | **中文说明**

> 免责声明：所有输出仅用于学习 / 研究，不构成投资建议。

## 1. 概述
Stock MCPilot 是一个跨平台 (macOS/Windows，通过 Tauri) 的桌面应用，聚合多市场（美股 / 港股 / A 股）股票数据，并借助本地或未来云端 LLM 生成结构化统计摘要与探索性分析结果。数据以本地 SQLite 缓存减少重复请求。当前仍在快速迭代。

## 2. 已有核心功能
1. 多市场（US / HK / CN）单标的日线数据查询与本地缓存
2. 盘中实时更新策略：交易时段使用最新价格，收盘后用官方收盘覆盖
3. 自适应收盘价折线图：动态刻度密度 + Brush 可视区拖拽 + 当前可见区标签
4. 财报面板：历史 EPS Actual / Estimate / Surprise (+%) 及下一次财报日期（多策略解析）
5. 近期资讯面板：最多 10 条纯文本新闻，滚动显示；yfinance 优先 + RSS 兜底；本地 FIFO 缓存
6. 涨跌榜页面：按市场获取涨幅 / 跌幅榜；严格过滤跨市场代码；重算或校正涨跌幅百分比
7. 即将财报页面：美股部分代表性标的未来财报日期（HK/CN 预留空实现）
8. 本地 LLM 分析（Ollama）：延长超时 + Fallback /generate + 去除思维标签
9. 全局双语 i18n（EN/中文）切换支持新页面
10. 设置页面：模式 / API Key（占位）/ 本地模型名称
11. 后端防御式设计：超时、回退、空结果不报错

### 近期新增（2025‑09）
- 新增 `/stocks/movers`、`/stocks/upcoming_earnings` 接口与对应前端页面
- 修复路由匹配顺序与正则，避免 upcoming 被动态 symbol 捕获导致 404/422
- Brush 逻辑修复（之前因数据切片导致缩放异常）
- LLM provider 添加超时、回退与输出清理

## 3. 技术栈
| 层 | 技术 |
|----|------|
| 桌面壳 | Tauri 2.x |
| 前端 | React + Vite + TypeScript + TailwindCSS + Zustand |
| 图表 | Recharts（后续可扩展 ECharts K 线） |
| 后端 | FastAPI |
| LLM | 本地 Ollama，未来接入 LiteLLM / LangChain |
| 数据源 | yfinance（当前主）、AKShare（规划） |
| 存储 | SQLite (SQLAlchemy) |

## 4. 目录结构（简化）
```
frontend/   # 前端代码 (React/Vite)
backend/    # FastAPI 后端 & 提供 LLM/数据接口
src-tauri/  # Tauri 配置与 Rust 入口
```

## 5. 本地开发准备
| 组件 | 要求 |
|------|------|
| Python | 3.10+ (推荐 3.11) |
| Node.js | 18+ 或 20+ |
| Rust | 最新 stable |
| Ollama | 本地模型推理（可选） |

## 6. 环境变量
后端 `.env`：
```
LLM_MODE=local
LLM_API_KEY=
LLM_LOCAL_MODEL=llama3
DATABASE_URL=sqlite:///./backend/storage/stock_cache.db
OLLAMA_ENDPOINT=http://localhost:11434
```
前端 `frontend/.env`：
```
VITE_API_BASE=http://127.0.0.1:8000
```

## 7. 启动步骤
```bash
# 克隆
git clone https://github.com/<your-org>/stock-mcpilot.git
cd stock-mcpilot

# Python 依赖
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt

# (可选) 拉取本地模型
docker pull ollama/ollama # 若尚未安装 Ollama
ollama pull llama3

# 启动后端
uvicorn backend.main:app --reload
# 健康检查
curl http://127.0.0.1:8000/health

# 前端
cd frontend
npm install
npm run dev
# 打开 http://127.0.0.1:5173
```
可选 Tauri：`cargo tauri dev`

## 8. 使用流程
1. 选择市场与输入股票代码
2. 查看左侧折线图（可调区间）与下方新闻
3. 右侧财报面板查看历史 EPS / 下一财报日
4. 可切换语言，或在“设置”中配置本地模型名称
5. 在问题输入框中提交分析请求（本地 LLM）

## 9. 主要接口（节选）
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 健康检查 |
| GET | `/stocks/{symbol}` | 日线+统计摘要 |
| GET | `/stocks/{symbol}/earnings` | 财报事件与下一财报日 |
| GET | `/stocks/{symbol}/news` | 最近最多 10 条新闻 |
| GET | `/stocks/movers` | 涨跌榜 (market,type,count) |
| GET | `/stocks/upcoming_earnings` | 即将财报 (US 实现) |
| POST | `/analysis` | 模型分析 |
| GET/POST | `/settings` | 获取 / 保存设置 |

## 10. 缓存策略简述
- 价格：按 (symbol, market, date) 主键存 SQLite
- 盘中：开市时多次覆盖当日行；收盘后以官方收盘修正
- 新闻：每次合并新数据后仅保留最新 10 条
- 未来：可考虑加入失效 TTL、Parquet 压缩或内存层

## 11. 路线图（部分）
- 技术指标 & 指标叠加 K 线
- 多标的对比 & 筛选
- LangChain 工具 & 回测模块
- 云端 LLM 聚合 (LiteLLM / OpenAI / Claude / Gemini)
- 安全存储（系统钥匙串）
- WebSocket / SSE 流式输出
- CI/CD + 自动测试
- 跨平台安装包发布

## 12. 更新日志（摘要）
### 2025-09-16
- 新增涨跌榜 & 即将财报接口/页面
- 路由顺序与正则修复避免 404/422
- LLM Provider 增强（超时 + fallback + 清理）
- Brush 数据切片问题修复
- 添加可见区间标签

### 2025-09-10
- 财报卡片滚动与布局优化
- 新闻缓存 + RSS 兜底

### 2025-09-05
- 盘中更新策略实现

### 2025-09-01
- 初始脚手架（行情 / 统计摘要 / 基本分析 / 设置）

## 13. 贡献
欢迎提交 Issue 或 PR。分支命名建议：`feat/<模块>` / `fix/<问题>`。

## 14. 许可证
MIT（参见 `LICENSE`）。

> 再次提示：不构成投资建议，风险自担。

---

欢迎共同改进 Stock MCPilot。
