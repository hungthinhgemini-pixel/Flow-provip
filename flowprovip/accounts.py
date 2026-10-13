"""Quản lý nhiều tài khoản Google.

Mỗi tài khoản là một profile trình duyệt riêng (thư mục user-data-dir). Tool KHÔNG lưu mật khẩu:
người dùng tự đăng nhập một lần trong cửa sổ trình duyệt, phiên đăng nhập được giữ trong profile.
Ngoài ra có thể nạp cookie xuất từ extension (JSON) vào profile.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

from flowprovip.config import app_home


@dataclass
class Account:
    id: str
    name: str
    enabled: bool = True
    # Ghi chú trạng thái lần kiểm tra gần nhất: "ok", "chưa đăng nhập", "hết quota", ...
    status: str = "mới"
    email: str = ""
    credits: int | None = None
    # Proxy riêng cho tài khoản (vd http://user:pass@host:port), để trống = không dùng
    proxy: str = ""
    # Cookie nạp thêm khi mở profile (danh sách dict theo định dạng Playwright)
    cookies: list = field(default_factory=list)

    @property
    def profile_dir(self) -> Path:
        d = app_home() / "profiles" / self.id
        d.mkdir(parents=True, exist_ok=True)
        return d


class AccountStore:
    def __init__(self, path: Path | None = None):
        self.path = path or app_home() / "accounts.json"
        self.accounts: list[Account] = []
        self.load()

    def load(self) -> None:
        if self.path.exists():
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            self.accounts = [Account(**a) for a in raw]

    def save(self) -> None:
        self.path.write_text(
            json.dumps([asdict(a) for a in self.accounts], ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def add(self, name: str, proxy: str = "") -> Account:
        acc = Account(id=_slug(name) + "-" + uuid.uuid4().hex[:6], name=name, proxy=proxy)
        self.accounts.append(acc)
        self.save()
        return acc

    def remove(self, account_id: str) -> None:
        self.accounts = [a for a in self.accounts if a.id != account_id]
        self.save()

    def get(self, account_id: str) -> Account | None:
        return next((a for a in self.accounts if a.id == account_id), None)

    def enabled(self) -> list[Account]:
        return [a for a in self.accounts if a.enabled]


def parse_cookies(text: str) -> list[dict]:
    """Chuyển cookie JSON (định dạng EditThisCookie / Cookie-Editor) sang định dạng Playwright."""
    data = json.loads(text)
    if isinstance(data, dict) and "cookies" in data:
        data = data["cookies"]
    out = []
    for c in data:
        cookie = {
            "name": c["name"],
            "value": c["value"],
            "domain": c.get("domain", ".google.com"),
            "path": c.get("path", "/"),
            "secure": bool(c.get("secure", True)),
            "httpOnly": bool(c.get("httpOnly", False)),
        }
        exp = c.get("expirationDate", c.get("expires"))
        if exp and exp > 0:
            cookie["expires"] = float(exp)
        same = str(c.get("sameSite", "")).lower()
        cookie["sameSite"] = {"strict": "Strict", "lax": "Lax"}.get(same, "None")
        if cookie["sameSite"] == "None":
            cookie["secure"] = True
        out.append(cookie)
    return out


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:30] or "acc"
