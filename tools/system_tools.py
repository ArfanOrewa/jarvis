"""
system_tools.py — Keyless system/utility tools for the Jarvis voice assistant.

Tools (all return str, never raise):
    get_time        Current time/date (system local or IANA timezone).
    calculator      Safe math expression evaluation (AST whitelist, no eval).
    unit_convert    Length / weight / temperature / volume conversions.
    dictionary      English word definitions (free dictionary API).
    system_info     CPU / RAM / disk / battery stats (psutil).
    clipboard_read  Read clipboard text (pyperclip).
    clipboard_write Write text to the clipboard (pyperclip).

Each module-level function is registered in FUNCS and described in SCHEMAS
(OpenAI function-calling format).
"""

import ast
import datetime as _dt
import math
import urllib.parse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import requests

SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "get_time",
            "description": (
                "Returns the current local time and date. "
                "Use this when the user asks what time it is, what day it is, "
                "or needs the current date/time for planning."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "timezone": {
                        "type": "string",
                        "description": (
                            "Optional IANA timezone like 'Asia/Kolkata' or "
                            "'America/New_York'. Empty means the system local time."
                        ),
                        "default": "",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calculator",
            "description": (
                "Evaluates a math expression safely using an AST whitelist "
                "(no eval). Supports + - * / // % **, parentheses, and functions "
                "sqrt, sin, cos, tan, log, exp, abs, round, pow. "
                "Use this for any arithmetic or math question."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "The math expression, e.g. 'sqrt(2**8) + 10%3'.",
                    },
                },
                "required": ["expression"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "unit_convert",
            "description": (
                "Converts between units: length (m, km, cm, mm, mile, yard, foot, "
                "inch), weight (kg, g, lb, oz), temperature (c, f, k), volume "
                "(l, ml, gallon, cup). "
                "Use this when the user asks to convert one unit to another."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "value": {"type": "number", "description": "The numeric value."},
                    "from_unit": {
                        "type": "string",
                        "description": "Source unit, e.g. 'km', 'lb', 'f'.",
                    },
                    "to_unit": {
                        "type": "string",
                        "description": "Target unit, e.g. 'mile', 'kg', 'c'.",
                    },
                },
                "required": ["value", "from_unit", "to_unit"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "dictionary",
            "description": (
                "Looks up an English word's definitions. "
                "Use this when the user asks what a word means or how to use it."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "word": {
                        "type": "string",
                        "description": "The English word to define.",
                    },
                },
                "required": ["word"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "system_info",
            "description": (
                "Reports system stats: CPU usage, core count, RAM usage, disk "
                "usage, and battery status. "
                "Use this when the user asks about their computer's status or health."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "clipboard_read",
            "description": (
                "Reads the current text on the system clipboard. "
                "Use this when the user says 'what's on my clipboard' or wants you "
                "to use something they just copied."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "clipboard_write",
            "description": (
                "Writes text to the system clipboard. "
                "Use this when the user asks you to copy something for them."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "The text to copy to the clipboard.",
                    },
                },
                "required": ["text"],
            },
        },
    },
]


def get_time(timezone=""):
    """Current local time and date."""
    try:
        timezone = str(timezone).strip()
        if timezone:
            try:
                tz = ZoneInfo(timezone)
            except ZoneInfoNotFoundError:
                return f"Unknown timezone: {timezone}"
            now = _dt.datetime.now(tz)
            return now.strftime("%A, %B %d, %Y — %I:%M %p ") + f"({timezone})"
        now = _dt.datetime.now().astimezone()
        return now.strftime("%A, %B %d, %Y — %I:%M %p ") + f"({now.tzname()})"
    except Exception as e:
        return f"get_time error: {e}"


_ALLOWED_BINOPS = {
    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b,
    ast.Div: lambda a, b: a / b,
    ast.FloorDiv: lambda a, b: a // b,
    ast.Mod: lambda a, b: a % b,
    ast.Pow: lambda a, b: a**b,
}
_ALLOWED_FUNCS = {
    "sqrt": math.sqrt,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "log": math.log,
    "exp": math.exp,
    "abs": abs,
    "round": round,
    "pow": pow,
}


def _safe_eval(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _ALLOWED_BINOPS:
        return _ALLOWED_BINOPS[type(node.op)](
            _safe_eval(node.left), _safe_eval(node.right)
        )
    if (
        isinstance(node, ast.UnaryOp)
        and isinstance(node.op, (ast.UAdd, ast.USub))
    ):
        val = _safe_eval(node.operand)
        return val if isinstance(node.op, ast.UAdd) else -val
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in _ALLOWED_FUNCS
        and not node.keywords
    ):
        return _ALLOWED_FUNCS[node.func.id](
            *[_safe_eval(a) for a in node.args]
        )
    raise ValueError(f"Unsupported expression: {ast.dump(node)}")


def calculator(expression):
    """Safe math evaluation via AST whitelist — never uses eval()."""
    try:
        tree = ast.parse(str(expression), mode="eval")
        result = _safe_eval(tree.body)
        if isinstance(result, float) and result.is_integer():
            result = int(result)
        return str(result)
    except Exception as e:
        return f"calculator error: {e}"


_length = {  # factors to metres
    "m": 1.0, "km": 1000.0, "cm": 0.01, "mm": 0.001,
    "mile": 1609.344, "yard": 0.9144, "foot": 0.3048, "inch": 0.0254,
}
_weight = {  # factors to kilograms
    "kg": 1.0, "g": 0.001, "lb": 0.45359237, "oz": 0.028349523125,
}
_volume = {  # factors to litres
    "l": 1.0, "ml": 0.001, "gallon": 3.785411784, "cup": 0.2365882365,
}


def _convert_temp(value, frm, to):
    # normalise to Celsius first
    if frm == "c":
        c = value
    elif frm == "f":
        c = (value - 32) * 5 / 9
    elif frm == "k":
        c = value - 273.15
    else:
        raise ValueError("temperature units: c, f, k")
    if to == "c":
        return c
    if to == "f":
        return c * 9 / 5 + 32
    if to == "k":
        return c + 273.15
    raise ValueError("temperature units: c, f, k")


def unit_convert(value, from_unit, to_unit):
    """Hand-rolled unit conversion across four dimensions."""
    try:
        frm = str(from_unit).strip().lower()
        to = str(to_unit).strip().lower()
        val = float(value)
        dims = {"length": _length, "weight": _weight, "volume": _volume}
        for dim, table in dims.items():
            if frm in table and to in table:
                result = val * table[frm] / table[to]
                return f"{val:g} {frm} = {result:g} {to}"
        if frm in ("c", "f", "k") and to in ("c", "f", "k"):
            result = _convert_temp(val, frm, to)
            return f"{val:g} {frm} = {result:g} {to}"
        supported = (
            "length: " + ", ".join(sorted(_length))
            + "; weight: " + ", ".join(sorted(_weight))
            + "; temperature: c, f, k"
            + "; volume: " + ", ".join(sorted(_volume))
        )
        return f"Cannot convert '{from_unit}' to '{to_unit}'. Supported: {supported}"
    except Exception as e:
        return f"unit_convert error: {e}"


def dictionary(word):
    """First two definitions with part of speech from dictionaryapi.dev."""
    try:
        word = str(word).strip()
        url = (
            "https://api.dictionaryapi.dev/api/v2/entries/en/"
            + urllib.parse.quote(word)
        )
        r = requests.get(url, timeout=15)
        if r.status_code == 404:
            return f"No definition found for '{word}'."
        r.raise_for_status()
        entries = r.json()
        defs = []
        for entry in entries:
            for meaning in entry.get("meanings", []):
                pos = meaning.get("partOfSpeech", "")
                for d in meaning.get("definitions", []):
                    text = d.get("definition", "").strip()
                    if text:
                        label = f"({pos}) " if pos else ""
                        defs.append(f"{label}{text}")
                        if len(defs) >= 2:
                            break
                if len(defs) >= 2:
                    break
            if len(defs) >= 2:
                break
        if not defs:
            return f"No definition found for '{word}'."
        return f"{word}:\n" + "\n".join(f"{i}. {d}" for i, d in enumerate(defs, 1))
    except Exception as e:
        return f"dictionary error: {e}"


def system_info():
    """CPU / RAM / disk / battery stats via psutil."""
    try:
        import psutil

        lines = []
        lines.append(f"CPU: {psutil.cpu_percent(interval=0.5)}% ({psutil.cpu_count()} cores)")
        mem = psutil.virtual_memory()
        lines.append(
            f"RAM: {mem.percent}% used ({mem.used / 1e9:.1f}/{mem.total / 1e9:.1f} GB)"
        )
        disk = psutil.disk_usage("/")
        lines.append(
            f"Disk: {disk.percent}% used ({disk.used / 1e9:.1f}/{disk.total / 1e9:.1f} GB)"
        )
        try:
            batt = psutil.sensors_battery()
            if batt is not None:
                state = "charging" if batt.power_plugged else "on battery"
                lines.append(f"Battery: {batt.percent}% ({state})")
            else:
                lines.append("Battery: not available")
        except Exception:
            lines.append("Battery: not available")
        return "\n".join(lines)
    except Exception as e:
        return f"system_info error: {e}"


def clipboard_read():
    """Read clipboard text (pyperclip), truncated to 500 chars."""
    try:
        import pyperclip

        text = pyperclip.paste() or ""
        if not text:
            return "Clipboard is empty."
        return text[:500]
    except Exception as e:
        return f"clipboard_read error: {e}"


def clipboard_write(text):
    """Write text to clipboard (pyperclip)."""
    try:
        import pyperclip

        pyperclip.copy(str(text))
        return "Copied to clipboard."
    except Exception as e:
        return f"clipboard_write error: {e}"


FUNCS = {
    "get_time": get_time,
    "calculator": calculator,
    "unit_convert": unit_convert,
    "dictionary": dictionary,
    "system_info": system_info,
    "clipboard_read": clipboard_read,
    "clipboard_write": clipboard_write,
}


if __name__ == "__main__":
    print("== get_time ==")
    print(get_time())
    print(get_time("Asia/Kolkata"))
    print("\n== calculator ==")
    print(calculator("sqrt(2**8) + 10%3"))
    print(calculator("2 * (3 + 4)"))
    print("\n== unit_convert ==")
    print(unit_convert(5, "km", "mile"))
    print(unit_convert(100, "f", "c"))
    print(unit_convert(2, "gallon", "l"))
    print(unit_convert(1, "parsec", "m"))
    print("\n== dictionary ==")
    print(dictionary("serendipity")[:400])
    print("\n== system_info ==")
    print(system_info())
    print("\n== clipboard ==")
    print(clipboard_write("jarvis test"))
    print(clipboard_read())
