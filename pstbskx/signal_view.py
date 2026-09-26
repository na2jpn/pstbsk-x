"""Audio-level and spectrum measurements for the live RX/TX display.

The display uses dBFS (not RF S/N). Decoding and report S/N need separate
measurements made on a validated TBSK frame.
"""
from __future__ import annotations

import numpy as np

SPECTRUM_BINS = 256


def measure_audio(samples, sample_rate=48000):
    signal = np.asarray(samples, dtype=np.float32).reshape(-1)
    if not len(signal):
        return np.full(SPECTRUM_BINS, -120., dtype=np.float32), -120.
    rms = float(np.sqrt(np.mean(signal.astype(np.float64) ** 2)))
    level = 20 * np.log10(max(rms, 1e-6))
    size = min(len(signal), 4096)
    window = np.hanning(size)
    spectrum = np.abs(np.fft.rfft(signal[-size:] * window)) / max(window.sum() / 2, 1)
    freqs = np.fft.rfftfreq(size, 1 / sample_rate)
    # Peak within each display bin preserves narrow tones at any audio offset.
    valid = freqs <= 3000
    indices = np.minimum((freqs[valid] * SPECTRUM_BINS / 3000).astype(int), SPECTRUM_BINS - 1)
    peaks = np.zeros(SPECTRUM_BINS, dtype=np.float32)
    np.maximum.at(peaks, indices, spectrum[valid])
    return (20 * np.log10(np.maximum(peaks, 1e-6))).astype(np.float32), float(level)


def meter_percent(dbfs):
    """Map -60..0 dBFS to a stable 0..100 meter scale."""
    return max(0, min(100, round((dbfs + 60) * 100 / 60)))
