from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

@dataclass
class QsoRecord:
    call: str
    freq_mhz: float | None = None
    band: str = ""
    mode: str = "TBSK"
    rst_sent: str = ""
    rst_rcvd: str = ""
    rx_snr: float | None = None
    af_hz: int | None = None
    qso_time_utc: datetime | None = None


def _f(name, value):
    if value is None or value == "":
        return ""
    s = str(value)
    return f"<{name}:{len(s.encode('utf-8'))}>{s}"


def _utc_time(dt: datetime | None) -> datetime:
    dt = dt or datetime.now(timezone.utc)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def make_adif_record(q: QsoRecord):
    t = _utc_time(q.qso_time_utc)
    parts = [
        _f("QSO_DATE", t.strftime("%Y%m%d")),
        _f("TIME_ON", t.strftime("%H%M%S")),
        _f("CALL", q.call.upper()),
        _f("MODE", q.mode),
    ]
    if q.freq_mhz is not None:
        parts.append(_f("FREQ", f"{q.freq_mhz:.6f}".rstrip("0").rstrip(".")))
    if q.band:
        parts.append(_f("BAND", q.band))
    if q.rst_sent:
        parts.append(_f("RST_SENT", q.rst_sent))
    if q.rst_rcvd:
        parts.append(_f("RST_RCVD", q.rst_rcvd))
    if q.rx_snr is not None:
        parts.append(_f("APP_PSTBSKX_RX_SNR", f"{q.rx_snr:+.1f}"))
    if q.af_hz is not None:
        parts.append(_f("APP_PSTBSKX_AF_HZ", q.af_hz))
    parts.append("<EOR>")
    return "".join(parts) + "\r\n"


def append_adif(path: Path, q: QsoRecord):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        header = "PSTBSK-X ADIF Log\r\n<ADIF_VER:5>3.1.7<PROGRAMID:8>PSTBSK-X<EOH>\r\n"
        path.write_text(header, encoding="utf-8", newline="")
    with path.open("a", encoding="utf-8", newline="") as fp:
        fp.write(make_adif_record(q))
