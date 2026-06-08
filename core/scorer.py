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
        item._score = type_priority * 100 - source_weight

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
