"""Narrowband audio and PTX1 receive interoperability checks."""
import sys
import types
import unittest
from unittest.mock import patch

import numpy as np

from pstbskx.frame import TYPE_CQ, pack_frame
from pstbskx.tone_profiles import (AF_OBW_TARGET_HZ, TX_PROFILE,
                                  audio_occupied_bandwidth, modulate_profile,
                                  normalize_profile)
from pstbskx.rx_decoder import BurstDecoder


class NarrowTxTests(unittest.TestCase):
    def test_migrated_settings_cannot_transmit_old_waveform(self):
        self.assertEqual(normalize_profile("web_160"), TX_PROFILE)
        self.assertEqual(normalize_profile("pstbskx_150"), TX_PROFILE)
        data=pack_frame(TYPE_CQ,42,"CQ CQ DE JH1HST JH1HST K")
        with patch.dict(sys.modules,{"sounddevice":types.ModuleType("sounddevice")}):
            actual=modulate_profile("web_160",2700,data)
            expected=modulate_profile(TX_PROFILE,1500,data)
        np.testing.assert_array_equal(actual,expected)

    def test_transmit_audio_width_and_receive_roundtrip(self):
        data=pack_frame(TYPE_CQ,42,"CQ CQ DE JH1HST JH1HST K")
        with patch.dict(sys.modules,{"sounddevice":types.ModuleType("sounddevice")}):
            pcm=modulate_profile(TX_PROFILE,1500,data)
            width,low,high=audio_occupied_bandwidth(pcm)
            decoded=BurstDecoder(lambda _:None).decode_burst(
                np.r_[np.zeros(4000),pcm,np.zeros(16000)])
        self.assertLessEqual(width,AF_OBW_TARGET_HZ)
        self.assertLess(low,1500)
        self.assertGreater(high,1500)
        self.assertEqual([(f.text,f.call,f.source) for f in decoded],
                         [("CQ CQ DE JH1HST JH1HST K","JH1HST","ptx1")])
