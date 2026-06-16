import sys
import json
import os
import uuid
import time
import subprocess

# 确保标准输出使用 UTF-8 编码
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')


def _ensure_package(package_name: str, import_name: str = None):
    """检查并自动安装缺失的 Python 包"""
    if import_name is None:
        import_name = package_name
    try:
        __import__(import_name)
        return True
    except ImportError:
        pass
    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", package_name, "-q"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return __import__(import_name)
    except Exception:
        return False


# 确保依赖已安装
if not _ensure_package("baidusearch", "baidusearch.baidusearch"):
    print(json.dumps({"error": "无法安装 baidusearch 库，请手动运行: pip install baidusearch"}, ensure_ascii=False))
    sys.exit(1)

from baidusearch.baidusearch import search as baidu_search


SESSION_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "search_sessions.json")
SESSION_TIMEOUT = 30 * 60  # 30 minutes


def _load_sessions() -> dict:
    """加载会话缓存文件"""
    if os.path.exists(SESSION_FILE):
        try:
            with open(SESSION_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def _save_sessions(sessions: dict):
    """保存会话缓存文件"""
    try:
        with open(SESSION_FILE, "w", encoding="utf-8") as f:
            json.dump(sessions, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _clean_expired_sessions(sessions: dict) -> dict:
    """清理过期会话"""
    now = time.time()
    return {
        sid: data for sid, data in sessions.items()
        if (now - data.get("created_at", 0)) < SESSION_TIMEOUT
    }


def do_search(query: str, max_results: int = 5) -> list:
    """执行百度搜索，返回摘要列表"""
    results = []
    search_results = baidu_search(query, num_results=max_results)

    for r in search_results:
        result = {
            "title": r.get("title", ""),
            "href": r.get("url", ""),
            "body": r.get("desp", ""),
        }
        results.append(result)
    return results


def search_save(query: str, max_results: int = 5) -> dict:
    """执行搜索，缓存结果并返回 session_id"""
    if not query:
        return {"error": "搜索关键词不能为空"}

    max_results = min(max(1, max_results), 20)

    try:
        results = do_search(query, max_results)

        session_id = str(uuid.uuid4())
        sessions = _load_sessions()
        sessions = _clean_expired_sessions(sessions)

        sessions[session_id] = {
            "query": query,
            "total_results": len(results),
            "results": results,
            "created_at": time.time(),
        }
        _save_sessions(sessions)

        return {
            "session_id": session_id,
            "query": query,
            "total_results": len(results),
            "results": results,
            "expires_in": "30分钟",
        }
    except Exception as e:
        return {"error": f"搜索失败: {str(e)}"}


def search_list() -> dict:
    """列出所有有效会话"""
    sessions = _load_sessions()
    sessions = _clean_expired_sessions(sessions)
    _save_sessions(sessions)

    result = {}
    for sid, data in sessions.items():
        result[sid] = {
            "query": data.get("query", ""),
            "total_results": data.get("total_results", 0),
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(data.get("created_at", 0))),
        }
    return {"sessions": result}


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else ""

    if action == "search":
        query = sys.argv[2] if len(sys.argv) > 2 else ""
        max_results = int(sys.argv[3]) if len(sys.argv) > 3 else 5
        result = search_save(query, max_results)
    elif action == "list":
        result = search_list()
    else:
        result = {"error": "请指定操作: search(搜索并缓存) 或 list(查看会话列表)\n示例: python scripts/do_search.py search 关键词 5"}

    print(json.dumps(result, ensure_ascii=False, indent=2))
