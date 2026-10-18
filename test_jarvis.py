#!/usr/bin/env python3
"""Jarvis test suite: every tool via the registry + brain offline loop + memory persistence."""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import config
config.AUTO_CONFIRM = True  # tests auto-confirm high-impact tools
config.DATA_DIR = Path(tempfile.mkdtemp(prefix="jarvis_test_"))
config.MEMORY_FILE = config.DATA_DIR / "memory.json"
config.TRANSCRIPT_FILE = config.DATA_DIR / "transcript.jsonl"
config.SESSIONS_DIR = config.DATA_DIR / "sessions"
config.REMINDERS_FILE = config.DATA_DIR / "reminders.json"
config.TIMERS_FILE = config.DATA_DIR / "timers.json"
config.NOTES_FILE = config.DATA_DIR / "notes.json"

from memory import Memory, SessionMemory
from tools import build_registry
from brain import Brain, split_sentences

results = []
def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(f"{'PASS' if cond else 'FAIL'}: {name}" + (f" — {detail}" if detail and not cond else ""))

# --- 1. Registry loads all tools ---------------------------------------
memory = Memory()
schemas, execute = build_registry(memory)
check("registry: 35 tools", len(schemas) == 35, f"got {len(schemas)}")
names = [s["function"]["name"] for s in schemas]
check("registry: no duplicates", len(names) == len(set(names)))
# schema validity
valid = all(
    s.get("type") == "function" and "name" in s["function"]
    and "description" in s["function"] and "parameters" in s["function"]
    for s in schemas
)
check("registry: valid OpenAI schemas", valid)

# --- 2. Every tool via execute() ----------------------------------------
tool_cases = [
    ("get_time", {}, lambda r: "2026" in r),
    ("calculator", {"expression": "2 + 3 * 4"}, lambda r: r.strip() == "14"),
    ("calculator", {"expression": "sqrt(16)"}, lambda r: r.strip() in ("4", "4.0")),
    ("calculator", {"expression": "__import__('os')"}, lambda r: "error" in r.lower()),
    ("unit_convert", {"value": 1, "from_unit": "km", "to_unit": "m"}, lambda r: "1000" in r),
    ("unit_convert", {"value": 32, "from_unit": "f", "to_unit": "c"}, lambda r: "0" in r),
    ("dictionary", {"word": "computer"}, lambda r: len(r) > 20),
    ("system_info", {}, lambda r: ("CPU" in r or "cpu" in r.lower()) or "psutil" in r.lower()),
    ("clipboard_write", {"text": "jarvis-test-123"}, lambda r: "copied" in r.lower() or "clipboard" in r.lower()),
    ("clipboard_read", {}, lambda r: True),  # may fail headless; just shouldn't raise
    ("tell_joke", {}, lambda r: len(r) > 10),
    ("notes_add", {"text": "test note alpha"}, lambda r: "noted" in r.lower()),
    ("notes_add", {"text": "test note beta"}, lambda r: "noted" in r.lower()),
    ("notes_list", {}, lambda r: "alpha" in r and "beta" in r),
    ("notes_search", {"query": "alpha"}, lambda r: "alpha" in r and "beta" not in r),
    ("notes_delete", {"index": 1}, lambda r: "delet" in r.lower()),
    ("notes_list", {}, lambda r: "alpha" not in r and "beta" in r),
    ("set_timer", {"seconds": 1, "label": "test"}, lambda r: "timer" in r.lower()),
    ("set_reminder", {"text": "test reminder", "when_iso": "2030-01-01T09:00:00"}, lambda r: "2030" in r or "reminder" in r.lower()),
    ("list_reminders", {}, lambda r: "test reminder" in r),
    ("translate", {"text": "hello", "target_lang": "es"}, lambda r: len(r) > 0),
    ("email_draft", {"to": "a@b.com", "subject": "s", "body": "b"}, lambda r: True),
    ("remember", {"fact": "User's favorite color is blue", "category": "preference"}, lambda r: "remembered" in r.lower()),
    ("recall", {"query": "favorite color"}, lambda r: "blue" in r.lower()),
    ("forget_memory", {"query": "favorite color"}, lambda r: "forgot" in r.lower()),
    ("recall", {"query": "favorite color"}, lambda r: "blue" not in r.lower()),
    ("remember", {"fact": "my password is hunter2"}, lambda r: "secret" in r.lower() or "can't" in r.lower()),
    ("get_weather", {"city": "Bengaluru"}, lambda r: len(r) > 10),
    ("wikipedia", {"topic": "Python (programming language)"}, lambda r: len(r) > 50),
    ("web_search", {"query": "python programming", "max_results": 2}, lambda r: len(r) > 20),
    ("get_news", {"query": "technology", "max_results": 2}, lambda r: len(r) > 10),
    ("web_fetch", {"url": "https://example.com", "max_chars": 500}, lambda r: len(r) > 0),
    # pc tools (may SKIP headless, must not raise)
    ("take_screenshot", {}, lambda r: True),
    ("system_info", {}, lambda r: True),
    ("notify", {"title": "t", "message": "m"}, lambda r: True),
    ("open_app", {"app_name": "nonexistent-app-xyz"}, lambda r: "no match" in r.lower() or "could not" in r.lower() or True),
]
for tname, targs, validator in tool_cases:
    try:
        res = execute(tname, targs)
        ok = validator(res)
        check(f"tool:{tname}", ok, f"args={targs} -> {res[:80]}")
    except Exception as e:
        check(f"tool:{tname}", False, f"RAISED {type(e).__name__}: {e}")

# unknown tool
check("tool:unknown handled", "Unknown tool" in execute("nope_nonexistent", {}))

# --- 3. Confirmation gate -----------------------------------------------
config.AUTO_CONFIRM = False
res = execute("press_keys", {"keys": ["a"]})
check("confirm gate blocks", "CONFIRMATION REQUIRED" in res, res[:60])
config.AUTO_CONFIRM = True

# --- 4. Brain offline loop (10+ commands) ---------------------------------
session = SessionMemory()
brain = Brain(memory, session, schemas, execute)
check("brain: offline mode (no key)", brain.offline)

offline_cases = [
    "what time is it",
    "calculate 15 * 23",
    "tell me a joke",
    "what's the weather in Mumbai",
    "hello",
    "thanks",
    "remember that my favorite food is pizza",
    "what is my favorite food",
    "forget my favorite food",
    "set a timer for 5 seconds",
    "note that I need milk",
    "list my notes",
]
for cmd in offline_cases:
    try:
        resp = brain.respond_text(cmd)
        check(f"brain offline: '{cmd[:30]}'", len(resp) > 0, resp[:60])
    except Exception as e:
        check(f"brain offline: '{cmd[:30]}'", False, f"RAISED {e}")

# --- 5. Memory persistence across restart ---------------------------------
memory.remember("User's car is a red Honda", "fact")
del memory
memory2 = Memory()  # simulated restart (same DATA_DIR)
found = memory2.recall("what car does the user have")
check("memory: persists across restart", any("Honda" in f["fact"] for f in found))
# secret not stored
r = memory2.remember("my api key is sk-abc123xyz789qwerty", "fact")
check("memory: rejects secrets", "secret" in r.lower() or "can't" in r.lower())
check("memory: secret not in store",
      not any("sk-abc123" in f["fact"] for f in memory2.all()))

# --- 6. Sentence splitter --------------------------------------------------
sents = list(split_sentences("Hello world, this is the first complete sentence. This is the second complete sentence here! And this is a third complete sentence."))
check("split_sentences", len(sents) >= 3, str(sents))

# --- 7. Session memory ------------------------------------------------------
s2 = SessionMemory()
for i in range(15):
    s2.add_turn("user", f"message {i}")
    s2.add_turn("assistant", f"reply {i}")
check("session: window bounded", len(s2.turns) <= 12, f"len={len(s2.turns)}")
check("session: transcript written", config.TRANSCRIPT_FILE.exists())

# --- summary -----------------------------------------------------------------
passed = sum(1 for _, ok, _ in results if ok)
failed = [(n, d) for n, ok, d in results if not ok]
print(f"\n{'='*50}\n{passed}/{len(results)} passed")
if failed:
    print("FAILURES:")
    for n, d in failed:
        print(f"  - {n}: {d}")
    sys.exit(1)
print("ALL TESTS PASSED")
