"""speaker.py — text-to-speech with platform-aware backend selection.

DESIGN DECISION (platform split):
  * macOS:   edge-tts (neural, online) -> mp3 played via `afplay`;
             fallback: macOS `say` (offline); final fallback: print.
  * Windows: pyttsx3 (offline, native SAPI5) — NOT edge-tts.
  * Linux/other: edge-tts with a detected player (mpg123/ffplay),
             fallback: pyttsx3, final fallback: print.

Rationale: playing edge-tts mp3s on Windows without extra deps is
awkward (`os.startfile` is async and unkillable; no bundled CLI player),
while pyttsx3 works out of the box and is offline. On macOS `afplay`
plays mp3s natively and neural edge-tts voices sound far better than
`say`, so edge-tts is the primary there. We deliberately avoid
pydub/sounddevice playback: pydub needs ffmpeg, which we don't want to
require.

All third-party imports (edge_tts, pyttsx3) are lazy — this module
imports with zero audio packages installed. ``say`` never raises;
on total backend failure it prints the text. ``self.backend_used``
reports which backend actually produced speech.
"""

from __future__ import annotations

import platform
import re
import shutil
import subprocess
import tempfile
import threading

MIN_SENTENCE_LEN = 20
_SENT_SPLIT_RE = re.compile(r"(?<=[.!?…])\s+")


def _strip_markdown(text: str) -> str:
    """Remove common markdown noise before TTS so it isn't spoken aloud."""
    text = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)  # code blocks
    text = text.replace("`", "")
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.MULTILINE)
    text = text.replace("*", "")
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)      # links -> label
    return re.sub(r"\s+", " ", text).strip()


def _split_sentences(text: str) -> list[str]:
    """Split on sentence-ending punctuation; merge fragments shorter than min_len."""
    parts = [p.strip() for p in _SENT_SPLIT_RE.split(text) if p.strip()]
    merged: list[str] = []
    buf = ""
    for p in parts:
        buf = f"{buf} {p}".strip() if buf else p
        if len(buf) >= MIN_SENTENCE_LEN:
            merged.append(buf)
            buf = ""
    if buf:
        if merged:
            merged[-1] = f"{merged[-1]} {buf}"
        else:
            merged.append(buf)
    return merged


class Speaker:
    """Speak text using the best available platform backend."""

    def __init__(self, voice: str = "en-US-GuyNeural", prefer: str = "auto") -> None:
        self.voice = voice
        self.prefer = prefer            # "auto" | "edge" | "say" | "pyttsx3" | "print"
        self.backend: str | None = None       # backend chosen for next say()
        self.backend_used: str | None = None  # backend that last produced speech
        self._edge_ok: bool | None = None     # None=untried, True/False after first synth
        self._player: threading.Thread | None = None
        self._player_proc: subprocess.Popen | None = None
        self._stop_flag = threading.Event()
        self._lock = threading.Lock()

    # -- backend probing (all lazy) -------------------------------------
    def _try_edge_synth(self, text: str, mp3_path: str) -> bool:
        """Synthesize with edge-tts. try/except IS the internet check (per spec)."""
        if self._edge_ok is False:
            return False
        try:
            import asyncio
            from edge_tts import Communicate
        except ImportError:
            self._edge_ok = False
            return False
        try:
            asyncio.run(Communicate(text, self.voice).save(mp3_path))
            self._edge_ok = True
            return True
        except Exception as exc:
            print(f"[speaker] edge-tts synth failed: {exc}")
            self._edge_ok = False
            return False

    def _edge_player(self) -> list[str] | None:
        """CLI command that can play an mp3, or None if no player found."""
        system = platform.system()
        if system == "Darwin" and shutil.which("afplay"):
            return ["afplay"]
        for player in ("mpg123", "ffplay"):
            if shutil.which(player):
                return [player, "-nodisp", "-autoexit"] if player == "ffplay" else [player]
        return None

    def _play_edge(self, mp3_path: str, interruptible: bool = False) -> bool:
        """Play an mp3. interruptible=True uses Popen so stop() can terminate()."""
        player = self._edge_player()
        if not player:
            return False
        try:
            if interruptible:
                with self._lock:
                    self._player_proc = subprocess.Popen(
                        player + [mp3_path],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                proc = self._player_proc
                proc.wait()
                with self._lock:
                    self._player_proc = None
                return proc.returncode == 0
            result = subprocess.run(player + [mp3_path],
                                    stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL)
            return result.returncode == 0
        except Exception as exc:
            print(f"[speaker] player failed: {exc}")
            return False

    def _say_macos(self, text: str) -> bool:
        """macOS `say` — offline fallback."""
        if platform.system() != "Darwin" or not shutil.which("say"):
            return False
        try:
            result = subprocess.run(["say", text],
                                    stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL)
            return result.returncode == 0
        except Exception as exc:
            print(f"[speaker] say failed: {exc}")
            return False

    def _say_pyttsx3(self, text: str) -> bool:
        """pyttsx3 — offline, primary backend on Windows (SAPI5)."""
        try:
            import pyttsx3
        except ImportError:
            return False
        try:
            engine = pyttsx3.init()
            engine.say(text)
            engine.runAndWait()
            engine.stop()
            return True
        except Exception as exc:
            print(f"[speaker] pyttsx3 failed: {exc}")
            return False

    def _speak_one(self, sentence: str, interruptible: bool = False) -> None:
        """Speak one sentence via the platform's backend order; print as last resort."""
        prefer = self.prefer
        system = platform.system()

        if system == "Windows":
            # Windows: pyttsx3 is reliable and offline; edge-tts mp3 playback
            # has no clean stdlib/clip route, so we don't use it here.
            order = ["pyttsx3"]
        elif system == "Darwin":
            # macOS: neural edge-tts + afplay first, then `say`.
            order = ["edge", "say"] if prefer in ("auto", "edge", "say") else [prefer]
            if prefer == "pyttsx3":
                order = ["pyttsx3", "edge", "say"]
        else:
            order = ["edge", "pyttsx3"] if prefer == "auto" else [prefer]

        if prefer == "print":
            order = []

        for backend in order:
            if backend == "edge":
                player = self._edge_player()
                if not player:
                    continue
                with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
                    mp3 = tmp.name
                try:
                    if self._try_edge_synth(sentence, mp3) and self._play_edge(mp3, interruptible):
                        self.backend = self.backend_used = "edge-tts"
                        return
                finally:
                    try:
                        import os
                        os.unlink(mp3)
                    except Exception:
                        pass
            elif backend == "say":
                if self._say_macos(sentence):
                    self.backend = self.backend_used = "say"
                    return
            elif backend == "pyttsx3":
                if self._say_pyttsx3(sentence):
                    self.backend = self.backend_used = "pyttsx3"
                    return

        self.backend = self.backend_used = "print"
        print(f"jarvis> {sentence}")

    # -- public API -----------------------------------------------------
    def say(self, text: str) -> None:
        """Speak ``text`` sentence-by-sentence. Never raises."""
        try:
            clean = _strip_markdown(text or "")
            if not clean:
                return
            for sentence in _split_sentences(clean):
                self._speak_one(sentence)
        except Exception as exc:
            print(f"[speaker] say failed: {exc}")
            print(f"jarvis> {text}")

    def say_interruptible(self, text: str, stop_event: threading.Event) -> None:
        """Like say(), but checks ``stop_event`` between sentences and stops."""
        try:
            clean = _strip_markdown(text or "")
            if not clean:
                return
            for sentence in _split_sentences(clean):
                if stop_event.is_set() or self._stop_flag.is_set():
                    break
                self._speak_one(sentence, interruptible=True)
        except Exception as exc:
            print(f"[speaker] say_interruptible failed: {exc}")
            print(f"jarvis> {text}")

    def stop(self) -> None:
        """Interrupt any in-progress interruptible playback."""
        self._stop_flag.set()
        with self._lock:
            proc = self._player_proc
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
            except Exception:
                pass

    def reset(self) -> None:
        """Clear the stop flag so the next say_* call runs normally."""
        self._stop_flag.clear()

    def close(self) -> None:
        """Stop playback; no persistent engine is held."""
        self.stop()
