import os
import sys
import tempfile
import threading
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from pstbskx.rx_decoder import BurstDecoder


class BrowserStreamingTests(unittest.TestCase):
    def test_web_tone_after_four_seconds_of_continuous_audio(self):
        # The 0.11 detector searched only the start of a continuous burst.
        with patch.dict(sys.modules,{"sounddevice":types.ModuleType("sounddevice")}):
            from pstbskx.tbsk_phy import TbskPhy
            low=np.asarray(TbskPhy(sample_rate=16000,points=10).modulate(
                "CQ CQ CQ DE JH1HST JH1HST JCC 1321 PSE BK".encode()),dtype=np.float32)
            web=np.interp(np.arange(len(low)*3)/3,np.arange(len(low)),low)
            rng=np.random.default_rng(7)
            samples=rng.normal(0,.0004,48000*12).astype(np.float32)
            samples[48000*4:48000*4+len(web)]+=.7*web
            received=[]; stages=[]; done=threading.Event()
            rx=BurstDecoder(lambda frame:(received.append(frame),done.set()),
                            on_diagnostic=stages.append)
            rx.start()
            try:
                for i in range(0,len(samples),2048):
                    self.assertTrue(rx.feed(samples[i:i+2048]))
                self.assertTrue(done.wait(15))
                self.assertEqual(received[0].text,
                    "CQ CQ CQ DE JH1HST JH1HST JCC 1321 PSE BK")
                self.assertEqual(received[0].source,"raw")
                self.assertIn("decoded",stages)
            finally: rx.close()


class UiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
        from PySide6.QtWidgets import QApplication
        cls.app=QApplication.instance() or QApplication([])

    def test_help_order_and_engine_heading(self):
        from pstbskx.app import MainWindow
        with tempfile.TemporaryDirectory() as td:
            w=MainWindow(Path(td)); w.first_launch=False
            self.assertEqual([a.text() for a in w.m_help.actions() if not a.isSeparator()],
                ["運用上の注意","ウィンドウサイズ・位置をリセット",
                 "PSTBSK-Xのバージョンアップ","PSTBSK-Xについて"])
            w.show_about()
            self.assertEqual(w.about_window.third_h.text(),"TBSKモデムエンジン")
            w.set_language("en")
            self.assertEqual(w.about_window.third_h.text(),"TBSK modem engine")
            w.close()

    def test_streaming_raw_prefix_is_extended_in_place(self):
        from datetime import datetime, timezone
        from pstbskx.app import MainWindow
        from pstbskx.rx_decoder import ReceivedFrame
        with tempfile.TemporaryDirectory() as td:
            w=MainWindow(Path(td)); w.first_launch=False; w._rx_active=True
            when=datetime.now(timezone.utc)
            for msg in ("CQ CQ CQ DE JH1HST","CQ CQ CQ DE JH1HST JH1HST JCC 1321 PSE BK"):
                w.rx_frame.emit(ReceivedFrame(when,1600,0.,"--",msg,0,-1,"raw"),w._rx_generation)
                self.app.processEvents()
            self.assertEqual(len(w._rows),1)
            self.assertIn("JCC 1321 PSE BK",w.decode.toPlainText())
            self.assertIn("S/N -- dB",w.decode.toPlainText())
            w.close()
