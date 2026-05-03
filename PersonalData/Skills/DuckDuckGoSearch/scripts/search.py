import sys
import json

from ddgs import DDGS


def text_search(query: str, max_results: int = 5) -> list:
    results = []
    with DDGS() as ddgs:
        for r in ddgs.text(query, max_results=max_results):
            results.append({
                "title": r.get("title", ""),
                "href": r.get("href", ""),
                "body": r.get("body", ""),
            })
    return results


def news_search(query: str, max_results: int = 5) -> list:
    results = []
    with DDGS() as ddgs:
        for r in ddgs.news(query, max_results=max_results):
            results.append({
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "body": r.get("body", ""),
                "source": r.get("source", ""),
                "date": r.get("date", ""),
            })
    return results


def images_search(query: str, max_results: int = 5) -> list:
    results = []
    with DDGS() as ddgs:
        for r in ddgs.images(query, max_results=max_results):
            results.append({
                "title": r.get("title", ""),
                "image": r.get("image", ""),
                "thumbnail": r.get("thumbnail", ""),
                "url": r.get("url", ""),
                "source": r.get("source", ""),
            })
    return results


def search(query: str, search_type: str = "text", max_results: int = 5) -> dict:
    if not query:
        return {"error": "搜索关键词不能为空"}

    max_results = min(max(1, max_results), 20)

    try:
        if search_type == "text":
            results = text_search(query, max_results)
        elif search_type == "news":
            results = news_search(query, max_results)
        elif search_type == "images":
            results = images_search(query, max_results)
        else:
            return {"error": f"不支持的搜索类型: {search_type}，可选值: text, news, images"}

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

    result = search(query, search_type, max_results)
    print(json.dumps(result, ensure_ascii=False, indent=2))
