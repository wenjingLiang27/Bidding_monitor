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

    def _filter_generic_safety_hits(self, text: str, hits: List[str]) -> List[str]:
        generic = {"安全检测", "安全测评", "安全评估", "安全评价", "风险评估"}
        cyber_context = [
            "网络安全",
            "信息安全",
            "信息系统",
            "信息化",
            "软件",
            "应用安全",
            "密码",
            "代码",
            "漏洞",
            "渗透",
            "等级保护",
            "等保",
            "密评",
            "安全服务",
            "检测服务",
        ]
        physical_context = [
            "消防",
            "档案",
            "道路",
            "交通",
            "危险化学品",
            "危化品",
            "工程",
            "设施",
            "维修维护",
            "监控维修",
            "食品",
            "药品",
            "水质",
            "环境",
            "数据安全",
        ]
        # 系统/平台类采购 含嵌入式安全检测 → 过滤
        procurement_context = [
            "系统服务", "平台服务", "集成服务", "开发服务",
            "设备采购", "系统采购", "硬件采购", "产品采购",
        ]
        security_service_context = [
            "安全服务", "检测服务", "测评服务", "安全检测服务",
            "渗透测试", "漏洞扫描", "网络安全服务",
        ]
        filtered = []
        for hit in hits:
            if hit not in generic:
                filtered.append(hit)
                continue
            idx = text.find(hit)
            window = text[max(0, idx - 300): idx + len(hit) + 300] if idx >= 0 else text
            if any(word in window for word in physical_context):
                continue
            if any(word in window for word in procurement_context) and not any(word in window for word in security_service_context):
                continue
            if any(word in window for word in cyber_context):
                filtered.append(hit)
        return filtered

    def _filter_generic_business_hits(self, text: str, hits: List[str]) -> List[str]:
        generic = {"系统测试", "软件测试", "软件测评"}
        target_context = [
            "软件",
            "信息系统",
            "应用系统",
            "业务系统",
            "平台",
            "网络安全",
            "信息安全",
            "漏洞",
            "代码",
            "渗透",
            "测评服务",
            "测试服务",
        ]
        equipment_context = [
            "设备",
            "仪器",
            "装置",
            "硬件",
            "供货",
            "调试",
            "安装",
            "采购",
            "货物",
            "试验仪器",
            "电转染",
        ]
        dev_context = [
            "国产化改造",
            "系统改造",
            "信息化改造",
            "升级改造",
            "新建系统",
            "系统建设",
            "系统集成",
            "集成项目",
            "总集",
            "集成服务",
        ]
        # 软件测试工具/产品采购上下文（非测试服务，应过滤）
        tool_purchase_kws = ["测试系统", "测试平台", "测试工具", "测试产品",
                            "软件系统", "软件产品", "软件平台", "系统采购", "平台"]
        service_override_kws = ["测试服务", "测评服务", "服务外包", "委托测试"]
        filtered = []
        for hit in hits:
            if hit not in generic:
                filtered.append(hit)
                continue
            idx = text.find(hit)
            window = text[max(0, idx - 300): idx + len(hit) + 300] if idx >= 0 else text
            
            # 「软件测试/软件测评」：检测是否为工具/产品采购而非测试服务
            if hit in ("软件测试", "软件测评"):
                if any(word in window for word in tool_purchase_kws) and not any(word in window for word in service_override_kws):
                    continue
                filtered.append(hit)
                continue
            
            if any(word in window for word in equipment_context) and not any(word in window for word in target_context):
                continue
            if any(word in window for word in dev_context):
                continue
            filtered.append(hit)
        return filtered

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
        business = self._filter_generic_business_hits(text, self._hits(text, self.accept_kws))
        borderline = self._filter_generic_safety_hits(text, self._hits(text, self.borderline_kws))
        non_target = self._hits(text, self.reject_kws)
        matched = list(dict.fromkeys(business + borderline + non_target))
        strong_direct = {"渗透测试", "代码审计", "软件测试", "软件测评", "系统测试", "第三方软件测试"}

        # 硬拒绝：运维/维保类项目一律 C，即使同时命中业务关键词
        ops_kws = {"运维", "运维服务", "集约运维", "运行维护", "安全运维", "网络运维", "系统运维", "维保服务"}
        if ops_kws & set(non_target):
            label, reason = "C", "硬拒绝：命中运维/维保类非目标词"
        elif business and (strong_direct & set(business)):
            label, reason = "A", "命中核心目标业务词"
        elif business and non_target:
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
