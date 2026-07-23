import sys
import json
import os
import time
import random
import subprocess
import re
from urllib.parse import urlparse

# 多 User-Agent 轮换，降低被反爬检测概率
_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
]


def _random_ua():
    return random.choice(_USER_AGENTS)

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
if not _ensure_package("requests"):
    print(json.dumps({"error": "无法安装 requests 库，请手动运行: pip install requests"}, ensure_ascii=False))
    sys.exit(1)

import requests

# 尝试安装 httpx（更好地处理现代 TLS 和 HTTP/2，减少 403）
HAS_HTTPX = _ensure_package("httpx", "httpx")
if HAS_HTTPX:
    import httpx

# 尝试安装 trafilatura（专业正文提取，自带反爬处理）
HAS_TRAFILATURA = _ensure_package("trafilatura", "trafilatura")
if HAS_TRAFILATURA:
    import trafilatura

# 可选导入 chardet，用于网页编码检测
try:
    import chardet
    HAS_CHARDET = True
except ImportError:
    HAS_CHARDET = False

# 可选导入 beautifulsoup4，用于 HTML 正文解析
try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False



SESSION_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "search_sessions.json")
SESSION_TIMEOUT = 30 * 60  # 30 minutes


def _load_sessions() -> dict:
    if os.path.exists(SESSION_FILE):
        try:
            with open(SESSION_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def _save_sessions(sessions: dict):
    try:
        with open(SESSION_FILE, "w", encoding="utf-8") as f:
            json.dump(sessions, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _clean_expired_sessions(sessions: dict) -> dict:
    now = time.time()
    return {
        sid: data for sid, data in sessions.items()
        if (now - data.get("created_at", 0)) < SESSION_TIMEOUT
    }


def fetch_page_content(url: str, timeout: int = 15) -> str:
    """获取网页内容，自动跟随百度跳转链接，多策略绕过403"""
    try:
        # 如果是百度跳转链接，跟随重定向获取真实 URL
        if "baidu.com/link" in url:
            url = _resolve_baidu_redirect(url)

        if not url or not url.startswith("http"):
            return "[无效链接]"

        # 第一策略：trafilatura（专业正文提取，自带反爬处理）
        if HAS_TRAFILATURA:
            try:
                content = _fetch_with_trafilatura(url, timeout)
                if content and content not in ("[页面内容为空]", ""):
                    return content
            except Exception:
                pass

        # 第二策略：直接访问原始页面（重试2次，轮换UA）
        for attempt in range(2):
            try:
                content = _fetch_with_headers(url, timeout)
                if content and content not in ("[页面内容为空]", ""):
                    return content
                time.sleep(0.5)
            except Exception:
                if attempt == 0:
                    time.sleep(1)

        # 第三策略：使用 httpx（HTTP/2 + 现代 TLS，能绕过部分403）
        if HAS_HTTPX:
            try:
                content = _fetch_with_httpx(url, timeout)
                if content and content not in ("[页面内容为空]", ""):
                    return content
            except Exception:
                pass

        return "[无法获取内容: 网站拒绝访问，建议尝试其他链接或换关键词重新搜索]"
    except Exception as e:
        return f"[无法获取内容: {str(e)}]"


def _resolve_baidu_redirect(url: str) -> str:
    """跟随百度重定向获取真实URL"""
    try:
        head_resp = requests.head(
            url,
            headers={"User-Agent": _random_ua()},
            timeout=5,
            allow_redirects=True,
        )
        real_url = head_resp.url
        if real_url and real_url != url:
            return real_url
    except Exception:
        pass
    return url


def _fetch_with_headers(url: str, timeout: int) -> str:
    """使用完整浏览器请求头获取页面内容"""
    ua = _random_ua()
    parsed = urlparse(url)
    origin = f"{parsed.scheme}://{parsed.netloc}"

    headers = {
        "User-Agent": ua,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',
        "Referer": origin,
        "Cache-Control": "max-age=0",
    }
    response = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
    response.raise_for_status()

    content_type = response.headers.get("Content-Type", "")
    if "text/html" not in content_type.lower():
        return ""

    # 编码检测
    if not response.encoding or response.encoding.lower() in ("iso-8859-1", "latin-1"):
        if HAS_CHARDET:
            detected = chardet.detect(response.content)
            if detected and detected.get("encoding"):
                response.encoding = detected["encoding"]
        else:
            meta_match = re.search(r'<meta[^>]*charset=["\']?([^"\'>\s]+)', response.text[:1000], re.IGNORECASE)
            if meta_match:
                response.encoding = meta_match.group(1)
            else:
                response.encoding = 'utf-8'

    html = response.text
    if HAS_BS4:
        return _extract_content_bs4(html)
    else:
        return _extract_content_regex(html)


def _get_baidu_cache_url(url: str) -> str:
    """获取百度快照链接"""
    return ""


def _fetch_with_trafilatura(url: str, timeout: int) -> str:
    """使用 trafilatura 获取页面（专业正文提取，自带反爬处理）"""
    if not HAS_TRAFILATURA:
        return ""

    try:
        downloaded = trafilatura.fetch_url(url, timeout=timeout)
        if not downloaded:
            return ""

        content = trafilatura.extract(
            downloaded,
            include_comments=False,
            include_tables=True,
            include_links=False,
            include_images=False,
            favor_precision=True,
        )

        if content:
            return _clean_text(content)
        return ""
    except Exception:
        return ""


def _fetch_with_httpx(url: str, timeout: int) -> str:
    """使用 httpx 获取页面（HTTP/2 + 现代 TLS，能绕过部分403）"""
    if not HAS_HTTPX:
        return ""

    ua = _random_ua()
    parsed = urlparse(url)
    origin = f"{parsed.scheme}://{parsed.netloc}"

    headers = {
        "User-Agent": ua,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',
        "Referer": origin,
    }

    client = httpx.Client(
        http2=True,
        timeout=timeout,
        follow_redirects=True,
        verify=True,
    )

    try:
        response = client.get(url, headers=headers)
        response.raise_for_status()

        content_type = response.headers.get("Content-Type", "")
        if "text/html" not in content_type.lower():
            return ""

        html = response.text
        if HAS_BS4:
            return _extract_content_bs4(html)
        else:
            return _extract_content_regex(html)
    finally:
        client.close()


def _extract_content_bs4(html: str) -> str:
    """使用 BeautifulSoup 提取正文内容"""
    try:
        soup = BeautifulSoup(html, "lxml")

        # 移除 script, style, noscript, iframe, svg
        for tag in soup.find_all(["script", "style", "noscript", "iframe", "svg"]):
            tag.decompose()

        # 尝试按优先级提取主要内容区域
        content = None

        # 1. 按常见文章 class/id 匹配
        for pattern in ["article", "post-content", "entry-content", "rich_text", "markdown-body", "content-detail", "article-content", "post", "article-body", "main-content", "article_body", "text-content"]:
            content = soup.find(class_=re.compile(pattern, re.IGNORECASE))
            if content:
                break
            content = soup.find(id=re.compile(pattern, re.IGNORECASE))
            if content:
                break

        # 2. 尝试 <article> 或 <main> 标签
        if not content:
            content = soup.find("article") or soup.find("main")

        # 3. 尝试常见的内容容器 div（CSDN、知乎、博客园等）
        if not content:
            for selector in [
                "div#content-body",
                "div.article-detail",
                "div.postBody",
                "div.blogpost-body",
                "div.ztext",
                "div.detail-content",
                "div.text-show",
                "div.content_main",
                "div.article_content",
                "div.topic-content",
                "div.question",
                "div.ql-editor",
                "div.BlogContent",
                "div.PostContent",
            ]:
                content = soup.select_one(selector)
                if content:
                    break

        # 4. 使用段落密度法找正文
        if not content:
            max_p_count = 0
            best_div = None
            for div in soup.find_all("div"):
                # 统计文本块数量
                text_elements = div.find_all(["p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "td", "blockquote", "pre", "span"])
                p_count = len(text_elements)
                text_len = len(div.get_text(strip=True))
                # 要求至少有 5 个文本元素，且文本长度超过 200 字
                if p_count > max_p_count and text_len > 200:
                    max_p_count = p_count
                    best_div = div
            if best_div and max_p_count > 3:
                content = best_div

        # 5. fallback: 使用 body 内容，但移除导航/页脚等
        if not content:
            body = soup.find("body")
            if body:
                for tag in body.find_all(["nav", "footer", "header", "aside", "sidebar"]):
                    tag.decompose()
                content = body

        if content:
            # 移除广告、侧边栏、评论区、相关推荐等
            for tag in content.find_all(attrs={"class": re.compile(r"(?:ad|advert|banner|sponsor|sidebar|comment|related|recommend|pagination|page-nav|toc|share|like|follow|subscribe|cookie)", re.IGNORECASE)}):
                tag.decompose()

            # 保留 <a> 标签的文本和链接
            text = content.get_text(separator="\n", strip=True)
            return _clean_text(text)

        return "[页面内容为空]"
    except Exception as e:
        return _extract_content_regex(html)


def _extract_content_regex(html: str) -> str:
    """使用正则表达式提取正文内容（fallback）"""
    try:
        html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r'<!--.*?-->', '', html, flags=re.DOTALL)
        html = re.sub(r'<nav[^>]*>.*?</nav>', '', html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r'<footer[^>]*>.*?</footer>', '', html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r'<header[^>]*>.*?</header>', '', html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r'<aside[^>]*>.*?</aside>', '', html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r'<noscript>.*?</noscript>', '', html, flags=re.DOTALL | re.IGNORECASE)

        # 尝试提取主要内容
        main_match = re.search(r'<(?:article|main|div)[^>]*(?:class|id)="[^"]*(?:article|content|main-content|post-content|entry-content|rich_text|markdown-body)[^"]*"[^>]*>(.*?)</(?:article|main|div)>', html, flags=re.DOTALL | re.IGNORECASE)
        if main_match:
            html = main_match.group(1)

        text = re.sub(r'<[^>]+>', '\n', html)
        text = re.sub(r'\n{3,}', '\n\n', text)
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        text = '\n'.join(lines)

        return _clean_text(text)
    except Exception as e:
        return f"[无法获取内容: {str(e)}]"


def _clean_text(text: str) -> str:
    """清理文本，移除无意义内容"""
    lines = [line.strip() for line in text.split('\n') if line.strip()]
    text = '\n'.join(lines)
    text = re.sub(r'^(?:Menu|Skip to content|Navigation|Home|菜单|导航|返回顶部|关闭|登录|注册).*?(\n|$)', '', text, flags=re.IGNORECASE)

    max_length = 15000
    if len(text) > max_length:
        text = text[:max_length] + "..."

    return text if text else "[页面内容为空]"


def fetch_by_session(session_id: str, result_index: int) -> dict:
    """根据 session_id 和索引获取网页详情"""
    sessions = _load_sessions()
    sessions = _clean_expired_sessions(sessions)
    _save_sessions(sessions)

    if session_id not in sessions:
        return {"error": "会话已过期或不存在，请先执行搜索创建会话"}

    session = sessions[session_id]
    results = session.get("results", [])

    if result_index < 0 or result_index >= len(results):
        return {
            "error": f"索引越界: 有效范围为 0-{len(results) - 1}",
            "total_results": len(results),
        }

    target = results[result_index]

    if not target.get("href"):
        return {
            "session_id": session_id,
            "result_index": result_index,
            "total_results": len(results),
            "result": {
                "title": target.get("title", ""),
                "href": "",
                "body": target.get("body", ""),
                "full_content": "[无有效链接]",
            },
        }

    full_content = fetch_page_content(target["href"])

    # 缓存已获取的内容
    results[result_index]["full_content"] = full_content
    sessions[session_id]["results"] = results
    _save_sessions(sessions)

    return {
        "session_id": session_id,
        "result_index": result_index,
        "total_results": len(results),
        "result": {
            "title": target.get("title", ""),
            "href": target.get("href", ""),
            "body": target.get("body", ""),
            "full_content": full_content,
        },
    }


def fetch_next(session_id: str) -> dict:
    """自动获取下一个未获取详情的结果"""
    sessions = _load_sessions()
    sessions = _clean_expired_sessions(sessions)
    _save_sessions(sessions)

    if session_id not in sessions:
        return {"error": "会话已过期或不存在，请先执行搜索创建会话"}

    session = sessions[session_id]
    results = session.get("results", [])

    if not results:
        return {"error": "搜索结果为空"}

    # 查找第一个没有 full_content 的结果
    next_index = None
    for i, r in enumerate(results):
        if "full_content" not in r or not r["full_content"]:
            next_index = i
            break

    if next_index is None:
        return {
            "session_id": session_id,
            "status": "completed",
            "message": "所有结果已获取完毕",
            "total_results": len(results),
        }

    target = results[next_index]

    if not target.get("href"):
        full_content = "[无有效链接]"
    else:
        full_content = fetch_page_content(target["href"])

    # 缓存
    results[next_index]["full_content"] = full_content
    sessions[session_id]["results"] = results
    _save_sessions(sessions)

    return {
        "session_id": session_id,
        "result_index": next_index,
        "total_results": len(results),
        "result": {
            "title": target.get("title", ""),
            "href": target.get("href", ""),
            "body": target.get("body", ""),
            "full_content": full_content,
        },
    }


def fetch_by_url(url: str) -> dict:
    """直接根据 URL 获取网页详情（不依赖 session）"""
    if not url:
        return {"error": "请提供有效的 URL"}

    full_content = fetch_page_content(url)

    return {
        "url": url,
        "full_content": full_content,
    }


def _parse_fetch_args(argv: list) -> tuple:
    """
    智能解析 fetch 命令参数，兼容带空格的 URL。
    策略：action 之后，倒数第二个参数作为 session_id，
    最后一个纯数字参数作为 result_index。
    """
    if len(argv) <= 2:
        return "", 0
    
    rest = argv[2:]
    
    if len(rest) >= 2 and rest[-1].lstrip('-').isdigit():
        try:
            result_index = int(rest[-1])
            session_id = " ".join(rest[:-1])
            return session_id, result_index
        except ValueError:
            pass
    
    # fallback
    if len(rest) >= 2:
        try:
            result_index = int(rest[-1])
            session_id = rest[-2]
            return session_id, result_index
        except ValueError:
            pass
    
    session_id = rest[0] if rest else ""
    return session_id, 0


def _parse_url_args(argv: list) -> str:
    """
    智能解析 url 命令参数，兼容带空格的 URL。
    策略：action 之后的所有参数拼接为 URL。
    """
    if len(argv) <= 2:
        return ""
    return " ".join(argv[2:])


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else ""

    if action == "fetch":
        session_id, result_index = _parse_fetch_args(sys.argv)
        result = fetch_by_session(session_id, result_index)
    elif action == "next":
        session_id = sys.argv[2] if len(sys.argv) > 2 else ""
        result = fetch_next(session_id)
    elif action == "url":
        url = _parse_url_args(sys.argv)
        result = fetch_by_url(url)
    else:
        result = {"error": "请指定操作: fetch(按索引获取)、next(自动获取下一个)、url(直接获取指定URL)\n示例: python scripts/fetch_page.py fetch session_id 0"}

    print(json.dumps(result, ensure_ascii=False, indent=2))
