"""Physical tone presets. Capture/output devices stay at 48 kHz.

The Web/CLI preset uses xpsk:10,10 at 16 kHz (100 samples per symbol).
At 48 kHz the same timing and nominal carrier use 30 points/cycle and
300 samples/symbol. This is a timing match, not a claim of validated RF
interoperability with every browser/audio resampler.
"""

PROFILES = {
    "pstbskx_150": {"points": 32, "bps": 150, "af": 1500},
    "web_160": {"points": 30, "bps": 160, "af": 1600},
}


def normalize_profile(value):
    return value if value in PROFILES else "pstbskx_150"


def tx_points(profile, af_hz):
    profile = normalize_profile(profile)
    if profile == "web_160":
        return 30
    return max(18, min(160, round(48000 / max(300, af_hz))))


def modulate_profile(profile, af_hz, payload):
    from .tbsk_phy import TbskPhy
    profile = normalize_profile(profile)
    if profile == "web_160":
        import numpy as np
        pcm = np.asarray(TbskPhy(sample_rate=16000,points=10).modulate(payload),dtype=np.float32)
        return np.interp(np.arange(len(pcm)*3)/3,np.arange(len(pcm)),pcm).astype(np.float32)
    return TbskPhy(points=tx_points(profile,af_hz)).modulate(payload)
