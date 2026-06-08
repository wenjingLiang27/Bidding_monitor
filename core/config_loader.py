from pathlib import Path
from typing import Dict, List


def load_list_config(path: Path, defaults: Dict[str, List[str]]) -> Dict[str, List[str]]:
    """读取简单 YAML 列表配置，避免为小工具引入 PyYAML 依赖。"""
    if not path.exists():
        return {k: list(v) for k, v in defaults.items()}

    data: Dict[str, List[str]] = {}
    current = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        if not line.startswith(" ") and line.endswith(":"):
            current = line[:-1].strip()
            data.setdefault(current, [])
            continue
        if current and line.strip().startswith("- "):
            data[current].append(line.strip()[2:].strip().strip('"').strip("'"))

    merged = {k: list(v) for k, v in defaults.items()}
    for key, values in data.items():
        merged[key] = [v for v in values if v]
    return merged
