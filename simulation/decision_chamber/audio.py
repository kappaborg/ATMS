"""Audio siren detection — Layer 1 preemption source.

Emergency sirens have characteristic acoustic signatures distinct from
ambient traffic noise:

| Type | Frequency band | Modulation |
|---|---|---|
| US wail | 600-1500 Hz | slow FM sweep (~0.2 Hz) |
| US yelp | 600-1500 Hz | fast FM sweep (~3-4 Hz) |
| US hi-low | 1100 / 800 Hz alternating | step-wise |
| EU Martinshorn | 410 / 660 Hz alternating | step-wise (Quinte interval) |
| Civilian air horn | broadband ~200 Hz | unmodulated |

This detector uses a real-time short-time FFT (STFT) on a 200 ms
window. For each window it computes:

1. **Energy in the siren band** (500-1600 Hz, covers both US + EU)
2. **Peak frequency stability** — sirens have a CLEAR dominant tone,
   not broadband (traffic noise is broadband)
3. **Frequency modulation** — the peak frequency varies cyclically
   over consecutive windows (signature of FM siren)

When all three conditions hold above their thresholds, the detector
emits an EmergencySignal. The detector does NOT use a trained CNN —
it relies on physics. This is more interpretable and runs on edge
hardware without a model artefact. Phase 6 can upgrade to YAMNet for
better noise robustness if needed.

Production install:
    pip install sounddevice  # for live microphone input
    # numpy is already a dependency

Dev test (no microphone):
    detector = AudioSirenDetector(wav_file=Path('test_siren.wav'))
    # — runs the same analysis on a recorded WAV
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np

from simulation.decision_chamber.state import EmergencySignal, EmergencySource

log = logging.getLogger("atms.chamber.audio")


class AudioSirenDetector:
    """Real-time STFT-based siren detection. One detector instance polls
    a microphone (or pre-recorded WAV for testing) in a background
    thread and surfaces an EmergencySignal whenever the last few
    windows of audio show siren-characteristic frequency modulation.

    Two recommended source-of-truth knobs:
    - `band_low_hz / band_high_hz`: tune for the local siren standard
      (US 600-1500, EU 400-700 + 600-1600 with Martinshorn coverage)
    - `min_confidence`: how stringent the detector is — lower = more
      false positives but better recall on weak sirens
    """

    name = "audio_siren"

    def __init__(
        self,
        sample_rate: int = 44100,
        window_seconds: float = 0.2,
        history_seconds: float = 2.0,
        band_low_hz: float = 500.0,
        band_high_hz: float = 1600.0,
        # Defaults calibrated against synthetic 0.5-amplitude wail (800 Hz
        # ± 300 Hz, 0.3 Hz cycle) + 0.1 amplitude white noise. With a
        # full-spectrum FFT (0..22kHz) the siren-band energy ratio
        # naturally caps around 0.20 because the broadband noise dilutes
        # the total. The clarity + FM checks discriminate siren from
        # broadband traffic noise even at low energy_ratio.
        min_energy_ratio: float = 0.10,
        min_peak_clarity: float = 10.0,  # peak / median, dominated by tonal signal
        min_fm_variation_hz: float = 100.0,  # how much peak freq must sweep
        min_confidence: float = 0.50,
        direction: str = "unknown",  # detector can't localise; operator config
        wav_file: Path | None = None,
    ):
        self._sample_rate = sample_rate
        self._window_size = int(sample_rate * window_seconds)
        self._history_windows = int(history_seconds / window_seconds)
        self._band_lo = band_low_hz
        self._band_hi = band_high_hz
        self._min_energy_ratio = min_energy_ratio
        self._min_peak_clarity = min_peak_clarity
        self._min_fm_variation = min_fm_variation_hz
        self._min_confidence = min_confidence
        self._direction = direction

        self._recent_peaks: deque[float] = deque(maxlen=self._history_windows)
        self._latest_signal: EmergencySignal | None = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

        if wav_file is not None:
            self._start_wav_loop(wav_file)
        else:
            self._start_microphone_loop()

    # ----- audio sources ------------------------------------------------

    def _start_microphone_loop(self) -> None:
        try:
            import sounddevice as sd  # noqa: PLC0415
        except ImportError:
            log.warning(
                "sounddevice unavailable — audio siren detector running with "
                "wav-only support. Install: pip install sounddevice"
            )
            return

        def reader_loop():
            with sd.InputStream(
                samplerate=self._sample_rate,
                channels=1,
                dtype="float32",
                blocksize=self._window_size,
            ) as stream:
                while not self._stop.is_set():
                    try:
                        block, _overflow = stream.read(self._window_size)
                        self._process_window(block[:, 0])
                    except Exception as e:
                        log.warning("audio mic read failed: %s", e)
                        time.sleep(0.5)

        self._thread = threading.Thread(target=reader_loop, daemon=True)
        self._thread.start()
        log.info("audio siren detector listening on default microphone")

    def _start_wav_loop(self, wav_file: Path) -> None:
        try:
            import wave  # noqa: PLC0415
        except ImportError:
            return

        def wav_loop():
            try:
                wf = wave.open(str(wav_file), "rb")
            except Exception as e:
                log.warning("could not open wav file %s: %s", wav_file, e)
                return
            sr = wf.getframerate()
            if sr != self._sample_rate:
                log.warning(
                    "wav sample rate %d != detector %d; expect inaccuracy",
                    sr, self._sample_rate,
                )
            while not self._stop.is_set():
                raw = wf.readframes(self._window_size)
                if not raw:
                    wf.rewind()
                    continue
                samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
                if wf.getnchannels() > 1:
                    samples = samples[::wf.getnchannels()]
                self._process_window(samples)
                time.sleep(self._window_size / self._sample_rate)
            wf.close()

        self._thread = threading.Thread(target=wav_loop, daemon=True)
        self._thread.start()
        log.info("audio siren detector replaying wav %s", wav_file)

    # ----- analysis -----------------------------------------------------

    def _process_window(self, samples: np.ndarray) -> None:
        if len(samples) < self._window_size // 2:
            return
        # Apply Hann window to reduce spectral leakage
        windowed = samples * np.hanning(len(samples))
        spectrum = np.abs(np.fft.rfft(windowed))
        freqs = np.fft.rfftfreq(len(windowed), d=1.0 / self._sample_rate)

        # 1) Band-limited energy ratio
        band_mask = (freqs >= self._band_lo) & (freqs <= self._band_hi)
        if not band_mask.any():
            return
        band_energy = spectrum[band_mask].sum()
        total_energy = spectrum.sum() + 1e-9
        energy_ratio = float(band_energy / total_energy)
        if energy_ratio < self._min_energy_ratio:
            return

        # 2) Peak clarity within band: peak / median spectral magnitude
        band_spec = spectrum[band_mask]
        band_freqs = freqs[band_mask]
        peak_idx = int(np.argmax(band_spec))
        peak_mag = float(band_spec[peak_idx])
        median_mag = float(np.median(band_spec)) + 1e-9
        clarity = peak_mag / median_mag
        if clarity < self._min_peak_clarity:
            return

        peak_freq = float(band_freqs[peak_idx])
        self._recent_peaks.append(peak_freq)

        # 3) Frequency-modulation detection over the history window
        if len(self._recent_peaks) < self._history_windows // 2:
            return  # not enough history yet
        peaks = np.array(self._recent_peaks)
        fm_variation = float(peaks.max() - peaks.min())
        if fm_variation < self._min_fm_variation:
            return

        # All three conditions met → siren detected with composite
        # confidence based on how strongly each condition fired.
        energy_score = min(1.0, energy_ratio / max(self._min_energy_ratio, 0.001))
        clarity_score = min(1.0, clarity / max(self._min_peak_clarity * 4, 0.001))
        fm_score = min(1.0, fm_variation / max(self._min_fm_variation * 2, 0.001))
        confidence = (energy_score + clarity_score + fm_score) / 3.0

        if confidence < self._min_confidence:
            return

        sig = EmergencySignal(
            source=EmergencySource.AUDIO_SIREN,
            direction=self._direction,
            confidence=confidence,
            detected_at=datetime.now(timezone.utc),
            notes=(
                f"band_energy={energy_ratio:.2f} clarity={clarity:.2f} "
                f"fm_hz={fm_variation:.0f} peak={peak_freq:.0f}Hz"
            ),
        )
        with self._lock:
            self._latest_signal = sig

    # ----- detector protocol --------------------------------------------

    def poll(self, tick_time: datetime, context: dict[str, Any]) -> list[EmergencySignal]:
        """Return the most recent siren signal if it's fresh (≤2 s old).
        The chamber's stale_signal_filter handles the actual age cutoff;
        we just check that we have a signal to report.
        """
        with self._lock:
            sig = self._latest_signal
        if sig is None:
            return []
        if tick_time - sig.detected_at > timedelta(seconds=2.0):
            return []
        return [sig]

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
