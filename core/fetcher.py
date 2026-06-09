import os
import re
import subprocess
import time
import hashlib
from datetime import date
from pathlib import Path
from typing import Iterable, List, Optional
from urllib.parse import urlencode

import urllib.request

from .body_fetch import extract_links, fetch_body, html_to_text
from .models import Item


try:
    import requests
except ImportError:  # pragma: no cover - fallback for minimal environments
    requests = None


PROJECT_DIR = Path(__file__).resolve().parents[1]
CACHE_DIR = str(PROJECT_DIR / "cache" / "fetcher")
SMART_FETCH_DIR = os.path.expanduser("~/.hermes/skills/productivity/smart-web-fetch/scripts")
SCRAPLING_SCRIPT = os.path.join(SMART_FETCH_DIR, "fetch_scrapling.py")
CACHE_TTL_TEXT = 7200
CACHE_TTL_TITLE = 86400
CACHE_TTL_RAW = 600


class _DiskCache:
    def __init__(self, directory: str):
        os.makedirs(directory, exist_ok=True)
        self.dir = directory

    def _key(self, url: str, suffix: str = "") -> str:
        h = hashlib.sha256(url.encode()).hexdigest()[:16]
        return os.path.join(self.dir, f"{h}{suffix}")

    def get(self, url: str, suffix: str = "", ttl: int = CACHE_TTL_TEXT) -> Optional[str]:
        if ttl == 0:
            return None
        path = self._key(url, suffix)
        if not os.path.exists(path):
            return None
        age = time.time() - os.path.getmtime(path)
        if ttl > 0 and age > ttl:
            try:
                os.remove(path)
            except OSError:
                pass
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except OSError:
            return None

    def set(self, url: str, content: str, suffix: str = ""):
        path = self._key(url, suffix)
        try:
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(content)
            os.replace(tmp, path)
        except OSError:
            pass

    def clear(self):
        for name in os.listdir(self.dir):
            try:
                os.remove(os.path.join(self.dir, name))
            except OSError:
                pass


def _backend_requests(url: str, timeout: int = 10) -> Optional[str]:
    if requests is None:
        return None
    try:
        r = requests.get(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept-Language": "zh-CN,zh;q=0.9",
            },
            timeout=timeout,
        )
        r.encoding = "utf-8"
        if r.status_code == 200 and len(r.text) > 200:
            return r.text
    except requests.RequestException:
        return None
    return None


def _backend_urllib(url: str, timeout: int = 10) -> Optional[str]:
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 bidding-monitor/1.0",
                "Accept-Language": "zh-CN,zh;q=0.9",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            ctype = resp.headers.get("content-type", "")
        encoding = "utf-8"
        m = re.search(r"charset=([\w-]+)", ctype, re.I)
        if m:
            encoding = m.group(1)
        text = raw.decode(encoding, errors="ignore")
        return text if len(text) > 200 else None
    except Exception:
        return None


def _backend_markdown_new(url: str, timeout: int = 8) -> Optional[str]:
    try:
        api_url = "https://markdown.new/" + url
        r = subprocess.run(
            [
                "curl",
                "-sL",
                "--max-time",
                str(timeout),
                api_url,
                "-H",
                "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            ],
            capture_output=True,
            timeout=timeout + 2,
        )
        if r.returncode != 0:
            return None
        text = r.stdout.decode("utf-8", errors="replace")
        idx = text.find("Markdown Content:")
        if idx < 0:
            return None
        content = text[idx + len("Markdown Content:"):].strip()
        return content if len(content) > 50 else None
    except (subprocess.TimeoutExpired, OSError):
        return None


def _backend_scrapling(url: str, timeout: int = 10) -> Optional[str]:
    if not os.path.exists(SCRAPLING_SCRIPT):
        return None
    try:
        r = subprocess.run(["python3", SCRAPLING_SCRIPT, url], capture_output=True, timeout=timeout)
        if r.returncode == 0:
            text = r.stdout.decode("utf-8", errors="replace").strip()
            return text if len(text) > 50 else None
    except (subprocess.TimeoutExpired, OSError):
        return None
    return None


def _backend_curl(url: str, timeout: int = 10) -> Optional[str]:
    try:
        r = subprocess.run(
            [
                "curl",
                "-sL",
                "--max-time",
                str(timeout),
                "-H",
                "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "-H",
                "Accept-Language: zh-CN,zh;q=0.9",
                "--compressed",
                url,
            ],
            capture_output=True,
            timeout=timeout + 3,
        )
        if r.returncode != 0:
            return None
        return r.stdout.decode("utf-8", errors="replace")
    except (subprocess.TimeoutExpired, OSError):
        return None


def _clean_html(text: str) -> str:
    if re.search(r"<body[^>]*>|<html[^>]*>", text, re.I):
        return html_to_text(text)
    return text


class Fetcher:
    """统一抓取器：缓存优先，多后端级联降级。"""

    def __init__(
        self,
        cache_dir: str = CACHE_DIR,
        ttl_text: int = CACHE_TTL_TEXT,
        ttl_title: int = CACHE_TTL_TITLE,
        ttl_html: int = CACHE_TTL_RAW,
    ):
        self.cache = _DiskCache(cache_dir)
        self._ttl_text = ttl_text
        self._ttl_title = ttl_title
        self._ttl_html = ttl_html
        self._backends = [
            ("requests", _backend_requests),
            ("urllib", _backend_urllib),
            ("markdown.new", _backend_markdown_new),
            ("scrapling", _backend_scrapling),
            ("curl", _backend_curl),
        ]

    def fetch_text(self, url: str, timeout: int = 15) -> str:
        cached = self.cache.get(url, ".txt", self._ttl_text)
        if cached is not None:
            return cached
        for _, backend in self._backends:
            result = backend(url, timeout=timeout)
            if not result:
                continue
            result = _clean_html(result)
            if len(result) > 50:
                self.cache.set(url, result, ".txt")
                return result
        return ""

    def fetch_title(self, url: str, timeout: int = 10) -> str:
        cached = self.cache.get(url, ".title", self._ttl_title)
        if cached is not None:
            return cached
        page = self.fetch_html(url, timeout=timeout)
        if page:
            m = re.search(r"<title[^>]*>(.*?)</title>", page, re.S | re.I)
            if m:
                title = html_mod.unescape(re.sub(r"<[^>]+>", " ", m.group(1))).strip()
                if title:
                    self.cache.set(url, title, ".title")
                    return title
        return ""

    def fetch_html(self, url: str, timeout: int = 10) -> str:
        cached = self.cache.get(url, ".html", self._ttl_html)
        if cached is not None:
            return cached
        html = _backend_requests(url, timeout=timeout) or _backend_urllib(url, timeout=timeout)
        if html:
            self.cache.set(url, html, ".html")
            return html
        html = _backend_curl(url, timeout=timeout)
        if html:
            self.cache.set(url, html, ".html")
            return html
        return ""

    def fetch_binary(self, url: str, timeout: int = 20) -> bytes:
        if requests is not None:
            try:
                r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=timeout)
                if r.status_code == 200 and len(r.content) > 100:
                    return r.content
            except requests.RequestException:
                pass
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except Exception:
            return b""

    def clear_cache(self):
        self.cache.clear()


class CCGPFetcher:
    BASE = "https://www.ccgp.gov.cn"
    SEARCH_BASE = "https://search.ccgp.gov.cn/bxsearch"
    CHANNELS = [
        "/cggg/zygg/gkzb/",
        "/cggg/zygg/jzxcs/",
        "/cggg/dfgg/gkzb/",
        "/cggg/dfgg/jzxcs/",
    ]

    def __init__(self, list_cache_ttl: int = 0):
        # 列表页变化很快，默认不使用 HTML 缓存；详情页仍由其他管道缓存。
        self.fetcher = Fetcher(ttl_html=list_cache_ttl)

    def fetch_recent(self, start: date, end: date, pages_per_channel: int = 30) -> List[Item]:
        items = []
        seen = set()
        for channel in self.CHANNELS:
            for page_url in self._index_urls(channel, pages_per_channel):
                try:
                    page = self.fetcher.fetch_html(page_url)
                    if not page:
                        raise RuntimeError("empty page")
                except Exception as exc:
                    print(f"  [抓取失败] {page_url}: {exc}")
                    continue
                parsed = self._parse_list(page, page_url)
                if not parsed:
                    break
                page_has_window_item = False
                page_is_before_window = True
                for url, title in parsed:
                    if url in seen:
                        continue
                    seen.add(url)
                    item = Item(title=title, url=url, source="中国政府采购网")
                    item_date = self._date_from_url(item.url)
                    if item_date is not None:
                        item.publish_date = item_date.isoformat()
                        if item_date >= start:
                            page_is_before_window = False
                    else:
                        page_is_before_window = False
                    if self._looks_in_window(item, start, end):
                        page_has_window_item = True
                        items.append(item)
                if not page_has_window_item and page_is_before_window:
                    break
        return items

    def fetch_keyword_search(
        self,
        keywords: Iterable[str],
        start: date,
        end: date,
        pages_per_keyword: int = 1,
    ) -> List[Item]:
        items = []
        seen = set()
        for kw in keywords:
            kw = (kw or "").strip()
            if not kw:
                continue
            for page_index in range(1, pages_per_keyword + 1):
                page_url = self._search_url(kw, start, end, page_index)
                page = self.fetcher.fetch_html(page_url, timeout=15)
                if not page:
                    continue
                if "访问过于频繁" in page or "频繁访问" in page:
                    print(f"  [搜索跳过] {kw}: 访问过于频繁")
                    break
                for url, title in self._parse_list(page, page_url):
                    if url in seen:
                        continue
                    seen.add(url)
                    item = Item(title=title, url=url, source="中国政府采购网(搜索)")
                    if self._looks_in_window(item, start, end):
                        items.append(item)
        return items

    def fetch_urls(self, urls: Iterable[str]) -> List[Item]:
        items = []
        for url in urls:
            try:
                detail = fetch_body(url)
                title = detail["title"] or url
                items.append(
                    Item(
                        title=title,
                        url=url,
                        source="中国政府采购网",
                        publish_date=detail["publish_date"] or None,
                        body=detail["body"],
                    )
                )
            except Exception as exc:
                print(f"  [URL失败] {url}: {exc}")
        return items

    def _index_urls(self, channel: str, pages: int):
        base = self.BASE + channel
        yield base
        for i in range(1, pages):
            yield base + f"index_{i}.htm"

    def _search_url(self, keyword: str, start: date, end: date, page_index: int):
        params = {
            "searchtype": "1",
            "page_index": str(page_index),
            "bidSort": "0",
            "buyerName": "",
            "projectId": "",
            "pinMu": "0",
            "bidType": "0",
            "dbselect": "bidx",
            "kw": keyword,
            "start_time": start.strftime("%Y:%m:%d"),
            "end_time": end.strftime("%Y:%m:%d"),
            "timeType": "6",
            "displayZone": "",
            "zoneId": "",
            "pppStatus": "0",
            "agentName": "",
        }
        return f"{self.SEARCH_BASE}?{urlencode(params)}"

    def _parse_list(self, page: str, page_url: str):
        results = []
        for url, label in extract_links(page, page_url):
            if not re.search(r"/cggg/.*/t20\d{6}_\d+\.htm", url):
                continue
            title = re.sub(r"\s+", " ", html_to_text(label)).strip()
            if title:
                results.append((url, title))
        return results

    def _looks_in_window(self, item: Item, start: date, end: date) -> bool:
        d = self._date_from_url(item.url)
        if d is None:
            return True
        return start <= d <= end

    def _date_from_url(self, url: str):
        m = re.search(r"/(20\d{4})/t(20\d{6})_", url)
        if not m:
            return None
        stamp = m.group(2)
        return date(int(stamp[:4]), int(stamp[4:6]), int(stamp[6:8]))
