"""JARVIS configuration — all settings in one place.

Convention: paste your OpenRouter key into OPENROUTER_API_KEY below.
Get one at https://openrouter.ai/keys
If you ever pasted a key into a chat window, revoke it and use a fresh one.
"""
import os
from pathlib import Path

# --- LLM ---------------------------------------------------------------
OPENROUTER_API_KEY = "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"
BASE_URL = "https://openrouter.ai/api/v1"
# Default model: reliable tool calling, cheap, fast.
# Your existing model ("openai/gpt-6-luna-pro") also works — just swap it in.
MODEL = "openai/gpt-5-mini"
MAX_TOOL_LOOPS = 5          # hard cap on tool iterations per turn (voice budget)
REQUEST_TIMEOUT = 30        # seconds per LLM call
LLM_RETRIES = 2             # retries on 5xx/timeout (never on 4xx/auth)

# --- Voice -------------------------------------------------------------
WHISPER_MODEL = "base"      # faster-whisper model: tiny < base < small
WHISPER_DEVICE = "cpu"
WHISPER_COMPUTE = "int8"
TTS_VOICE = "en-US-GuyNeural"   # edge-tts voice (male); try en-US-AriaNeural for female
TTS_RATE = 175              # pyttsx3 fallback rate (words/min)
WAKE_WORD = "hey_jarvis"    # openWakeWord pretrained model name
WAKE_THRESHOLD = 0.5
SAMPLE_RATE = 16000

# --- Behavior ----------------------------------------------------------
USER_NAME = "Arfan"
TIMEZONE = "Asia/Kolkata"
AUTO_CONFIRM = False        # True = skip confirmation prompts (used by tests)
CONFIRM_TOOLS = {           # tools that ask before running (when AUTO_CONFIRM=False)
    "press_keys", "type_text", "mouse_move", "mouse_click",
    "set_volume", "window_minimize",
}

# --- Storage -----------------------------------------------------------
DATA_DIR = Path(os.environ.get("JARVIS_DATA_DIR", Path.home() / ".jarvis"))
MEMORY_FILE = DATA_DIR / "memory.json"
TRANSCRIPT_FILE = DATA_DIR / "transcript.jsonl"
SESSIONS_DIR = DATA_DIR / "sessions"
REMINDERS_FILE = DATA_DIR / "reminders.json"
TIMERS_FILE = DATA_DIR / "timers.json"
NOTES_FILE = DATA_DIR / "notes.json"
SCREENSHOT_DIR = Path.home() / "screenshots"

# --- Persona -----------------------------------------------------------
PERSONA_FILE = Path(__file__).parent / "persona.txt"


def ensure_dirs():
    DATA_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)


def has_api_key() -> bool:
    return bool(OPENROUTER_API_KEY and OPENROUTER_API_KEY != "PASTE_YOUR_KEY_HERE")
