#!/usr/bin/env python3
"""LAN Share Pro: complete local network file sharing server.

Features:
- Password login and cookie sessions
- SQLite metadata and share codes
- Stream upload/download for large files
- HTTP range support for resumable download
- Search, pagination, and stats APIs
- Protected file storage path handling
"""

from __future__ import annotations

import hashlib
import hmac
import json
import mimetypes
import os
import queue
import re
import secrets
import shutil
import socket
import sqlite3
import threading
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterator

ROOT_DIR = Path(__file__).resolve().parent
WEB_DIR = ROOT_DIR / "web"
DATA_DIR = Path(os.getenv("LAN_SHARE_DATA_DIR", ROOT_DIR / "data"))
UPLOAD_DIR = Path(os.getenv("LAN_SHARE_UPLOAD_DIR", ROOT_DIR / "uploads"))
DB_PATH = DATA_DIR / "lan_share.db"
PASSWORD_FILE = DATA_DIR / "admin_password.txt"

HOST = os.getenv("LAN_SHARE_HOST", "0.0.0.0")
PORT = int(os.getenv("LAN_SHARE_PORT", "8765"))
MAX_UPLOAD_MB = int(os.getenv("LAN_SHARE_MAX_MB", "4096"))
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024
SESSION_HOURS = int(os.getenv("LAN_SHARE_SESSION_HOURS", "24"))


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_now_iso() -> str:
    return utc_now().isoformat(timespec="seconds")


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value)


def load_or_create_password() -> str:
    env_password = os.getenv("LAN_SHARE_PASSWORD", "").strip()
    if env_password:
        return env_password

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if PASSWORD_FILE.exists():
        stored = PASSWORD_FILE.read_text(encoding="utf-8").strip()
        if stored:
            return stored

    generated = secrets.token_urlsafe(14)
    PASSWORD_FILE.write_text(generated, encoding="utf-8")
    os.chmod(PASSWORD_FILE, 0o600)
    return generated


ADMIN_PASSWORD = load_or_create_password()


def get_local_ipv4() -> list[str]:
    addresses: set[str] = set()
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = info[4][0]
            if ip and not ip.startswith("127."):
                addresses.add(ip)
    except OSError:
        pass

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            if ip and not ip.startswith("127."):
                addresses.add(ip)
    except OSError:
        pass

    return sorted(addresses)


def sanitize_filename(filename: str) -> str:
    name = Path(filename).name
    name = name.replace("\x00", "")
    name = re.sub(r"[\r\n]+", "_", name).strip()
    if not name:
        name = "unnamed.bin"
    if len(name) > 180:
        stem = Path(name).stem[:150] or "file"
        suffix = Path(name).suffix[:20]
        name = f"{stem}{suffix}"
    return name


def safe_join(base: Path, child_name: str) -> Path:
    base_resolved = base.resolve()
    target = (base / child_name).resolve()
    if base_resolved != target and base_resolved not in target.parents:
        raise ValueError("Invalid storage path")
    return target


@dataclass
class Session:
    token: str
    expires_at: datetime


class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}
        self._lock = threading.Lock()

    def issue(self) -> str:
        token = secrets.token_urlsafe(32)
        expires = utc_now() + timedelta(hours=SESSION_HOURS)
        with self._lock:
            self._sessions[token] = Session(token=token, expires_at=expires)
        return token

    def validate(self, token: str | None) -> bool:
        if not token:
            return False
        now = utc_now()
        with self._lock:
            session = self._sessions.get(token)
            if not session:
                return False
            if session.expires_at < now:
                self._sessions.pop(token, None)
                return False
            return True

    def revoke(self, token: str | None) -> None:
        if not token:
            return
        with self._lock:
            self._sessions.pop(token, None)

    def cleanup(self) -> None:
        now = utc_now()
        with self._lock:
            expired = [t for t, s in self._sessions.items() if s.expires_at < now]
            for token in expired:
                self._sessions.pop(token, None)


class LoginGuard:
    def __init__(self, max_attempts: int = 6, lock_seconds: int = 90):
        self.max_attempts = max_attempts
        self.lock_seconds = lock_seconds
        self._state: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def check_allowed(self, ip: str) -> tuple[bool, int]:
        now = utc_now()
        with self._lock:
            info = self._state.get(ip)
            if not info:
                return True, 0
            lock_until = info.get("lock_until")
            if lock_until and lock_until > now:
                remaining = int((lock_until - now).total_seconds())
                return False, max(remaining, 1)
            if lock_until and lock_until <= now:
                self._state.pop(ip, None)
            return True, 0

    def record_fail(self, ip: str) -> None:
        now = utc_now()
        with self._lock:
            info = self._state.setdefault(ip, {"count": 0, "lock_until": None})
            info["count"] = int(info.get("count", 0)) + 1
            if info["count"] >= self.max_attempts:
                info["lock_until"] = now + timedelta(seconds=self.lock_seconds)
                info["count"] = 0

    def record_success(self, ip: str) -> None:
        with self._lock:
            self._state.pop(ip, None)


class Database:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._lock = threading.Lock()
        self.conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        schema = """
        CREATE TABLE IF NOT EXISTS files (
            id TEXT PRIMARY KEY,
            stored_name TEXT UNIQUE NOT NULL,
            original_name TEXT NOT NULL,
            mime_type TEXT NOT NULL,
            size_bytes INTEGER NOT NULL,
            sha256 TEXT NOT NULL,
            created_at TEXT NOT NULL,
            uploaded_by TEXT NOT NULL,
            downloads INTEGER NOT NULL DEFAULT 0,
            deleted INTEGER NOT NULL DEFAULT 0,
            deleted_at TEXT
        );

        CREATE TABLE IF NOT EXISTS shares (
            code TEXT PRIMARY KEY,
            file_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            max_downloads INTEGER NOT NULL,
            download_count INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY (file_id) REFERENCES files(id)
        );

        CREATE TABLE IF NOT EXISTS notes (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            content TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL,
            updated_by TEXT NOT NULL
        );

        INSERT OR IGNORE INTO notes (id, content, updated_at, updated_by)
        VALUES (1, '', '1970-01-01T00:00:00+00:00', 'system');

        CREATE INDEX IF NOT EXISTS idx_files_created_at ON files(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_files_original_name ON files(original_name);
        CREATE INDEX IF NOT EXISTS idx_shares_file_id ON shares(file_id);
        """
        with self._lock:
            self.conn.executescript(schema)
            self.conn.commit()

    def add_file(
        self,
        file_id: str,
        stored_name: str,
        original_name: str,
        mime_type: str,
        size_bytes: int,
        sha256: str,
        uploaded_by: str,
    ) -> None:
        sql = """
        INSERT INTO files (id, stored_name, original_name, mime_type, size_bytes, sha256, created_at, uploaded_by)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """
        with self._lock:
            self.conn.execute(
                sql,
                (file_id, stored_name, original_name, mime_type, size_bytes, sha256, utc_now_iso(), uploaded_by),
            )
            self.conn.commit()

    def get_file(self, file_id: str, include_deleted: bool = False) -> sqlite3.Row | None:
        sql = "SELECT * FROM files WHERE id = ?"
        params: list[Any] = [file_id]
        if not include_deleted:
            sql += " AND deleted = 0"
        with self._lock:
            row = self.conn.execute(sql, params).fetchone()
        return row

    def list_files(self, query: str, page: int, page_size: int, sort: str, order: str) -> dict[str, Any]:
        sort_map = {
            "created_at": "created_at",
            "size": "size_bytes",
            "name": "original_name COLLATE NOCASE",
            "downloads": "downloads",
        }
        sort_sql = sort_map.get(sort, "created_at")
        order_sql = "ASC" if order.lower() == "asc" else "DESC"

        where = "WHERE deleted = 0"
        params: list[Any] = []
        if query:
            where += " AND original_name LIKE ?"
            params.append(f"%{query}%")

        offset = (page - 1) * page_size
        count_sql = f"SELECT COUNT(*) AS total FROM files {where}"
        list_sql = (
            "SELECT * FROM files "
            f"{where} ORDER BY {sort_sql} {order_sql} LIMIT ? OFFSET ?"
        )

        with self._lock:
            total = int(self.conn.execute(count_sql, params).fetchone()["total"])
            rows = self.conn.execute(list_sql, [*params, page_size, offset]).fetchall()

        return {"total": total, "items": rows}

    def increment_download(self, file_id: str) -> None:
        with self._lock:
            self.conn.execute("UPDATE files SET downloads = downloads + 1 WHERE id = ?", (file_id,))
            self.conn.commit()

    def soft_delete_file(self, file_id: str) -> int:
        with self._lock:
            cur = self.conn.execute(
                "UPDATE files SET deleted = 1, deleted_at = ? WHERE id = ? AND deleted = 0",
                (utc_now_iso(), file_id),
            )
            self.conn.commit()
            return cur.rowcount

    def stats(self) -> dict[str, Any]:
        with self._lock:
            totals = self.conn.execute(
                "SELECT COUNT(*) AS file_count, COALESCE(SUM(size_bytes), 0) AS total_size FROM files WHERE deleted = 0"
            ).fetchone()
            today = utc_now() - timedelta(days=1)
            recent = self.conn.execute(
                "SELECT COUNT(*) AS uploaded_24h FROM files WHERE deleted = 0 AND created_at >= ?",
                (today.isoformat(timespec="seconds"),),
            ).fetchone()
        return {
            "file_count": int(totals["file_count"]),
            "total_size": int(totals["total_size"]),
            "uploaded_24h": int(recent["uploaded_24h"]),
        }

    def create_share(self, file_id: str, expires_hours: int, max_downloads: int) -> sqlite3.Row:
        code = secrets.token_urlsafe(6).replace("_", "").replace("-", "")[:10]
        created_at = utc_now()
        expires_at = created_at + timedelta(hours=expires_hours)

        with self._lock:
            # regenerate code if collision happens
            while True:
                existing = self.conn.execute("SELECT code FROM shares WHERE code = ?", (code,)).fetchone()
                if not existing:
                    break
                code = secrets.token_urlsafe(6).replace("_", "").replace("-", "")[:10]

            self.conn.execute(
                """
                INSERT INTO shares (code, file_id, created_at, expires_at, max_downloads)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    code,
                    file_id,
                    created_at.isoformat(timespec="seconds"),
                    expires_at.isoformat(timespec="seconds"),
                    max_downloads,
                ),
            )
            self.conn.commit()
            row = self.conn.execute("SELECT * FROM shares WHERE code = ?", (code,)).fetchone()
        return row

    def get_share(self, code: str) -> sqlite3.Row | None:
        with self._lock:
            row = self.conn.execute("SELECT * FROM shares WHERE code = ?", (code,)).fetchone()
        return row

    def increment_share_download(self, code: str) -> None:
        with self._lock:
            self.conn.execute(
                "UPDATE shares SET download_count = download_count + 1 WHERE code = ?",
                (code,),
            )
            self.conn.commit()

    def get_note(self) -> sqlite3.Row | None:
        with self._lock:
            return self.conn.execute("SELECT * FROM notes WHERE id = 1").fetchone()

    def update_note(self, content: str, updated_by: str) -> sqlite3.Row:
        updated_at = utc_now_iso()
        with self._lock:
            self.conn.execute(
                "UPDATE notes SET content = ?, updated_at = ?, updated_by = ? WHERE id = 1",
                (content, updated_at, updated_by),
            )
            self.conn.commit()
            return self.conn.execute("SELECT * FROM notes WHERE id = 1").fetchone()


class EventBroker:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subscribers: dict[int, queue.Queue[dict[str, Any]]] = {}
        self._next_id = 1

    def subscribe(self) -> tuple[int, queue.Queue[dict[str, Any]]]:
        subscriber_queue: queue.Queue[dict[str, Any]] = queue.Queue()
        with self._lock:
            subscriber_id = self._next_id
            self._next_id += 1
            self._subscribers[subscriber_id] = subscriber_queue
        return subscriber_id, subscriber_queue

    def unsubscribe(self, subscriber_id: int) -> None:
        with self._lock:
            self._subscribers.pop(subscriber_id, None)

    def publish(self, event: str, data: dict[str, Any] | None = None) -> None:
        payload = {
            "event": event,
            "data": {**(data or {}), "sent_at": utc_now_iso()},
        }
        with self._lock:
            subscribers = list(self._subscribers.values())
        for subscriber_queue in subscribers:
            subscriber_queue.put(payload)


DATA_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
DB = Database(DB_PATH)
SESSIONS = SessionStore()
LOGIN_GUARD = LoginGuard()
EVENTS = EventBroker()


class AppHandler(BaseHTTPRequestHandler):
    server_version = "LanSharePro/1.0"
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:
        self._route("GET")

    def do_POST(self) -> None:
        self._route("POST")

    def do_DELETE(self) -> None:
        self._route("DELETE")

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Allow", "GET, POST, DELETE, OPTIONS")
        self.end_headers()

    def log_message(self, fmt: str, *args: Any) -> None:
        now = datetime.now().strftime("%H:%M:%S")
        print(f"[{now}] {self.address_string()} {fmt % args}")

    def _route(self, method: str) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        try:
            if method == "GET" and path in {"/", "/index.html", "/styles.css", "/app.js"}:
                self._serve_static(path)
                return

            if method == "GET" and path.startswith("/s/"):
                code = path.split("/", 2)[2]
                self._serve_share_landing(code)
                return

            if path == "/api/health" and method == "GET":
                return self._json(200, {"ok": True, "version": self.server_version})

            if path == "/api/login" and method == "POST":
                return self._handle_login()

            if path == "/api/logout" and method == "POST":
                return self._handle_logout()

            if path.startswith("/api/public/") and method == "GET":
                parts = path.split("/")
                if len(parts) == 5 and parts[4] == "download":
                    code = parts[3]
                    return self._handle_public_download(code)

            if not self._is_authenticated():
                return self._json(401, {"error": "Unauthorized"})

            if path == "/api/me" and method == "GET":
                return self._json(200, {"authenticated": True})

            if path == "/api/network" and method == "GET":
                urls = [f"http://{ip}:{PORT}" for ip in get_local_ipv4()]
                return self._json(200, {"urls": urls, "host": HOST, "port": PORT})

            if path == "/api/stats" and method == "GET":
                return self._json(200, DB.stats())

            if path == "/api/events" and method == "GET":
                return self._handle_events()

            if path == "/api/note" and method == "GET":
                return self._json(200, {"note": self._format_note_row(DB.get_note())})

            if path == "/api/note" and method == "POST":
                return self._handle_note_update()

            if path == "/api/files" and method == "GET":
                return self._handle_list_files(query)

            if path == "/api/upload" and method == "POST":
                return self._handle_upload(query)

            file_match = re.fullmatch(r"/api/files/([A-Za-z0-9\-]+)/download", path)
            if file_match and method == "GET":
                return self._handle_download(file_match.group(1))

            delete_match = re.fullmatch(r"/api/files/([A-Za-z0-9\-]+)", path)
            if delete_match and method == "DELETE":
                return self._handle_delete(delete_match.group(1))

            share_match = re.fullmatch(r"/api/files/([A-Za-z0-9\-]+)/share", path)
            if share_match and method == "POST":
                return self._handle_create_share(share_match.group(1))

            return self._json(404, {"error": "Not found"})
        except ConnectionResetError:
            return
        except BrokenPipeError:
            return
        except Exception as exc:
            return self._json(500, {"error": "Internal server error", "detail": str(exc)})

    def _parse_int(
        self,
        raw: str | None,
        *,
        default: int,
        min_value: int | None = None,
        max_value: int | None = None,
    ) -> int:
        try:
            value = int(str(raw if raw is not None else default))
        except (TypeError, ValueError):
            value = default
        if min_value is not None:
            value = max(min_value, value)
        if max_value is not None:
            value = min(max_value, value)
        return value

    def _has_chunked_body(self) -> bool:
        transfer_encoding = self.headers.get("Transfer-Encoding", "")
        return "chunked" in transfer_encoding.lower()

    def _content_length_header(self) -> int | None:
        raw = self.headers.get("Content-Length")
        if raw is None:
            return None
        return self._parse_int(raw, default=0, min_value=0)

    def _iter_fixed_length_body(self, content_length: int, chunk_size: int) -> Iterator[bytes]:
        remaining = content_length
        while remaining > 0:
            chunk = self.rfile.read(min(chunk_size, remaining))
            if not chunk:
                raise ValueError("Request body ended unexpectedly")
            remaining -= len(chunk)
            yield chunk

    def _iter_chunked_body(self, chunk_size: int) -> Iterator[bytes]:
        while True:
            chunk_header = self.rfile.readline()
            if not chunk_header:
                raise ValueError("Chunked body ended unexpectedly")

            chunk_meta = chunk_header.split(b";", 1)[0].strip()
            try:
                chunk_length = int(chunk_meta, 16)
            except ValueError as exc:
                raise ValueError("Invalid chunk size") from exc

            if chunk_length == 0:
                while True:
                    trailer = self.rfile.readline()
                    if trailer in {b"", b"\r\n", b"\n"}:
                        return

            remaining = chunk_length
            while remaining > 0:
                chunk = self.rfile.read(min(chunk_size, remaining))
                if not chunk:
                    raise ValueError("Chunked upload interrupted")
                remaining -= len(chunk)
                yield chunk

            delimiter = self.rfile.read(2)
            if delimiter == b"\r\n":
                continue
            if delimiter[:1] == b"\n":
                if len(delimiter) == 2:
                    # One extra byte was already buffered; treat it as invalid to keep parsing strict.
                    raise ValueError("Invalid chunk delimiter")
                continue
            raise ValueError("Invalid chunk delimiter")

    def _iter_request_body(self, *, chunk_size: int = 64 * 1024) -> Iterator[bytes]:
        if self._has_chunked_body():
            yield from self._iter_chunked_body(chunk_size)
            return

        content_length = self._content_length_header()
        if content_length is None:
            raise ValueError("Request body length unknown")
        yield from self._iter_fixed_length_body(content_length, chunk_size)

    def _read_request_body(self, *, max_bytes: int | None = None) -> bytes:
        body_parts: list[bytes] = []
        total = 0
        for chunk in self._iter_request_body():
            total += len(chunk)
            if max_bytes is not None and total > max_bytes:
                raise ValueError("Request body too large")
            body_parts.append(chunk)
        return b"".join(body_parts)

    def _read_json(self) -> dict[str, Any]:
        try:
            raw = self._read_request_body(max_bytes=1024 * 1024)
        except ValueError:
            return {}
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))

    def _json(self, status: int, payload: dict[str, Any], cookie: str | None = None) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(data)

    def _serve_static(self, path: str) -> None:
        target = "index.html" if path in {"/", "/index.html"} else path.lstrip("/")
        if target not in {"index.html", "styles.css", "app.js"}:
            return self._json(404, {"error": "Not found"})
        file_path = WEB_DIR / target
        if not file_path.exists():
            return self._json(404, {"error": "Asset missing"})
        content = file_path.read_bytes()
        mime = {
            "index.html": "text/html; charset=utf-8",
            "styles.css": "text/css; charset=utf-8",
            "app.js": "application/javascript; charset=utf-8",
        }[target]
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _serve_share_landing(self, code: str) -> None:
        share = DB.get_share(code)
        if not share:
            self.send_error(404, "Share link not found")
            return

        expires_at = parse_iso(share["expires_at"])
        if expires_at < utc_now():
            self.send_error(410, "Share link expired")
            return

        file_row = DB.get_file(share["file_id"]) 
        if not file_row:
            self.send_error(404, "File not available")
            return

        html = f"""<!doctype html>
<html lang=\"zh-CN\">
<head>
  <meta charset=\"UTF-8\" />
  <meta name=\"viewport\" content=\"width=device-width,initial-scale=1\" />
  <title>文件分享 - {file_row['original_name']}</title>
  <style>
    body {{ margin:0; min-height:100vh; display:grid; place-items:center; background:linear-gradient(130deg,#041431,#0f2648 45%,#2a496f); color:#f8fbff; font-family:'Avenir Next','PingFang SC',sans-serif; }}
    .card {{ width:min(92vw,520px); border-radius:22px; padding:30px; background:rgba(255,255,255,.10); backdrop-filter: blur(8px); box-shadow:0 18px 60px rgba(3,9,22,.5); }}
    h1 {{ margin:0 0 8px; font-family:'Bodoni 72','STSong',serif; font-size:30px; letter-spacing:.5px; }}
    p {{ opacity:.9; margin:8px 0; }}
    a {{ display:inline-block; margin-top:16px; text-decoration:none; background:#9fe870; color:#1f2b0d; padding:10px 18px; border-radius:10px; font-weight:700; }}
  </style>
</head>
<body>
  <article class=\"card\">
    <h1>LAN Share 下载页</h1>
    <p>文件：<strong>{file_row['original_name']}</strong></p>
    <p>大小：{file_row['size_bytes']} bytes</p>
    <p>链接有效至：{share['expires_at']}</p>
    <a href=\"/api/public/{code}/download\">点击下载</a>
  </article>
</body>
</html>"""
        data = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _get_cookie_token(self) -> str | None:
        raw = self.headers.get("Cookie")
        if not raw:
            return None
        cookie = SimpleCookie()
        cookie.load(raw)
        token = cookie.get("lan_session")
        return token.value if token else None

    def _is_authenticated(self) -> bool:
        SESSIONS.cleanup()
        return SESSIONS.validate(self._get_cookie_token())

    def _handle_login(self) -> None:
        client_ip = self.client_address[0]
        allowed, wait = LOGIN_GUARD.check_allowed(client_ip)
        if not allowed:
            return self._json(429, {"error": f"Too many attempts. Retry in {wait}s."})

        data = self._read_json()
        password = str(data.get("password", ""))
        if not hmac.compare_digest(password, ADMIN_PASSWORD):
            LOGIN_GUARD.record_fail(client_ip)
            return self._json(401, {"error": "Invalid password"})

        LOGIN_GUARD.record_success(client_ip)
        token = SESSIONS.issue()
        max_age = SESSION_HOURS * 3600
        cookie = f"lan_session={token}; HttpOnly; Path=/; Max-Age={max_age}; SameSite=Lax"
        return self._json(200, {"ok": True}, cookie=cookie)

    def _handle_logout(self) -> None:
        token = self._get_cookie_token()
        SESSIONS.revoke(token)
        cookie = "lan_session=; HttpOnly; Path=/; Max-Age=0; SameSite=Lax"
        return self._json(200, {"ok": True}, cookie=cookie)

    def _handle_list_files(self, query: dict[str, list[str]]) -> None:
        q = query.get("query", [""])[0].strip()
        page = self._parse_int(query.get("page", ["1"])[0], default=1, min_value=1, max_value=100000)
        page_size = self._parse_int(query.get("page_size", ["20"])[0], default=20, min_value=1, max_value=100)
        sort = query.get("sort", ["created_at"])[0]
        order = query.get("order", ["desc"])[0]

        listing = DB.list_files(q, page, page_size, sort, order)
        items = [self._format_file_row(row) for row in listing["items"]]
        total_pages = max(1, (listing["total"] + page_size - 1) // page_size)
        return self._json(
            200,
            {
                "items": items,
                "total": listing["total"],
                "page": page,
                "page_size": page_size,
                "total_pages": total_pages,
            },
        )

    def _handle_upload(self, query: dict[str, list[str]]) -> None:
        content_length = self._content_length_header()
        if content_length is None and not self._has_chunked_body():
            return self._json(411, {"error": "Request body length unknown"})
        if content_length is not None and content_length > MAX_UPLOAD_BYTES:
            return self._json(
                413,
                {
                    "error": f"File too large. Max allowed is {MAX_UPLOAD_MB} MB",
                    "max_bytes": MAX_UPLOAD_BYTES,
                },
            )

        requested_name = query.get("filename", [""])[0] or self.headers.get("X-File-Name", "")
        original_name = sanitize_filename(urllib.parse.unquote(requested_name) or "unnamed.bin")
        mime_type = self.headers.get("Content-Type", "application/octet-stream")

        file_id = secrets.token_hex(16)
        suffix = Path(original_name).suffix[:20]
        stored_name = f"{file_id}{suffix}"
        target_path = safe_join(UPLOAD_DIR, stored_name)

        digest = hashlib.sha256()
        bytes_written = 0
        chunk_size = 1024 * 1024
        temp_path = safe_join(UPLOAD_DIR, f".{stored_name}.part")

        try:
            with open(temp_path, "wb") as f:
                for chunk in self._iter_request_body(chunk_size=chunk_size):
                    f.write(chunk)
                    digest.update(chunk)
                    bytes_written += len(chunk)
                    if bytes_written > MAX_UPLOAD_BYTES:
                        raise ValueError(f"File too large. Max allowed is {MAX_UPLOAD_MB} MB")

            if content_length is not None and bytes_written != content_length:
                if temp_path.exists():
                    temp_path.unlink(missing_ok=True)
                return self._json(400, {"error": "Upload interrupted"})

            shutil.move(str(temp_path), str(target_path))
            DB.add_file(
                file_id=file_id,
                stored_name=stored_name,
                original_name=original_name,
                mime_type=mime_type,
                size_bytes=bytes_written,
                sha256=digest.hexdigest(),
                uploaded_by=self.client_address[0],
            )

            row = DB.get_file(file_id)
            EVENTS.publish(
                "files_changed",
                {"action": "uploaded", "file_id": file_id, "name": original_name},
            )
            return self._json(201, {"file": self._format_file_row(row)})
        except ValueError as exc:
            temp_path.unlink(missing_ok=True)
            target_path.unlink(missing_ok=True)
            message = str(exc)
            if "too large" in message.lower():
                return self._json(413, {"error": message, "max_bytes": MAX_UPLOAD_BYTES})
            return self._json(400, {"error": message})
        except Exception as exc:
            temp_path.unlink(missing_ok=True)
            target_path.unlink(missing_ok=True)
            return self._json(500, {"error": "Upload failed", "detail": str(exc)})

    def _handle_download(self, file_id: str) -> None:
        row = DB.get_file(file_id)
        if not row:
            return self._json(404, {"error": "File not found"})
        path = safe_join(UPLOAD_DIR, row["stored_name"])
        if not path.exists():
            return self._json(404, {"error": "Stored file missing"})

        DB.increment_download(file_id)
        EVENTS.publish("files_changed", {"action": "downloaded", "file_id": file_id})
        self._stream_file(path, row["original_name"], row["mime_type"])

    def _handle_public_download(self, code: str) -> None:
        share = DB.get_share(code)
        if not share:
            return self._json(404, {"error": "Share not found"})

        expires_at = parse_iso(share["expires_at"])
        if expires_at < utc_now():
            return self._json(410, {"error": "Share expired"})

        if int(share["download_count"]) >= int(share["max_downloads"]):
            return self._json(410, {"error": "Share download limit reached"})

        row = DB.get_file(share["file_id"])
        if not row:
            return self._json(404, {"error": "File not found"})

        path = safe_join(UPLOAD_DIR, row["stored_name"])
        if not path.exists():
            return self._json(404, {"error": "Stored file missing"})

        DB.increment_share_download(code)
        DB.increment_download(row["id"])
        EVENTS.publish("files_changed", {"action": "downloaded", "file_id": row["id"]})
        self._stream_file(path, row["original_name"], row["mime_type"])

    def _handle_delete(self, file_id: str) -> None:
        row = DB.get_file(file_id)
        if not row:
            return self._json(404, {"error": "File not found"})

        if DB.soft_delete_file(file_id) == 0:
            return self._json(404, {"error": "File already deleted"})

        path = safe_join(UPLOAD_DIR, row["stored_name"])
        if path.exists():
            path.unlink(missing_ok=True)

        EVENTS.publish("files_changed", {"action": "deleted", "file_id": file_id})
        return self._json(200, {"ok": True, "deleted_id": file_id})

    def _handle_create_share(self, file_id: str) -> None:
        row = DB.get_file(file_id)
        if not row:
            return self._json(404, {"error": "File not found"})

        body = self._read_json()
        expires_hours = self._parse_int(body.get("expires_hours"), default=24, min_value=1, max_value=720)
        max_downloads = self._parse_int(body.get("max_downloads"), default=20, min_value=1, max_value=100000)

        share = DB.create_share(file_id, expires_hours, max_downloads)
        share_url = self._absolute_url(f"/s/{share['code']}")
        return self._json(
            201,
            {
                "code": share["code"],
                "share_url": share_url,
                "expires_at": share["expires_at"],
                "max_downloads": share["max_downloads"],
            },
        )

    def _handle_note_update(self) -> None:
        body = self._read_json()
        content = str(body.get("content", ""))
        if len(content) > 20000:
            return self._json(413, {"error": "Note too large. Max allowed is 20000 characters"})

        row = DB.update_note(content, self.client_address[0])
        formatted = self._format_note_row(row)
        EVENTS.publish("note_changed", {"note": formatted})
        return self._json(200, {"note": formatted})

    def _handle_events(self) -> None:
        subscriber_id, subscriber_queue = EVENTS.subscribe()
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "keep-alive")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()
            self.wfile.write(self._sse_frame("connected", {"ok": True}))
            self.wfile.flush()

            while True:
                try:
                    payload = subscriber_queue.get(timeout=15)
                    self.wfile.write(self._sse_frame(payload["event"], payload["data"]))
                except queue.Empty:
                    self.wfile.write(b": keepalive\n\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            return
        finally:
            EVENTS.unsubscribe(subscriber_id)

    def _sse_frame(self, event: str, data: dict[str, Any]) -> bytes:
        payload = json.dumps(data, ensure_ascii=False)
        return f"event: {event}\ndata: {payload}\n\n".encode("utf-8")

    def _absolute_url(self, path: str) -> str:
        host_header = self.headers.get("Host")
        if host_header:
            return f"http://{host_header}{path}"
        return f"http://127.0.0.1:{PORT}{path}"

    def _format_note_row(self, row: sqlite3.Row | None) -> dict[str, Any]:
        if row is None:
            return {"content": "", "updated_at": "", "updated_by": "system"}
        return {
            "content": row["content"],
            "updated_at": row["updated_at"],
            "updated_by": row["updated_by"],
        }

    def _format_file_row(self, row: sqlite3.Row | None) -> dict[str, Any]:
        if row is None:
            return {}
        return {
            "id": row["id"],
            "name": row["original_name"],
            "mime_type": row["mime_type"],
            "size_bytes": int(row["size_bytes"]),
            "sha256": row["sha256"],
            "downloads": int(row["downloads"]),
            "created_at": row["created_at"],
        }

    def _stream_file(self, file_path: Path, download_name: str, mime_type: str) -> None:
        size = file_path.stat().st_size
        range_header = self.headers.get("Range", "")

        start = 0
        end = size - 1
        status = HTTPStatus.OK

        if range_header.startswith("bytes="):
            part = range_header[len("bytes=") :].strip()
            if "," in part:
                return self._json(416, {"error": "Multiple ranges not supported"})

            left, _, right = part.partition("-")
            try:
                if left == "":
                    suffix_len = int(right)
                    if suffix_len <= 0:
                        raise ValueError
                    start = max(size - suffix_len, 0)
                    end = size - 1
                else:
                    start = int(left)
                    end = int(right) if right else size - 1
                if start < 0 or end < start or end >= size:
                    raise ValueError
                status = HTTPStatus.PARTIAL_CONTENT
            except ValueError:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.end_headers()
                return

        content_length = end - start + 1
        quoted_name = urllib.parse.quote(download_name)

        self.send_response(status)
        self.send_header("Content-Type", mime_type or "application/octet-stream")
        self.send_header(
            "Content-Disposition",
            f"attachment; filename*=UTF-8''{quoted_name}",
        )
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(content_length))
        if status == HTTPStatus.PARTIAL_CONTENT:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()

        with open(file_path, "rb") as f:
            f.seek(start)
            remaining = content_length
            block = 1024 * 1024
            while remaining > 0:
                chunk = f.read(min(block, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)


def main() -> None:
    httpd = ThreadingHTTPServer((HOST, PORT), AppHandler)
    print("=" * 72)
    print("LAN Share Pro started")
    print(f"Root Dir      : {ROOT_DIR}")
    print(f"Data Dir      : {DATA_DIR}")
    print(f"Upload Dir    : {UPLOAD_DIR}")
    print(f"Database      : {DB_PATH}")
    print(f"Listen        : http://{HOST}:{PORT}")
    urls = get_local_ipv4()
    if urls:
        for ip in urls:
            print(f"LAN URL       : http://{ip}:{PORT}")
    print(f"Admin Password: {ADMIN_PASSWORD}")
    print(f"Max Upload    : {MAX_UPLOAD_MB} MB")
    print("=" * 72)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")


if __name__ == "__main__":
    main()
