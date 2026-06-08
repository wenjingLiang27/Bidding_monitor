import html
import os
import smtplib
from email.message import EmailMessage
from pathlib import Path
from typing import Iterable, List

from .config_loader import load_list_config
from .models import Item


def _load_mail_config(config_dir: str) -> dict:
    data = load_list_config(
        Path(config_dir) / "mail.yaml",
        {
            "smtp_host": [],
            "smtp_port": [],
            "smtp_user": [],
            "smtp_password": [],
            "mail_from": [],
            "mail_to": [],
        },
    )
    return {k: (v[0] if isinstance(v, list) and v else "") for k, v in data.items()}


class Mailer:
    """SMTP 邮件发送器，支持环境变量或 config/mail.yaml。"""

    def __init__(self, config_dir: str):
        cfg = _load_mail_config(config_dir)
        self.host = os.getenv("BIDDING_SMTP_HOST") or os.getenv("SMTP_HOST") or cfg.get("smtp_host", "")
        self.port = int(os.getenv("BIDDING_SMTP_PORT") or os.getenv("SMTP_PORT") or cfg.get("smtp_port", "") or 465)
        self.user = os.getenv("BIDDING_SMTP_USER") or os.getenv("SMTP_USER") or cfg.get("smtp_user", "")
        self.password = (
            os.getenv("BIDDING_SMTP_PASSWORD")
            or os.getenv("SMTP_PASSWORD")
            or os.getenv("SMTP_PASS")
            or cfg.get("smtp_password", "")
        )
        self.mail_from = os.getenv("BIDDING_MAIL_FROM") or os.getenv("MAIL_FROM") or cfg.get("mail_from", "") or self.user
        env_to = os.getenv("BIDDING_MAIL_TO") or os.getenv("MAIL_TO") or ""
        self.mail_to = [x.strip() for x in env_to.split(",") if x.strip()] or [
            x.strip() for x in (cfg.get("mail_to", "") or "").split(",") if x.strip()
        ]

    def configured(self) -> bool:
        return bool(self.host and self.user and self.password and self.mail_from and self.mail_to)

    def missing(self) -> List[str]:
        missing = []
        for key, value in [
            ("SMTP_HOST", self.host),
            ("SMTP_USER", self.user),
            ("SMTP_PASSWORD", self.password),
            ("MAIL_TO", self.mail_to),
        ]:
            if not value:
                missing.append(key)
        return missing

    def send_report(self, items: Iterable[Item], start_date, end_date) -> bool:
        items = list(items)
        msg = EmailMessage()
        msg["Subject"] = f"招标监控日报 {start_date} ~ {end_date}：{len(items)} 条"
        msg["From"] = self.mail_from
        msg["To"] = ", ".join(self.mail_to)
        msg.set_content(self._render_text(items, start_date, end_date))
        msg.add_alternative(self._render_html(items, start_date, end_date), subtype="html")

        if self.port == 465:
            with smtplib.SMTP_SSL(self.host, self.port, timeout=30) as smtp:
                smtp.login(self.user, self.password)
                smtp.send_message(msg)
        else:
            with smtplib.SMTP(self.host, self.port, timeout=30) as smtp:
                smtp.starttls()
                smtp.login(self.user, self.password)
                smtp.send_message(msg)
        return True

    def _render_text(self, items: List[Item], start_date, end_date) -> str:
        lines = [f"招标监控 {start_date} ~ {end_date}", f"共 {len(items)} 条", ""]
        if not items:
            lines.append("今日暂无命中项目。")
        for idx, item in enumerate(items, 1):
            lines.append(f"{idx}. {item.title}")
            lines.append(f"   {item.url}")
            lines.append(f"   关键词：{', '.join(item._matched_kws) or '-'}")
            if item._ai_analysis:
                lines.append(f"   AI分析：{item._ai_analysis}")
            lines.append("")
        return "\n".join(lines)

    def _render_html(self, items: List[Item], start_date, end_date) -> str:
        rows = []
        for idx, item in enumerate(items, 1):
            title = html.escape(item.title)
            url = html.escape(item.url)
            kws = html.escape(", ".join(item._matched_kws) or "-")
            ai = html.escape(item._ai_analysis or "-")
            rows.append(
                "<tr>"
                f"<td>{idx}</td>"
                f"<td><a href=\"{url}\">{title}</a></td>"
                f"<td>{kws}</td>"
                f"<td>{ai}</td>"
                f"<td>{item._score}</td>"
                "</tr>"
            )
        if not rows:
            rows.append("<tr><td colspan=\"5\">今日暂无命中项目。</td></tr>")
        return (
            "<html><body>"
            f"<h2>招标监控 {start_date} ~ {end_date}</h2>"
            f"<p>共 {len(items)} 条</p>"
            "<table border=\"1\" cellpadding=\"6\" cellspacing=\"0\">"
            "<thead><tr><th>#</th><th>项目</th><th>关键词</th><th>AI分析</th><th>分数</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody>"
            "</table></body></html>"
        )
