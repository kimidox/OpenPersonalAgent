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


def _parse_search_args(argv: list) -> tuple:
    """
    智能解析命令行参数，兼容带空格的关键词。
    支持两种调用方式：
    1. python do_search.py search "关键词 带空格" 8
    2. python do_search.py search 关键词 带空格 8  （当引号被 shell 吞掉时）
    
    策略：action 之后，最后一个纯数字参数作为 max_results，
    其余全部拼接为 query。
    """
    if len(argv) <= 2:
        return "", 5
    
    # 去掉 action（argv[1]），剩余参数
    rest = argv[2:]
    
    # 尝试将最后一个参数解析为数字（max_results）
    max_results = 5
    if rest and rest[-1].isdigit():
        try:
            max_results = int(rest[-1])
            rest = rest[:-1]
        except ValueError:
            pass
    
    # 剩余部分拼接为 query
    query = " ".join(rest) if rest else ""
    return query, max_results


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else ""

    if action == "search":
        query, max_results = _parse_search_args(sys.argv)
        result = search_save(query, max_results)
    elif action == "list":
        result = search_list()
    else:
        result = {"error": "请指定操作: search(搜索并缓存) 或 list(查看会话列表)\n示例: python scripts/do_search.py search 关键词 5"}

    print(json.dumps(result, ensure_ascii=False, indent=2))
