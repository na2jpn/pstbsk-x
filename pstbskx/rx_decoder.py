"""Burst receiver for PSTBSK-X frames in the 300–2700 Hz audio passband.

Search narrowband SinTone(32,24) and legacy XPskSin preambles before
demodulation. PTX1 frames require length/CRC validation; raw UTF-8 is
displayed separately.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import math
import queue
import re
import threading

import numpy as np

from .audio_io import SAMPLE_RATE
from .frame import unpack_frame, TYPE_CQ, TYPE_REPORT, TYPE_QSL, TYPE_FINAL
from .qso import CQ_RE, CALL
from .tbsk_phy import TbskPhy
from .tone_profiles import TX_POINTS, TX_CYCLES

_FROM = re.compile(rf"\bDE\s+(?P<call>{CALL})\b", re.I)


@dataclass(frozen=True)
class ReceivedFrame:
    when: datetime
    af_hz: int
    snr_db: float
    call: str
    text: str
    kind: int
    seq: int
    source: str = "ptx1"


def sender_call(text: str, kind: int) -> str:
    match = CQ_RE.match(text) if kind == TYPE_CQ else _FROM.search(text)
    return match.group("frm" if kind == TYPE_CQ else "call").upper() if match else "--"


class BurstDecoder:
    """One decoder worker; feed() must never block the PortAudio capture loop."""

    def __init__(self, on_frame, sample_rate=SAMPLE_RATE, *, threshold_db=-53,
                 on_diagnostic=None):
        self.on_frame = on_frame
        self.on_diagnostic = on_diagnostic or (lambda stage: None)
        self.sample_rate = sample_rate
        self.threshold_db = threshold_db
        self.queue = queue.Queue(maxsize=1600)
        self.stop = threading.Event()
        self.thread = None
        self._templates = None

    def start(self):
        self.thread = threading.Thread(target=self._run, daemon=True, name="PSTBSK-X TBSK RX")
        self.thread.start()

    def close(self):
        self.stop.set()
        try: self.queue.put_nowait(None)
        except queue.Full: pass

    def feed(self, samples):
        if self.stop.is_set(): return False
        try:
            self.queue.put_nowait(np.asarray(samples, dtype=np.float32).copy())
            return True
        except queue.Full:
            # A stale partial burst cannot safely be decoded after dropped PCM.
            self.close()
            return False

    def _run(self):
        chunks = []
        quiet = 0
        last_probe = 0
        preroll = []
        # Up to 512 UTF-8 payload bytes at the slowest 300 Hz setting can
        # occupy roughly 140 seconds on the air.
        max_samples = self.sample_rate * 150
        for_chunk = self.sample_rate // 3
        while not self.stop.is_set():
            try: chunk = self.queue.get(timeout=.2)
            except queue.Empty: continue
            if chunk is None: break
            rms = float(np.sqrt(np.mean(np.square(chunk.astype(np.float64)))))
            active = 20 * math.log10(max(rms, 1e-8)) >= self.threshold_db
            if not chunks:
                if active:
                    chunks = preroll + [chunk]
                    quiet = 0
                else:
                    preroll.append(chunk)
                    while sum(map(len, preroll)) > self.sample_rate // 4:
                        preroll.pop(0)
                continue
            chunks.append(chunk)
            quiet = 0 if active else quiet + len(chunk)
            length = sum(map(len, chunks))
            # Receiver noise can keep the level above SQ indefinitely. Probe
            # short rolling windows even without a silent inter-frame gap.
            if length - last_probe >= self.sample_rate * 3 and length >= self.sample_rate * 6:
                recent = np.concatenate(chunks)[-self.sample_rate * 9:]
                try:
                    for frame in self.decode_burst(recent):
                        if not self.stop.is_set(): self.on_frame(frame)
                except Exception:
                    self.on_diagnostic("error")
                last_probe = length
            if quiet >= for_chunk or length >= max_samples:
                burst = np.concatenate(chunks)
                if not self.stop.is_set():
                    try:
                        for frame in self.decode_burst(burst):
                            if not self.stop.is_set(): self.on_frame(frame)
                    except Exception:
                        self.on_diagnostic("error")
                preroll = [chunk] if not active else []
                chunks = []
                quiet = 0
                last_probe = 0

    def _tone_templates(self):
        if self._templates is None:
            # The encoder's AF selection quantizes to integral points/cycle.
            self._templates = []
            for points in range(round(self.sample_rate / 2700),
                                round(self.sample_rate / 300) + 1):
                phy = TbskPhy(sample_rate=self.sample_rate, points=points)
                # A preamble carries a known waveform. Twelve tone lengths
                # distinguish it from copies of the tone in the payload.
                wave = np.asarray(phy.modulate(b""), dtype=np.float32)
                template = wave[:points * 10 * 12]
                self._templates.append((points, template, "xpsk", 10))
            narrow = TbskPhy(sample_rate=self.sample_rate, points=TX_POINTS,
                             cycles=TX_CYCLES, tone_type="sin")
            wave = np.asarray(narrow.modulate(b""), dtype=np.float32)
            self._templates.append((TX_POINTS, wave[:TX_POINTS * TX_CYCLES * 12],
                                    "sin", TX_CYCLES))
            # Browser/CLI preset is generated at 16 kHz with xpsk:10,10.
            # Its sampled waveform differs from a freshly generated 48 kHz
            # xpsk:30,10 waveform, despite their identical symbol duration.
            if self.sample_rate == 48000:
                web = np.asarray(TbskPhy(sample_rate=16000, points=10).modulate(b""),dtype=np.float32)
                up = np.interp(np.arange(len(web)*3)/3,np.arange(len(web)),web).astype(np.float32)
                self._templates.append((30,up[:30*10*12],"web",10))
        return self._templates

    def decode_burst(self, samples):
        """Decode completed audio; also useful for recorded PCM tests."""
        signal = np.asarray(samples, dtype=np.float32).reshape(-1)
        if len(signal) < 3000: return []
        # Search the first 3 seconds for each preamble; candidates are ranked
        # by normalized correlation rather than a narrow spectral peak (XPSK
        # spreads energy away from its nominal AF frequency).
        search = signal[:min(len(signal), self.sample_rate * 3)]
        nfft = 1 << (len(search) + round(self.sample_rate / 300) * 10 * 12 - 1).bit_length()
        spectrum = np.fft.rfft(search, nfft)
        scores = []
        for points, template, tone_type, cycles in self._tone_templates():
            if len(template) >= len(search): continue
            corr = np.fft.irfft(spectrum * np.conj(np.fft.rfft(template, nfft)), nfft)
            valid = corr[:len(search) - len(template) + 1]
            # Normalize using local input energy, preventing a loud unrelated
            # burst from overwhelming a quieter but matching preamble.
            energy = np.cumsum(np.r_[0., np.square(search.astype(np.float64))])
            local = energy[len(template):] - energy[:-len(template)]
            coherence = np.abs(valid) / np.sqrt(np.maximum(local, 1e-9) *
                                                np.dot(template, template))
            strongest = float(np.max(coherence))
            # Payload may contain another exact copy of the tone; start at the
            # earliest strong match so the TBSK preamble is not skipped.
            matches = np.flatnonzero(coherence >= max(.55, strongest * .80))
            at = int(matches[0]) if len(matches) else int(np.argmax(coherence))
            scores.append((float(coherence[at]), points, at, tone_type, cycles))
        scores.sort(reverse=True, key=lambda item: item[0])
        results = []
        candidates = 0
        rejected = 0
        seen = set()
        for score, points, at, tone_type, cycles in scores[:8]:
            if score < .55: break
            if tone_type == "xpsk" and any(abs(points - prior) <= 1 for prior in seen): continue
            candidates += 1
            if tone_type == "xpsk": seen.add(points)
            # Start ahead of the preamble and include its entire beginning.
            begin = max(0, at - points * cycles)
            phy = TbskPhy(sample_rate=self.sample_rate, points=points,
                          cycles=cycles, tone_type="sin" if tone_type == "sin" else "xpsk")
            try: raw = phy.demodulate_bytes(signal[begin:])
            except Exception:
                rejected += 1
                continue
            frame = unpack_frame(raw) if raw else None
            if frame and (frame["size"] > 526 or frame["type"] not in (
                1, TYPE_CQ, TYPE_REPORT, TYPE_QSL, TYPE_FINAL)):
                rejected += 1
                continue
            if not frame:
                # A failed PSTBSK-X CRC is never reinterpreted as plain text.
                if not raw or raw.startswith(b"PTX1") or len(raw) > 512:
                    rejected += 1
                    continue
                try: plain = raw.decode("utf-8")
                except UnicodeDecodeError:
                    rejected += 1
                    continue
                if len(plain.strip()) < 4 or any(ord(ch) < 32 and ch not in "\n\r\t" for ch in plain):
                    rejected += 1
                    continue
            # This is a preamble quality estimate, not a calibrated RF S/N.
            power = max(score * score, 1e-6)
            snr = max(-30., min(40., 10 * math.log10(power / max(1e-6, 1 - power))))
            if not frame:
                if any(r.text == plain for r in results): continue
                results.append(ReceivedFrame(datetime.now(timezone.utc),
                    round(self.sample_rate / points), snr, "--", plain, 0, -1, "raw"))
                continue
            key = (frame["seq"], frame["type"], frame["text"])
            if key in { (r.seq, r.kind, r.text) for r in results }: continue
            results.append(ReceivedFrame(datetime.now(timezone.utc),
                round(self.sample_rate / points), snr,
                sender_call(frame["text"], frame["type"]), frame["text"],
                frame["type"], frame["seq"]))
        # Web/CLI waveforms originate at 16 kHz. Ask the library to find its
        # own preamble in that clock domain. This also catches frames arriving
        # later than the first three seconds of continuous receiver audio.
        if not results and self.sample_rate == 48000:
            recent = signal[-self.sample_rate * 9:]
            web_phy = TbskPhy(sample_rate=16000, points=10)
            # Fallback does not have a matched-preamble S/N measurement.
            # Estimate signal-to-floor contrast from short audio windows.
            block=1600; count=len(recent)//block
            power=np.sqrt(np.mean(np.square(recent[:count*block].astype(np.float64)
                        .reshape(count,block)),axis=1))
            floor=max(float(np.percentile(power,10)),1e-7)
            active=max(float(np.percentile(power,90))-floor,1e-7)
            fallback_snr=max(-30.,min(40.,20*math.log10(active/floor)))
            for phase in range(3):
                try: raw = web_phy.demodulate_bytes(recent[phase::3])
                except Exception:
                    rejected += 1
                    continue
                if not raw: continue
                candidates += 1
                frame = unpack_frame(raw)
                if frame and frame["size"] <= 526 and frame["type"] in (
                        1,TYPE_CQ,TYPE_REPORT,TYPE_QSL,TYPE_FINAL):
                    results.append(ReceivedFrame(datetime.now(timezone.utc),1600,fallback_snr,
                        sender_call(frame["text"],frame["type"]),frame["text"],
                        frame["type"],frame["seq"]))
                    break
                if raw.startswith(b"PTX1") or len(raw)>512:
                    rejected += 1
                    continue
                try: plain=raw.decode("utf-8")
                except UnicodeDecodeError:
                    rejected += 1
                    continue
                if len(plain.strip())<4 or any(ord(ch)<32 and ch not in "\n\r\t" for ch in plain):
                    rejected += 1
                    continue
                results.append(ReceivedFrame(datetime.now(timezone.utc),1600,fallback_snr,
                                             "--",plain,0,-1,"raw"))
                break
        self.on_diagnostic("decoded" if results else "rejected" if rejected
                           else "candidate" if candidates else "searching")
        return results
