"""Tool registry: combines schemas + functions from all tool modules.

Usage:
    from tools import build_registry
    TOOLS, execute = build_registry(memory)
    # TOOLS -> list of OpenAI-format schemas
    # execute(name, args) -> str
"""
import importlib
import config

_MODULES = [
    "tools.web_tools",
    "tools.system_tools",
    "tools.pc_tools",
    "tools.personal_tools",
]


def build_registry(memory=None):
    schemas: list = []
    funcs: dict = {}

    for mod_name in _MODULES:
        try:
            mod = importlib.import_module(mod_name)
        except ImportError as e:
            print(f"[tools] WARNING: could not import {mod_name}: {e}")
            continue
        # bind memory for personal_tools
        if memory is not None and hasattr(mod, "bind_memory"):
            try:
                mod.bind_memory(memory)
            except Exception as e:
                print(f"[tools] WARNING: bind_memory failed for {mod_name}: {e}")
        schemas.extend(getattr(mod, "SCHEMAS", []))
        funcs.update(getattr(mod, "FUNCS", {}))

    def execute(name: str, args: dict) -> str:
        fn = funcs.get(name)
        if fn is None:
            return f"Unknown tool: {name}"
        # confirmation gate for high-impact tools
        if name in config.CONFIRM_TOOLS and not config.AUTO_CONFIRM:
            return (f"CONFIRMATION REQUIRED: the assistant wants to run '{name}' "
                    f"with args {args}. Ask the user for explicit confirmation first, "
                    f"then call the tool again after they confirm.")
        try:
            result = fn(**args)
            return str(result)
        except TypeError as e:
            return f"Tool argument error for {name}: {e}"
        except Exception as e:
            return f"Tool {name} failed: {type(e).__name__}: {e}"

    return schemas, execute


def list_tool_names(memory=None) -> list:
    schemas, _ = build_registry(memory)
    return [s["function"]["name"] for s in schemas]
