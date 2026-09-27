from __future__ import annotations
import json, shutil, os, tempfile
from datetime import datetime
from pathlib import Path

DEFAULT_CONFIG = {
    "language": "ja",
    "callsign": "",
    "warning_ack": False,
    "rig": {
        "maker": "ICOM",
        "model": "IC-7300",
        "com": "",
        "audio_in": "",
        "audio_out": "",
    },
    "display": {
        "show_jst": True,
    },
    "autocq": {
        "interval_sec": 10,
        "repeat_count": 10,
    },
    "tx": {"allow_disconnected": False},
    "tbsk": {"tone_profile": "narrow_100"},
    "rx_display": {"sq": 12, "sensitivity": 50},
    "backup": {"on_exit": True, "every_enabled": False, "every_count": 30, "pending_qsos": 0},
    "windows": {},
}

class AppPaths:
    def __init__(self, base: Path):
        self.base = Path(base)
        self.config_dir = self.base / "config"
        self.log_dir = self.base / "log"
        self.bak_dir = self.base / "bak"
        self.licenses_dir = self.base / "licenses"
        self.config_file = self.config_dir / "config.json"
        self.log_file = self.log_dir / "tbskx.adi"

    def ensure(self):
        for p in (self.config_dir, self.log_dir, self.bak_dir, self.licenses_dir):
            p.mkdir(parents=True, exist_ok=True)

class ConfigStore:
    def __init__(self, paths: AppPaths):
        self.paths = paths
        self.data = json.loads(json.dumps(DEFAULT_CONFIG))

    def load(self):
        self.paths.ensure()
        if self.paths.config_file.exists():
            try:
                incoming = json.loads(self.paths.config_file.read_text(encoding="utf-8"))
                self._merge(self.data, incoming)
            except Exception:
                pass
        return self.data

    def save(self):
        self.paths.ensure()
        temporary = self.paths.config_file.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.paths.config_file)

    @staticmethod
    def _merge(dst, src):
        for k, v in src.items():
            if isinstance(v, dict) and isinstance(dst.get(k), dict):
                ConfigStore._merge(dst[k], v)
            else:
                dst[k] = v


def backup_log(paths: AppPaths, keep: int = 10):
    """Create one timestamped backup and retain at most ``keep`` newest copies."""
    paths.ensure()
    if not paths.log_file.exists() or paths.log_file.stat().st_size == 0:
        return None

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    dst = paths.bak_dir / f"tbskx_{stamp}.adi"
    seq = 1
    while dst.exists():
        dst = paths.bak_dir / f"tbskx_{stamp}_{seq:02d}.adi"
        seq += 1

    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=paths.bak_dir, suffix=".tmp", delete=False) as fp:
            temporary = Path(fp.name)
            with paths.log_file.open("rb") as source:
                shutil.copyfileobj(source, fp)
            fp.flush(); os.fsync(fp.fileno())
        if temporary.stat().st_size != paths.log_file.stat().st_size:
            raise OSError("Backup size verification failed")
        os.replace(temporary, dst)
    finally:
        if temporary is not None and temporary.exists(): temporary.unlink()

    items = sorted(
        paths.bak_dir.glob("tbskx_*.adi"),
        key=lambda p: p.name,
        reverse=True,
    )
    for old in items[max(0, int(keep)):]:
        try:
            old.unlink()
        except OSError:
            pass
    return dst
