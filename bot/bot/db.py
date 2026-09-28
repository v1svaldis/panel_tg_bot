import json
import re
import sqlite3
import threading
from pathlib import Path

from bot.pricing import validate_percent
from bot.timeutil import iso, parse_dt, utcnow

_CODE_RE = re.compile(r"[A-Z0-9_-]{2,32}")


class Database:
    def __init__(self, path: Path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.Lock()
        self._write(self._migrate)

    def close(self) -> None:
        with self.lock:
            self.conn.close()

    def _write(self, fn):
        with self.lock:
            try:
                result = fn()
                self.conn.commit()
                return result
            except Exception:
                self.conn.rollback()
                raise

    def _migrate(self):
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
              tg_id INTEGER PRIMARY KEY,
              username TEXT,
              full_name TEXT,
              created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS nodes (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              kind TEXT NOT NULL,
              name TEXT NOT NULL,
              base_url TEXT NOT NULL,
              token TEXT NOT NULL,
              sub_base_url TEXT,
              protocols_json TEXT NOT NULL,
              enabled INTEGER NOT NULL DEFAULT 1,
              created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS plans (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              name TEXT NOT NULL,
              days INTEGER NOT NULL,
              price INTEGER NOT NULL,
              quota_gb INTEGER NOT NULL DEFAULT 0,
              enabled INTEGER NOT NULL DEFAULT 1,
              created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS promos (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              code TEXT NOT NULL UNIQUE,
              percent INTEGER NOT NULL,
              max_uses INTEGER,
              used INTEGER NOT NULL DEFAULT 0,
              expires_at TEXT,
              enabled INTEGER NOT NULL DEFAULT 1,
              created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS settings (
              key TEXT PRIMARY KEY,
              value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS orders (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              tg_id INTEGER NOT NULL,
              tg_username TEXT,
              tg_name TEXT,
              node_id INTEGER NOT NULL,
              plan_name TEXT NOT NULL,
              days INTEGER NOT NULL,
              quota_gb INTEGER NOT NULL,
              protocol TEXT NOT NULL,
              inbound_id INTEGER,
              protocol_label TEXT NOT NULL,
              promo_id INTEGER,
              promo_code TEXT,
              price INTEGER NOT NULL,
              status TEXT NOT NULL,
              comment TEXT,
              renew_key_id INTEGER,
              created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS keys (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              tg_id INTEGER NOT NULL,
              node_id INTEGER NOT NULL,
              protocol TEXT NOT NULL,
              protocol_label TEXT NOT NULL,
              inbound_id INTEGER,
              panel_user_id TEXT NOT NULL,
              username TEXT,
              sub_id TEXT,
              link TEXT NOT NULL,
              direct_link TEXT,
              expires_at TEXT NOT NULL,
              reminded_3 INTEGER NOT NULL DEFAULT 0,
              reminded_1 INTEGER NOT NULL DEFAULT 0,
              reminded_0 INTEGER NOT NULL DEFAULT 0,
              created_at TEXT NOT NULL
            );
            """
        )
        self._add_column("users", "blocked", "INTEGER NOT NULL DEFAULT 0")
        self._add_column("orders", "devices", "INTEGER NOT NULL DEFAULT 1")
        self._add_column("keys", "devices", "INTEGER NOT NULL DEFAULT 1")
        self._add_column("keys", "order_id", "INTEGER")

    def _add_column(self, table: str, name: str, ddl: str) -> None:
        cols = {row["name"] for row in self.conn.execute(f"PRAGMA table_info({table})")}
        if name not in cols:
            self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")

    def upsert_user(self, tg_id: int, username: str | None, full_name: str | None) -> None:
        now = iso(utcnow())

        def work():
            self.conn.execute(
                """
                INSERT INTO users (tg_id, username, full_name, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(tg_id) DO UPDATE SET
                  username=excluded.username,
                  full_name=excluded.full_name
                """,
                (tg_id, username, full_name, now),
            )

        self._write(work)

    def get_user(self, tg_id: int):
        with self.lock:
            row = self.conn.execute("SELECT * FROM users WHERE tg_id=?", (tg_id,)).fetchone()
        return dict(row) if row else None

    def is_blocked(self, tg_id: int) -> bool:
        user = self.get_user(tg_id)
        return bool(user and user.get("blocked"))

    def set_blocked(self, tg_id: int, blocked: bool) -> None:
        self._write(lambda: self.conn.execute(
            "UPDATE users SET blocked=? WHERE tg_id=?",
            (1 if blocked else 0, tg_id),
        ))

    def search_users(self, query: str):
        text = (query or "").strip().lstrip("@")
        if not text:
            return []
        with self.lock:
            if text.isdigit():
                row = self.conn.execute("SELECT * FROM users WHERE tg_id=?", (int(text),)).fetchone()
                return [dict(row)] if row else []
            rows = self.conn.execute(
                "SELECT * FROM users WHERE username = ? COLLATE NOCASE",
                (text,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_nodes(self, enabled_only: bool = True):
        sql = "SELECT * FROM nodes"
        if enabled_only:
            sql += " WHERE enabled=1"
        sql += " ORDER BY id"
        with self.lock:
            return [dict(r) for r in self.conn.execute(sql).fetchall()]

    def get_node(self, node_id: int):
        with self.lock:
            row = self.conn.execute("SELECT * FROM nodes WHERE id=?", (node_id,)).fetchone()
        return dict(row) if row else None

    def add_node(self, kind, name, base_url, token, sub_base_url, protocols) -> int:
        now = iso(utcnow())

        def work():
            cur = self.conn.execute(
                """
                INSERT INTO nodes (kind, name, base_url, token, sub_base_url, protocols_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (kind, name.strip(), base_url.strip(), token.strip(), (sub_base_url or "").strip(),
                 json.dumps(protocols, ensure_ascii=False), now),
            )
            return cur.lastrowid

        return self._write(work)

    def delete_node(self, node_id: int) -> str | None:
        def work():
            count = self.conn.execute(
                "SELECT COUNT(*) AS c FROM keys WHERE node_id=?", (node_id,)
            ).fetchone()["c"]
            if count:
                return "На этой локации ещё есть ключи. Сначала удалите их."
            cur = self.conn.execute("DELETE FROM nodes WHERE id=?", (node_id,))
            if cur.rowcount == 0:
                return "Локация не найдена"
            return None

        return self._write(work)

    def list_plans(self, enabled_only: bool = True):
        sql = "SELECT * FROM plans"
        if enabled_only:
            sql += " WHERE enabled=1"
        sql += " ORDER BY price, id"
        with self.lock:
            return [dict(r) for r in self.conn.execute(sql).fetchall()]

    def get_plan(self, plan_id: int):
        with self.lock:
            row = self.conn.execute("SELECT * FROM plans WHERE id=?", (plan_id,)).fetchone()
        return dict(row) if row else None

    def add_plan(self, name: str, days: int, price: int, quota_gb: int) -> int:
        if days < 1:
            raise ValueError("Срок должен быть больше 0 дней")
        if price < 0 or quota_gb < 0:
            raise ValueError("Цена и трафик не могут быть отрицательными")
        now = iso(utcnow())

        def work():
            cur = self.conn.execute(
                """
                INSERT INTO plans (name, days, price, quota_gb, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (name.strip(), days, price, quota_gb, now),
            )
            return cur.lastrowid

        return self._write(work)

    def delete_plan(self, plan_id: int) -> None:
        self._write(lambda: self.conn.execute("DELETE FROM plans WHERE id=?", (plan_id,)))

    def add_promo(self, code: str, percent: int, max_uses: int | None, expires_at: str | None) -> int:
        percent = validate_percent(percent)
        code = code.strip().upper()
        if not _CODE_RE.fullmatch(code):
            raise ValueError("Код: 2–32 символа, латиница, цифры, _ и -")
        now = iso(utcnow())

        def work():
            try:
                cur = self.conn.execute(
                    """
                    INSERT INTO promos (code, percent, max_uses, expires_at, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (code, percent, max_uses, expires_at, now),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError("Такой промокод уже есть") from exc
            return cur.lastrowid

        return self._write(work)

    def list_promos(self):
        with self.lock:
            return [dict(r) for r in self.conn.execute("SELECT * FROM promos ORDER BY id DESC").fetchall()]

    def delete_promo(self, promo_id: int) -> None:
        self._write(lambda: self.conn.execute("DELETE FROM promos WHERE id=?", (promo_id,)))

    def _promo_block(self, promo: dict) -> str | None:
        if promo.get("expires_at") and parse_dt(promo["expires_at"]) < utcnow():
            return "Срок промокода истёк"
        if promo["max_uses"] is not None and promo["used"] >= promo["max_uses"]:
            return "Промокод больше нельзя использовать"
        return None

    def find_promo(self, code: str):
        with self.lock:
            row = self.conn.execute(
                "SELECT * FROM promos WHERE code=? AND enabled=1",
                (code.strip().upper(),),
            ).fetchone()
        if not row:
            return None, "Промокод не найден"
        promo = dict(row)
        err = self._promo_block(promo)
        if err:
            return None, err
        return promo, None

    def reserve_promo(self, code: str):
        def work():
            row = self.conn.execute(
                "SELECT * FROM promos WHERE code=? AND enabled=1",
                (code.strip().upper(),),
            ).fetchone()
            if not row:
                return None, "Промокод не найден"
            promo = dict(row)
            err = self._promo_block(promo)
            if err:
                return None, err
            self.conn.execute("UPDATE promos SET used = used + 1 WHERE id=?", (promo["id"],))
            promo["used"] += 1
            return promo, None

        return self._write(work)

    def release_promo(self, promo_id: int) -> None:
        self._write(lambda: self.conn.execute(
            "UPDATE promos SET used = used - 1 WHERE id=? AND used > 0", (promo_id,)
        ))

    def get_setting(self, key: str, default: str = "") -> str:
        with self.lock:
            row = self.conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        self._write(lambda: self.conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        ))

    def create_order(self, **fields) -> int:
        now = iso(utcnow())

        def work():
            cur = self.conn.execute(
                """
                INSERT INTO orders (
                  tg_id, tg_username, tg_name, node_id, plan_name, days, quota_gb,
                  protocol, inbound_id, protocol_label, promo_id, promo_code,
                  price, status, comment, renew_key_id, devices, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    fields["tg_id"], fields.get("tg_username"), fields.get("tg_name"),
                    fields["node_id"], fields["plan_name"], fields["days"], fields["quota_gb"],
                    fields["protocol"], fields.get("inbound_id"), fields["protocol_label"],
                    fields.get("promo_id"), fields.get("promo_code"),
                    fields["price"], fields.get("status", "pending"),
                    (fields.get("comment") or "")[:500], fields.get("renew_key_id"),
                    fields.get("devices", 1), now,
                ),
            )
            return cur.lastrowid

        return self._write(work)

    def get_order(self, order_id: int):
        with self.lock:
            row = self.conn.execute(
                """
                SELECT o.*, n.name AS node_name, n.kind AS node_kind
                FROM orders o LEFT JOIN nodes n ON n.id = o.node_id
                WHERE o.id=?
                """,
                (order_id,),
            ).fetchone()
        return dict(row) if row else None

    def list_orders(self, status: str):
        with self.lock:
            return [dict(r) for r in self.conn.execute(
                """
                SELECT o.*, n.name AS node_name
                FROM orders o LEFT JOIN nodes n ON n.id = o.node_id
                WHERE o.status=?
                ORDER BY o.id DESC
                LIMIT 20
                """,
                (status,),
            ).fetchall()]

    def transition(self, order_id: int, from_status: str, to_status: str) -> bool:
        def work():
            cur = self.conn.execute(
                "UPDATE orders SET status=? WHERE id=? AND status=?",
                (to_status, order_id, from_status),
            )
            return cur.rowcount == 1

        return self._write(work)

    def add_key(self, **fields) -> int:
        now = iso(utcnow())

        def work():
            cur = self.conn.execute(
                """
                INSERT INTO keys (
                  tg_id, node_id, protocol, protocol_label, inbound_id, panel_user_id,
                  username, sub_id, link, direct_link, expires_at, devices, order_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    fields["tg_id"], fields["node_id"], fields["protocol"], fields["protocol_label"],
                    fields.get("inbound_id"), fields["panel_user_id"], fields.get("username"),
                    fields.get("sub_id"), fields["link"], fields.get("direct_link"),
                    fields["expires_at"], fields.get("devices", 1), fields.get("order_id"), now,
                ),
            )
            return cur.lastrowid

        return self._write(work)

    def get_key(self, key_id: int):
        with self.lock:
            row = self.conn.execute(
                """
                SELECT k.*, n.name AS node_name, n.kind AS node_kind
                FROM keys k JOIN nodes n ON n.id = k.node_id
                WHERE k.id=?
                """,
                (key_id,),
            ).fetchone()
        return dict(row) if row else None

    def list_keys(self, tg_id: int):
        with self.lock:
            return [dict(r) for r in self.conn.execute(
                """
                SELECT k.*, n.name AS node_name
                FROM keys k JOIN nodes n ON n.id = k.node_id
                WHERE k.tg_id=?
                ORDER BY k.id DESC
                """,
                (tg_id,),
            ).fetchall()]

    def list_keys_all(self):
        with self.lock:
            return [dict(r) for r in self.conn.execute(
                """
                SELECT k.*, n.name AS node_name
                FROM keys k JOIN nodes n ON n.id = k.node_id
                ORDER BY k.id
                """
            ).fetchall()]

    def used_slots(self, tg_id: int) -> int:
        with self.lock:
            row = self.conn.execute(
                "SELECT COALESCE(SUM(devices), 0) AS s FROM keys WHERE tg_id=?",
                (tg_id,),
            ).fetchone()
        return int(row["s"])

    def count_keys(self, tg_id: int) -> int:
        with self.lock:
            row = self.conn.execute(
                "SELECT COUNT(*) AS c FROM keys WHERE tg_id=?",
                (tg_id,),
            ).fetchone()
        return int(row["c"])

    def keys_for_order(self, order_id: int):
        with self.lock:
            return [dict(row) for row in self.conn.execute(
                """
                SELECT k.*, n.name AS node_name
                FROM keys k LEFT JOIN nodes n ON n.id = k.node_id
                WHERE k.order_id=?
                ORDER BY k.id
                """,
                (order_id,),
            ).fetchall()]

    def delete_key(self, key_id: int) -> None:
        self._write(lambda: self.conn.execute("DELETE FROM keys WHERE id=?", (key_id,)))

    def update_key_expiry(self, key_id: int, expires_at: str) -> None:
        self._write(lambda: self.conn.execute(
            """
            UPDATE keys
            SET expires_at=?, reminded_3=0, reminded_1=0, reminded_0=0
            WHERE id=?
            """,
            (expires_at, key_id),
        ))

    def mark_reminded(self, key_id: int, kind: int) -> None:
        if kind == 3:
            sql = "UPDATE keys SET reminded_3=1 WHERE id=?"
        elif kind == 1:
            sql = "UPDATE keys SET reminded_1=1, reminded_3=1 WHERE id=?"
        elif kind == 0:
            sql = "UPDATE keys SET reminded_0=1, reminded_1=1, reminded_3=1 WHERE id=?"
        else:
            return
        self._write(lambda: self.conn.execute(sql, (key_id,)))
