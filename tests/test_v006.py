import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from pstbskx.audio_io import device_choices, resolve_device, play_samples
from pstbskx.frame import unpack_frame, TYPE_CQ


class FakeAudio:
    def __init__(self):
        self.written=0
    def query_hostapis(self):
        return [{"name":"MME"},{"name":"Windows WASAPI"}]
    def query_devices(self):
        return [
            {"name":"USB Audio", "hostapi":0,"max_output_channels":2,"max_input_channels":0},
            {"name":"USB Audio", "hostapi":1,"max_output_channels":2,"max_input_channels":0},
            {"name":"Mic", "hostapi":1,"max_output_channels":0,"max_input_channels":1},
        ]
    def check_output_settings(self, **kwargs):
        if kwargs["device"]!=1: raise RuntimeError("Wrong output")
    def OutputStream(self, **kwargs):
        self.check_output_settings(**{k:v for k,v in kwargs.items() if k in ("device","channels","samplerate","dtype")})
        return self
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def write(self, data): self.written+=len(data)


class AudioTests(unittest.TestCase):
    def test_prefers_single_wasapi_endpoint_and_plays_selected_device(self):
        fake=FakeAudio()
        items=device_choices("output",fake)
        self.assertEqual(len(items),1)
        self.assertEqual(items[0][2],1)
        self.assertEqual(resolve_device(items[0][1],sd=fake),1)
        self.assertTrue(play_samples([.1]*2048,items[0][1],threading.Event(),fake))
        self.assertEqual(fake.written,2048)

    def test_keeps_two_identically_named_wasapi_devices_separately(self):
        fake=FakeAudio()
        original=fake.query_devices
        fake.query_devices=lambda:original()+[{"name":"USB Audio","hostapi":1,"max_output_channels":2,"max_input_channels":0}]
        items=device_choices("output",fake)
        self.assertEqual(len(items),2)
        self.assertEqual([resolve_device(item[1],sd=fake) for item in items],[1,3])


class UiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
        from PySide6.QtWidgets import QApplication
        cls.app=QApplication.instance() or QApplication([])

    def test_reset_keeps_hidden_windows_hidden_and_sequence_can_repeat(self):
        from pstbskx.app import MainWindow
        with tempfile.TemporaryDirectory() as td:
            w=MainWindow(Path(td)); w.show(); self.app.processEvents()
            w.show_about(); self.app.processEvents(); w.about_window.close()
            w.reset_windows(); self.app.processEvents()
            self.assertFalse(w.about_window.isVisible())
            self.assertIsNone(w.settings_window)
            w._select_sequence("report"); self.assertTrue(w.report_radio.isChecked())
            w._select_sequence("cq"); self.assertTrue(w.cq_radio.isChecked())
            w._select_sequence("cq"); self.assertTrue(w.cq_radio.isChecked())
            w.close()

    def test_updater_path_field_explains_itself_and_shows_selection(self):
        from pstbskx.app import MainWindow
        with tempfile.TemporaryDirectory() as td:
            w=MainWindow(Path(td)); w.show_update(); self.app.processEvents()
            update=w.update_window
            self.assertEqual(update.path_label.text(),"選択した更新ZIP")
            self.assertIn("まだ選択",update.path.placeholderText())
            chosen=str(Path(td)/"PSTBSK-X_0.07_win64.zip")
            with patch("pstbskx.app.QFileDialog.getOpenFileName",return_value=(chosen,"ZIP")):
                update.select_zip()
            self.assertEqual(update.path.text(),chosen)
            self.assertEqual(update.path.toolTip(),chosen)
            w.close()

    def test_real_tx_frames_audio_and_releases_ptt_on_error(self):
        from pstbskx.app import MainWindow
        class Radio:
            def __init__(self): self.ptt=[]
            def set_ptt(self,on): self.ptt.append(on); return True
            def disconnect(self): pass
        def modulate(profile,af,payload):
            frame=unpack_frame(payload)
            assert frame and frame["type"]==TYPE_CQ
            return [.1]*1200
        with tempfile.TemporaryDirectory() as td:
            w=MainWindow(Path(td)); w.config["callsign"]="JH1HST"; w.apply_settings()
            radio=Radio(); w.radio=radio; w._update_connection_label()
            with patch("pstbskx.app.modulate_profile",modulate), patch("pstbskx.app.audio_occupied_bandwidth",return_value=(500,1250,1750)), patch("pstbskx.app.check_output"), patch("pstbskx.app.play_samples",return_value=True) as output:
                self.assertTrue(w.tx(w.session.cq_text(),"cq",True))
                deadline=time.monotonic()+3
                while w._tx_busy and time.monotonic()<deadline:
                    self.app.processEvents(); time.sleep(.005)
                self.assertEqual(radio.ptt,[True,False])
                output.assert_called_once()
                self.assertFalse(w._tx_busy)
            with patch("pstbskx.app.modulate_profile",modulate), patch("pstbskx.app.audio_occupied_bandwidth",return_value=(500,1250,1750)), patch("pstbskx.app.check_output"), patch("pstbskx.app.play_samples",side_effect=RuntimeError("device busy")):
                self.assertTrue(w.tx(w.session.cq_text(),"cq",True))
                deadline=time.monotonic()+3
                while w._tx_busy and time.monotonic()<deadline:
                    self.app.processEvents(); time.sleep(.005)
                self.assertEqual(radio.ptt,[True,False,True,False])
                self.assertIn("device busy",w.statusBar().currentMessage())
            w.stop_autocq()
            with patch("pstbskx.app.modulate_profile",modulate), patch("pstbskx.app.audio_occupied_bandwidth",return_value=(1600,700,2300)), patch("pstbskx.app.check_output") as check:
                self.assertTrue(w.tx(w.session.cq_text(),"cq",True))
                deadline=time.monotonic()+3
                while w._tx_busy and time.monotonic()<deadline:
                    self.app.processEvents(); time.sleep(.005)
                self.assertEqual(radio.ptt,[True,False,True,False])
                check.assert_not_called()
                self.assertIn("1.5 kHz",w.statusBar().currentMessage())
            w.radio=None; w.close()
