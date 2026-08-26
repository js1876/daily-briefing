"""Local-only configuration for Toss Securities read-only market data."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tomllib


class TossConfigError(ValueError):
    """Raised when local Toss API configuration is missing or invalid."""


@dataclass(frozen=True)
class TossMarketConfig:
    client_id: str
    client_secret: str
    base_url: str = "https://openapi.tossinvest.com"
    timeout_seconds: float = 12.0

    @classmethod
    def from_toml(cls, path: Path) -> "TossMarketConfig":
        try:
            raw = tomllib.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise TossConfigError(f"설정 파일이 없습니다: {path}") from exc
        except tomllib.TOMLDecodeError as exc:
            raise TossConfigError(f"설정 파일 TOML 형식이 올바르지 않습니다: {path}") from exc

        section = raw.get("toss_market")
        if not isinstance(section, dict):
            raise TossConfigError("[toss_market] 설정 섹션이 없습니다.")

        client_id = str(section.get("client_id", "")).strip()
        client_secret = str(section.get("client_secret", "")).strip()
        if not client_id or client_id.startswith("PASTE_"):
            raise TossConfigError("client_id를 입력해주세요.")
        if not client_secret or client_secret.startswith("PASTE_"):
            raise TossConfigError("client_secret을 입력해주세요.")

        base_url = str(section.get("base_url", cls.base_url)).rstrip("/")
        if base_url != "https://openapi.tossinvest.com":
            raise TossConfigError("시장조회 전용 클라이언트는 공식 API 서버만 허용합니다.")

        timeout_seconds = float(section.get("timeout_seconds", cls.timeout_seconds))
        if not 1 <= timeout_seconds <= 30:
            raise TossConfigError("timeout_seconds는 1~30초 범위여야 합니다.")
        return cls(client_id, client_secret, base_url, timeout_seconds)
