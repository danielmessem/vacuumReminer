#!/usr/bin/env python3
"""Apply the staged cqyi87 PR1 files to a client.py checkout.

Usage:
    python apply_to_upstream.py /path/to/DeebotUniverse-client.py
"""

from __future__ import annotations

from pathlib import Path
import shutil
import sys

HERE = Path(__file__).resolve().parent

FILES = (
    "deebot_client/commands/json/y1.py",
    "deebot_client/messages/json/y1.py",
    "deebot_client/hardware/cqyi87.py",
    "tests/commands/json/test_y1.py",
    "tests/messages/json/test_y1.py",
    "tests/test_y1_hardware.py",
)


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    if old not in text:
        raise RuntimeError(f"Could not locate upstream anchor: {label}")
    return text.replace(old, new, 1)


def patch_commands_init(target: Path) -> None:
    path = target / "deebot_client/commands/json/__init__.py"
    text = path.read_text()
    import_line = "from .work_mode import GetWorkMode, SetWorkMode\n"
    y1_import = (
        "from .work_mode import GetWorkMode, SetWorkMode\n"
        "from .y1 import (\n"
        "    Y1Charge,\n"
        "    Y1CleanArea,\n"
        "    Y1FieldQuery,\n"
        "    Y1PauseClean,\n"
        "    Y1ResumeClean,\n"
        "    Y1StartClean,\n"
        ")\n"
    )
    text = replace_once(text, import_line, y1_import, "JSON command imports")

    registry_anchor = "    GetWorkMode,\n    SetWorkMode\n]"
    registry_block = (
        "    GetWorkMode,\n"
        "    SetWorkMode,\n\n"
        "    Y1StartClean,\n"
        "    Y1CleanArea,\n"
        "    Y1PauseClean,\n"
        "    Y1ResumeClean,\n"
        "    Y1Charge,\n"
        "    Y1FieldQuery,\n"
        "]"
    )
    text = replace_once(text, registry_anchor, registry_block, "JSON command registry")
    path.write_text(text)


def patch_messages_init(target: Path) -> None:
    path = target / "deebot_client/messages/json/__init__.py"
    text = path.read_text()
    import_line = "from .work_state import OnWorkState\n"
    text = replace_once(
        text,
        import_line,
        import_line + "from .y1 import OnY1State\n",
        "JSON message imports",
    )

    registry_anchor = "    OnWorkState,\n]"
    text = replace_once(
        text,
        registry_anchor,
        "    OnWorkState,\n\n    OnY1State,\n]",
        "JSON message registry",
    )
    path.write_text(text)


def apply(target: Path) -> None:
    if not (target / "deebot_client").is_dir():
        raise RuntimeError(f"Not a client.py checkout: {target}")

    for relative in FILES:
        source = HERE / relative
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)

    patch_commands_init(target)
    patch_messages_init(target)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: apply_to_upstream.py /path/to/client.py")
    destination = Path(sys.argv[1]).expanduser().resolve()
    apply(destination)
    print(f"Applied cqyi87 PR1 staging files to {destination}")
