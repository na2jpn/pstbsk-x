import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from pstbskx.frame import TYPE_CQ, pack_frame
from pstbskx.rx_decoder import BurstDecoder
from pstbskx.tone_profiles import tx_points


class WebToneTests(unittest.TestCase):
    def test_16khz_resampled_utf8_and_corrupt_ptx1(self):
        with patch.dict(sys.modules, {"sounddevice": types.ModuleType("sounddevice")}):
            from pstbskx.tbsk_phy import TbskPhy
            phy=TbskPhy(sample_rate=16000, points=10)
            def wave(data):
                low=np.asarray(phy.modulate(data),dtype=np.float32)
                high=np.interp(np.arange(len(low)*3)/3,np.arange(len(low)),low)
                return np.r_[np.zeros(4000),high,np.zeros(16000)]
            decoded=BurstDecoder(lambda _:None).decode_burst(wave("今日は草加からです".encode("utf-8")))
            self.assertEqual([(x.text,x.source,x.af_hz) for x in decoded],
                             [("今日は草加からです","raw",1600)])
            bad=bytearray(pack_frame(TYPE_CQ,9,"CQ CQ DE JA1ABC JA1ABC K")); bad[-1]^=0x01
            self.assertEqual(BurstDecoder(lambda _:None).decode_burst(wave(bytes(bad))),[])

    def test_tx_profile_mapping(self):
        self.assertEqual(tx_points("pstbskx_150",1500),32)
        self.assertEqual(tx_points("web_160",1500),30)
        with patch.dict(sys.modules, {"sounddevice": types.ModuleType("sounddevice")}):
            from pstbskx.tbsk_phy import TbskPhy
            from pstbskx.tone_profiles import modulate_profile
            actual=modulate_profile("web_160",1500,b"TEST")
            low=np.asarray(TbskPhy(sample_rate=16000,points=10).modulate(b"TEST"))
            expected=np.interp(np.arange(len(low)*3)/3,np.arange(len(low)),low)
            np.testing.assert_allclose(actual,expected,atol=1e-6)


class RawUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
        from PySide6.QtWidgets import QApplication
        cls.app=QApplication.instance() or QApplication([])

    def test_raw_does_not_select_station_or_log_qso(self):
        from datetime import datetime, timezone
        from pstbskx.app import MainWindow
        from pstbskx.rx_decoder import ReceivedFrame
        with tempfile.TemporaryDirectory() as td:
            w=MainWindow(Path(td)); w.first_launch=False; w._rx_active=True
            w.rx_frame.emit(ReceivedFrame(datetime.now(timezone.utc),1600,5,"--",
                "RRR JH1HST DE JA1ABC TU QSO 73",0,-1,"raw"),w._rx_generation)
            self.app.processEvents()
            self.assertIn("[TBSK RAW]",w.decode.toPlainText())
            self.assertFalse(w.session.his_call)
            self.assertFalse(w.paths.log_file.exists())
            self.assertIsNone(w.qso_log_window)
            w.close()
