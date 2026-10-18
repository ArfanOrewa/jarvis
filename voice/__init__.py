"""jarvis.voice — voice I/O layer for the Jarvis assistant.

Modules:
  * wakeword — "hey jarvis" detection (openwakeword).
  * listener — mic capture with energy endpointing + faster-whisper STT.
  * speaker  — TTS with platform backends (edge-tts, say, pyttsx3, print).

All third-party imports are lazy (inside functions/methods) so importing
this package never requires any audio dependency to be installed.
"""
