#!/usr/bin/env python3
"""
JARVIS one-time setup. Run this on YOUR machine:

    python setup_jarvis.py

It asks for your API key (typed locally, hidden as you type),
writes it into the .env file next to jarvis.py, and installs
the one dependency. The key never leaves your computer.
"""
import getpass
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

print("=== JARVIS setup ===\n")
print("Paste your API key below. It stays on THIS machine only,")
print("saved into the .env file next to jarvis.py.\n")

api_key = getpass.getpass("API key: ").strip()
if not api_key:
    print("No key entered. Aborting.")
    sys.exit(1)

print("\nWhich provider is the key for?")
print("  1) OpenRouter  (https://openrouter.ai)")
print("  2) OpenAI      (https://platform.openai.com)")
print("  3) Meta        (https://dev.meta.ai)")
print("  4) Custom")
choice = (input("Choose [1-4] (default 1): ").strip() or "1")

presets = {
    "1": ("https://openrouter.ai/api/v1", "anthropic/claude-sonnet-4"),
    "2": ("https://api.openai.com/v1", "gpt-4o-mini"),
    "3": ("https://api.meta.ai/v1", "muse-spark-1.1"),
}
if choice in presets:
    base_url, model = presets[choice]
    custom_model = input(f"Model [{model}]: ").strip()
    if custom_model:
        model = custom_model
else:
    base_url = input("Base URL (no trailing slash): ").strip()
    model = input("Model name: ").strip()

(ROOT / ".env").write_text(
    f"JARVIS_API_KEY={api_key}\n"
    f"JARVIS_BASE_URL={base_url}\n"
    f"JARVIS_MODEL={model}\n",
    encoding="utf-8",
)
print("\nWrote .env")

print("Installing dependencies...")
r = subprocess.run([sys.executable, "-m", "pip", "install", "-r",
                    str(ROOT / "requirements.txt")])
if r.returncode != 0:
    print("pip install had issues — try running it manually:")
    print("  pip install -r requirements.txt")
    sys.exit(1)

print("\nDone! Start JARVIS with:  python jarvis.py")
