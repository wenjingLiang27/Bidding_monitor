# bidding-monitor

政府采购招标监控恢复版，按“标题召回、正文判定、人工标注闭环”的思路实现。

## 运行

```powershell
cd D:\WSL\bidding-monitor
python bidding_monitor.py --dry-run --no-ai
```

默认采集窗口为昨天到今天，即 T-1 00:00 到今天。

数据默认保存在：

```text
~\.hermes\bidding_data\bidding.sqlite3
```

如需改到项目内或其他位置，可设置 `BIDDING_DATA_DIR`。

检查指定公告：

```powershell
python bidding_monitor.py --dry-run --no-ai --url "https://www.ccgp.gov.cn/cggg/dfgg/gkzb/202606/t20260605_26699390.htm"
```

查看待标注：

```powershell
python bidding_monitor.py --pending-label
```

按关键词查看已标注样例统计：

```powershell
python bidding_monitor.py --stats-detail --kw "漏洞扫描" --show-samples 3
```

只输出建议标签，不写入人工标签：

```powershell
python bidding_monitor.py --suggest-labels
```

AI 分析使用 DeepSeek OpenAI-compatible 接口，推荐通过环境变量配置：

```powershell
$env:DEEPSEEK_API_KEY="你的 DeepSeek API Key"
$env:DEEPSEEK_MODEL="deepseek-v4-pro"
python bidding_monitor.py
```

AI 分析会写入邮件正文和 `data\bidding.sqlite3` 的 `ai_analysis` 字段。

人工标注入库：

```powershell
python bidding_monitor.py --label-url "https://example.com/notice.htm" A --label-note "明确软件测试"
python bidding_monitor.py --label-batch B "验收测评" --label-note "边界项目"
```

默认不会覆盖已有人工标签；需要覆盖时追加 `--force-label`。

## 标签原则

- A：明确会做，渗透测试、漏洞扫描、代码审计、软件测试、系统测试。
- B：边界项目，需要观察，例如网络安全检测、网络安全测评、验收测评。
- C：不做，例如纯等保、纯密评、纯运维、纯平台建设。

关键词只是 label hint，不是 label truth。人工标签仍以采购正文和附件内容为准。
