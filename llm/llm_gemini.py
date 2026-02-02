import os
import requests
from langchain_google_genai import ChatGoogleGenerativeAI

def check_gemini_available():
    """检查 Gemini API 是否可用"""
    try:
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            return False
        
        proxies = {}
        if os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY"):
            proxy_url = os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY")
            proxies = {"http": proxy_url, "https": proxy_url}
        
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3-flash-preview:generateContent?key={api_key}"
        headers = {"Content-Type": "application/json"}
        data = {"contents": [{"parts": [{"text": "test"}]}]}
        
        response = requests.post(url, headers=headers, json=data, proxies=proxies, timeout=5)
        return response.status_code == 200
    except Exception:
        return False

def get_gemini_llm(temperature=0.3):
    """获取 Gemini LLM 实例"""
    # 确保进程读到代理（从 .env 加载到系统环境变量）
    https_proxy = os.getenv("HTTPS_PROXY")
    http_proxy = os.getenv("HTTP_PROXY")
    
    if https_proxy:
        os.environ["HTTPS_PROXY"] = https_proxy
    if http_proxy:
        os.environ["HTTP_PROXY"] = http_proxy
        
    return ChatGoogleGenerativeAI(
        model=os.getenv("LLM_MODEL", "gemini-3-flash-preview"),
        google_api_key=os.getenv("GOOGLE_API_KEY"),
        temperature=float(temperature),
        transport="rest"
    )

def parse_gemini_response(content):
    """解析 Gemini 特有的列表/对象格式返回值"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts = []
        for item in content:
            if isinstance(item, dict) and 'text' in item:
                texts.append(item['text'])
            else:
                texts.append(str(item))
        return ''.join(texts)
    return str(content)
