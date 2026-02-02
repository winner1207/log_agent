import os
from langchain_openai import ChatOpenAI

def get_deepseek_llm(temperature=0.3):
    """获取 DeepSeek LLM 实例"""
    return ChatOpenAI(
        model="deepseek-chat",
        openai_api_key=os.getenv("DEEPSEEK_API_KEY"),
        openai_api_base=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        temperature=float(temperature)
    )

def parse_deepseek_response(content):
    """解析 DeepSeek 返回值（通常直接是字符串）"""
    return str(content) if content else ""
