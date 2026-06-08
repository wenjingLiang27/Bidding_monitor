from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Item:
    title: str
    url: str
    source: str = "中国政府采购网"
    publish_date: Optional[str] = None
    body: str = ""

    _filter_stage: str = ""
    _match_type: str = ""
    _score: int = 999
    _matched_kws: List[str] = field(default_factory=list)
    _business_hit: List[str] = field(default_factory=list)
    _non_target_hit: List[str] = field(default_factory=list)
    _domain_hints: dict = field(default_factory=dict)
    _ai_analysis: str = ""
