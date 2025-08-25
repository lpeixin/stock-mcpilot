from sqlalchemy import create_engine, MetaData, Table, Column, String, Date, Float, Integer, select
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
