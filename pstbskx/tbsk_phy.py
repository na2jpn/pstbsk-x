"""Thin wrapper around nyatla/TBSKmodem modulation/demodulation APIs."""
from __future__ import annotations

class TbskPhy:
    def __init__(self, sample_rate=48000, points=32, cycles=10, amplitude=0.5,
                 tone_type="xpsk"):
        self.sample_rate=sample_rate
        self.points=points; self.cycles=cycles; self.amplitude=amplitude
        try:
            from tbskmodem import TbskModulator, TbskDemodulator, TbskTone
        except Exception as e:
            raise RuntimeError("tbskmodem is not installed") from e
        self._TbskDemodulator=TbskDemodulator
        self.tone=(TbskTone.createSin(points, cycles) if tone_type == "sin"
                   else TbskTone.createXPskSin(points, cycles)).mul(amplitude)
        self.mod=TbskModulator(self.tone)
    @property
    def nominal_bps(self):
        return self.sample_rate/len(self.tone)
    def modulate(self, payload:bytes):
        return list(self.mod.modulate(payload))
    def demodulate_bytes(self, samples):
        demod=self._TbskDemodulator(self.tone)
        it=demod.demodulateAsBytes(iter(samples))
        if it is None: return None
        return b"".join(it)
