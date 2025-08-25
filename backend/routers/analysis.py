from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from ..routers.stocks import get_stock_daily
from ..providers.base import get_provider

class AnalysisRequest(BaseModel):
    symbol: str
    market: str = "US"
    question: str | None = None
    days: int = 60

class AnalysisResponse(BaseModel):
    symbol: str
    market: str
    summary: dict
    analysis: str

router = APIRouter()

@router.post("/", response_model=AnalysisResponse)
def analyze(req: AnalysisRequest):
    daily = get_stock_daily(req.symbol, req.market, req.days)
    provider = get_provider()
    prompt = f"你是资深股票分析助手。以下是{req.symbol} 最近的统计摘要: {daily.summary.model_dump()}\n"
    if req.question:
        prompt += f"用户问题: {req.question}\n"
    prompt += "请基于统计摘要给出简洁的风险与机会分析（不构成投资建议）。"
    try:
        analysis_text = provider.generate(prompt)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return AnalysisResponse(symbol=daily.symbol, market=daily.market, summary=daily.summary.model_dump(), analysis=analysis_text)
