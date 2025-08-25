from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .routers import stocks, analysis, settings

app = FastAPI(title="Stock MCPilot API", version="0.1.0")

origins = [
    "http://localhost",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
def health():
    return {"status": "ok"}

app.include_router(stocks.router, prefix="/stocks", tags=["stocks"])
app.include_router(analysis.router, prefix="/analysis", tags=["analysis"])
app.include_router(settings.router, prefix="/settings", tags=["settings"])
