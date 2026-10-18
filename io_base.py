"""io_base.py — Input/Output abstraction for the Jarvis voice assistant.

The contract is simple: an IO source turns speech/typing into text
(`listen`), and a sink turns text into speech/printing (`speak`).

Design rules (see module docstring of each class):
  * ALL third-party audio imports are LAZY — they live inside
    functions/methods, never at module top level. ``import io_base``
    must succeed on a machine with zero audio packages installed.
  * Every method degrades gracefully: returns "" / None or prints a
    message instead of crashing the process.

Concrete classes:
  * TextIO   — terminal stdin/stdout, zero dependencies.
  * VoiceIO  — composes a WakeWord + Listener + Speaker (see the
    ``jarvis.voice`` package). Barge-in is intentionally NOT handled
    here; the interruptible speak loop lives in main.py. VoiceIO
    keeps the simple blocking flow: wait for wake word, record one
    utterance, transcribe it.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class IO(ABC):
    """Abstract I/O interface: text in, text out."""

    @abstractmethod
    def listen(self) -> str:
        """Block until one utterance is captured; return its text ("" if none)."""
        ...

    @abstractmethod
    def speak(self, text: str) -> None:
        """Speak (or otherwise present) ``text`` to the user."""
        ...

    def close(self) -> None:
        """Release any held resources. No-op by default; override as needed."""


class TextIO(IO):
    """Plain terminal I/O. Works everywhere, no dependencies."""

    def listen(self) -> str:
        try:
            return input("you> ")
        except (EOFError, KeyboardInterrupt):
            return ""

    def speak(self, text: str) -> None:
        print(f"jarvis> {text}")


class VoiceIO(IO):
    """Voice I/O: wake word -> record utterance -> transcribe -> speak.

    Composition root for the voice pipeline. Takes already-constructed
    ``WakeWord``, ``Listener`` and ``Speaker`` objects so each can be
    configured/tested independently.

    Kept deliberately simple: no barge-in, no continuous listening.
    The main loop (main.py) owns the interruptible speak behaviour.
    """

    def __init__(self, wake_word=None, listener=None, speaker=None,
                 use_wake_word: bool = True) -> None:
        self.wake_word = wake_word
        self.listener = listener
        self.speaker = speaker
        self.use_wake_word = use_wake_word

    # -- IO interface ---------------------------------------------------
    def listen(self) -> str:
        """Wait for the wake word (optional), record one utterance, transcribe."""
        try:
            if self.use_wake_word:
                if self.wake_word is None:
                    print("[voice] no wake-word detector configured; listening anyway")
                else:
                    print("say 'hey jarvis'...")
                    if not self.wake_word.wait():
                        return ""
            if self.listener is None:
                print("[voice] no listener configured")
                return ""
            pcm = self.listener.listen_once()
            if not pcm:
                return ""
            return self.listener.transcribe(pcm) or ""
        except Exception as exc:  # never let audio kill the process
            print(f"[voice] listen failed: {exc}")
            return ""

    def speak(self, text: str) -> None:
        """Speak ``text`` sentence-by-sentence via the configured speaker."""
        try:
            if self.speaker is None:
                print(f"jarvis> {text}")
                return
            self.speaker.say(text)
        except Exception as exc:
            print(f"[voice] speak failed: {exc}")
            print(f"jarvis> {text}")

    def close(self) -> None:
        """Release audio resources held by the components."""
        for comp in (self.wake_word, self.listener, self.speaker):
            try:
                if comp is not None and hasattr(comp, "close"):
                    comp.close()
            except Exception:
                pass
