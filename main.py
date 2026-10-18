#!/usr/bin/env python3
"""JARVIS — main entry point.

Usage:
    python main.py --text     # text mode (no mic/speaker needed)
    python main.py --voice    # voice mode (mic + speaker)
    python main.py            # auto: voice if mic available, else text
"""
import argparse
import sys
import time

import config


def _probe_mic() -> bool:
    try:
        import sounddevice as sd
        devices = sd.query_devices()
        return any(d.get("max_input_channels", 0) > 0 for d in devices)
    except Exception:
        return False


def build_io(mode: str):
    """Return (io, description). Never raises."""
    from io_base import TextIO
    if mode == "text":
        return TextIO(), "text mode"
    # voice requested: probe mic
    try:
        from io_base import VoiceIO
        from voice.wakeword import WakeWord
        from voice.listener import Listener
        from voice.speaker import Speaker
    except ImportError as e:
        print(f"[main] voice imports unavailable ({e}) — falling back to text mode")
        return TextIO(), "text mode (voice unavailable)"
    if not _probe_mic():
        print("[main] no microphone found — text mode")
        return TextIO(), "text mode (no mic)"
    try:
        speaker = Speaker()
        listener = Listener()
        wake = WakeWord()
        io = VoiceIO(wake, listener, speaker, use_wake_word=True)
        return io, f"voice mode (TTS: {speaker.backend_used})"
    except Exception as e:
        print(f"[main] voice init failed ({e}) — text mode")
        return TextIO(), "text mode (voice init failed)"


def main():
    parser = argparse.ArgumentParser(description="JARVIS personal AI assistant")
    parser.add_argument("--text", action="store_true", help="text mode (no mic)")
    parser.add_argument("--voice", action="store_true", help="voice mode")
    parser.add_argument("--no-wake", action="store_true",
                        help="voice mode without wake word (listen immediately)")
    args = parser.parse_args()

    config.ensure_dirs()

    mode = "text" if args.text else ("voice" if args.voice else "auto")
    if mode == "auto":
        mode = "voice" if _probe_mic() else "text"

    # memory + session
    from memory import Memory, SessionMemory
    memory = Memory()
    session = SessionMemory()

    # tools
    from tools import build_registry
    schemas, execute = build_registry(memory)
    print(f"[main] {len(schemas)} tools loaded")

    # brain
    from brain import Brain
    brain = Brain(memory, session, schemas, execute)
    if brain.offline:
        print("[main] no API key — local-only mode (time/math/jokes/weather work)")

    # IO
    io, desc = build_io(mode)
    if args.no_wake and hasattr(io, "use_wake_word"):
        io.use_wake_word = False

    print()
    print("=" * 56)
    print("  J.A.R.V.I.S. — Just A Rather Very Intelligent System")
    print(f"  Mode: {desc}")
    print("  Say 'hey jarvis' (voice) or type. 'exit' to quit.")
    print("=" * 56)
    print()

    # restore pending timers/reminders
    try:
        from tools import personal_tools
        if hasattr(personal_tools, "restore_pending"):
            personal_tools.restore_pending()
    except Exception as e:
        print(f"[main] reminder restore: {e}")

    # greeting
    io.speak(f"Systems online. Running in {desc}.")

    try:
        while True:
            try:
                text = io.listen()
            except (KeyboardInterrupt, EOFError):
                break
            if not text or not text.strip():
                continue
            low = text.strip().lower()
            if low in ("exit", "quit", "shutdown", "goodbye"):
                io.speak("Shutting down. Goodbye.")
                break
            try:
                sentences = list(brain.respond(text))
            except Exception as e:
                io.speak(f"I ran into a problem: {e}")
                continue
            for s in sentences:
                io.speak(s)
    finally:
        # session card
        try:
            recent = " | ".join(
                f"{t['role']}: {t['text'][:80]}" for t in session.turns[-4:])
            session.write_session_card(recent or "empty session")
        except Exception:
            pass
        try:
            io.close()
        except Exception:
            pass
        print("[main] Jarvis shut down.")


if __name__ == "__main__":
    sys.exit(main())
