#!/usr/bin/env python3
"""招标监控入口脚本。"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="招标监控")
    parser.add_argument("--test", action="store_true", help="测试模式")
    parser.add_argument("--month", action="store_true", help="整月覆盖模式")
    parser.add_argument("--no-ai", action="store_true", help="跳过 AI 分析")
    parser.add_argument("--dry-run", action="store_true", help="只打印结果，不发送邮件")
    parser.add_argument("--date", help="指定日期 YYYY-MM-DD")
    parser.add_argument("--days", type=int, default=2, help="向前覆盖天数，默认 2（昨天到今天）")
    parser.add_argument("--url", action="append", default=[], help="直接检查公告 URL，可传多次")
    parser.add_argument("--urls-file", help="从文件读取公告 URL，每行一个")

    parser.add_argument("--pending-label", action="store_true", help="列出待人工标注项目")
    parser.add_argument("--kw", help="按关键词过滤标注/统计结果")
    parser.add_argument("--show-labeled", action="store_true", help="包含已标注项目")
    parser.add_argument("--stats-detail", action="store_true", help="输出标注统计")
    parser.add_argument("--show-samples", type=int, default=0, help="统计时每类展示样例数")
    parser.add_argument("--suggest-labels", action="store_true", help="根据业务边界输出建议标签，不落库")
    parser.add_argument("--label-url", nargs=2, metavar=("URL", "LABEL"), help="按 URL 写入人工标签 A/B/C")
    parser.add_argument("--label-batch", nargs=2, metavar=("LABEL", "KW"), help="按关键词批量写入人工标签 A/B/C")
    parser.add_argument("--label-note", default="", help="标注备注")
    parser.add_argument("--force-label", action="store_true", help="允许覆盖已有人工标签")
    return parser


if __name__ == "__main__":
    from core.scheduler import Scheduler

    args = build_parser().parse_args()

    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_dir = os.path.join(script_dir, "config")
    data_dir = os.getenv("BIDDING_DATA_DIR") or os.path.expanduser("~/.hermes/bidding_data")

    scheduler = Scheduler(config_dir, data_dir)
    scheduler.refresh_window(args.date, args.days)

    if args.month:
        scheduler.YESTERDAY = scheduler.TODAY.replace(day=1)
        print(f"  [模式] 整月覆盖: {scheduler.YESTERDAY} ~ {scheduler.TODAY}")

    if args.test:
        scheduler.mail_to = "1545103938@qq.com"
        print("  [模式] 测试模式（仅发送到 1545103938@qq.com）")

    if args.pending_label:
        scheduler.show_pending_label(args.kw, args.show_labeled)
        sys.exit(0)

    if args.stats_detail:
        scheduler.show_stats_detail(args.kw, args.show_samples)
        sys.exit(0)

    if args.suggest_labels:
        scheduler.suggest_labels(args.kw)
        sys.exit(0)

    if args.label_url:
        url, label = args.label_url
        scheduler.label_url(url, label, args.label_note, args.force_label)
        sys.exit(0)

    if args.label_batch:
        label, kw = args.label_batch
        scheduler.label_batch(label, kw, args.label_note, args.force_label)
        sys.exit(0)

    urls = list(args.url)
    if args.urls_file:
        urls.extend(scheduler.read_urls_file(args.urls_file))

    count = scheduler.run(
        send_email=not args.dry_run,
        ai_enabled=not args.no_ai,
        urls=urls,
    )
    print(f"\n完成！共 {count} 条")
    sys.exit(0)
