"""Persistent, local management storage for the PAY.153 operations center.

The module keeps the management interface deliberately small: callers deal in
plain dictionaries while this implementation owns SQLite connections,
encryption, masking, migrations and legacy-file import.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken


SCHEMA = """
CREATE TABLE IF NOT EXISTS proxy_pools (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    external_key TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    rail TEXT NOT NULL DEFAULT '',
    country TEXT NOT NULL DEFAULT '',
    region TEXT NOT NULL DEFAULT '',
    pool_kind TEXT NOT NULL DEFAULT 'entry',
    payload TEXT NOT NULL,
    proxy_count INTEGER NOT NULL DEFAULT 0,
    enabled INTEGER NOT NULL DEFAULT 1,
    last_checked_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS billing_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_key TEXT NOT NULL UNIQUE,
    rail TEXT NOT NULL DEFAULT '',
    country TEXT NOT NULL DEFAULT '',
    region TEXT NOT NULL DEFAULT '',
    payload TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'manual',
    verified_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS asn_recommendations (
    country TEXT PRIMARY KEY,
    region TEXT NOT NULL DEFAULT '',
    label TEXT NOT NULL DEFAULT '',
    items_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS success_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL UNIQUE,
    recorded_at TEXT NOT NULL,
    link_type TEXT NOT NULL DEFAULT '',
    plan TEXT NOT NULL DEFAULT '',
    country TEXT NOT NULL DEFAULT '',
    currency TEXT NOT NULL DEFAULT '',
    account_ref_hash TEXT NOT NULL DEFAULT '',
    account_email_secret TEXT NOT NULL DEFAULT '',
    account_id_secret TEXT NOT NULL DEFAULT '',
    entry_ip_secret TEXT NOT NULL DEFAULT '',
    entry_country TEXT NOT NULL DEFAULT '',
    entry_region TEXT NOT NULL DEFAULT '',
    entry_city TEXT NOT NULL DEFAULT '',
    payment_ip_secret TEXT NOT NULL DEFAULT '',
    payment_country TEXT NOT NULL DEFAULT '',
    payment_region TEXT NOT NULL DEFAULT '',
    payment_city TEXT NOT NULL DEFAULT '',
    checkout_amount TEXT NOT NULL DEFAULT '',
    checkout_url_secret TEXT NOT NULL DEFAULT '',
    attempt INTEGER,
    max_attempts INTEGER
);

CREATE INDEX IF NOT EXISTS idx_proxy_pools_country ON proxy_pools(country, rail, pool_kind);
CREATE INDEX IF NOT EXISTS idx_billing_profiles_country ON billing_profiles(country, rail);
CREATE INDEX IF NOT EXISTS idx_success_records_recorded_at ON success_records(recorded_at DESC);
CREATE INDEX IF NOT EXISTS idx_success_records_country ON success_records(country, link_type);
"""


def now_text() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def text(value: Any, limit: int = 240) -> str:
    return str(value or "").strip()[:limit]


def normalize_country(value: Any) -> str:
    value = text(value, 2).upper()
    return value if re.fullmatch(r"[A-Z]{2}", value) else ""


def normalize_asn(value: Any) -> str:
    match = re.fullmatch(r"AS?(\d{1,10})", text(value, 20).upper())
    return f"AS{match.group(1)}" if match else ""


def account_hash(email: str, account_id: str) -> str:
    value = text(email, 240).lower() or text(account_id, 240)
    return hashlib.sha256(value.encode("utf-8")).hexdigest() if value else ""


def mask_email(value: str) -> str:
    value = text(value, 240)
    if "@" not in value:
        return value[:3] + "…" if len(value) > 3 else value
    local, domain = value.split("@", 1)
    visible = local[:2] if len(local) > 2 else local[:1]
    return f"{visible}***@{domain}"


def mask_ip(value: str) -> str:
    value = text(value, 80)
    if ":" in value:
        parts = value.split(":")
        return ":".join(parts[:3] + ["*"]) if len(parts) > 3 else value
    parts = value.split(".")
    return ".".join(parts[:3] + ["*"]) if len(parts) == 4 else value


def mask_account_id(value: str) -> str:
    value = text(value, 240)
    return f"{value[:4]}…{value[-4:]}" if len(value) > 10 else value


def mask_display(value: str) -> str:
    value = text(value, 240)
    if len(value) <= 2:
        return "•••" if value else ""
    if len(value) <= 6:
        return f"{value[:1]}…{value[-1:]}"
    return f"{value[:2]}…{value[-2:]}"


def mask_address(value: str) -> str:
    value = text(value, 240)
    if len(value) <= 5:
        return "•••" if value else ""
    return f"{value[:3]}…{value[-2:]}"


def mask_proxy(value: str) -> str:
    value = text(value, 500)
    if "@" in value:
        prefix, address = value.rsplit("@", 1)
        scheme = ""
        if "://" in prefix:
            scheme, prefix = prefix.split("://", 1)
            scheme += "://"
        return f"{scheme}***:***@{address}"
    parts = value.split(":")
    if len(parts) >= 4:
        return ":".join(parts[:2] + ["***", "***"])
    return value


class ManageStore:
    """Deep persistence module behind the /manage interface."""

    def __init__(self, db_path: str | Path, encryption_key: bytes | str, legacy_success_path: str | Path | None = None):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(encryption_key, str):
            encryption_key = encryption_key.encode("ascii")
        self._fernet = Fernet(encryption_key)
        self._lock = threading.RLock()
        self._initialize()
        if legacy_success_path:
            self.import_legacy_success_links(legacy_success_path)

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.db_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._lock, self._connect() as connection:
            connection.executescript(SCHEMA)
            connection.commit()

    def _seal(self, value: Any) -> str:
        if value in (None, "", [], {}):
            return ""
        raw = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        return self._fernet.encrypt(raw).decode("ascii")

    def _open(self, value: str, default: Any = None) -> Any:
        if not value:
            return default
        try:
            raw = self._fernet.decrypt(value.encode("ascii"))
            return json.loads(raw.decode("utf-8"))
        except (InvalidToken, ValueError, json.JSONDecodeError):
            return default

    @staticmethod
    def _items(items: Any) -> list[dict[str, str]]:
        output: list[dict[str, str]] = []
        seen: set[str] = set()
        if not isinstance(items, list):
            return output
        for item in items:
            if isinstance(item, str):
                asn = normalize_asn(item)
                item = {"asn": asn, "provider": "", "tier": "B", "note": ""}
            if not isinstance(item, dict):
                continue
            asn = normalize_asn(item.get("asn"))
            if not asn or asn in seen:
                continue
            seen.add(asn)
            tier = text(item.get("tier"), 1).upper()
            output.append({
                "asn": asn,
                "provider": text(item.get("provider"), 80),
                "tier": tier if tier in {"A", "B", "C"} else "B",
                "note": text(item.get("note"), 160),
            })
        return output

    def seed_asn_recommendations(self, defaults: dict[str, dict[str, Any]]) -> None:
        for country, value in defaults.items():
            country = normalize_country(country)
            items = self._items(value.get("items")) if isinstance(value, dict) else []
            if not country or not items:
                continue
            with self._lock, self._connect() as connection:
                connection.execute(
                    """INSERT OR IGNORE INTO asn_recommendations
                       (country, region, label, items_json, updated_at)
                       VALUES (?, ?, ?, ?, ?)""",
                    (country, text(value.get("region"), 80), text(value.get("label"), 80), json.dumps(items, ensure_ascii=False), now_text()),
                )
                connection.commit()

    def summary(self) -> dict[str, Any]:
        with self._lock, self._connect() as connection:
            counts = {}
            for key, table in (
                ("proxy_pools", "proxy_pools"),
                ("billing_profiles", "billing_profiles"),
                ("asn_regions", "asn_recommendations"),
                ("success_records", "success_records"),
            ):
                counts[key] = int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            latest = connection.execute(
                "SELECT recorded_at, country, link_type FROM success_records ORDER BY recorded_at DESC LIMIT 1"
            ).fetchone()
        return {
            **counts,
            "last_success": dict(latest) if latest else None,
            "storage": "sqlite",
        }

    def upsert_proxy_pool(self, payload: dict[str, Any]) -> dict[str, Any]:
        pool_id = payload.get("id")
        external_key = text(payload.get("external_key"), 180) or f"manual:{uuid.uuid4().hex}"
        proxies = [text(item, 600) for item in (payload.get("proxies") or []) if text(item, 600)]
        name = text(payload.get("name"), 120) or "未命名代理池"
        rail = text(payload.get("rail"), 40) or "shared"
        country = normalize_country(payload.get("country"))
        region = text(payload.get("region"), 80)
        pool_kind = text(payload.get("pool_kind"), 30) or "entry"
        sealed_payload = self._seal({"proxies": proxies})
        proxy_count = len(proxies)
        enabled = 1 if payload.get("enabled", True) else 0
        updated_at = now_text()
        with self._lock, self._connect() as connection:
            if pool_id:
                try:
                    cursor = connection.execute(
                        """UPDATE proxy_pools SET external_key=?, name=?, rail=?, country=?, region=?,
                           pool_kind=?, payload=?, proxy_count=?, enabled=?, updated_at=? WHERE id=?""",
                        (external_key, name, rail, country, region, pool_kind, sealed_payload, proxy_count, enabled, updated_at, int(pool_id)),
                    )
                except sqlite3.IntegrityError as exc:
                    raise ValueError("代理池标识已存在") from exc
                if not cursor.rowcount:
                    return {}
            else:
                connection.execute(
                    """INSERT INTO proxy_pools
                       (external_key, name, rail, country, region, pool_kind, payload, proxy_count, enabled, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(external_key) DO UPDATE SET name=excluded.name, rail=excluded.rail,
                       country=excluded.country, region=excluded.region, pool_kind=excluded.pool_kind,
                       payload=excluded.payload, proxy_count=excluded.proxy_count, enabled=excluded.enabled,
                       updated_at=excluded.updated_at""",
                    (external_key, name, rail, country, region, pool_kind, sealed_payload, proxy_count, enabled, updated_at, updated_at),
                )
            connection.commit()
            row = connection.execute(
                "SELECT * FROM proxy_pools WHERE id=? OR external_key=? ORDER BY id DESC LIMIT 1",
                (int(pool_id or 0), external_key),
            ).fetchone()
        return self._proxy_row(row, reveal=False)

    def _proxy_row(self, row: sqlite3.Row | None, reveal: bool = False) -> dict[str, Any]:
        if not row:
            return {}
        payload = self._open(row["payload"], {}) or {}
        proxies = payload.get("proxies") if isinstance(payload, dict) else []
        proxies = proxies if isinstance(proxies, list) else []
        result = {
            "id": row["id"], "external_key": row["external_key"], "name": row["name"],
            "rail": row["rail"], "country": row["country"], "region": row["region"],
            "pool_kind": row["pool_kind"], "proxy_count": row["proxy_count"],
            "enabled": bool(row["enabled"]), "last_checked_at": row["last_checked_at"],
            "created_at": row["created_at"], "updated_at": row["updated_at"],
            "proxy_preview": [mask_proxy(item) for item in proxies[:3]],
        }
        if reveal:
            result["proxies"] = proxies
        return result

    def list_proxy_pools(self, country: str = "", rail: str = "") -> list[dict[str, Any]]:
        conditions: list[str] = []
        values: list[Any] = []
        if normalize_country(country):
            conditions.append("country=?")
            values.append(normalize_country(country))
        if text(rail, 40):
            conditions.append("rail=?")
            values.append(text(rail, 40))
        where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        with self._lock, self._connect() as connection:
            rows = connection.execute(f"SELECT * FROM proxy_pools{where} ORDER BY country, rail, pool_kind, id", values).fetchall()
        return [self._proxy_row(row) for row in rows]

    def get_proxy_pool(self, pool_id: int, reveal: bool = False) -> dict[str, Any]:
        with self._lock, self._connect() as connection:
            row = connection.execute("SELECT * FROM proxy_pools WHERE id=?", (int(pool_id),)).fetchone()
        return self._proxy_row(row, reveal=reveal)

    def delete_proxy_pool(self, pool_id: int) -> bool:
        with self._lock, self._connect() as connection:
            cursor = connection.execute("DELETE FROM proxy_pools WHERE id=?", (int(pool_id),))
            connection.commit()
            return cursor.rowcount > 0

    def upsert_billing_profile(self, payload: dict[str, Any]) -> dict[str, Any]:
        profile_id = payload.get("id")
        profile_key = text(payload.get("profile_key"), 180)
        if not profile_key:
            profile_key = f"{text(payload.get('rail'), 40) or 'hosted'}:{normalize_country(payload.get('country')) or 'US'}"
        profile = {
            key: text(payload.get(key), 240)
            for key in ("name", "email", "line1", "line2", "city", "state", "postal_code")
        }
        country = normalize_country(payload.get("country"))
        rail = text(payload.get("rail"), 40)
        region = text(payload.get("region"), 80)
        sealed_profile = self._seal(profile)
        source = text(payload.get("source"), 40) or "manual"
        verified_at = text(payload.get("verified_at"), 40) or None
        updated_at = now_text()
        with self._lock, self._connect() as connection:
            row = None
            if profile_id:
                try:
                    cursor = connection.execute(
                        """UPDATE billing_profiles SET profile_key=?, rail=?, country=?, region=?, payload=?,
                           source=?, verified_at=?, updated_at=? WHERE id=?""",
                        (profile_key, rail, country, region, sealed_profile, source, verified_at, updated_at, int(profile_id)),
                    )
                except sqlite3.IntegrityError as exc:
                    raise ValueError("账单档案键已存在") from exc
                if cursor.rowcount:
                    row = connection.execute("SELECT * FROM billing_profiles WHERE id=?", (int(profile_id),)).fetchone()
            if row is None:
                connection.execute(
                    """INSERT INTO billing_profiles
                       (profile_key, rail, country, region, payload, source, verified_at, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(profile_key) DO UPDATE SET rail=excluded.rail, country=excluded.country,
                       region=excluded.region, payload=excluded.payload, source=excluded.source,
                       verified_at=excluded.verified_at, updated_at=excluded.updated_at""",
                    (profile_key, rail, country, region, sealed_profile, source, verified_at, now_text(), updated_at),
                )
                row = connection.execute("SELECT * FROM billing_profiles WHERE profile_key=?", (profile_key,)).fetchone()
            connection.commit()
        return self._billing_row(row, reveal=False)

    def _billing_row(self, row: sqlite3.Row | None, reveal: bool = False) -> dict[str, Any]:
        if not row:
            return {}
        profile = self._open(row["payload"], {}) or {}
        result = {
            "id": row["id"], "profile_key": row["profile_key"], "rail": row["rail"],
            "country": row["country"], "region": row["region"], "source": row["source"],
            "verified_at": row["verified_at"], "created_at": row["created_at"], "updated_at": row["updated_at"],
            "name_masked": mask_display(profile.get("name", "")),
            "email_masked": mask_email(profile.get("email", "")),
            "address_masked": " · ".join(filter(None, [
                mask_address(profile.get("line1", "")),
                mask_display(profile.get("city", "")),
                mask_address(profile.get("postal_code", "")),
            ]))[:180],
        }
        if reveal:
            result["profile"] = profile
        return result

    def list_billing_profiles(self, country: str = "", rail: str = "") -> list[dict[str, Any]]:
        conditions: list[str] = []
        values: list[Any] = []
        if normalize_country(country):
            conditions.append("country=?")
            values.append(normalize_country(country))
        if text(rail, 40):
            conditions.append("rail=?")
            values.append(text(rail, 40))
        where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        with self._lock, self._connect() as connection:
            rows = connection.execute(f"SELECT * FROM billing_profiles{where} ORDER BY country, rail, profile_key", values).fetchall()
        return [self._billing_row(row) for row in rows]

    def get_billing_profile(self, profile_id: int, reveal: bool = False) -> dict[str, Any]:
        with self._lock, self._connect() as connection:
            row = connection.execute("SELECT * FROM billing_profiles WHERE id=?", (int(profile_id),)).fetchone()
        return self._billing_row(row, reveal=reveal)

    def delete_billing_profile(self, profile_id: int) -> bool:
        with self._lock, self._connect() as connection:
            cursor = connection.execute("DELETE FROM billing_profiles WHERE id=?", (int(profile_id),))
            connection.commit()
            return cursor.rowcount > 0

    def upsert_asn_recommendation(self, payload: dict[str, Any]) -> dict[str, Any]:
        country = normalize_country(payload.get("country"))
        items = self._items(payload.get("items"))
        if not country:
            raise ValueError("国家/地区需要使用两位国家代码")
        if not items:
            raise ValueError("至少需要一个有效 ASN")
        with self._lock, self._connect() as connection:
            connection.execute(
                """INSERT INTO asn_recommendations (country, region, label, items_json, updated_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(country) DO UPDATE SET region=excluded.region, label=excluded.label,
                   items_json=excluded.items_json, updated_at=excluded.updated_at""",
                (country, text(payload.get("region"), 80), text(payload.get("label"), 80) or country, json.dumps(items, ensure_ascii=False), now_text()),
            )
            connection.commit()
            row = connection.execute("SELECT * FROM asn_recommendations WHERE country=?", (country,)).fetchone()
        return self._asn_row(row)

    def _asn_row(self, row: sqlite3.Row | None) -> dict[str, Any]:
        if not row:
            return {}
        try:
            items = json.loads(row["items_json"])
        except json.JSONDecodeError:
            items = []
        return {
            "country": row["country"], "region": row["region"], "label": row["label"],
            "items": self._items(items), "updated_at": row["updated_at"],
        }

    def list_asn_recommendations(self, country: str = "") -> list[dict[str, Any]]:
        country = normalize_country(country)
        with self._lock, self._connect() as connection:
            if country:
                rows = connection.execute("SELECT * FROM asn_recommendations WHERE country=?", (country,)).fetchall()
            else:
                rows = connection.execute("SELECT * FROM asn_recommendations ORDER BY country").fetchall()
        return [self._asn_row(row) for row in rows]

    def record_success(self, result: dict[str, Any]) -> dict[str, Any]:
        job_id = text(result.get("job_id"), 100) or f"legacy-{uuid.uuid4().hex}"
        email = text(result.get("account_email"), 240)
        account_id = text(result.get("account_id"), 240)
        values = (
            job_id, text(result.get("recorded_at"), 40) or now_text(), text(result.get("link_type"), 40),
            text(result.get("plan"), 40), normalize_country(result.get("country")), text(result.get("currency"), 20),
            account_hash(email, account_id), self._seal(email), self._seal(account_id),
            self._seal(text(result.get("entry_ip"), 100)), normalize_country(result.get("entry_country")),
            text(result.get("entry_region"), 100), text(result.get("entry_city"), 100),
            self._seal(text(result.get("payment_ip"), 100)), normalize_country(result.get("payment_proxy_country") or result.get("payment_country")),
            text(result.get("payment_region"), 100), text(result.get("payment_city"), 100),
            text(result.get("checkout_amount"), 60), self._seal(text(result.get("url"), 1200)),
            result.get("attempt"), result.get("max_attempts"),
        )
        with self._lock, self._connect() as connection:
            connection.execute(
                """INSERT INTO success_records
                   (job_id, recorded_at, link_type, plan, country, currency, account_ref_hash,
                    account_email_secret, account_id_secret, entry_ip_secret, entry_country, entry_region,
                    entry_city, payment_ip_secret, payment_country, payment_region, payment_city,
                    checkout_amount, checkout_url_secret, attempt, max_attempts)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(job_id) DO UPDATE SET recorded_at=excluded.recorded_at,
                   link_type=excluded.link_type, plan=excluded.plan, country=excluded.country,
                   currency=excluded.currency, account_ref_hash=excluded.account_ref_hash,
                   account_email_secret=excluded.account_email_secret, account_id_secret=excluded.account_id_secret,
                   entry_ip_secret=excluded.entry_ip_secret, entry_country=excluded.entry_country,
                   entry_region=excluded.entry_region, entry_city=excluded.entry_city,
                   payment_ip_secret=excluded.payment_ip_secret, payment_country=excluded.payment_country,
                   payment_region=excluded.payment_region, payment_city=excluded.payment_city,
                   checkout_amount=excluded.checkout_amount, checkout_url_secret=excluded.checkout_url_secret,
                   attempt=excluded.attempt, max_attempts=excluded.max_attempts""",
                values,
            )
            connection.commit()
            row = connection.execute("SELECT * FROM success_records WHERE job_id=?", (job_id,)).fetchone()
        return self._success_row(row)

    def _success_row(self, row: sqlite3.Row | None, reveal: bool = False) -> dict[str, Any]:
        if not row:
            return {}
        email = self._open(row["account_email_secret"], "") or ""
        account_id = self._open(row["account_id_secret"], "") or ""
        entry_ip = self._open(row["entry_ip_secret"], "") or ""
        payment_ip = self._open(row["payment_ip_secret"], "") or ""
        url = self._open(row["checkout_url_secret"], "") or ""
        result = {
            "id": row["id"], "job_id": row["job_id"], "recorded_at": row["recorded_at"],
            "link_type": row["link_type"], "plan": row["plan"], "country": row["country"],
            "currency": row["currency"], "account": mask_email(email), "account_id": mask_account_id(account_id),
            "entry_ip": mask_ip(entry_ip), "entry_country": row["entry_country"],
            "entry_region": row["entry_region"], "entry_city": row["entry_city"],
            "payment_ip": mask_ip(payment_ip), "payment_country": row["payment_country"],
            "payment_region": row["payment_region"], "payment_city": row["payment_city"],
            "checkout_amount": row["checkout_amount"], "attempt": row["attempt"],
            "max_attempts": row["max_attempts"],
        }
        if reveal:
            result.update({"account_email": email, "account_id_raw": account_id, "entry_ip_raw": entry_ip, "payment_ip_raw": payment_ip, "url": url})
        return result

    def list_success_records(self, limit: int = 100, country: str = "", link_type: str = "", query: str = "") -> list[dict[str, Any]]:
        conditions: list[str] = []
        values: list[Any] = []
        if normalize_country(country):
            conditions.append("country=?")
            values.append(normalize_country(country))
        if text(link_type, 40):
            conditions.append("link_type=?")
            values.append(text(link_type, 40))
        where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM success_records{where} ORDER BY recorded_at DESC LIMIT ?",
                (*values, max(1, min(int(limit or 100), 500))),
            ).fetchall()
        output = [self._success_row(row) for row in rows]
        query = text(query, 120).lower()
        if query:
            output = [item for item in output if query in json.dumps(item, ensure_ascii=False).lower()]
        return output

    def import_legacy_success_links(self, path: str | Path) -> int:
        path = Path(path)
        if not path.exists():
            return 0
        imported = 0
        try:
            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(record, dict):
                        continue
                    before = self.get_success_by_job(text(record.get("job_id"), 100))
                    self.record_success(record)
                    if not before:
                        imported += 1
        except OSError:
            return imported
        return imported

    def get_success_by_job(self, job_id: str) -> dict[str, Any]:
        job_id = text(job_id, 100)
        if not job_id:
            return {}
        with self._lock, self._connect() as connection:
            row = connection.execute("SELECT * FROM success_records WHERE job_id=?", (job_id,)).fetchone()
        return self._success_row(row)
