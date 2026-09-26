import os
import tempfile
import threading
import unittest
from pathlib import Path

import numpy as np

from pstbskx.audio_io import capture_input
from pstbskx.signal_view import measure_audio, meter_percent


class CaptureTests(unittest.TestCase):
    def test_tone_bin_and_meter_come_from_audio_samples(self):
        t=np.arange(4096)/48000
        profile,level=measure_audio(0.2*np.sin(2*np.pi*1500*t))
        self.assertAlmostEqual(profile.argmax()*3000/256,1500,delta=18)
        self.assertGreater(meter_percent(level),50)
        silence,_=measure_audio(np.zeros(4096))
        self.assertLess(float(silence.max()),-110)

    def test_input_stream_uses_saved_endpoint(self):
        stop=threading.Event()
        class FakeSound:
            def query_devices(self): return [{"name":"A","hostapi":0,"max_input_channels":1}]
            def query_hostapis(self): return [{"name":"WASAPI"}]
            def check_input_settings(self,**args):
                assert args["device"]==0 and args["channels"]==1
            def InputStream(self,**args):
                assert args["device"]==0
                return self
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def read(self,size): return np.ones((size,1),np.float32)*.2,False
        chunks=[]
        def on_chunk(data):
            chunks.append(data); stop.set()
        capture_input("WASAPI|A|1",stop,on_chunk,FakeSound())
        self.assertEqual(len(chunks),1)
        self.assertEqual(chunks[0].shape,(2048,))

    def test_input_falls_back_to_supported_device_rate(self):
        stop=threading.Event()
        class FakeSound:
            def query_devices(self,index=None):
                devices=[{"name":"B","hostapi":0,"max_input_channels":1,"default_samplerate":44100}]
                return devices if index is None else devices[index]
            def query_hostapis(self): return [{"name":"WASAPI"}]
            def check_input_settings(self,**args):
                if args["samplerate"] != 44100: raise ValueError("unsupported rate")
            def InputStream(self,**args):
                assert args["samplerate"]==44100
                return self
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def read(self,size): return np.zeros((size,1),np.float32),False
        chunks=[]
        def on_chunk(data):
            chunks.append(data); stop.set()
        capture_input("WASAPI|B|1",stop,on_chunk,FakeSound())
        self.assertAlmostEqual(len(chunks[0]),2048*48000/44100,delta=1)

    def test_stereo_mix_opens_two_channels_and_folds_to_mono(self):
        stop=threading.Event()
        class FakeSound:
            def query_devices(self):
                return [{"name":"Stereo Mix","hostapi":0,"max_input_channels":2,
                         "default_samplerate":48000}]
            def query_hostapis(self): return [{"name":"WASAPI"}]
            def check_input_settings(self,**args):
                assert args["channels"]==2 and args["samplerate"]==48000
            def InputStream(self,**args):
                assert args["channels"]==2
                return self
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def read(self,size):
                return np.tile([.2,.4],(size,1)).astype(np.float32),False
        chunks=[]
        def on_chunk(data):
            chunks.append(data); stop.set()
        capture_input("WASAPI|Stereo Mix|1",stop,on_chunk,FakeSound())
        self.assertEqual(chunks[0].shape,(2048,))
        self.assertAlmostEqual(float(chunks[0][0]),.3,places=5)


class DisplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
        from PySide6.QtWidgets import QApplication
        cls.app=QApplication.instance() or QApplication([])

    def test_receive_controls_and_tx_switch_at_default_size(self):
        from pstbskx.app import MainWindow
        with tempfile.TemporaryDirectory() as td:
            w=MainWindow(Path(td)); w.first_launch=False; w.config["callsign"]="JH1HST"; w.resize(1280,800); w.show(); self.app.processEvents()
            self.assertEqual(w.right_scroll.verticalScrollBar().maximum(),0)
            self.assertEqual(w.main_scroll.verticalScrollBar().maximum(),0)
            w.sensitivity.setValue(70); w.sq_value.setValue(20)
            self.assertEqual(w.config["rx_display"],{"sq":20,"sensitivity":70})
            profile,_=measure_audio(.3*np.sin(2*np.pi*1000*np.arange(4096)/48000))
            w._rx_active=True  # Simulate a running input stream.
            w._received_audio(profile,-17.,w._rx_generation)
            self.assertGreater(w.rx_meter.value(),20)
            self.assertEqual(w.sq_state.toolTip(),"SQ 開")
            self.assertIsNotNone(w.spectrum.spectrum)
            self.app.processEvents(); self.assertFalse(w.spectrum.grab().isNull())
            w._tx_busy=True; w._tx_auto=False; w._spectrum_title()
            self.assertTrue(w.spec_group.title().startswith("TX"))
            w._transmitted_audio(profile)
            self.assertIsNotNone(w.spectrum.spectrum)
            w._transmission_completed("cq",False,"",None)
            self.assertTrue(w.spec_group.title().startswith("RX"))
            self.assertIsNone(w.spectrum.spectrum)
            w.close()
