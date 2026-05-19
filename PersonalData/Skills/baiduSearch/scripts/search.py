import sys
import json
import re
import requests
from urllib.parse import urlparse

from baidusearch.baidusearch import search as baidu_search


def fetch_page_content(url: str, timeout: int = 10) -> str:
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
        response = requests.get(url, headers=headers, timeout=timeout)
        response.raise_for_status()
        
        content_type = response.headers.get("Content-Type", "")
        if "text/html" not in content_type.lower():
            return ""
        
        html = response.text
        
        html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r'<!--.*?-->', '', html, flags=re.DOTALL)
        html = re.sub(r'<nav[^>]*>.*?</nav>', '', html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r'<footer[^>]*>.*?</footer>', '', html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r'<header[^>]*>.*?</header>', '', html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r'<aside[^>]*>.*?</aside>', '', html, flags=re.DOTALL | re.IGNORECASE)
        
        text = re.sub(r'<[^>]+>', ' ', html)
        text = re.sub(r'\s+', ' ', text)
        text = text.strip()
        
        max_length = 5000
        if len(text) > max_length:
            text = text[:max_length] + "..."
        
        return text
    except Exception as e:
        return f"[无法获取内容: {str(e)}]"


def text_search(query: str, max_results: int = 5, fetch_content: bool = True) -> list:
    results = []
    search_results = baidu_search(query, num_results=max_results)
    
    for r in search_results:
        result = {
            "title": r.get("title", ""),
            "href": r.get("url", ""),
            "body": r.get("desp", ""),
        }
        if fetch_content and result["href"]:
            result["full_content"] = fetch_page_content(result["href"])
        results.append(result)
    return results


def search(query: str, search_type: str = "text", max_results: int = 5, fetch_content: bool = True) -> dict:
    if not query:
        return {"error": "搜索关键词不能为空"}

    max_results = min(max(1, max_results), 20)

    try:
        results = text_search(query, max_results, fetch_content)

        return {
            "query": query,
            "search_type": search_type,
            "total_results": len(results),
            "results": results
        }
    except Exception as e:
        return {"error": f"搜索失败: {str(e)}"}


if __name__ == "__main__":
    query = sys.argv[1] if len(sys.argv) > 1 else ""
    search_type = sys.argv[2] if len(sys.argv) > 2 else "text"
    max_results = int(sys.argv[3]) if len(sys.argv) > 3 else 5
    fetch_content_arg = sys.argv[4].lower() != "false" if len(sys.argv) > 4 else True

    result = search(query, search_type, max_results, fetch_content_arg)
    print(json.dumps(result, ensure_ascii=False, indent=2))
