"""listener.py — microphone capture + faster-whisper transcription.

All third-party imports (sounddevice, numpy, faster_whisper) are lazy,
so constructing ``Listener`` and importing this module are cheap and
dependency-free.

Two-step flow:
    listener = Listener()                 # cheap, loads nothing heavy
    pcm = listener.listen_once()          # blocks, returns raw PCM bytes
    text = listener.transcribe(pcm)       # Whisper model loads here, first time
"""

from __future__ import annotations

import math
import tempfile
import time
import wave

SAMPLE_RATE = 16000


class Listener:
    """Record one utterance from the mic (energy endpointing) and transcribe it."""

    def __init__(self, whisper_model: str = "base") -> None:
        self.whisper_model = whisper_model
        self._whisper = None          # faster_whisper WhisperModel, loaded lazily
        self._whisper_error: str | None = None

    # -- lazy Whisper ---------------------------------------------------
    def _load_whisper(self) -> bool:
        """Lazy-load the Whisper model on first transcribe. Returns True on success."""
        if self._whisper is not None:
            return True
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            self._whisper_error = f"faster_whisper not installed ({exc})"
            return False
        try:
            self._whisper = WhisperModel(self.whisper_model,
                                         device="cpu", compute_type="int8")
            return True
        except Exception as exc:
            self._whisper_error = f"could not load whisper '{self.whisper_model}': {exc}"
            return False

    # -- capture --------------------------------------------------------
    def listen_once(self, timeout: float = 10, silence_ms: int = 800) -> bytes | None:
        """Record from the mic until ``silence_ms`` of silence or ``timeout``.

        Simple energy endpointing: the noise floor is calibrated from the
        first 300 ms of audio; per-30 ms-frame RMS above ~3x the floor
        counts as speech. Capture starts on the first speech frame and
        stops after ``silence_ms`` of consecutive silence (or ``timeout``
        overall). Returns raw 16 kHz mono int16 PCM bytes, or None if no
        speech was heard. Never raises.
        """
        try:
            import numpy as np
            import sounddevice as sd
        except ImportError as exc:
            print(f"[listener] unavailable (missing audio lib): {exc}")
            return None

        frame_ms = 30
        frame_len = int(SAMPLE_RATE * frame_ms / 1000)
        deadline = time.time() + timeout

        try:
            # 1) calibrate: 300 ms of (assumed) background noise
            calib = sd.rec(int(SAMPLE_RATE * 0.3), samplerate=SAMPLE_RATE,
                           channels=1, dtype="int16")
            sd.wait()
            calib = np.asarray(calib, dtype=np.float64).ravel()
            noise_rms = float(np.sqrt(np.mean(calib ** 2))) if calib.size else 1.0
            noise_rms = max(noise_rms, 1.0)          # avoid divide-by-near-zero
            speech_thresh = noise_rms * 3.0

            # 2) stream until speech starts, then until silence or timeout
            frames: list[bytes] = []
            silence_frames = 0
            silence_limit = math.ceil(silence_ms / frame_ms)
            heard_speech = False

            with sd.InputStream(samplerate=SAMPLE_RATE, channels=1,
                                dtype="int16", blocksize=frame_len) as stream:
                while time.time() < deadline:
                    frame, _ = stream.read(frame_len)
                    arr = np.asarray(frame, dtype=np.float64).ravel()
                    rms = float(np.sqrt(np.mean(arr ** 2))) if arr.size else 0.0
                    is_speech = rms > speech_thresh

                    if is_speech:
                        heard_speech = True
                        silence_frames = 0
                        frames.append(frame.tobytes())
                    elif heard_speech:
                        silence_frames += 1
                        frames.append(frame.tobytes())  # keep trailing pad small
                        if silence_frames >= silence_limit:
                            break
                    # else: pre-speech silence — discard

            if not heard_speech:
                return None
            return b"".join(frames)
        except Exception as exc:
            print(f"[listener] capture error: {exc}")
            return None

    # -- transcription --------------------------------------------------
    def transcribe(self, pcm: bytes) -> str:
        """Transcribe raw 16 kHz mono int16 PCM with faster-whisper. Returns "" on failure."""
        if not pcm:
            return ""
        if not self._load_whisper():
            print(f"[listener] transcribe unavailable: {self._whisper_error}")
            return ""
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp_path = tmp.name
            with wave.open(tmp_path, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(SAMPLE_RATE)
                wf.writeframes(pcm)
            segments, _info = self._whisper.transcribe(
                tmp_path, beam_size=1, vad_filter=True, language="en")
            text = " ".join(seg.text for seg in segments).strip()
            return text
        except Exception as exc:
            print(f"[listener] transcribe error: {exc}")
            return ""
        finally:
            if tmp_path:
                try:
                    import os
                    os.unlink(tmp_path)
                except Exception:
                    pass

    def close(self) -> None:
        """No persistent stream/model handles to release; kept for the IO contract."""
        pass
