"""Narrowband transmitter; legacy XPskSin presets remain receive-only.

Existing 0.14 TX configuration values migrate to narrowband transmission.
Generated audio measurements cannot certify a connected radio's RF output.
"""

import numpy as np

TX_PROFILE = "narrow_100"
TX_AF_HZ = 1500
TX_POINTS = 32
TX_CYCLES = 24  # 48000 / (32 * 24) = 62.5 symbols/second
AF_OBW_TARGET_HZ = 1500


def normalize_profile(value):
    """Never carry a legacy wideband TX selection into 0.15."""
    return TX_PROFILE


def tx_points(profile, af_hz):
    return TX_POINTS


def modulate_profile(profile, af_hz, payload):
    from .tbsk_phy import TbskPhy
    return np.asarray(TbskPhy(points=TX_POINTS, cycles=TX_CYCLES,
                              tone_type="sin").modulate(payload), dtype=np.float32)


def audio_occupied_bandwidth(samples, sample_rate=48000):
    """99% occupied audio width and 0.5%/99.5% frequency edges (Hz).

    Average Hann-windowed active PCM blocks to avoid a huge FFT for long TX.
    This is an engineering AF check, not an RF occupied-bandwidth measurement.
    """
    signal = np.asarray(samples, dtype=np.float64).reshape(-1)
    size = 16384
    if len(signal) < size:
        signal = np.pad(signal, (0, size - len(signal)))
    window = np.hanning(size)
    power = np.zeros(size // 2 + 1, dtype=np.float64)
    for start in range(0, len(signal) - size + 1, size // 2):
        block = signal[start:start + size]
        if np.max(np.abs(block)) < 1e-6:
            continue
        power += np.abs(np.fft.rfft(block * window)) ** 2
    if not np.any(power):
        raise ValueError("No audio signal")
    power[1:-1] *= 2
    cumulative = np.cumsum(power) / np.sum(power)
    frequency = np.fft.rfftfreq(size, 1 / sample_rate)
    low, high = np.interp([.005, .995], cumulative, frequency)
    return float(high - low), float(low), float(high)
