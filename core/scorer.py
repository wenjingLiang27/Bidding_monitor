"""评分过滤引擎 — 域判断 + 评分排序。"""
from typing import Dict, List

from .models import Item
from .rules import KeywordEngine


class Scorer:
    def __init__(self, rules: KeywordEngine, weights: Dict = None):
        self.rules = rules
        self.weights = weights or self._default_weights()

    def filter(self, items: List[Item]) -> List[Item]:
        passed = []
        for item in items:
            title = item.title
            if self.rules.is_closed(title):
                item._filter_stage = "closed"
                continue
            if self.rules.has_noise(title) and not self.rules.has_match_kws(title):
                item._filter_stage = "noise"
                continue

            result = self.rules.filter_title_by_domains(title)
            if result["action"] == "body":
                item._filter_stage = "needs_body"
                item._domain_hints = result["domains"]
                passed.append(item)
            elif result["reason"] == "no_test" and result.get("domains", {}).get("it"):
                item._filter_stage = "needs_body"
                item._domain_hints = result["domains"]
                passed.append(item)
            else:
                item._filter_stage = result["reason"]
        return passed

    def filter_zip(self, item: Item, body: str) -> bool:
        tl = item.title.lower()
        is_etc = any(kw.lower() in tl for kw in self.rules.etc_only_kws)
        if is_etc:
            return any(kw.lower() in body.lower() for kw in self.rules.etc_override_kws)
        return True

    def assign_score(self, item: Item):
        mt = self.weights.get("match_type", {})
        sw = self.weights.get("source_weights", {})
        type_priority = mt.get(item._match_type, 5)
        source_weight = sw.get(item.source, 1)
        score = type_priority * 100 - source_weight

        hits = set(item._matched_kws)
        strong_hits = {"渗透测试", "漏洞扫描", "代码审计", "软件测试", "系统测试", "第三方软件测试"}
        borderline_hits = {
            "网络安全检测",
            "网络安全测评",
            "网络安全评估",
            "安全检测",
            "安全测评",
            "安全评估",
            "风险评估",
            "验收测评",
            "验收测试",
            "第三方测试",
        }
        non_target_hits = set(item._non_target_hit)
        business_hits = set(item._business_hit)
        borderline_only_hits = hits - business_hits - non_target_hits

        if business_hits:
            score -= 18
        elif borderline_only_hits:
            score += 25

        score -= 12 * len(hits & strong_hits)
        score -= 5 * len(hits & borderline_hits)
        score -= min(8, max(0, len(hits) - 1) * 2)
        if hits & strong_hits:
            score += min(6, 3 * len(non_target_hits))
        else:
            score += 12 * len(non_target_hits)

        if item._match_type == "zip":
            score += 20
        item._score = max(1, score)

    def sort(self, items: List[Item]) -> List[Item]:
        for item in items:
            self.assign_score(item)
        return sorted(items, key=lambda x: x._score)

    @staticmethod
    def _default_weights() -> Dict:
        return {
            "match_type": {"body": 1, "zip": 2, "title": 3},
            "source_weights": {"中国政府采购网": 10, "中国政府采购网(搜索)": 10},
        }
