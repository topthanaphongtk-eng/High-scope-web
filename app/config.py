from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class MesSettings(BaseModel):
    wsdl_url: str
    timeout_seconds: int = 5
    wsdl_cache_dir: Path = Path("./logs/wsdl_cache")
    verify_ssl: bool = True


class CaptureSettings(BaseModel):
    watch_root: Path = Path(r"D:\Auto save")
    recursive: bool = True
    file_patterns: list[str] = Field(default_factory=lambda: ["*.tif", "*.tiff"])
    stable_poll_ms: int = 200
    stable_required_checks: int = 2


class StorageSettings(BaseModel):
    shared_root: Path = Path(r"\\b1-1-s1\local\WI\Picture high")
    compute_sha256: bool = True


class MssqlSettings(BaseModel):
    """Connection details for the central SQL Server. All stations + the web
    monitor point at the same instance/database — that's what makes the
    history shared."""

    server: str = ""
    database: str = "HighScopeCapture"
    user: str = ""
    password: str = ""
    port: int = 1433
    encrypt: bool = True
    trust_server_certificate: bool = True
    driver: str = "ODBC Driver 17 for SQL Server"


class AppSettings(BaseModel):
    log_dir: Path = Path("./logs")
    log_level: str = "INFO"


class Settings(BaseModel):
    mes: MesSettings
    capture: CaptureSettings
    storage: StorageSettings
    mssql: MssqlSettings = Field(default_factory=MssqlSettings)
    app: AppSettings

    @classmethod
    def from_yaml(cls, path: Path | str) -> Settings:
        data: dict[str, Any] = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        return cls.model_validate(data)

    def to_yaml(self, path: Path | str) -> None:
        """Serialise back to YAML in the same shape settings.yaml expects.
        Pydantic's model_dump → yaml.safe_dump preserves keys + types.
        Paths are stored as posix-style strings so users can edit by hand."""
        def _norm(v: Any) -> Any:
            if isinstance(v, Path):
                return v.as_posix()
            if isinstance(v, dict):
                return {k: _norm(x) for k, x in v.items()}
            if isinstance(v, list):
                return [_norm(x) for x in v]
            return v

        data = _norm(self.model_dump())
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        # Atomic write: temp file + replace, so a crash never leaves a half
        # file that breaks the next launch.
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(
            yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        tmp.replace(target)
