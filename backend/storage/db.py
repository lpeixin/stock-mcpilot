"""SQLite 存储层。

相比改造前的三点变化：

1. **UPSERT 改成单条 SQL**。原实现是"先 DELETE 再 INSERT"，每行两次往返，
   一次批量写入 200 根 K 线要跑 400 条语句。现在用 SQLite 原生的
   ``INSERT ... ON CONFLICT DO UPDATE``，一次搞定。
2. **修掉新闻去重的隐患**。原实现靠 ``try/except`` 吞掉唯一键冲突来去重，
   但 SQLAlchemy 在异常后会让当前事务失效，后续 insert 全部失败——结果是
   一条重复新闻就能让整批写入静默丢失。现在用 ``ON CONFLICT DO NOTHING``。
3. **新闻表重建**。旧 ``news`` 表只有 ``(published_at, text)`` 两个字段，存不下
   原文链接与来源。新表 ``news_items`` 带上 title/url/publisher/summary。
   旧表是纯派生缓存（全部可从网络重新拉取），因此直接重建，不做数据搬运。
"""

from __future__ import annotations

import os

from sqlalchemy import (
    Column,
    Date,
    DateTime,
    Float,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    select,
    text as sql_text,
)
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./backend/storage/stock_cache.db")

engine = create_engine(DATABASE_URL, future=True)

# WAL 让读写可以并发，避免查询时被写入阻塞。
try:
    with engine.begin() as _conn:
        _conn.execute(sql_text("PRAGMA journal_mode=WAL"))
        _conn.execute(sql_text("PRAGMA synchronous=NORMAL"))
        _conn.execute(sql_text("PRAGMA busy_timeout=5000"))
except Exception:  # noqa: BLE001 - 某些环境（如只读挂载）不允许改 pragma
    pass

metadata = MetaData()

prices = Table(
    "prices",
    metadata,
    Column("symbol", String, primary_key=True),
    Column("market", String, primary_key=True),
    Column("date", Date, primary_key=True),
    Column("open", Float),
    Column("high", Float),
    Column("low", Float),
    Column("close", Float),
    Column("volume", Integer),
)

news_items = Table(
    "news_items",
    metadata,
    Column("symbol", String, primary_key=True),
    Column("market", String, primary_key=True),
    Column("published_at", DateTime, primary_key=True),
    Column("title", Text, nullable=False),
    Column("url", Text),
    Column("publisher", String),
    Column("summary", Text),
)

Index("ix_news_symbol_market_time", news_items.c.symbol, news_items.c.market, news_items.c.published_at)


def _migrate() -> None:
    """轻量迁移：旧 ``news`` 表是纯缓存，直接换成结构更完整的 ``news_items``。"""
    with engine.begin() as conn:
        existing = {
            row[0]
            for row in conn.execute(
                sql_text("SELECT name FROM sqlite_master WHERE type='table'")
            ).fetchall()
        }
        if "news" in existing:
            conn.execute(sql_text("DROP TABLE news"))
    metadata.create_all(engine)


_migrate()


# --------------------------------------------------------------------------
# 行情
# --------------------------------------------------------------------------

def upsert_prices(rows: list[dict]) -> None:
    """批量写入/更新日线。空列表直接返回。"""
    if not rows:
        return
    statement = sqlite_insert(prices).values(rows)
    statement = statement.on_conflict_do_update(
        index_elements=[prices.c.symbol, prices.c.market, prices.c.date],
        set_={
            column: statement.excluded[column]
            for column in ("open", "high", "low", "close", "volume")
        },
    )
    with engine.begin() as conn:
        conn.execute(statement)


def load_prices(symbol: str, market: str, start, end) -> list[dict]:
    with engine.begin() as conn:
        statement = (
            select(prices)
            .where(
                (prices.c.symbol == symbol)
                & (prices.c.market == market)
                & (prices.c.date >= start)
                & (prices.c.date <= end)
            )
            .order_by(prices.c.date)
        )
        return [dict(row._mapping) for row in conn.execute(statement).fetchall()]


def latest_price_date(symbol: str, market: str):
    """返回本地缓存里最新一根 K 线的日期，没有则 None。"""
    with engine.begin() as conn:
        statement = (
            select(prices.c.date)
            .where((prices.c.symbol == symbol) & (prices.c.market == market))
            .order_by(prices.c.date.desc())
            .limit(1)
        )
        row = conn.execute(statement).fetchone()
        return row[0] if row else None


def earliest_price_date(symbol: str, market: str):
    with engine.begin() as conn:
        statement = (
            select(prices.c.date)
            .where((prices.c.symbol == symbol) & (prices.c.market == market))
            .order_by(prices.c.date.asc())
            .limit(1)
        )
        row = conn.execute(statement).fetchone()
        return row[0] if row else None


def count_prices(symbol: str, market: str) -> int:
    with engine.begin() as conn:
        statement = select(sql_text("COUNT(*)")).select_from(prices).where(
            (prices.c.symbol == symbol) & (prices.c.market == market)
        )
        return int(conn.execute(statement).scalar() or 0)


# --------------------------------------------------------------------------
# 新闻
# --------------------------------------------------------------------------

def add_news_items(symbol: str, market: str, items: list[dict], keep: int = 30) -> None:
    """写入新闻并只保留最新 ``keep`` 条。

    重复项用 ``ON CONFLICT DO NOTHING`` 跳过，不再依赖异常吞没（那会让整个事务失效）。
    """
    if not items:
        return
    rows: list[dict] = []
    for item in items:
        published = item.get("published_at")
        title = item.get("title") or item.get("text")
        if not published or not title:
            continue
        rows.append(
            {
                "symbol": symbol,
                "market": market,
                "published_at": published,
                "title": title,
                "url": item.get("url"),
                "publisher": item.get("publisher"),
                "summary": item.get("summary"),
            }
        )
    if not rows:
        return

    statement = sqlite_insert(news_items).values(rows).on_conflict_do_nothing(
        index_elements=[
            news_items.c.symbol,
            news_items.c.market,
            news_items.c.published_at,
        ]
    )
    with engine.begin() as conn:
        conn.execute(statement)

        # 只保留最新 keep 条
        statement = (
            select(news_items.c.published_at)
            .where((news_items.c.symbol == symbol) & (news_items.c.market == market))
            .order_by(news_items.c.published_at.desc())
            .offset(keep)
            .limit(1)
        )
        cutoff = conn.execute(statement).fetchone()
        if cutoff:
            conn.execute(
                news_items.delete().where(
                    (news_items.c.symbol == symbol)
                    & (news_items.c.market == market)
                    & (news_items.c.published_at <= cutoff[0])
                )
            )


def load_news(symbol: str, market: str, limit: int = 10) -> list[dict]:
    with engine.begin() as conn:
        statement = (
            select(news_items)
            .where((news_items.c.symbol == symbol) & (news_items.c.market == market))
            .order_by(news_items.c.published_at.desc())
            .limit(limit)
        )
        return [dict(row._mapping) for row in conn.execute(statement).fetchall()]
