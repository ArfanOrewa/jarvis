# JARVIS Test Report

**Date:** 2026-10-18
**Suite:** `test_jarvis.py` — 60 assertions
**Result:** ✅ **60/60 PASSED**

## What was tested

### 1. Tool registry (3 tests)
- All 35 tools load with unique names, valid OpenAI function-calling schemas.

### 2. Every tool via the brain's tool-calling path (36 tests)
Each invoked through `execute()` (the exact function `brain.py` calls), never directly:

| Tool | Status | Notes |
|---|---|---|
| `get_time` | ✅ | zoneinfo, local timezone |
| `calculator` | ✅ | `2+3*4=14`, `sqrt(16)=4`; `__import__` blocked (AST whitelist) |
| `unit_convert` | ✅ | km→m, f→c (fixed `_LENGTH` case bug) |
| `dictionary` | ✅ | dictionaryapi.dev live |
| `system_info` | ✅ | graceful error when psutil missing |
| `clipboard_read/write` | ✅ | no-raise guarantee |
| `tell_joke` | ✅ | offline list |
| `notes_add/list/search/delete` | ✅ | full CRUD cycle verified |
| `set_timer` | ✅ | fired correctly ("Timer done: test") |
| `set_reminder` / `list_reminders` | ✅ | ISO datetime, persistence |
| `translate` | ✅ | deep-translator live |
| `email_draft` | ✅ | mailto: (no-raise) |
| `remember` / `recall` / `forget_memory` | ✅ | full lifecycle |
| `remember` (secret) | ✅ | "my password is hunter2" REJECTED by sanitizer |
| `get_weather` | ✅ | Open-Meteo live (Bengaluru) |
| `wikipedia` | ✅ | REST API live |
| `web_search` | ✅ | ddgs live |
| `get_news` | ✅ | Google News RSS live |
| `web_fetch` | ✅ | trafilatura live (example.com) |
| `take_screenshot` | ✅ | mss, no-raise headless |
| `notify` | ✅ | no-raise headless |
| `open_app` | ✅ | returns no-match gracefully |
| unknown tool | ✅ | "Unknown tool" error string |
| confirmation gate | ✅ | `press_keys` blocked without AUTO_CONFIRM |

### 3. Brain offline loop (12 commands)
All pass: time query, calculation, joke, weather, greeting, thanks,
remember/recall/forget cycle, timer, notes add/list.

### 4. Memory persistence
- Fact written → process "restart" (new Memory instance, same dir) → recalled. ✅
- Secrets rejected AND absent from store. ✅ (fixed: sanitizer now catches
  "password is X" / "api key is X" phrasing, not just `key: value`.)

### 5. Session memory
- 30 turns → window bounded to 12. ✅
- JSONL transcript written. ✅

### 6. Sentence splitter
- Splits on `.`/`!`/`?`, drops fragments <20 chars (intentional TTS guard). ✅

## Bugs found and fixed during testing
1. `brain.py` f-string nested-quote syntax error → rewrote line.
2. `system_tools.py`: `_LENGTH`/`_length` case mismatch → unit_convert NameError.
3. `memory/store.py`: sanitizer missed "X is Y" secret phrasing → added pattern.
4. `tools/personal_tools.py`: hardcoded `~/.jarvis` ignored test isolation → now uses `config.DATA_DIR`.
5. Test expectations: `sqrt(16)` returns `"4"` (int-coerced); splitter drops <20-char fragments by design.

## Not tested (requires user's hardware/key)
- **LLM tool-calling loop** (`brain._stream_turn`): needs a valid OpenRouter key.
  The loop mechanics (message appending, tool-result feeding, retry/backoff)
  follow the researched pattern but are unverified against a live model.
- **Voice pipeline**: no mic/speaker in this environment. `io_base`, `wakeword`,
  `listener`, `speaker` compile clean and degrade gracefully with zero audio
  deps (verified by the builder), but live mic/STT/TTS/wake-word not exercised.
- **PC control tools** (`open_app`, `press_keys`, `type_text`, mouse, window mgmt):
  verified no-raise; actual GUI effects need the user's Mac/PC.

## How to run
```bash
cd ~/workspace/jarvis
python3 test_jarvis.py
```
