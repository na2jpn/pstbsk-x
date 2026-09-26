import tempfile, unittest
from pathlib import Path
from datetime import datetime, timezone, timedelta

from pstbskx.frame import pack_frame, unpack_frame, TYPE_REPORT
from pstbskx.qso import QsoSession, DecodeRow
from pstbskx.adif import QsoRecord, make_adif_record
from pstbskx.storage import AppPaths, ConfigStore, backup_log
from pstbskx.geometry import clamp_window_rect
from pstbskx.timeutil import format_clock


class CoreTests(unittest.TestCase):
    def test_frame_utf8_crc(self):
        b = pack_frame(TYPE_REPORT, 7, "今日は草加です")
        f = unpack_frame(b)
        self.assertEqual(f["text"], "今日は草加です")
        self.assertEqual(f["seq"], 7)
        bad = bytearray(b); bad[-1] ^= 1
        self.assertIsNone(unpack_frame(bytes(bad)))

    def test_sequence_and_insert_fields(self):
        s = QsoSession("JH1HST")
        self.assertEqual(s.cq_text(), "CQ CQ DE JH1HST JH1HST K")
        s.select_decode(DecodeRow(datetime.now(), 1326, -10.2, "JA1ABC", "CQ CQ DE JA1ABC"))
        self.assertEqual(s.report_text("今日は草加です"), "R JA1ABC DE JH1HST UR -10dB -10dB 今日は草加です BK")
        self.assertEqual(s.report_text("", marker_if_empty=True), "R JA1ABC DE JH1HST UR -10dB -10dB [A] BK")
        self.assertEqual(s.qsl_text("TNX"), "RR JA1ABC DE JH1HST QSL TNX BK")
        self.assertEqual(s.qsl_text("", marker_if_empty=True), "RR JA1ABC DE JH1HST QSL [B] BK")
        self.assertEqual(s.final_text(), "RRR JA1ABC DE JH1HST TU QSO 73")
        self.assertTrue(s.is_final_from_peer("RRR JH1HST DE JA1ABC TU QSO 73"))

    def test_autocq_reply_detection(self):
        s = QsoSession("JH1HST")
        self.assertEqual(s.reply_call_to_me("R JH1HST DE JA1ABC UR -10dB -10dB BK"), "JA1ABC")
        self.assertEqual(s.reply_call_to_me("RR JH1HST DE JA1ABC QSL BK"), "JA1ABC")
        self.assertIsNone(s.reply_call_to_me("CQ CQ DE JA1ABC JA1ABC K"))

    def test_observe_each_rx_updates_snr(self):
        s = QsoSession("JH1HST")
        s.select_decode(DecodeRow(datetime.now(), 1326, -10.2, "JA1ABC", "CQ CQ DE JA1ABC"))
        s.observe_decode(DecodeRow(datetime.now(), 1328, -8.6, "JA1ABC", "RR JH1HST DE JA1ABC QSL BK"))
        self.assertEqual(s.af_hz, 1328)
        self.assertAlmostEqual(s.current_rx_snr, -8.6)

    def test_adif_uses_utc(self):
        jst = timezone(timedelta(hours=9))
        t = datetime(2026, 9, 25, 13, 0, 0, tzinfo=jst)  # 04:00 UTC
        x = make_adif_record(QsoRecord("JA1ABC", mode="TBSK", rst_sent="-10", rx_snr=-9.5, af_hz=1326, qso_time_utc=t))
        self.assertIn("<QSO_DATE:8>20260925", x)
        self.assertIn("<TIME_ON:6>040000", x)
        self.assertIn("<CALL:6>JA1ABC", x)
        self.assertIn("<MODE:4>TBSK", x)
        self.assertIn("<APP_PSTBSKX_RX_SNR:4>-9.5", x)

    def test_backup_keeps_max_10(self):
        with tempfile.TemporaryDirectory() as td:
            p = AppPaths(Path(td)); p.ensure(); p.log_file.write_text("x")
            for _ in range(12):
                backup_log(p, 10)
            self.assertEqual(len(list(p.bak_dir.glob("tbskx_*.adi"))), 10)

    def test_window_rect_recovers_from_removed_monitor(self):
        screens = [(0, 0, 1920, 1040)]
        x, y, w, h = clamp_window_rect((3000, 200, 1180, 760), screens, (1180, 760), (700, 520))
        self.assertGreaterEqual(x, 0); self.assertGreaterEqual(y, 0)
        self.assertLessEqual(x + w, 1920); self.assertLessEqual(y + h, 1040)

    def test_clock_jst_utc_and_blink(self):
        t = datetime(2026, 9, 25, 4, 31, 0, tzinfo=timezone.utc)
        self.assertEqual(format_clock(t, True, True), "JST 2026-09-25 13:31   UTC 2026-09-25 04:31")
        self.assertEqual(format_clock(t, False, True), "UTC 2026-09-25 04:31")
        self.assertEqual(format_clock(t, True, False), "JST 2026-09-25 13 31   UTC 2026-09-25 04 31")
        midnight=datetime(2026,9,24,16,0,tzinfo=timezone.utc)
        self.assertEqual(format_clock(midnight),"JST 2026-09-25 01:00   UTC 2026-09-24 16:00")

    def test_config_merges_new_defaults(self):
        with tempfile.TemporaryDirectory() as td:
            p=AppPaths(Path(td)); p.ensure(); p.config_file.write_text('{"callsign":"JH1HST"}', encoding="utf-8")
            c=ConfigStore(p).load()
            self.assertTrue(c["display"]["show_jst"])
            self.assertEqual(c["autocq"]["interval_sec"], 10)
            self.assertIn("windows", c)


if __name__ == "__main__":
    unittest.main()
