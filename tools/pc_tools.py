"""pc_tools.py — Jarvis system-control tools (macOS + Windows 10).

10 tools that let the assistant control the user's computer: open apps,
press keys, type text, move/click the mouse, screenshot, manage windows,
set volume, and show notifications.

Design notes:
- Every function returns `str` and NEVER raises: all failures are caught
  and returned as "Error: ..." strings.
- Heavy/GUI libraries (pyautogui, rapidfuzz, mss, pycaw, win11toast,
  pygetwindow, pyperclip) are imported lazily INSIDE the functions, so
  `import tools` (or this module) never fails when an optional dependency
  is missing.
- No API keys, no network access, no config imports.
"""

import os
import platform
import subprocess
import time

# ----------------------------------------------------------------------------
# Platform helpers
# ----------------------------------------------------------------------------

_IS_MAC = platform.system() == "Darwin"
_IS_WINDOWS = platform.system() == "Windows"

# Common spoken aliases -> full application names.
APP_ALIASES = {
    "chrome": "Google Chrome",
    "vscode": "Visual Studio Code",
    "code": "Visual Studio Code",
    "terminal": "Terminal",
    "finder": "Finder",
    "notes": "Notes",
    "mail": "Mail",
    "safari": "Safari",
    "spotify": "Spotify",
    "slack": "Slack",
    "zoom": "zoom.us",
    "discord": "Discord",
    "notepad": "Notepad",
    "word": "Microsoft Word",
    "excel": "Microsoft Excel",
    "explorer": "File Explorer",
}


def _err(func_name, exc):
    """Format any exception as a safe string result (functions never raise)."""
    return "Error in %s: %s: %s" % (func_name, type(exc).__name__, exc)


# ----------------------------------------------------------------------------
# App discovery
# ----------------------------------------------------------------------------

def _mac_app_names():
    """Return list of .app names found in the standard macOS app dirs."""
    names = []
    home = os.path.expanduser("~")
    for d in ("/Applications", "/System/Applications",
              os.path.join(home, "Applications")):
        try:
            for entry in os.listdir(d):
                if entry.endswith(".app"):
                    names.append(entry[:-4])
        except OSError:
            continue
    # Deduplicate, keep order.
    seen = set()
    out = []
    for n in names:
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out


def _windows_app_names():
    """Return {display_name: lnk_path} from the Start Menu folders."""
    apps = {}
    dirs = [
        os.path.join(os.environ.get("PROGRAMDATA", ""),
                     r"Microsoft\Windows\Start Menu\Programs"),
        os.path.join(os.environ.get("APPDATA", ""),
                     r"Microsoft\Windows\Start Menu\Programs"),
    ]
    for d in dirs:
        try:
            for root, _, files in os.walk(d):
                for f in files:
                    if f.lower().endswith(".lnk"):
                        apps[f[:-4]] = os.path.join(root, f)
        except OSError:
            continue
    return apps


def _best_match(query, candidates):
    """Fuzzy-match query against candidates. Returns (best, score)."""
    try:
        from rapidfuzz import process, fuzz
        best = process.extractOne(query, candidates, scorer=fuzz.WRatio,
                                  score_cutoff=70)
        if best:
            return best[0], int(best[1])
    except Exception:
        pass
    # difflib fallback when rapidfuzz is unavailable.
    import difflib
    matches = difflib.get_close_matches(query, list(candidates), n=1,
                                        cutoff=0.6)
    if matches:
        return matches[0], 80
    return None, 0


# ----------------------------------------------------------------------------
# Tools
# ----------------------------------------------------------------------------

def open_app(app_name: str) -> str:
    """Open an application by (fuzzy-matched) name."""
    try:
        if not isinstance(app_name, str) or not app_name.strip():
            return "Error: app_name must be a non-empty string."
        query = app_name.strip()
        query = APP_ALIASES.get(query.lower(), query)
        if _IS_MAC:
            candidates = _mac_app_names()
            best, score = _best_match(query, candidates)
            if not best:
                return "no match for '%s'" % app_name
            subprocess.Popen(["open", "-a", best],
                             stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
            return "Opened %s" % best
        elif _IS_WINDOWS:
            apps = _windows_app_names()
            best, score = _best_match(query, list(apps.keys()))
            if not best:
                return "no match for '%s'" % app_name
            os.startfile(apps[best])  # noqa: S606 - local .lnk only
            return "Opened %s" % best
        return "Error: unsupported platform '%s'" % platform.system()
    except Exception as exc:  # never raise
        return _err("open_app", exc)


_KEY_ALIASES = {
    "cmd": "command", "command": "command", "meta": "command",
    "ctrl": "ctrl", "control": "ctrl", "ctl": "ctrl",
    "alt": "alt", "option": "alt",
    "shift": "shift", "esc": "esc", "escape": "esc",
    "space": "space", "enter": "enter", "return": "enter", "tab": "tab",
    "up": "up", "down": "down", "left": "left", "right": "right",
    "del": "delete", "delete": "delete", "backspace": "backspace",
}


def press_keys(keys) -> str:
    """Press a single key or a key combination, e.g. ["command","space"]."""
    try:
        if not isinstance(keys, (list, tuple)) or not keys:
            return "Error: keys must be a non-empty list, e.g. ['command','space']."
        import pyautogui
        normalized = []
        for k in keys:
            k = str(k).strip().lower()
            normalized.append(_KEY_ALIASES.get(k, k))
        if len(normalized) == 1:
            pyautogui.press(normalized[0])
        else:
            pyautogui.hotkey(*normalized)
        return "Pressed %s" % "+".join(normalized)
    except Exception as exc:
        return _err("press_keys", exc)


def type_text(text: str) -> str:
    """Type text via clipboard paste (unicode-safe)."""
    try:
        if not isinstance(text, str):
            return "Error: text must be a string."
        import pyperclip
        import pyautogui
        pyperclip.copy(text)
        paste_key = "command" if _IS_MAC else "ctrl"
        pyautogui.hotkey(paste_key, "v")
        return "Typed %d characters" % len(text)
    except Exception as exc:
        return _err("type_text", exc)


def mouse_move(x: int, y: int) -> str:
    """Move the mouse cursor to screen coordinates (x, y)."""
    try:
        import pyautogui
        pyautogui.moveTo(int(x), int(y), duration=0.2)
        return "Moved mouse to (%d, %d)" % (int(x), int(y))
    except Exception as exc:
        return _err("mouse_move", exc)


def mouse_click(button: str = "left") -> str:
    """Click the mouse. button is 'left', 'right', or 'middle'."""
    try:
        import pyautogui
        b = str(button).strip().lower()
        if b not in ("left", "right", "middle"):
            return "Error: button must be 'left', 'right', or 'middle'."
        pyautogui.click(button=b)
        return "Clicked (%s button)" % b
    except Exception as exc:
        return _err("mouse_click", exc)


def take_screenshot() -> str:
    """Capture the screen and save it, returning the file path."""
    try:
        import mss  # imported here per contract
        shot_dir = os.path.join(os.path.expanduser("~"), "screenshots")
        os.makedirs(shot_dir, exist_ok=True)
        fname = "jarvis_%s.png" % time.strftime("%Y%m%d_%H%M%S")
        path = os.path.join(shot_dir, fname)
        with mss.mss() as sct:
            sct.shot(output=path)
        return path
    except Exception as exc:
        return _err("take_screenshot", exc)


def window_focus(app_name: str) -> str:
    """Bring an application's window to the front."""
    try:
        if not isinstance(app_name, str) or not app_name.strip():
            return "Error: app_name must be a non-empty string."
        name = app_name.strip()
        if _IS_MAC:
            script = 'tell application "%s" to activate' % name.replace('"', "")
            subprocess.run(["osascript", "-e", script], check=True,
                           stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL)
            return "Focused %s" % name
        elif _IS_WINDOWS:
            import pygetwindow as gw
            wins = gw.getWindowsWithTitle(name)
            if not wins:
                return "no match for '%s'" % name
            w = wins[0]
            try:
                w.restore()
            except Exception:
                pass
            w.activate()
            return "Focused %s" % w.title
        return "Error: unsupported platform '%s'" % platform.system()
    except Exception as exc:
        return _err("window_focus", exc)


def window_minimize(app_name: str) -> str:
    """Minimize an application's window(s)."""
    try:
        if not isinstance(app_name, str) or not app_name.strip():
            return "Error: app_name must be a non-empty string."
        name = app_name.strip()
        if _IS_MAC:
            script = ('tell application "System Events" to set visible of '
                      'process "%s" to false' % name.replace('"', ""))
            subprocess.run(["osascript", "-e", script], check=True,
                           stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL)
            return "Minimized %s" % name
        elif _IS_WINDOWS:
            import pygetwindow as gw
            wins = gw.getWindowsWithTitle(name)
            if not wins:
                return "no match for '%s'" % name
            wins[0].minimize()
            return "Minimized %s" % wins[0].title
        return "Error: unsupported platform '%s'" % platform.system()
    except Exception as exc:
        return _err("window_minimize", exc)


def set_volume(level: int) -> str:
    """Set the system output volume, 0-100."""
    try:
        level = int(level)
        if not 0 <= level <= 100:
            return "Error: level must be 0-100, got %s." % level
        if _IS_MAC:
            subprocess.run(
                ["osascript", "-e",
                 "set volume output volume %d" % level],
                check=True, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL)
            return "Volume set to %d%%" % level
        elif _IS_WINDOWS:
            from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
            from comtypes import CLSCTX_ALL
            from ctypes import cast, POINTER
            speakers = AudioUtilities.GetSpeakers()
            interface = speakers.Activate(
                IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            volume = cast(interface, POINTER(IAudioEndpointVolume))
            volume.SetMasterVolumeLevelScalar(level / 100.0, None)
            return "Volume set to %d%%" % level
        return "Error: unsupported platform '%s'" % platform.system()
    except Exception as exc:
        return _err("set_volume", exc)


def notify(title: str, message: str) -> str:
    """Show a desktop notification."""
    try:
        t, m = str(title), str(message)
        if _IS_MAC:
            script = 'display notification "%s" with title "%s"' % (
                m.replace('"', ""), t.replace('"', ""))
            subprocess.run(["osascript", "-e", script], check=True,
                           stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL)
            return "Notification sent: %s" % t
        elif _IS_WINDOWS:
            try:
                from win11toast import toast
                toast(t, m)
                return "Notification sent: %s" % t
            except Exception:
                from plyer import notification as pn
                pn.notify(title=t, message=m, app_name="Jarvis",
                          timeout=10)
                return "Notification sent: %s" % t
        return "Error: unsupported platform '%s'" % platform.system()
    except Exception as exc:
        return _err("notify", exc)


# ----------------------------------------------------------------------------
# Schema + registry (OpenAI function-calling format)
# ----------------------------------------------------------------------------

SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "open_app",
            "description": ("Open a desktop application by name, with fuzzy "
                            "matching and common aliases (e.g. 'chrome', "
                            "'vscode'). Use when the user asks to open or "
                            "launch an app."),
            "parameters": {
                "type": "object",
                "properties": {
                    "app_name": {"type": "string",
                                "description": "Name of the app to open."}
                },
                "required": ["app_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "press_keys",
            "description": ("Press a keyboard key or shortcut combination, "
                            "e.g. ['command','space'] on macOS or "
                            "['ctrl','c'] on Windows. Use for shortcuts, "
                            "copy/paste, or navigating apps."),
            "parameters": {
                "type": "object",
                "properties": {
                    "keys": {"type": "array",
                             "items": {"type": "string"},
                             "description": "Keys to press, e.g. ['ctrl','c']."}
                },
                "required": ["keys"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "type_text",
            "description": ("Type arbitrary text into the focused window via "
                            "clipboard paste, which is unicode-safe. Use "
                            "when the user asks to type, write, or enter "
                            "text into a document, field, or app."),
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string",
                             "description": "Text to type."}
                },
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "mouse_move",
            "description": ("Move the mouse cursor to screen coordinates "
                            "(x, y). Use when the user wants the pointer "
                            "moved to a specific screen location."),
            "parameters": {
                "type": "object",
                "properties": {
                    "x": {"type": "integer", "description": "X coordinate."},
                    "y": {"type": "integer", "description": "Y coordinate."},
                },
                "required": ["x", "y"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "mouse_click",
            "description": ("Click the mouse at the current cursor position. "
                            "Use after moving the cursor, or when the user "
                            "asks to click something on screen."),
            "parameters": {
                "type": "object",
                "properties": {
                    "button": {"type": "string", "enum": ["left", "right", "middle"],
                               "default": "left",
                               "description": "Which mouse button to click."}
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "take_screenshot",
            "description": ("Capture the current screen and save it as a PNG "
                            "in ~/screenshots, returning the file path. Use "
                            "when the user asks to see, capture, or share "
                            "what is on their screen."),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "window_focus",
            "description": ("Bring an application's window to the front and "
                            "give it focus. Use when the user wants to "
                            "switch to or activate a specific app."),
            "parameters": {
                "type": "object",
                "properties": {
                    "app_name": {"type": "string",
                                "description": "App or window title to focus."}
                },
                "required": ["app_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "window_minimize",
            "description": ("Minimize an application's window(s). Use when "
                            "the user asks to minimize, hide, or dismiss an "
                            "app's window."),
            "parameters": {
                "type": "object",
                "properties": {
                    "app_name": {"type": "string",
                                "description": "App or window title to minimize."}
                },
                "required": ["app_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_volume",
            "description": ("Set the system output volume from 0 to 100. "
                            "Use when the user asks to turn the volume up, "
                            "down, mute (0), or set a level."),
            "parameters": {
                "type": "object",
                "properties": {
                    "level": {"type": "integer", "minimum": 0, "maximum": 100,
                              "description": "Volume level, 0-100."}
                },
                "required": ["level"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "notify",
            "description": ("Show a desktop notification with a title and "
                            "message. Use to alert the user about completed "
                            "tasks, reminders, or important events."),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string",
                              "description": "Notification title."},
                    "message": {"type": "string",
                                "description": "Notification body text."},
                },
                "required": ["title", "message"],
            },
        },
    },
]

FUNCS = {
    "open_app": open_app,
    "press_keys": press_keys,
    "type_text": type_text,
    "mouse_move": mouse_move,
    "mouse_click": mouse_click,
    "take_screenshot": take_screenshot,
    "window_focus": window_focus,
    "window_minimize": window_minimize,
    "set_volume": set_volume,
    "notify": notify,
}


# ----------------------------------------------------------------------------
# Self-tests
# ----------------------------------------------------------------------------

def _self_test():
    """Call each function once and print the result. GUI-dependent tools may
    be skipped on headless systems."""
    gui_needs = {"open_app", "press_keys", "type_text", "mouse_move",
                 "mouse_click", "take_screenshot", "window_focus",
                 "window_minimize"}
    cases = {
        "open_app": ("open_app", ("Calculator",), {}),
        "press_keys": ("press_keys", (["escape"],), {}),
        "type_text": ("type_text", ("jarvis self-test",), {}),
        "mouse_move": ("mouse_move", (100, 100), {}),
        "mouse_click": ("mouse_click", (), {}),
        "take_screenshot": ("take_screenshot", (), {}),
        "window_focus": ("window_focus", ("Finder",), {}),
        "window_minimize": ("window_minimize", ("Finder",), {}),
        "set_volume": ("set_volume", (50,), {}),
        "notify": ("notify", ("Jarvis test", "self-test notification"), {}),
    }
    headless = not (os.environ.get("DISPLAY") or _IS_MAC or _IS_WINDOWS)
    for name, (func_name, args, kwargs) in cases.items():
        try:
            if headless and name in gui_needs:
                print("SKIP %-16s (headless, no display)" % name)
                continue
            result = FUNCS[func_name](*args, **kwargs)
            print("OK   %-16s -> %s" % (name, str(result)[:120]))
        except Exception as exc:
            print("SKIP %-16s (%s)" % (name, exc))
    assert len(SCHEMAS) == 10 and set(FUNCS) == {s["function"]["name"] for s in SCHEMAS}
    print("pc_tools self-test done: %d schemas, %d funcs" % (len(SCHEMAS), len(FUNCS)))


if __name__ == "__main__":
    _self_test()
