import sqlite3
from pathlib import Path

from .models import Item


class Store:
    def __init__(self, data_dir: str):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.data_dir / "bidding.sqlite3"
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self._init()

    def _init(self):
        self.conn.execute(
            """
            create table if not exists items (
              id integer primary key autoincrement,
              url text unique not null,
              title text not null,
              source text,
              publish_date text,
              body text,
              filter_stage text,
              match_type text,
              score integer,
              matched_kws text,
              business_hit text,
              non_target_hit text,
              ai_analysis text,
              human_label text,
              label_note text,
              created_at text default current_timestamp,
              updated_at text default current_timestamp
            )
            """
        )
        self._ensure_column("items", "ai_analysis", "text")
        self.conn.commit()

    def _ensure_column(self, table: str, column: str, decl: str):
        cols = {row["name"] for row in self.conn.execute(f"pragma table_info({table})").fetchall()}
        if column not in cols:
            self.conn.execute(f"alter table {table} add column {column} {decl}")

    def upsert(self, item: Item):
        self.conn.execute(
            """
            insert into items
              (url,title,source,publish_date,body,filter_stage,match_type,score,
               matched_kws,business_hit,non_target_hit,ai_analysis)
            values (?,?,?,?,?,?,?,?,?,?,?,?)
            on conflict(url) do update set
              title=excluded.title,
              source=excluded.source,
              publish_date=coalesce(excluded.publish_date, items.publish_date),
              body=coalesce(nullif(excluded.body,''), items.body),
              filter_stage=excluded.filter_stage,
              match_type=excluded.match_type,
              score=excluded.score,
              matched_kws=excluded.matched_kws,
              business_hit=excluded.business_hit,
              non_target_hit=excluded.non_target_hit,
              ai_analysis=excluded.ai_analysis,
              updated_at=current_timestamp
            """,
            (
                item.url,
                item.title,
                item.source,
                item.publish_date,
                item.body,
                item._filter_stage,
                item._match_type,
                item._score,
                ",".join(item._matched_kws),
                ",".join(item._business_hit),
                ",".join(item._non_target_hit),
                item._ai_analysis,
            ),
        )
        self.conn.commit()

    def rows(self, where="", params=()):
        sql = "select * from items"
        if where:
            sql += " where " + where
        sql += " order by publish_date desc, id desc"
        return self.conn.execute(sql, params).fetchall()

    def labeled_stats(self, kw: str = ""):
        where = "human_label in ('A','B','C')"
        params = []
        if kw:
            where += " and (title like ? or matched_kws like ? or business_hit like ? or non_target_hit like ?)"
            params = [f"%{kw}%"] * 4
        return self.rows(where, params)

    def label_url(self, url: str, label: str, note: str = "", force: bool = False) -> int:
        row = self.conn.execute("select human_label from items where url = ?", (url,)).fetchone()
        if not row:
            return 0
        if row["human_label"] and not force:
            return -1
        self.conn.execute(
            """
            update items
            set human_label = ?, label_note = ?, updated_at = current_timestamp
            where url = ?
            """,
            (label, note, url),
        )
        self.conn.commit()
        return 1

    def label_where(self, where: str, params=(), label: str = "", note: str = "", force: bool = False) -> int:
        guard = "" if force else " and (human_label is null or human_label = '')"
        cur = self.conn.execute(
            f"""
            update items
            set human_label = ?, label_note = ?, updated_at = current_timestamp
            where {where}{guard}
            """,
            (label, note, *params),
        )
        self.conn.commit()
        return cur.rowcount

    def close(self):
        self.conn.close()
