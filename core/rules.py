from pathlib import Path
from typing import Dict, List

from .config_loader import load_list_config


DEFAULT_KEYWORDS = {
    "it_domain": [
        "信息化", "网络", "安全", "系统", "软件", "平台", "数据", "应用", "密码",
        "代码", "测评", "检测", "测试", "评估", "运维",
    ],
    "test_domain": [
        "测试", "测评", "检测", "评估", "验收", "审计", "扫描", "渗透",
    ],
    "business": [
        "渗透测试", "漏洞扫描", "代码审计", "软件测试", "系统测试", "第三方软件测试",
    ],
    "borderline": [
        "风险评估", "验收测评", "验收测试", "第三方测评", "网络安全检测",
        "网络安全测评", "网络安全评估", "安全检测", "安全测评", "安全评估",
    ],
    "non_target": [
        "等级保护测评", "等保测评", "等级保护", "密评", "密码应用安全性评估",
        "商用密码应用安全性评估", "运维服务", "集约运维", "平台建设",
    ],
    "noise": [
        "压力测试仪", "渗透压", "光学检测", "性能测试系统", "检测设备", "测试设备",
        "实验仪器", "复印纸", "车辆", "家具", "装修", "物业",
    ],
    "closed": ["终止公告", "废标公告", "流标公告", "更正公告", "中标公告", "成交公告"],
}


class KeywordEngine:
    def __init__(self, config_dir: str):
        self.config_dir = Path(config_dir)
        self.keywords = load_list_config(self.config_dir / "keywords.yaml", DEFAULT_KEYWORDS)
        scope = load_list_config(
            self.config_dir / "business_scope.yaml",
            {
                "accept": self.keywords["business"],
                "borderline": self.keywords["borderline"],
                "reject": self.keywords["non_target"],
            },
        )
        self.accept_kws = scope["accept"]
        self.borderline_kws = scope["borderline"]
        self.reject_kws = scope["reject"]
        self.etc_only_kws = ["等级保护", "等保测评", "密评", "密码应用安全性评估"]
        self.etc_override_kws = self.accept_kws + ["第三方软件测试", "软件测评"]

    def _hits(self, text: str, kws: List[str]) -> List[str]:
        return [kw for kw in kws if kw and kw.lower() in text.lower()]

    def is_closed(self, text: str) -> bool:
        return bool(self._hits(text, self.keywords["closed"]))

    def has_noise(self, text: str) -> bool:
        return bool(self._hits(text, self.keywords["noise"]))

    def has_match_kws(self, text: str) -> bool:
        return bool(
            self._hits(text, self.accept_kws)
            or self._hits(text, self.borderline_kws)
            or self._hits(text, self.reject_kws)
        )

    def filter_title_by_domains(self, title: str) -> Dict:
        it_hits = self._hits(title, self.keywords["it_domain"])
        test_hits = self._hits(title, self.keywords["test_domain"])
        if not it_hits:
            return {"action": "reject", "reason": "no_it", "domains": {}}
        if not test_hits and not self.has_match_kws(title):
            return {"action": "reject", "reason": "no_test", "domains": {"it": it_hits}}
        return {"action": "body", "domains": {"it": it_hits, "test": test_hits}}

    def classify_text(self, text: str) -> Dict:
        business = self._hits(text, self.accept_kws)
        borderline = self._hits(text, self.borderline_kws)
        non_target = self._hits(text, self.reject_kws)
        matched = list(dict.fromkeys(business + borderline + non_target))

        if business and non_target:
            label, reason = "B", "目标业务与非目标业务同时出现"
        elif business:
            label, reason = "A", "命中目标业务词"
        elif borderline:
            label, reason = "B", "命中边界业务词"
        elif non_target:
            label, reason = "C", "仅命中非目标业务词"
        else:
            label, reason = "", "无业务边界命中"

        return {
            "label": label,
            "reason": reason,
            "matched": matched,
            "business_hit": business,
            "non_target_hit": non_target,
            "borderline_hit": borderline,
        }

    def is_body_match(self, title: str, body: str):
        """正文命中判断，兼容原 body_fetch_pipeline 接口。"""
        result = self.classify_text(f"{title}\n{body}")
        if result["label"] in ("A", "B"):
            return True, result["matched"]
        return False, result["matched"]
