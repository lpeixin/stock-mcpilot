# Placeholder for LangChain agent integration.
from langchain.schema import Document

def build_analysis_docs(summary: dict) -> list[Document]:
    return [Document(page_content=str(summary), metadata={"type": "stock_summary"})]
