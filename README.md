# J.A.R.V.I.S. — Just A Rather Very Intelligent System

A fully functional, voice-controlled AI PC assistant. Runs on your computer,
controls it, remembers things about you, and talks back.

## What it can do (35 tools)

| Category | Tools |
|---|---|
| **Web** | `web_search`, `web_fetch`, `wikipedia`, `get_news`, `get_weather` |
| **System** | `get_time`, `calculator`, `unit_convert`, `dictionary`, `system_info`, `clipboard_read`, `clipboard_write` |
| **PC control** | `open_app`, `press_keys`, `type_text`, `mouse_move`, `mouse_click`, `take_screenshot`, `window_focus`, `window_minimize`, `set_volume`, `notify` |
| **Personal** | `set_timer`, `set_reminder`, `list_reminders`, `notes_add/list/search/delete`, `tell_joke`, `translate`, `email_draft`, `remember`, `recall`, `forget_memory` |

All web integrations are **free with no API keys** (DuckDuckGo, Open-Meteo,
Google News RSS, Wikipedia, dictionaryapi.dev).

## Setup

**1. Python 3.12** (3.9+ works; 3.12 tested).

**2. Install dependencies:**
```bash
cd jarvis
pip install -r requirements.txt
```
For text mode only, you need just: `requests openai python-dateutil ddgs
trafilatura feedparser deep-translator`. Voice needs the rest
(`sounddevice`, `faster-whisper`, `openwakeword`, …). macOS also needs
`brew install ffmpeg`.

**3. Add your OpenRouter key** — open `config.py` and paste it:
```python
OPENROUTER_API_KEY = "PASTE_YOUR_KEY_HERE"
```
Get one at https://openrouter.ai/keys. (If you ever pasted a key into a chat,
revoke it and use a fresh one.) Without a key, Jarvis runs in **local-only
mode** — time, math, jokes, weather, timers, and notes still work.

**4. macOS permissions** (voice/PC control only): System Settings → Privacy &
Security → grant **Accessibility** (keyboard/mouse), **Screen Recording**
(screenshots), **Microphone**, and **Input Monitoring** to your terminal.

## Usage

```bash
python main.py --text    # text mode (no mic needed) — best for testing
python main.py --voice   # voice mode: say "hey jarvis", then speak
python main.py           # auto: voice if a mic is found, else text
```

**Voice mode:** say **"hey jarvis"** → speak your command → Jarvis answers
out loud. You can interrupt while it's talking (barge-in).

**Text mode:** just type. Same brain, same 35 tools.

**Examples:**
- "What time is it in Tokyo?"
- "Calculate 15 percent of 240"
- "What's the weather in Bengaluru?"
- "Search the web for Python 3.13 release notes"
- "Remember that my favorite IDE is VS Code"
- "Remind me tomorrow at 9am to call mom"
- "Open Chrome" / "Take a screenshot" / "What are my notes?"

## Project layout

```
config.py        # settings + API key placeholder
main.py          # entry point, mode detection, main loop
io_base.py       # TextIO / VoiceIO (same brain, both modes)
brain.py         # OpenRouter function-calling loop, streaming, fast path
persona.txt      # edit to change how Jarvis talks
memory/          # long-term facts (memory.json) + session context
tools/           # 35 tools: web_, system_, pc_, personal_
voice/           # wake word, mic/VAD/STT listener, TTS speaker
```

See `ARCHITECTURE.md` for the full design and `TEST_REPORT.md` for test results.

## Safety

- Destructive/high-impact tools (`press_keys`, `type_text`, mouse, volume…)
  **ask for confirmation** before running (disable with `AUTO_CONFIRM=True` in
  `config.py`, used by tests).
- Memory **never stores** passwords, API keys, tokens, or card numbers — a
  sanitizer blocks them before storage.
- Web content is treated as untrusted data and can never trigger tools directly.

## Honest limitations

- Reminders/timers fire while Jarvis is running (persisted across restarts,
  but the process must be alive).
- Voice quality depends on your mic; `faster-whisper base` is fast but not
  perfect in noisy rooms.
- The LLM tool loop needs an internet connection + OpenRouter key; without it
  you get local-only mode.
