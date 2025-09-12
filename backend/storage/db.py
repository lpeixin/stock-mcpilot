from sqlalchemy import create_engine, MetaData, Table, Column, String, Date, Float, Integer, select, Text, DateTime, func, and_
import os

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./backend/storage/stock_cache.db")
engine = create_engine(DATABASE_URL, future=True)
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

news = Table(
    "news",
    metadata,
    Column("symbol", String, primary_key=True),
    Column("market", String, primary_key=True),
    Column("published_at", DateTime, primary_key=True),
    Column("text", Text, nullable=False),
)

metadata.create_all(engine)

def upsert_prices(rows):
    if not rows:
        return
    with engine.begin() as conn:
        for r in rows:
            conn.execute(prices.delete().where(
                (prices.c.symbol==r['symbol']) &
                (prices.c.market==r['market']) &
                (prices.c.date==r['date'])
            ))
            conn.execute(prices.insert().values(**r))

def load_prices(symbol: str, market: str, start, end):
    with engine.begin() as conn:
        stmt = select(prices).where(
            (prices.c.symbol==symbol) &
            (prices.c.market==market) &
            (prices.c.date>=start) &
            (prices.c.date<=end)
        )
        rows = conn.execute(stmt).fetchall()
        return [dict(r._mapping) for r in rows]

def add_news_items(symbol: str, market: str, items: list[dict]):
    if not items:
        return
    with engine.begin() as conn:
        # insert or ignore duplicates on primary key
        for it in items:
            try:
                conn.execute(news.insert().values(symbol=symbol, market=market, published_at=it['published_at'], text=it['text']))
            except Exception:
                # duplicate -> ignore
                pass
        # keep only latest 10 by published_at
        stmt = select(news.c.published_at).where((news.c.symbol==symbol) & (news.c.market==market)).order_by(news.c.published_at.desc())
        all_ts = [r[0] for r in conn.execute(stmt).fetchall()]
        if len(all_ts) > 10:
            cutoff = all_ts[10-1]  # keep index 0..9
            conn.execute(news.delete().where((news.c.symbol==symbol) & (news.c.market==market) & (news.c.published_at < cutoff)))

def load_news(symbol: str, market: str) -> list[dict]:
    with engine.begin() as conn:
        stmt = select(news).where((news.c.symbol==symbol) & (news.c.market==market)).order_by(news.c.published_at.desc()).limit(10)
        rows = conn.execute(stmt).fetchall()
        return [dict(r._mapping) for r in rows]
