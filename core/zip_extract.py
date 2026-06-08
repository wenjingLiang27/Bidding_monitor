import io
import re
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List
from urllib.parse import urljoin

from .body_fetch import extract_links
from .models import Item


def fetch_zip_text(url: str, fetcher=None, timeout: int = 30) -> str:
    if fetcher is None:
        from .fetcher import Fetcher

        fetcher = Fetcher()
    data = fetcher.fetch_binary(url, timeout=timeout)
    out = []
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for name in zf.namelist():
            if name.endswith("/"):
                continue
            lower = name.lower()
            if not lower.endswith((".txt", ".csv", ".xml", ".html", ".htm")):
                continue
            raw = zf.read(name)
            out.append(raw.decode("utf-8", errors="ignore"))
    return "\n".join(out)


class AttachmentParser:
    """详情页附件解析器，支持 ZIP/DOCX/TXT/HTML 的关键词检索。"""

    def __init__(self, rules, fetcher):
        self.rules = rules
        self.fetcher = fetcher

    def check_attachment(self, page_url: str):
        page = self.fetcher.fetch_html(page_url)
        matched = []
        for url, _ in extract_links(page, page_url):
            if not self._looks_attachment(url):
                continue
            text = self._extract_text(url)
            if not text:
                continue
            ok, kws = self.rules.is_body_match("", text)
            if ok:
                matched.extend(kws)
        return bool(matched), list(dict.fromkeys(matched))

    def _looks_attachment(self, url: str) -> bool:
        return bool(re.search(r"\.(zip|docx?|xlsx?|pdf|txt|html?)($|\?)", url, re.I))

    def _extract_text(self, url: str) -> str:
        lower = url.lower()
        try:
            if lower.endswith(".zip"):
                return fetch_zip_text(url, self.fetcher)
            if lower.endswith((".txt", ".html", ".htm")):
                return self.fetcher.fetch_text(url)
            if lower.endswith(".docx"):
                data = self.fetcher.fetch_binary(url)
                return self._docx_text(data)
        except Exception:
            return ""
        return ""

    def _docx_text(self, data: bytes) -> str:
        out = []
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            for name in zf.namelist():
                if name.startswith("word/") and name.endswith(".xml"):
                    xml = zf.read(name).decode("utf-8", errors="ignore")
                    out.append(re.sub(r"<[^>]+>", " ", xml))
        return "\n".join(out)


def _check_one(item: Item, scorer, attachment_parser):
    print(f"  [ZIP检查] {item.title[:60]}...")
    has_match, matched_kws = attachment_parser.check_attachment(item.url)
    if has_match:
        if scorer.filter_zip(item, item.body or ""):
            item._match_type = "zip"
            item._matched_kws = matched_kws
            item._filter_stage = "passed"
            print(f"    -> 命中附件关键词: {matched_kws}")
        else:
            print("    -> 附件命中但等保/非IT过滤跳过")
            item._filter_stage = "no_match"
    else:
        print("    -> 附件无命中")
        item._filter_stage = "no_match"
    return item


def zip_extract_pipeline(items: List[Item], scorer, attachment_parser) -> List[Item]:
    """附件回退管道：并发下载并解析附件关键词。"""
    needs = [it for it in items if it._filter_stage == "needs_zip"]
    passed = [it for it in items if it._filter_stage == "passed"]

    if not needs:
        return items

    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = {pool.submit(_check_one, it, scorer, attachment_parser): it for it in needs}
        for f in as_completed(futures):
            try:
                f.result()
            except Exception:
                futures[f]._filter_stage = "no_match"

    return passed + needs
