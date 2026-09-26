"""PortAudio device selection and cancellable TBSK output.

Device names are resolved anew at startup: PortAudio indices can change after
Windows devices are plugged in or removed.
"""
from __future__ import annotations

import re

SAMPLE_RATE = 48000


def _sd():
    import sounddevice
    return sounddevice


def _rank(api_name):
    name = api_name.lower()
    for priority, token in enumerate(("wasapi", "asio", "wdm-ks", "directsound", "mme")):
        if token in name:
            return priority
    return 10


def device_choices(kind, sd=None):
    """Prefer one host driver per name, retaining same-named physical endpoints.

    Names are folded only within the same direction. The selected item keeps a
    stable host/name identity and resolves to the current PortAudio index at use.
    """
    sd = sd or _sd()
    devices = sd.query_devices()
    hosts = sd.query_hostapis()
    channels = "max_input_channels" if kind == "input" else "max_output_channels"
    groups = {}
    for index, device in enumerate(devices):
        if not device.get(channels, 0):
            continue
        name = str(device["name"]).strip()
        host = str(hosts[device["hostapi"]]["name"])
        canonical = re.sub(r"\s+", " ", name).casefold()
        groups.setdefault(canonical, []).append((_rank(host), index, name, host))
    choices=[]
    for group in groups.values():
        priority=min(item[0] for item in group)
        selected=sorted((item for item in group if item[0]==priority), key=lambda item:item[1])
        for ordinal, (_,index,name,host) in enumerate(selected,1):
            suffix=f" #{ordinal}" if len(selected)>1 else ""
            choices.append((f"{name}{suffix} ({host})", f"{host}|{name}|{ordinal}", index))
    return sorted(choices,key=lambda item:item[0].casefold())


def resolve_device(value, kind="output", sd=None):
    sd = sd or _sd()
    if value in (None, "", "AUTO"):
        return None
    if value == "UNSET":
        raise ValueError("Audio device is not selected")
    devices = sd.query_devices()
    channels = "max_input_channels" if kind == "input" else "max_output_channels"
    if str(value).isdecimal():  # legacy Ver0.05 configuration
        index = int(value)
        if index < len(devices) and devices[index].get(channels, 0):
            return index
        raise ValueError("Saved audio device is no longer available")
    if "|" not in str(value):
        raise ValueError("Invalid audio device selection")
    parts = str(value).split("|")
    if len(parts) not in (2,3): raise ValueError("Invalid audio device selection")
    host,name=parts[:2]
    ordinal=int(parts[2]) if len(parts)==3 else 1
    hosts = sd.query_hostapis()
    matches=[]
    for index, device in enumerate(devices):
        if device.get(channels, 0) and device["name"] == name and hosts[device["hostapi"]]["name"] == host:
            matches.append(index)
    if 0 < ordinal <= len(matches): return matches[ordinal-1]
    raise ValueError(f"Audio device is no longer available: {name}")


def check_output(device, sd=None, sample_rate=SAMPLE_RATE):
    sd = sd or _sd()
    index = resolve_device(device, "output", sd)
    sd.check_output_settings(device=index, channels=1, samplerate=sample_rate, dtype="float32")
    return index


def check_input(device, sd=None, sample_rate=SAMPLE_RATE):
    sd = sd or _sd()
    index = resolve_device(device, "input", sd)
    sd.check_input_settings(device=index, channels=1, samplerate=sample_rate, dtype="float32")
    return index


def capture_input(device, stop, on_samples, sd=None, sample_rate=SAMPLE_RATE):
    """Read selected Audio IN until stopped. Runs only in a worker thread."""
    sd = sd or _sd()
    index = resolve_device(device, "input", sd)
    info = sd.query_devices()[index]
    # A stereo-mix endpoint may take a different Windows path when opened as
    # one channel. Keep its native pair, then fold it to mono for TBSK RX.
    candidates = [2, 1] if info.get("max_input_channels", 0) >= 2 else [1]
    rates = [sample_rate]
    native = round(info.get("default_samplerate", sample_rate))
    if native != sample_rate: rates.append(native)
    for actual_rate in rates:
        for channels in candidates:
            try:
                sd.check_input_settings(device=index, channels=channels,
                                        samplerate=actual_rate, dtype="float32")
                break
            except Exception:
                continue
        else:
            continue
        break
    else:
        raise ValueError("Selected Audio IN does not support mono or stereo capture")
    with sd.InputStream(device=index, channels=channels, samplerate=actual_rate,
                        dtype="float32", blocksize=2048) as stream:
        while not stop.is_set():
            data, overflowed = stream.read(2048)
            if not stop.is_set():
                samples=data.mean(axis=1) if channels == 2 else data[:, 0].copy()
                if actual_rate != sample_rate:
                    import numpy as np
                    length=round(len(samples)*sample_rate/actual_rate)
                    samples=np.interp(np.arange(length)*actual_rate/sample_rate,
                                      np.arange(len(samples)),samples).astype("float32")
                on_samples(samples)


def play_samples(samples, device, stop, sd=None, sample_rate=SAMPLE_RATE, on_chunk=None):
    """Complete only after the output stream has drained; STOP interrupts chunks."""
    sd = sd or _sd()
    import numpy as np
    index = check_output(device, sd, sample_rate)
    data = np.asarray(samples, dtype="float32").reshape(-1, 1)
    with sd.OutputStream(device=index, channels=1, samplerate=sample_rate,
                         dtype="float32", blocksize=1024) as stream:
        for offset in range(0, len(data), 1024):
            if stop.is_set():
                return False
            stream.write(data[offset:offset + 1024])
            if on_chunk is not None:
                on_chunk(data[offset:offset + 1024, 0])
        # PortAudio write can return before the final block has reached the DAC.
        remaining = len(data) / sample_rate
        stop.wait(min(0.16, remaining))
        return not stop.is_set()


def monitor_tone(device, stop, sd=None):
    import numpy as np
    t = np.arange(SAMPLE_RATE, dtype="float32") / SAMPLE_RATE
    envelope = np.minimum(1.0, np.minimum(t * 25, (1 - t) * 25))
    return play_samples(0.2 * np.sin(2 * np.pi * 800 * t) * envelope,
                        device, stop, sd)
