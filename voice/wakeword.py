"""wakeword.py — "hey jarvis" wake-word detection via openwakeword.

All third-party imports are lazy (inside methods) so this module imports
cleanly on machines without openwakeword / sounddevice installed.

Usage:
    ww = WakeWord()
    if ww.wait(timeout=60):   # blocks until "hey jarvis" or timeout
        ...
    ww.close()
"""

from __future__ import annotations

import time


class WakeWord:
    """Detect the wake word "hey jarvis" from the microphone.

    Uses openwakeword's bundled ``hey_jarvis`` model on 16 kHz mono
    int16 audio in 80 ms blocks (1280 samples).
    """

    def __init__(self, model_name: str = "hey_jarvis", threshold: float = 0.5) -> None:
        self.model_name = model_name
        self.threshold = threshold
        self._model = None          # openwakeword Model, loaded lazily
        self.available = False      # True once the model loaded OK
        self._load_error: str | None = None

    # -- lazy model -----------------------------------------------------
    def _load(self) -> bool:
        """Lazy-load openwakeword. Returns True on success."""
        if self._model is not None:
            return True
        try:
            from openwakeword.model import Model
        except ImportError as exc:
            self._load_error = f"openwakeword not installed ({exc})"
            return False
        try:
            # download_models=False: use the bundled hey_jarvis model only.
            # (openwakeword ships hey_jarvis as a built-in model.)
            self._model = Model(wakeword_models=[self.model_name])
            self.available = True
            return True
        except Exception as exc:
            self._load_error = f"could not load model '{self.model_name}': {exc}"
            self.available = False
            return False

    # -- public API -----------------------------------------------------
    def wait(self, timeout: float | None = None) -> bool:
        """Block until the wake word is heard. Returns False on timeout/unavailable.

        Opens a sounddevice InputStream at 16000 Hz mono int16 with an
        80 ms blocksize and feeds frames to the model. Calls
        ``model.reset()`` after a detection so the detector re-arms.
        """
        if not self._load():
            print(f"[wakeword] unavailable: {self._load_error}")
            return False
        try:
            import numpy as np
            import sounddevice as sd
        except ImportError as exc:
            print(f"[wakeword] unavailable (missing audio lib): {exc}")
            return False

        deadline = None if timeout is None else time.time() + timeout
        blocksize = 1280  # 80 ms @ 16 kHz
        try:
            with sd.InputStream(samplerate=16000, channels=1,
                                dtype="int16", blocksize=blocksize) as stream:
                while True:
                    if deadline is not None and time.time() >= deadline:
                        return False
                    frame, _ = stream.read(blocksize)
                    scores = self._model.predict(np.asarray(frame, dtype=np.int16))
                    if scores.get(self.model_name, 0.0) >= self.threshold:
                        try:
                            self._model.reset()
                        except Exception:
                            pass
                        return True
        except Exception as exc:
            print(f"[wakeword] stream error: {exc}")
            return False

    def close(self) -> None:
        """No persistent stream is held (opened per wait()), so this is a no-op."""
        self._model = None
        self.available = False
