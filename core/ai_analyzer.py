import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Iterable, List

from .config_loader import load_list_config
from .models import Item


def _load_ai_config(config_dir: str) -> dict:
    data = load_list_config(
        Path(config_dir) / "ai.yaml",
        {
            "provider": [],
            "base_url": [],
            "api_key": [],
            "model": [],
            "timeout": [],
        },
    )
    return {k: (v[0] if isinstance(v, list) and v else "") for k, v in data.items()}


class DeepSeekAnalyzer:
    """DeepSeek OpenAI-compatible analyzer."""

    def __init__(self, config_dir: str):
        cfg = _load_ai_config(config_dir)
        self.provider = os.getenv("AI_PROVIDER") or cfg.get("provider", "") or "deepseek"
        self.base_url = (
            os.getenv("DEEPSEEK_BASE_URL")
            or os.getenv("AI_BASE_URL")
            or cfg.get("base_url", "")
            or "https://api.deepseek.com/chat/completions"
        )
        self.api_key = os.getenv("DEEPSEEK_API_KEY") or os.getenv("AI_API_KEY") or cfg.get("api_key", "")
        self.model = os.getenv("DEEPSEEK_MODEL") or os.getenv("AI_MODEL") or cfg.get("model", "") or "deepseek-v4-pro"
        self.timeout = int(os.getenv("AI_TIMEOUT") or cfg.get("timeout", "") or 45)

    def configured(self) -> bool:
        return bool(self.api_key)

    def analyze_items(self, items: Iterable[Item]) -> List[Item]:
        for item in items:
            item._ai_analysis = self.analyze_item(item)
        return list(items)

    def analyze_item(self, item: Item) -> str:
        prompt = self._build_prompt(item)
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是招投标线索分析助手。根据采购公告标题、正文片段和命中关键词，"
                        "判断该项目对软件测试/系统测试/渗透测试/漏洞扫描/代码审计业务的跟进价值。"
                        "输出中文，控制在 120 字以内。"
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
        }
        req = urllib.request.Request(
            self.base_url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="replace"))
            return data["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError, json.JSONDecodeError) as exc:
            return f"AI分析失败：响应格式异常（{exc}）"
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:300]
            return f"AI分析失败：HTTP {exc.code} {detail}"
        except Exception as exc:
            return f"AI分析失败：{exc}"

    def _build_prompt(self, item: Item) -> str:
        body = (item.body or "").replace("\r", " ").replace("\n", " ")
        body = body[:2500]
        return (
            f"标题：{item.title}\n"
            f"链接：{item.url}\n"
            f"命中关键词：{', '.join(item._matched_kws) or '-'}\n"
            f"目标业务词：{', '.join(item._business_hit) or '-'}\n"
            f"非目标业务词：{', '.join(item._non_target_hit) or '-'}\n"
            f"正文片段：{body}\n\n"
            "请按这个格式输出：建议：A/B/C；原因：...；关注点：..."
        )
