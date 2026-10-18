"""personal_tools.py — Jarvis personal-assistant tools.

13 tools for everyday help: timers, reminders, quick notes, jokes,
translation, email drafts, and long-term memory (via a bound Memory
instance).

Design notes:
- Every function returns `str` and NEVER raises: all failures are caught
  and returned as "Error: ..." strings.
- Heavy libraries (deep_translator) are imported lazily INSIDE functions.
- Storage lives under ~/.jarvis/ (Path.home() directly — no config import).
- Persistence helpers `_load_json` / `_save_json` use atomic tmp+rename.
- Memory tools (remember/recall/forget_memory) delegate to a module-level
  Memory bound via `bind_memory(mem)`; if unbound they report
  "Memory not available."
"""

import json
import os
import random
import threading
import time
import webbrowser
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote

# ----------------------------------------------------------------------------
# Storage + persistence helpers
# ----------------------------------------------------------------------------

import config

JARVIS_DIR = config.DATA_DIR
TIMERS_FILE = config.TIMERS_FILE
REMINDERS_FILE = config.REMINDERS_FILE
NOTES_FILE = config.NOTES_FILE

_write_lock = threading.Lock()


def _ensure_dir():
    try:
        JARVIS_DIR.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass


def _load_json(path, default):
    """Load JSON from path; return `default` on any failure."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _save_json(path, obj):
    """Atomically write JSON (tmp file + rename). Returns True on success."""
    try:
        _ensure_dir()
        tmp = Path(str(path) + ".tmp")
        with _write_lock:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(obj, f, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
        return True
    except Exception:
        return False


def _err(func_name, exc):
    return "Error in %s: %s: %s" % (func_name, type(exc).__name__, exc)


# notify is reused by timers/reminders; import lazily to keep this module
# importable without the GUI stack present.
def _notify(title, message):
    try:
        from pc_tools import notify as _pc_notify  # sibling module
        return _pc_notify(title, message)
    except Exception:
        pass
    try:
        from plyer import notification as pn
        pn.notify(title=str(title), message=str(message),
                  app_name="Jarvis", timeout=10)
        return "Notification sent"
    except Exception:
        print("[jarvis] %s: %s" % (title, message))
        return "Notification printed to console"


# ----------------------------------------------------------------------------
# Timers
# ----------------------------------------------------------------------------

def set_timer(seconds: int, label: str = "") -> str:
    """Set a countdown timer that notifies when it fires."""
    try:
        seconds = int(seconds)
        if seconds <= 0:
            return "Error: seconds must be a positive integer."
        label = str(label or "Timer")
        fire_at = time.time() + seconds

        timers = _load_json(TIMERS_FILE, [])
        timers.append({"fire_at": fire_at, "label": label})
        _save_json(TIMERS_FILE, timers)

        def _fire():
            _notify("Timer done", label)
            print("[jarvis] Timer done: %s" % label)
            try:
                remaining = [t for t in _load_json(TIMERS_FILE, [])
                             if t.get("fire_at", 0) > time.time()]
                _save_json(TIMERS_FILE, remaining)
            except Exception:
                pass

        t = threading.Timer(seconds, _fire)
        t.daemon = True
        t.start()
        return "Timer set for %ds (%s)" % (seconds, label)
    except Exception as exc:
        return _err("set_timer", exc)


# ----------------------------------------------------------------------------
# Reminders (background checker thread)
# ----------------------------------------------------------------------------

_reminder_thread = None
_reminder_lock = threading.Lock()


def _reminder_loop():
    """Wake every 30s and notify on due reminders."""
    while True:
        try:
            now = time.time()
            reminders = _load_json(REMINDERS_FILE, [])
            pending = []
            for r in reminders:
                when = r.get("when")
                if when is None:
                    continue
                try:
                    due = datetime.fromisoformat(when).timestamp()
                except Exception:
                    pending.append(r)
                    continue
                if due <= now:
                    _notify("Reminder", r.get("text", ""))
                    print("[jarvis] Reminder: %s" % r.get("text", ""))
                else:
                    pending.append(r)
            if len(pending) != len(reminders):
                _save_json(REMINDERS_FILE, pending)
        except Exception:
            pass
        time.sleep(30)


def _start_reminder_thread():
    global _reminder_thread
    with _reminder_lock:
        if _reminder_thread is None or not _reminder_thread.is_alive():
            _reminder_thread = threading.Thread(target=_reminder_loop,
                                                daemon=True,
                                                name="jarvis-reminders")
            _reminder_thread.start()


def set_reminder(text: str, when_iso: str) -> str:
    """Schedule a reminder at an ISO datetime, e.g. '2026-10-18T18:30:00'."""
    try:
        if not isinstance(text, str) or not text.strip():
            return "Error: text must be a non-empty string."
        try:
            when = datetime.fromisoformat(str(when_iso).strip())
        except Exception:
            return ("Error: when_iso must be ISO format like "
                    "'2026-10-18T18:30:00'.")
        if when <= datetime.now():
            return "Error: reminder time must be in the future."
        reminders = _load_json(REMINDERS_FILE, [])
        rid = max([r.get("id", 0) for r in reminders] + [0]) + 1
        reminders.append({"id": rid, "text": text.strip(),
                          "when": when.isoformat()})
        _save_json(REMINDERS_FILE, reminders)
        _start_reminder_thread()
        human = when.strftime("%A, %B %d at %I:%M %p")
        return "Reminder #%d set for %s: %s" % (rid, human, text.strip())
    except Exception as exc:
        return _err("set_reminder", exc)


def list_reminders() -> str:
    """List all pending reminders."""
    try:
        reminders = _load_json(REMINDERS_FILE, [])
        now = time.time()
        lines = []
        for r in sorted(reminders, key=lambda x: x.get("when", "")):
            try:
                when = datetime.fromisoformat(r["when"])
            except Exception:
                continue
            if when.timestamp() <= now:
                continue
            lines.append("#%d — %s — %s" % (
                r.get("id"), when.strftime("%a %b %d, %I:%M %p"),
                r.get("text", "")))
        if not lines:
            return "No pending reminders."
        return "Pending reminders:\n" + "\n".join(lines)
    except Exception as exc:
        return _err("list_reminders", exc)


# ----------------------------------------------------------------------------
# Notes
# ----------------------------------------------------------------------------

def notes_add(text: str) -> str:
    """Save a quick note."""
    try:
        if not isinstance(text, str) or not text.strip():
            return "Error: text must be a non-empty string."
        notes = _load_json(NOTES_FILE, [])
        notes.append({"text": text.strip(),
                      "ts": datetime.now().isoformat(timespec="seconds")})
        if _save_json(NOTES_FILE, notes):
            return "Noted."
        return "Error: could not save the note."
    except Exception as exc:
        return _err("notes_add", exc)


def notes_list() -> str:
    """List all saved notes, numbered."""
    try:
        notes = _load_json(NOTES_FILE, [])
        if not notes:
            return "No notes saved."
        lines = ["%d. %s (%s)" % (i + 1, n.get("text", ""),
                                  n.get("ts", "?"))
                 for i, n in enumerate(notes)]
        return "\n".join(lines)
    except Exception as exc:
        return _err("notes_list", exc)


def notes_search(query: str) -> str:
    """Search notes for a keyword."""
    try:
        q = str(query).strip().lower()
        if not q:
            return "Error: query must be a non-empty string."
        notes = _load_json(NOTES_FILE, [])
        hits = ["%d. %s (%s)" % (i + 1, n.get("text", ""),
                                 n.get("ts", "?"))
                for i, n in enumerate(notes)
                if q in str(n.get("text", "")).lower()]
        if not hits:
            return "No notes match '%s'." % query
        return "Matching notes:\n" + "\n".join(hits)
    except Exception as exc:
        return _err("notes_search", exc)


def notes_delete(index: int) -> str:
    """Delete a note by its 1-based number (see notes_list)."""
    try:
        idx = int(index)
        notes = _load_json(NOTES_FILE, [])
        if not 1 <= idx <= len(notes):
            return "Error: index %d out of range (1-%d)." % (idx, len(notes))
        removed = notes.pop(idx - 1)
        if _save_json(NOTES_FILE, notes):
            return "Deleted note %d: %s" % (idx, removed.get("text", ""))
        return "Error: could not save after deleting."
    except Exception as exc:
        return _err("notes_delete", exc)


# ----------------------------------------------------------------------------
# Jokes (offline)
# ----------------------------------------------------------------------------

_JOKES = [
    "Why do programmers prefer dark mode? Because light attracts bugs.",
    "Why did the developer go broke? Because he used up all his cache.",
    "How do you comfort a JavaScript bug? You console it.",
    "Why do Python devs hate Java? Because Java needs coffee to run.",
    "There are only 10 kinds of people: those who understand binary and those who don't.",
    "A SQL query walks into a bar, sees two tables and asks: mind if I join you?",
    "Why was the JavaScript developer sad? Because he didn't Node how to Express himself.",
    "Debugging: being the detective in a crime movie where you are also the murderer.",
    "I told my computer I needed a break, and now it won't stop sending me KitKat ads.",
    "Why do programmers always mix up Halloween and Christmas? Because Oct 31 == Dec 25.",
    "Real programmers count from 0.",
    "A programmer's spouse says: 'Go to the store and get a loaf of bread. If they have eggs, get a dozen.' They came home with 12 loaves of bread.",
    "Why did the computer catch a cold? It left its Windows open.",
    "The best thing about a boolean is that even if you're wrong, you're only off by a bit.",
    "Why don't programmers like nature? Too many bugs.",
]


def tell_joke() -> str:
    """Tell a clean, offline tech/general joke."""
    try:
        return random.choice(_JOKES)
    except Exception as exc:
        return _err("tell_joke", exc)


# ----------------------------------------------------------------------------
# Translation (offline-safe fallback via deep_translator)
# ----------------------------------------------------------------------------

def translate(text: str, target_lang: str = "en") -> str:
    """Translate text to the target language code (default 'en')."""
    try:
        if not isinstance(text, str) or not text.strip():
            return "Error: text must be a non-empty string."
        target = str(target_lang).strip().lower() or "en"
        from deep_translator import GoogleTranslator  # lazy import
        return GoogleTranslator(source="auto", target=target).translate(
            text.strip())
    except Exception as exc:
        return _err("translate", exc)


# ----------------------------------------------------------------------------
# Email draft
# ----------------------------------------------------------------------------

def email_draft(to: str, subject: str, body: str) -> str:
    """Open a pre-filled email draft in the user's default mail app."""
    try:
        addr = str(to).strip()
        if not addr:
            return "Error: 'to' must be a non-empty email address."
        url = "mailto:%s?subject=%s&body=%s" % (
            quote(addr), quote(str(subject)), quote(str(body)))
        webbrowser.open(url)
        return "Draft opened in your mail app."
    except Exception as exc:
        return _err("email_draft", exc)


# ----------------------------------------------------------------------------
# Memory (bound instance)
# ----------------------------------------------------------------------------

_memory = None


def bind_memory(mem):
    """Bind the shared Memory instance used by remember/recall/forget_memory."""
    global _memory
    _memory = mem
    return "Memory bound."


def remember(fact: str, category: str = "fact") -> str:
    """Save a fact to long-term memory."""
    try:
        if _memory is None:
            return "Memory not available."
        if not isinstance(fact, str) or not fact.strip():
            return "Error: fact must be a non-empty string."
        result = _memory.remember(fact.strip(), category=str(category))
        return str(result) if result else "Remembered: %s" % fact.strip()
    except Exception as exc:
        return _err("remember", exc)


def recall(query: str) -> str:
    """Recall memories matching a query, one per line."""
    try:
        if _memory is None:
            return "Memory not available."
        results = _memory.recall(str(query))
        if not results:
            return "No memories found for '%s'." % query
        if isinstance(results, str):
            return results
        return "\n".join("- %s" % r for r in results)
    except Exception as exc:
        return _err("recall", exc)


def forget_memory(query: str) -> str:
    """Forget memories matching a query."""
    try:
        if _memory is None:
            return "Memory not available."
        result = _memory.forget(str(query))
        return str(result) if result else "Forgot memories matching '%s'." % query
    except Exception as exc:
        return _err("forget_memory", exc)


# ----------------------------------------------------------------------------
# Schema + registry (OpenAI function-calling format)
# ----------------------------------------------------------------------------

SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "set_timer",
            "description": ("Start a countdown timer for a number of seconds "
                            "that notifies the user when it finishes. Use "
                            "when the user asks for a timer or countdown."),
            "parameters": {
                "type": "object",
                "properties": {
                    "seconds": {"type": "integer", "minimum": 1,
                                "description": "Countdown length in seconds."},
                    "label": {"type": "string",
                              "description": "Optional timer label."},
                },
                "required": ["seconds"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_reminder",
            "description": ("Schedule a reminder for a future date and time, "
                            "e.g. '2026-10-18T18:30:00'. The user is "
                            "notified when it is due. Use when the user asks "
                            "to be reminded of something later."),
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string",
                             "description": "What to remind the user about."},
                    "when_iso": {"type": "string",
                                 "description": "ISO datetime, e.g. '2026-10-18T18:30:00'."},
                },
                "required": ["text", "when_iso"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_reminders",
            "description": ("List all pending reminders. Use when the user "
                            "asks what reminders they have or wants to "
                            "review upcoming reminders."),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "notes_add",
            "description": ("Save a quick note. Use when the user asks to "
                            "jot something down, take a note, or remember "
                            "something short-term."),
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string",
                             "description": "Note text to save."}
                },
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "notes_list",
            "description": ("List all saved notes, numbered. Use when the "
                            "user asks to see their notes."),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "notes_search",
            "description": ("Search saved notes for a keyword. Use when the "
                            "user asks to find a note about something."),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string",
                              "description": "Keyword to search for."}
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "notes_delete",
            "description": ("Delete a note by its 1-based number from "
                            "notes_list. Use when the user asks to delete or "
                            "remove a note."),
            "parameters": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer", "minimum": 1,
                              "description": "1-based note number."}
                },
                "required": ["index"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "tell_joke",
            "description": ("Tell a clean, family-friendly joke (tech and "
                            "general, offline). Use when the user asks for a "
                            "joke or wants to lighten the mood."),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "translate",
            "description": ("Translate text into the target language "
                            "(language code like 'en', 'es', 'hi'; default "
                            "'en'). Use when the user asks to translate "
                            "something."),
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string",
                             "description": "Text to translate."},
                    "target_lang": {"type": "string", "default": "en",
                                    "description": "Target language code."},
                },
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "email_draft",
            "description": ("Open a pre-filled email draft (to, subject, "
                            "body) in the user's default mail app for them "
                            "to review and send. Use when the user asks to "
                            "draft or write an email."),
            "parameters": {
                "type": "object",
                "properties": {
                    "to": {"type": "string",
                           "description": "Recipient email address."},
                    "subject": {"type": "string",
                                "description": "Email subject."},
                    "body": {"type": "string", "description": "Email body."},
                },
                "required": ["to", "subject", "body"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remember",
            "description": ("Save a fact to the user's long-term memory. "
                            "Use when the user says 'remember that...' or "
                            "shares a durable preference or fact."),
            "parameters": {
                "type": "object",
                "properties": {
                    "fact": {"type": "string",
                             "description": "Fact to remember."},
                    "category": {"type": "string", "default": "fact",
                                 "description": "Memory category."},
                },
                "required": ["fact"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "recall",
            "description": ("Recall saved memories matching a query, "
                            "returned one per line. Use when the user asks "
                            "what you remember about something."),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string",
                              "description": "Query to search memory."}
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "forget_memory",
            "description": ("Delete saved memories matching a query. Use "
                            "when the user asks to forget something you "
                            "remembered."),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string",
                              "description": "Query for memories to forget."}
                },
                "required": ["query"],
            },
        },
    },
]

FUNCS = {
    "set_timer": set_timer,
    "set_reminder": set_reminder,
    "list_reminders": list_reminders,
    "notes_add": notes_add,
    "notes_list": notes_list,
    "notes_search": notes_search,
    "notes_delete": notes_delete,
    "tell_joke": tell_joke,
    "translate": translate,
    "email_draft": email_draft,
    "remember": remember,
    "recall": recall,
    "forget_memory": forget_memory,
}


# ----------------------------------------------------------------------------
# Self-tests
# ----------------------------------------------------------------------------

def _self_test():
    """Call each function once and print the result."""
    headless = not os.environ.get("DISPLAY")
    cases = [
        ("set_timer", (2, "self-test"), {}),
        ("set_reminder", ("self-test reminder",
                          (datetime.now() + timedelta(hours=1)).isoformat(
                              timespec="seconds")), {}),
        ("list_reminders", (), {}),
        ("notes_add", ("self-test note",), {}),
        ("notes_list", (), {}),
        ("notes_search", ("self-test",), {}),
        ("notes_delete", (1,), {}),
        ("tell_joke", (), {}),
        ("translate", ("Hello world", "es"), {}),
        ("email_draft", ("test@example.com", "Hi", "Body"), {}),
        ("remember", ("self-test fact",), {}),
        ("recall", ("self-test",), {}),
        ("forget_memory", ("self-test",), {}),
    ]
    for name, args, kwargs in cases:
        try:
            if name == "email_draft" and headless:
                print("SKIP email_draft      (headless, would open browser)")
                continue
            result = FUNCS[name](*args, **kwargs)
            print("OK   %-16s -> %s" % (name, str(result)[:120]))
        except Exception as exc:
            print("SKIP %-16s (%s)" % (name, exc))
    assert len(SCHEMAS) == 13 and set(FUNCS) == {s["function"]["name"] for s in SCHEMAS}
    print("personal_tools self-test done: %d schemas, %d funcs"
          % (len(SCHEMAS), len(FUNCS)))


if __name__ == "__main__":
    _self_test()
