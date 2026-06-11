import re
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable, List

from .ai_analyzer import DeepSeekAnalyzer
from .body_fetch import body_fetch_pipeline, fetch_body
from .fetcher import CCGPFetcher, Fetcher
from .mailer import Mailer
from .models import Item
from .rules import KeywordEngine
from .scorer import Scorer
from .store import Store
from .zip_extract import AttachmentParser, zip_extract_pipeline


class Scheduler:
    def __init__(self, config_dir: str, data_dir: str):
        self.config_dir = config_dir
        self.data_dir = data_dir
        self.rules = KeywordEngine(config_dir)
        self.scorer = Scorer(self.rules)
        self.http = Fetcher()
        self.fetcher = CCGPFetcher()
        self.attachment_parser = AttachmentParser(self.rules, self.http)
        self.mailer = Mailer(config_dir)
        self.ai_analyzer = DeepSeekAnalyzer(config_dir)
        self.store = Store(data_dir)
        self.mail_to = ""
        self.TODAY = date.today()
        self.YESTERDAY = self.TODAY

    def refresh_window(self, date_text: str = None, days: int = 1):
        self.TODAY = self._parse_date(date_text) if date_text else date.today()
        days = max(days, 1)
        self.YESTERDAY = self.TODAY - timedelta(days=days - 1)

    def read_urls_file(self, path: str) -> List[str]:
        return [
            line.strip()
            for line in Path(path).read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]

    def run(self, send_email: bool = True, ai_enabled: bool = True, urls: Iterable[str] = ()):
        if urls:
            items = self.fetcher.fetch_urls(urls)
        else:
            print(f"  [窗口] {self.YESTERDAY} ~ {self.TODAY}")
            # 先关键词全文搜索，再日期搜索兜底，最后浏览列表
            keywords = self.rules.accept_kws + [""]  # 6个业务关键词 + 日期兜底
            items = self.fetcher.fetch_keyword_search(keywords, self.YESTERDAY, self.TODAY, pages_per_keyword=1)
            items = self._merge_items(
                items,
                self.fetcher.fetch_recent(self.YESTERDAY, self.TODAY),
            )

        passed = self.scorer.filter(items)
        checked = body_fetch_pipeline(passed, self.rules, self.http)
        checked = zip_extract_pipeline(checked, self.scorer, self.attachment_parser)
        final = []
        for item in checked:
            if item._filter_stage == "passed":
                self._classify_item(item)
                if item._match_type:
                    final.append(item)

        final = self.scorer.sort(final)
        if ai_enabled:
            self._analyze_items(final)
            ai_c_count = 0
            kept = []
            for item in final:
                if re.search(r"建议[：:]\\s*C\\b", item._ai_analysis or ""):
                    item._filter_stage = "ai_c"
                    item._match_type = ""
                    ai_c_count += 1
                else:
                    kept.append(item)
            if ai_c_count:
                print(f"  [AI过滤] 剔除 AI 判 C 的 {ai_c_count} 条")
            final = kept

        for item in items:
            self.store.upsert(item)

        self._print_pipeline_summary(items, final)
        self._print_final(final)
        if send_email:
            self._send_email(final)
        return len(final)

    def show_pending_label(self, kw: str = "", show_labeled: bool = False):
        where = "1=1"
        params = []
        if not show_labeled:
            where += " and (human_label is null or human_label = '')"
        if kw:
            where += " and (title like ? or matched_kws like ? or business_hit like ? or non_target_hit like ?)"
            params = [f"%{kw}%"] * 4
        rows = self.store.rows(where, params)
        for row in rows:
            label = row["human_label"] or "-"
            print(f"[{label}] {row['title']}")
            print(f"    {row['url']}")
            print(f"    stage={row['filter_stage']} kws={row['matched_kws']}")

    def show_stats_detail(self, kw: str = "", show_samples: int = 0):
        rows = self.store.labeled_stats(kw)
        by_kw = defaultdict(lambda: defaultdict(list))
        for row in rows:
            label = row["human_label"]
            for key in self._split(row["matched_kws"]):
                by_kw[key][label].append(row)

        for key in sorted(by_kw):
            counts = by_kw[key]
            print(f"\n{key}")
            print(f"A={len(counts['A'])} B={len(counts['B'])} C={len(counts['C'])}")
            if show_samples:
                for label in ["A", "B", "C"]:
                    samples = counts[label][:show_samples]
                    if samples:
                        print(f"{label}:")
                        for row in samples:
                            print(f"  {row['title']}")

    def suggest_labels(self, kw: str = ""):
        rows = self.store.rows("(human_label is null or human_label = '')")
        for row in rows:
            text = f"{row['title']}\n{row['body'] or ''}"
            if kw and kw not in text:
                continue
            result = self.rules.classify_text(text)
            if not result["label"]:
                continue
            conflict = result["business_hit"] and result["non_target_hit"]
            flag = "冲突项" if conflict else "建议"
            print(f"\n[{flag}] {result['label']} - {row['title']}")
            print(f"    reason={result['reason']}")
            print(f"    business_hit={','.join(result['business_hit']) or '-'}")
            print(f"    non_target_hit={','.join(result['non_target_hit']) or '-'}")
            print(f"    {row['url']}")

    def label_url(self, url: str, label: str, note: str = "", force: bool = False):
        label = self._normalize_label(label)
        result = self.store.label_url(url, label, note, force)
        if result == 1:
            print(f"  [标注] 已写入 {label}: {url}")
        elif result == -1:
            print("  [标注] 跳过：该 URL 已有人工标签。需要覆盖请加 --force-label")
        else:
            print("  [标注] 未找到该 URL。请先运行采集或用 --url 抓取入库后再标注。")

    def label_batch(self, label: str, kw: str, note: str = "", force: bool = False):
        label = self._normalize_label(label)
        where = "(title like ? or matched_kws like ? or business_hit like ? or non_target_hit like ?)"
        params = [f"%{kw}%"] * 4
        count = self.store.label_where(where, params, label, note, force)
        print(f"  [批量标注] {label} / {kw}: 写入 {count} 条")

    def _hydrate_body(self, item: Item):
        if item.body:
            return
        try:
            detail = fetch_body(item.url)
            item.body = detail["body"]
            item.publish_date = item.publish_date or detail["publish_date"] or None
            if detail["title"] and len(detail["title"]) > len(item.title):
                item.title = detail["title"]
        except Exception as exc:
            item._filter_stage = "body_fetch_failed"
            print(f"  [正文失败] {item.title}: {exc}")

    def _classify_item(self, item: Item):
        result = self.rules.classify_text(f"{item.title}\n{item.body}")
        item._auto_label = result["label"]
        item._matched_kws = result["matched"]
        item._business_hit = result["business_hit"]
        item._non_target_hit = result["non_target_hit"]

        if result["label"] in ("A", "B"):
            item._filter_stage = "final"
            item._match_type = "body"
        elif result["label"] == "C":
            item._match_type = ""
            item._filter_stage = "non_target"
        else:
            item._match_type = ""
            item._filter_stage = "body_no_match"

    def _analyze_items(self, items: List[Item]):
        if not items:
            return
        if not self.ai_analyzer.configured():
            print("  [AI] 未配置 DEEPSEEK_API_KEY，已跳过 AI 分析")
            return
        print(f"  [AI] DeepSeek 分析 {len(items)} 条...")
        self.ai_analyzer.analyze_items(items)

    def _print_pipeline_summary(self, items: List[Item], final: List[Item]):
        counts = defaultdict(int)
        for item in items:
            counts[item._filter_stage or "unknown"] += 1
        print("\n过滤层统计")
        for key in sorted(counts):
            print(f"  {key}: {counts[key]}")
        print(f"  最终命中: {len(final)}")

    def _print_final(self, items: List[Item]):
        if not items:
            return
        print("\n命中项目")
        for i, item in enumerate(items, 1):
            print(f"{i}. {item.title}")
            print(f"   {item.url}")
            print(f"   label={item._auto_label or '-'} kws={','.join(item._matched_kws)} score={item._score}")
            if item._ai_analysis:
                print(f"   ai={item._ai_analysis}")

    def _send_email(self, items: List[Item]):
        if not self.mailer.configured():
            print(f"  [邮件] 未发送，缺少配置：{', '.join(self.mailer.missing())}")
            print("  [邮件] 可用环境变量：SMTP_HOST/SMTP_PORT/SMTP_USER/SMTP_PASSWORD/MAIL_TO")
            return
        try:
            self.mailer.send_report(items, self.YESTERDAY, self.TODAY)
            print(f"  [邮件] 已发送到 {', '.join(self.mailer.mail_to)}")
        except Exception as exc:
            print(f"  [邮件] 发送失败：{exc}")

    def _merge_items(self, base: List[Item], extra: List[Item]) -> List[Item]:
        def _key(url: str) -> str:
            return url.replace("http://", "https://")
        seen = {_key(item.url) for item in base}
        for item in extra:
            if _key(item.url) not in seen:
                seen.add(_key(item.url))
                base.append(item)
        return base

    def _split(self, value: str):
        return [x for x in (value or "").split(",") if x]

    def _parse_date(self, value: str) -> date:
        return datetime.strptime(value, "%Y-%m-%d").date()

    def _normalize_label(self, label: str) -> str:
        label = label.strip().upper()
        if label not in {"A", "B", "C"}:
            raise SystemExit("标签必须是 A / B / C")
        return label
