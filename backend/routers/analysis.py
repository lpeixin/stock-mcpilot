from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from ..routers.stocks import get_stock_daily
from ..providers.base import get_provider

class AnalysisRequest(BaseModel):
    symbol: str
    market: str = "US"
    question: str | None = None
    days: int = 60
    language: str | None = None  # 'en' or 'zh'

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
    lang = req.language or provider.__class__.__name__  # fallback later replaced
    # Determine language fallback from settings_state if not provided
    from ..providers.base import settings_state
    if lang not in ('en', 'zh'):
        lang = settings_state.get('language', 'en')
    summary_dict = daily.summary.model_dump()
    if lang == 'zh':
        prompt = (f"你是资深股票分析助手。以下是 {req.symbol} 最近的统计摘要: {summary_dict}\n" )
        if req.question:
            prompt += f"用户问题: {req.question}\n"
        prompt += "请基于统计摘要用中文输出结构化的分析: 1) 概览 2) 短期动量 3) 波动与风险 4) 机会与关注点 5) 结论与免责声明。避免绝对化措辞。"
    else:
        prompt = (f"You are a senior equities analysis assistant. Here is the recent statistical summary for {req.symbol}: {summary_dict}\n" )
        if req.question:
            prompt += f"User question: {req.question}\n"
        prompt += "Provide a concise, structured English analysis: 1) Overview 2) Short-term Momentum 3) Volatility & Risk 4) Opportunities & Watchpoints 5) Conclusion & Disclaimer. Avoid overconfident language."
    try:
        analysis_text = provider.generate(prompt)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return AnalysisResponse(symbol=daily.symbol, market=daily.market, summary=summary_dict, analysis=analysis_text)
