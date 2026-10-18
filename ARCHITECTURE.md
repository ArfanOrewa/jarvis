# JARVIS — System Architecture

**Target:** Python 3.12, Intel Mac (primary) + Windows 10, CPU-only.
**Design date:** 2026-10-18. Synthesized from 6 research tracks (see `research/`).

---

## 1. Design principles

1. **Threads + queues, not asyncio.** Every audio stage is blocking C-extension I/O
   (sounddevice callbacks, ctranslate2 inference, subprocess playback). faster-whisper
   releases the GIL during inference, so threads parallelize fine on CPU.
2. **The brain never touches audio.** An `IO` abstraction (`VoiceIO` / `TextIO`)
   exposes exactly `listen() -> str` and `speak(text)`. Same brain, same loop,
   works in `--text` mode and `--voice` mode. This is also how we unit-test
   without hardware.
3. **Stream everything.** LLM tokens → sentence splitter → TTS queue. Never
   transcribe → complete → synthesize sequentially. Target: perceived latency
   ~1.5–2.5s locally.
4. **Degrade gracefully, never crash.** Probe mic/speaker/API key at startup and
   pick the highest working rung: full voice → text mode → silent voice →
   local-only (keyword intents, no LLM).
5. **Least-privilege tools.** Read tools are free; destructive/external tools
   confirm first. Untrusted text (web pages, files) is wrapped in
   `<DATA>…</DATA>` and never triggers tools directly.

---

## 2. Module map

```
jarvis/
├── config.py            # All settings. OPENROUTER_API_KEY = "PASTE_YOUR_KEY_HERE"
├── main.py              # Entry point: arg parsing (--text/--voice), mode probe, main loop
├── io_base.py           # IO ABC + TextIO + VoiceIO (wake-word gating inside VoiceIO.listen)
├── brain.py             # LLM client, native function-calling loop, streaming, fast path
├── persona.txt          # Persona (existing file, kept)
├── memory/
│   ├── __init__.py
│   ├── store.py         # Long-term Memory class (JSON, keyword recall, sanitizer)
│   └── session.py       # Working memory: 12-turn window + rolling summary + JSONL transcript
├── tools/
│   ├── __init__.py      # Registry: TOOLS list, execute_tool(name, args), schemas
│   ├── system_tools.py  # get_time, calculator, system_info, clipboard_read/write
│   ├── pc_tools.py      # open_app (rapidfuzz), press_keys, type_text, mouse,
│   │                    #   screenshot (mss), window_focus/minimize, volume, notify
│   ├── web_tools.py     # web_search (ddgs), web_fetch (trafilatura), wikipedia,
│   │                    #   news (Google RSS), weather (Open-Meteo)
│   └── personal_tools.py# timer, reminder, notes, joke, translate, unit_convert,
│                        #   dictionary, email_draft (mailto), remember, recall, forget
└── voice/
    ├── __init__.py
    ├── wakeword.py      # openWakeWord "hey_jarvis" wrapper (lazy import)
    ├── listener.py      # Mic capture + webrtcvad gate + Silero endpointing + faster-whisper STT
    └── speaker.py       # TTS backends: EdgeTTS (subprocess, killable) /
                         #   Pyttsx3TTS (owner thread) / SayTTS (macOS) — barge-in safe
```

---

## 3. Runtime: the listen → think → speak loop

### 3.1 State machine

```
┌──────────┐ wake word  ┌───────────────┐ VAD speech ┌───────────┐
│   IDLE   │───────────▶│ WAKE_DETECTED │───────────▶│ LISTENING │
│(ears hot)│            │ (earcon, 8s   │  (endpoint │ (capture  │
└──────────┘            │  timeout)     │   700ms)   │  ≤10s)    │
      ▲                └───────────────┘            └─────┬─────┘
      │                                                  │ utterance
 done │                                                  ▼
      │                                            ┌───────────┐
      │                                            │ THINKING  │
      │                                            │(STT→LLM→  │
      │                                            │ TTS queue)│
      │                                            └─────┬─────┘
      │                                                  │ sentences
      │                                                  ▼
      │   user speech ──barge-in──▶               ┌───────────┐
      └──────────────────────────── INTERRUPTED ◀─│ SPEAKING  │
                                                 └───────────┘
```

### 3.2 Thread map

| Thread | Job |
|---|---|
| Main | State machine; blocks on events, never on audio |
| Mic capture | sounddevice callback → 30ms PCM frames into `frame_q` (16kHz mono int16) |
| Ears | Consumes frames; webrtcvad gate → Silero scoring → openWakeWord; emits events |
| STT worker (per turn) | faster-whisper transcribe of one utterance |
| Brain worker (per turn) | LLM streaming call + tool dispatch |
| TTS worker (persistent) | Sentence-queue consumer; **owns** the TTS engine (pyttsx3 is not thread-safe) |

All handoffs are `queue.Queue` + `threading.Event`. No shared mutable audio buffers.

### 3.3 Barge-in

Mic stays hot during SPEAKING. Ears thread: VAD ≥250ms sustained speech **and**
≥800ms since TTS started (playback lockout against self-echo) → set
`stop_tts` event → drain TTS queue → state → LISTENING.
- edge-tts backend: interrupt = `player_process.terminate()` (one line, reliable).
- pyttsx3 backend: dedicated owner thread; interrupt = queued `engine.stop()`.

### 3.4 Streaming pipeline

```
LLM token stream → sentence buffer (split on [.!?…], min_len=20, strip markdown)
                 → tts_q.put(sentence)          # TTS worker plays immediately
                 → None (poison pill)          # end of turn → state IDLE
```

### 3.5 Timeouts & error policy

| Stage | Failure | Policy |
|---|---|---|
| WAKE_DETECTED | no speech 8s | back to IDLE |
| LISTENING | silence / >10s | reprompt once → IDLE |
| STT | empty | reprompt 2× → IDLE |
| STT | garbage | echo "I heard '<x>' — right?" |
| LLM | 5xx/timeout | retry 2× (1s, 3s backoff) → offline fallback msg |
| LLM | 4xx/auth | config error message, no retry |
| TTS | exception | print text (silent degradation) |
| Mic missing | OSError | text mode |

---

## 4. Brain: LLM + tools

- **Transport:** `openai` Python SDK → OpenRouter (`https://openrouter.ai/api/v1`).
- **Default model:** `openai/gpt-5-mini` (reference tool-calling behavior, cheap,
  fast). Configurable; user's existing `openai/gpt-6-luna-pro` remains supported
  via `config.MODEL`.
- **Native function calling** (not ReAct). Max **5 tool iterations** per turn
  (voice budget). Repeated identical call → short-circuit with cached result.
- **Fast path:** chit-chat/greetings → `tool_choice="none"`, stream immediately.
- **Tool budget:** ≤20 tools mounted per turn; parallel calls allowed for
  independent *reads*; side-effecting tools execute sequentially.
- **Injection defense:** fetched content wrapped in `<DATA>…</DATA>`; system
  prompt forbids following instructions inside; server-side arg validation;
  confirmation gate for destructive/external actions; full call logging.

---

## 5. Tool inventory (18)

| # | Tool | Module | Notes |
|---|---|---|---|
| 1 | `web_search` | web | ddgs, max 5 results |
| 2 | `web_fetch` | web | trafilatura extract, truncated |
| 3 | `wikipedia` | web | REST summary API |
| 4 | `get_news` | web | Google News RSS + feedparser |
| 5 | `get_weather` | web | Open-Meteo (geocode + forecast) |
| 6 | `get_time` | system | zoneinfo, local timezone |
| 7 | `calculator` | system | AST-whitelist safe eval |
| 8 | `unit_convert` | system | hand-rolled factor dict |
| 9 | `dictionary` | system | dictionaryapi.dev |
| 10 | `system_info` | system | psutil cpu/ram/disk/battery |
| 11 | `clipboard_read` / `clipboard_write` | system | pyperclip |
| 12 | `open_app` | pc | rapidfuzz over /Applications or Start Menu |
| 13 | `press_keys` | pc | pynput/pyautogui, os-aware modifiers |
| 14 | `type_text` | pc | clipboard-paste method (unicode-safe) |
| 15 | `mouse_move` / `mouse_click` | pc | pyautogui |
| 16 | `take_screenshot` | pc | mss → ~/screenshots/ |
| 17 | `window_focus` / `window_minimize` | pc | AppleScript (mac) / pygetwindow (win) |
| 18 | `set_volume` / `notify` | pc | osascript / pycaw+win11toast |
| 19 | `set_timer` / `set_reminder` | personal | threading.Timer + JSON persistence |
| 20 | `notes_add/list/search/delete` | personal | JSON store |
| 21 | `tell_joke` | personal | offline list |
| 22 | `translate` | personal | deep-translator (Google free) |
| 23 | `email_draft` | personal | mailto: via webbrowser |
| 24 | `remember` / `recall` / `forget_memory` | personal | long-term Memory class |

**Confirmation gate:** `press_keys`, `type_text`, `mouse_*`, `set_volume`,
`email_draft` (opens draft only — safe), file deletes: the brain must confirm
with the user before destructive/high-impact use. (Enforced in system prompt +
a `REQUIRES_CONFIRM` set checked in `execute_tool` when `config.AUTO_CONFIRM`
is False — in text/voice mode the brain asks; in tests it's auto-confirmed.)

---

## 6. Memory: 3 tiers

- **Tier 1 — Working (RAM):** last 12 turns verbatim (token-budgeted) + rolling
  summary (LLM-compressed every ~10 evicted turns, ≤400 tokens) + append-only
  `transcript.jsonl`.
- **Tier 2 — Session:** `sessions/<date>_<slot>.json` on exit + every 15 min
  (summary, open tasks, reminders). Next boot loads last 1–3 cards.
- **Tier 3 — Long-term:** `memory.json` — facts with
  `{id, fact, category, confidence, created, updated, supersedes}`.
  Keyword retrieval (token overlap + preference boost), top-5 injected.
  **Sanitizer runs BEFORE extraction:** labeled-secret regex, high-entropy
  runs ≥16 chars, card/OTP shapes, PEM blocks. Never store secrets.
- **Storage dir:** `~/.jarvis/` (mode 0700). Atomic tmp+rename writes.

---

## 7. Voice pipeline choices

| Component | Choice | Notes |
|---|---|---|
| STT | faster-whisper `base`, int8, cpu_threads≤4, `vad_filter=True`, `language="en"` | ~0.2–0.3s per command |
| TTS primary | edge-tts `en-US-GuyNeural` | neural, free, needs net |
| TTS fallback (mac) | `say` subprocess | zero deps, never breaks |
| TTS fallback (win) | pyttsx3 sapi5 | offline |
| Wake word | openWakeWord `hey_jarvis` | pretrained; ONNX on Windows |
| VAD gate | webrtcvad-wheels (aggr. 2) | cheap per-frame |
| VAD endpoint | Silero v6 (onnxruntime) | 700–800ms silence → end turn |

All voice imports are **lazy** — `import voice.*` never happens in text mode,
so `--text` runs with zero audio dependencies.

---

## 8. Dependencies (pinned, Intel-Mac safe)

```
# core (always)
requests>=2.31
openai>=1.0
python-dateutil>=2.9

# integrations (keyless)
ddgs>=9.0
trafilatura>=1.8
feedparser>=6.0
deep-translator>=1.11

# pc control
pyautogui>=0.9.54
pynput>=1.8.1
mss>=10.1.0
pyperclip>=1.11.0
psutil>=7.0
rapidfuzz>=3.14.3
plyer>=2.1.0
# windows-only: pygetwindow, pycaw, win11toast, pywin32

# voice (lazy-loaded; not needed for --text)
sounddevice>=0.4
numpy>=1.24
faster-whisper>=1.0
openwakeword>=0.5
onnxruntime>=1.17
silero-vad>=6.2
webrtcvad-wheels>=2.0.14
edge-tts>=7.3.1
pyttsx3>=2.99
```

No torch. No ARM-only wheels. No API keys.

---

## 9. What was deliberately excluded

- Coqui XTTS (CPU too slow), Porcupine (no personal plan 2026),
  `googletrans` (abandonware), `wikipedia` package (breakage-prone),
  win10toast (dead), `keyboard` lib on macOS, brightness control
  (not feasible cross-platform), vector DBs (overkill <1000 facts),
  asyncio for audio (fights blocking C extensions).
