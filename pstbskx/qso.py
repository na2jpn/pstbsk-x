from __future__ import annotations
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

CALL = r"[A-Z0-9/]+"
FINAL_RE = re.compile(
    rf"^\s*RRR\s+(?P<to>{CALL})\s+DE\s+(?P<frm>{CALL})\s+TU\s+QSO\s+73\s*$",
    re.I,
)
REPORT_RE = re.compile(r"\bUR\s+(?P<snr>[+-]?\d{1,2})(?:\s*dB)?\b", re.I)
CQ_RE = re.compile(rf"^\s*CQ(?:\s+CQ)*\s+DE\s+(?P<frm>{CALL})\b", re.I)

@dataclass
class DecodeRow:
    when: datetime
    af_hz: int
    snr_db: float
    call: str
    text: str

@dataclass
class QsoSession:
    my_call: str
    his_call: str = ""
    af_hz: int = 1500
    current_rx_snr: float | None = None
    report_sent: str = ""
    report_rcvd: str = ""
    started_utc: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    logged: bool = False

    @staticmethod
    def _snr_text(value: float | None) -> str:
        if value is None:
            return "+00"
        return f"{int(round(value)):+03d}"

    def cq_text(self) -> str:
        return f"CQ CQ DE {self.my_call} {self.my_call} K"

    def select_decode(self, row: DecodeRow):
        if row.call.upper() != self.his_call.upper():
            self.started_utc = row.when
            self.report_sent = ""
            self.report_rcvd = ""
            self.logged = False
        self.his_call = row.call.upper()
        self.af_hz = int(row.af_hz)
        self.current_rx_snr = float(row.snr_db)
        self._capture_report(row.text)

    def observe_decode(self, row: DecodeRow):
        if self.his_call and row.call.upper() == self.his_call.upper():
            self.af_hz = int(row.af_hz)
            self.current_rx_snr = float(row.snr_db)
            self._capture_report(row.text)

    def _capture_report(self, text: str):
        m = REPORT_RE.search(text or "")
        if m:
            self.report_rcvd = f"{int(m.group('snr')):+03d}"

    def report_text(self, free: str = "", marker_if_empty: bool = False) -> str:
        snr = self._snr_text(self.current_rx_snr)
        if free.strip():
            extra = f" {free.strip()}"
        elif marker_if_empty:
            extra = " [A]"
        else:
            extra = ""
        return f"R {self.his_call} DE {self.my_call} UR {snr}dB {snr}dB{extra} BK"

    def qsl_text(self, free: str = "", marker_if_empty: bool = False) -> str:
        if free.strip():
            extra = f" {free.strip()}"
        elif marker_if_empty:
            extra = " [B]"
        else:
            extra = ""
        return f"RR {self.his_call} DE {self.my_call} QSL{extra} BK"

    def final_text(self) -> str:
        return f"RRR {self.his_call} DE {self.my_call} TU QSO 73"

    def free_text(self, text: str) -> str:
        return text.strip()

    def sequence_preview(self, kind: str, free_a: str = "", free_b: str = "") -> str:
        """Show the actual TX format even before a peer has been selected."""
        if kind == "cq":
            return self.cq_text()
        peer = self.his_call or "{HISCALL}"
        if kind == "report":
            snr = (self._snr_text(self.current_rx_snr) if self.current_rx_snr is not None
                   else "{S/N}")
            extra = free_a.strip() or "[A]"
            return f"R {peer} DE {self.my_call} UR {snr}dB {snr}dB {extra} BK"
        if kind == "qsl":
            extra = free_b.strip() or "[B]"
            return f"RR {peer} DE {self.my_call} QSL {extra} BK"
        if kind == "final":
            return f"RRR {peer} DE {self.my_call} TU QSO 73"
        raise ValueError(f"Unknown QSO sequence: {kind}")

    def mark_report_sent(self):
        self.report_sent = self._snr_text(self.current_rx_snr)

    def is_final_from_peer(self, text: str) -> bool:
        m = FINAL_RE.match(text or "")
        return bool(
            m
            and m.group("to").upper() == self.my_call.upper()
            and m.group("frm").upper() == self.his_call.upper()
        )

    def reply_call_to_me(self, text: str) -> str | None:
        """Return the sender callsign for an addressed reply to our call.

        This intentionally ignores general CQ text, so AutoCQ stops only when a
        decoded message is actually addressed to the current operator.
        """
        if not self.my_call:
            return None
        my = re.escape(self.my_call.upper())
        m = re.search(rf"(?:^|\s)(?:R|RR|RRR)?\s*{my}\s+DE\s+(?P<frm>{CALL})\b", text or "", re.I)
        return m.group("frm").upper() if m else None

    @staticmethod
    def cq_call(text: str) -> str | None:
        m = CQ_RE.match(text or "")
        return m.group("frm").upper() if m else None
