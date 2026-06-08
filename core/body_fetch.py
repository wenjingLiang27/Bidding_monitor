import html
import re
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List
from urllib.parse import urljoin

from .models import Item


def fetch_url(url: str, timeout: int = 20) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 bidding-monitor/1.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        ctype = resp.headers.get("content-type", "")
    encoding = "utf-8"
    m = re.search(r"charset=([\w-]+)", ctype, re.I)
    if m:
        encoding = m.group(1)
    else:
        head = raw[:1000].decode("ascii", errors="ignore")
        m = re.search(r"charset=['\"]?([\w-]+)", head, re.I)
        if m:
            encoding = m.group(1)
    return raw.decode(encoding, errors="ignore")


def html_to_text(page: str) -> str:
    page = re.sub(r"(?is)<script.*?</script>|<style.*?</style>", " ", page)
    page = re.sub(r"(?i)<br\s*/?>|</p>|</tr>|</li>", "\n", page)
    text = re.sub(r"(?s)<[^>]+>", " ", page)
    text = html.unescape(text)
    return re.sub(r"[ \t\r\f\v]+", " ", text).strip()


def extract_title(page: str) -> str:
    for pattern in [r"<h1[^>]*>(.*?)</h1>", r"<title[^>]*>(.*?)</title>"]:
        m = re.search(pattern, page, re.I | re.S)
        if m:
            return re.sub(r"\s+", " ", html_to_text(m.group(1))).strip()
    return ""


def extract_publish_date(text: str) -> str:
    m = re.search(r"(20\d{2})[年/-](\d{1,2})[月/-](\d{1,2})", text)
    if not m:
        return ""
    y, mo, d = m.groups()
    return f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"


def extract_links(page: str, base_url: str):
    links = []
    for href, label in re.findall(r"<a[^>]+href=['\"]([^'\"]+)['\"][^>]*>(.*?)</a>", page, re.I | re.S):
        links.append((urljoin(base_url, href), html_to_text(label)))
    return links


def fetch_body(url: str) -> dict:
    page = fetch_url(url)
    text = html_to_text(page)
    return {
        "title": extract_title(page),
        "body": text,
        "publish_date": extract_publish_date(text),
        "links": extract_links(page, url),
    }


def _fetch_one(item: Item, rules, fetcher):
    """单个正文抓取 + 匹配。"""
    body = fetcher.fetch_text(item.url, timeout=15)
    if body and len(body) > 50:
        item.body = body
        matched, kws = rules.is_body_match(item.title, body)
        if matched:
            item._match_type = "body"
            item._matched_kws = kws
            item._filter_stage = "passed"
            return item
    item._filter_stage = "needs_zip"
    return item


def body_fetch_pipeline(items: List[Item], rules, fetcher) -> List[Item]:
    """正文回退管道：并发抓取详情页正文，二次匹配关键词。"""
    needs = [it for it in items if it._filter_stage == "needs_body"]
    passed = [it for it in items if it._filter_stage == "passed"]

    if not needs:
        return items

    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = {pool.submit(_fetch_one, it, rules, fetcher): it for it in needs}
        for f in as_completed(futures):
            try:
                f.result()
            except Exception:
                futures[f]._filter_stage = "needs_zip"

    return passed + needs
