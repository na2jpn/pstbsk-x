import os
import sys
import tempfile
import threading
import types
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import numpy as np

from pstbskx.frame import TYPE_CQ, TYPE_FINAL, pack_frame
from pstbskx.qso import DecodeRow
from pstbskx.rx_decoder import BurstDecoder, ReceivedFrame


class DecoderTests(unittest.TestCase):
    def test_modulated_frame_decodes_with_af_snr_and_crc(self):
        # TBSKmodem imports its optional PortAudio wrapper even for offline
        # modulation. No audio hardware is needed for this waveform test.
        with patch.dict(sys.modules, {"sounddevice": types.ModuleType("sounddevice")}):
            from pstbskx.tbsk_phy import TbskPhy
            phy=TbskPhy(points=32)
            payload=pack_frame(TYPE_CQ, 17, "CQ CQ DE JA1ABC JA1ABC K")
            rng=np.random.default_rng(13)
            wave=np.asarray(phy.modulate(payload), dtype=np.float32)
            samples=np.r_[np.zeros(6000), wave, np.zeros(18000)]
            samples+=rng.normal(0,.008,len(samples))
            frames=BurstDecoder(lambda frame:None).decode_burst(samples)
            self.assertEqual(len(frames),1)
            self.assertEqual((frames[0].af_hz,frames[0].call,frames[0].seq),
                             (1500,"JA1ABC",17))
            self.assertEqual(frames[0].text,"CQ CQ DE JA1ABC JA1ABC K")
            self.assertTrue(np.isfinite(frames[0].snr_db))
            corrupt=bytearray(payload); corrupt[12]^=1
            bad=np.r_[np.zeros(6000),phy.modulate(bytes(corrupt)),np.zeros(18000)]
            self.assertEqual(BurstDecoder(lambda frame:None).decode_burst(bad),[])

    def test_continuous_receiver_noise_does_not_require_silence(self):
        with patch.dict(sys.modules, {"sounddevice": types.ModuleType("sounddevice")}):
            from pstbskx.tbsk_phy import TbskPhy
            rng=np.random.default_rng(29)
            samples=rng.normal(0,.001,48000*10).astype(np.float32)
            frame=np.asarray(TbskPhy(points=32).modulate(
                pack_frame(TYPE_CQ,42,"CQ CQ DE JA1ABC JA1ABC K")),dtype=np.float32)
            samples[48000:48000+len(frame)]+=.5*frame
            found=[]; event=threading.Event()
            receiver=BurstDecoder(lambda row:(found.append(row),event.set()))
            receiver.start()
            try:
                for offset in range(0,len(samples),2048):
                    receiver.feed(samples[offset:offset+2048])
                self.assertTrue(event.wait(15),"continuous background noise blocked RX")
                self.assertEqual(found[0].call,"JA1ABC")
            finally:
                receiver.close()


class QsoLogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
        from PySide6.QtWidgets import QApplication
        cls.app=QApplication.instance() or QApplication([])

    def test_final_requires_explicit_record_and_uses_utc_reports(self):
        from pstbskx.app import MainWindow
        with tempfile.TemporaryDirectory() as td:
            w=MainWindow(Path(td)); w.first_launch=False
            w.config["callsign"]="JH1HST"; w.apply_settings()
            w.frequency_hz=28080000
            when=datetime(2026,9,25,14,10,tzinfo=timezone.utc)
            w.session.select_decode(DecodeRow(when,1326,-10,"JA1ABC","CQ CQ DE JA1ABC"))
            w.session.report_sent="-10"; w.session.report_rcvd="-09"
            w._refresh_session()
            w.rx_frame.emit(ReceivedFrame(when,1326,-8,"JA1ABC",
                "RRR JH1HST DE JA1ABC TU QSO 73",TYPE_FINAL,123),w._rx_generation)
            # Only active Audio IN is permitted to deliver frames.
            self.app.processEvents()
            self.assertFalse(w.paths.log_file.exists())
            w._rx_active=True
            w.rx_frame.emit(ReceivedFrame(when,1326,-8,"JA1ABC",
                "RRR JH1HST DE JA1ABC TU QSO 73",TYPE_FINAL,123),w._rx_generation)
            self.app.processEvents()
            self.assertIsNotNone(w.qso_log_window)
            self.assertFalse(w.paths.log_file.exists())
            self.assertEqual(w.qso_log_window.record.mode,"TBSK")
            self.assertEqual(w.qso_log_window.record.band,"10m")
            w.qso_log_window.save.click()
            data=w.paths.log_file.read_text(encoding="utf-8")
            self.assertIn("<QSO_DATE:8>20260925",data)
            self.assertIn("<TIME_ON:6>141000",data)
            self.assertIn("<MODE:4>TBSK",data)
            self.assertIn("<RST_SENT:3>-10",data)
            self.assertIn("<RST_RCVD:3>-09",data)
            w.rx_frame.emit(ReceivedFrame(when,1326,-8,"JA1ABC",
                "RRR JH1HST DE JA1ABC TU QSO 73",TYPE_FINAL,123),w._rx_generation)
            self.app.processEvents()
            self.assertEqual(w.paths.log_file.read_text(encoding="utf-8").count("<EOR>"),1)
            w.close()

    def test_pending_templates_are_gray_and_autocq_rejection_visible(self):
        from pstbskx.app import MainWindow
        with tempfile.TemporaryDirectory() as td:
            w=MainWindow(Path(td)); w.first_launch=False
            self.assertIn("color:#888",w.report_btn.label.styleSheet())
            w.session.select_decode(DecodeRow(datetime.now(timezone.utc),1500,-10,"JA1ABC","CQ CQ DE JA1ABC"))
            w._refresh_session()
            self.assertIn("color:#202020",w.report_btn.label.styleSheet())
            w.autocq_btn.click()
            self.assertFalse(w.autocq_btn.isChecked())
            self.assertEqual(w.statusBar().currentMessage(),
                             "無線機へ接続するか『未接続でも送信可』を有効にしてください。")
            w.close()

    def test_autocq_active_button_has_a_red_face(self):
        from pstbskx.app import MainWindow
        with tempfile.TemporaryDirectory() as td:
            w=MainWindow(Path(td)); w.first_launch=False
            w.allow_disconnected.setChecked(True); w.show(); self.app.processEvents()
            with patch.object(w,"tx",return_value=True):
                w.autocq_btn.click(); self.app.processEvents()
                self.assertTrue(w.autocq_btn.isChecked())
                image=w.autocq_btn.grab().toImage()
                face=image.pixelColor(6,image.height()//2)
                self.assertGreater(face.red(),120)
                self.assertLess(face.green(),75)
                self.assertLess(face.blue(),100)
            w.stop_autocq(); self.app.processEvents()
            face=w.autocq_btn.grab().toImage().pixelColor(6,w.autocq_btn.height()//2)
            self.assertGreater(face.green(),170)
            w.close()
