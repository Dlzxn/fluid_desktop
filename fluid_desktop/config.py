import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

APP_NAME = "Fluidd Desktop"
CONFIG_DIR = Path.home() / ".fluidd_desktop"
CONFIG_FILE = CONFIG_DIR / "config.json"


@dataclass
class Config:
    last_ip: str | None = None
    # Дополнительные подсети для поиска, например ["192.168.1.0/24"].
    extra_subnets: list[str] = field(default_factory=list)
    poll_interval_sec: float = 3.0
    rescan_interval_sec: float = 15.0
    progress_notifications: bool = True

    @classmethod
    def load(cls) -> "Config":
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**known)

    def save(self) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False), encoding="utf-8")
