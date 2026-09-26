import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from pstbskx.qso import DecodeRow, QsoSession


class SequencePreviewTests(unittest.TestCase):
    def test_full_templates_before_and_after_selecting_peer(self):
        s=QsoSession("JH1HST")
        self.assertEqual(s.sequence_preview("report"),
                         "R {HISCALL} DE JH1HST UR {S/N}dB {S/N}dB [A] BK")
        self.assertEqual(s.sequence_preview("qsl"),"RR {HISCALL} DE JH1HST QSL [B] BK")
        self.assertEqual(s.sequence_preview("final"),"RRR {HISCALL} DE JH1HST TU QSO 73")
        s.select_decode(DecodeRow(datetime.now(timezone.utc),1326,-10.2,"JA1ABC","CQ CQ DE JA1ABC"))
        self.assertEqual(s.sequence_preview("report","今日は草加からです"),
                         "R JA1ABC DE JH1HST UR -10dB -10dB 今日は草加からです BK")
        self.assertEqual(s.sequence_preview("qsl",free_b="TNX"),"RR JA1ABC DE JH1HST QSL TNX BK")


class MainLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
        from PySide6.QtWidgets import QApplication
        cls.app=QApplication.instance() or QApplication([])

    def test_selection_never_transmits_and_preview_is_shared(self):
        from pstbskx.app import MainWindow
        with tempfile.TemporaryDirectory() as td:
            w=MainWindow(Path(td)); w.first_launch=False; w.config["callsign"]="JH1HST"; w.apply_settings()
            w.resize(1280,800); w.show(); self.app.processEvents()
            self.assertEqual(w.connection_label.text(),"未接続")
            self.assertLess(w.connection_label.x(),w.connect_btn.x())
            self.assertEqual(w.qso_group.title(),"交信シーケンス / AutoCQ")
            self.assertEqual(w.preview_lab.text(),"送信内容")
            self.assertIs(w.preview.parentWidget(),w.right_scroll.widget())
            self.assertTrue(w.sequence_send.isEnabled())  # initial CQ can be sent
            with patch.object(w,"tx") as send:
                w.report_radio.click()
                self.assertIn("{HISCALL}",w.report_btn.label.text())
                self.assertEqual(w.preview.toPlainText(),w.report_btn.label.text())
                self.assertFalse(w.sequence_send.isEnabled())
                w.session.select_decode(DecodeRow(datetime.now(timezone.utc),1326,-10,"JA1ABC","CQ CQ DE JA1ABC"))
                w._refresh_session()
                self.assertIn("R JA1ABC DE JH1HST UR -10dB",w.preview.toPlainText())
                self.assertTrue(w.sequence_send.isEnabled())
                w.qsl_btn.click()
                self.assertIn("RR JA1ABC DE JH1HST QSL",w.preview.toPlainText())
                w.sequence_send.click()
                send.assert_called_once_with("RR JA1ABC DE JH1HST QSL BK",kind="qsl")
                send.reset_mock()
                w.free.setText("今日は草加です")
                self.assertEqual(w.preview.toPlainText(),"今日は草加です")
                send.assert_not_called()
            w.sq_value.setValue(65); w.sensitivity.setValue(20)
            w.rx_reset.click()
            self.assertEqual((w.sq_value.value(),w.sensitivity.value()),(12,50))
            self.assertEqual(w.config["rx_display"],{"sq":12,"sensitivity":50})
            self.assertEqual(w.main_scroll.verticalScrollBar().maximum(),0)
            self.assertEqual(w.right_scroll.verticalScrollBar().maximum(),0)
            w.set_language("en")
            self.assertEqual(w.preview_lab.text(),"TX Message")
            self.assertEqual(w.qso_group.title(),"QSO Sequence / AutoCQ")
            self.app.processEvents()
            self.assertEqual(w.main_scroll.verticalScrollBar().maximum(),0)
            self.assertEqual(w.right_scroll.verticalScrollBar().maximum(),0)
            w.close()
