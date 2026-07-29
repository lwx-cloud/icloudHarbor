"""TTY password input with visible asterisk masking."""

from __future__ import annotations

import getpass
import importlib
import os
import sys
from collections.abc import Callable
from typing import Any


def masked_password_prompt(prompt: str) -> str:
    """Read a password while rendering one ``*`` per entered character."""

    if not sys.stdin.isatty() or not sys.stdout.isatty():
        return getpass.getpass(prompt)

    sys.stdout.write(prompt)
    sys.stdout.flush()
    if os.name == "nt":
        import msvcrt

        return _read_masked(msvcrt.getwch, _write)

    termios: Any = importlib.import_module("termios")

    descriptor = sys.stdin.fileno()
    original = termios.tcgetattr(descriptor)
    changed = termios.tcgetattr(descriptor)
    changed[3] &= ~(termios.ECHO | termios.ICANON)
    try:
        termios.tcsetattr(descriptor, termios.TCSADRAIN, changed)
        return _read_masked(lambda: sys.stdin.read(1), _write)
    finally:
        termios.tcsetattr(descriptor, termios.TCSADRAIN, original)


def _write(value: str) -> None:
    sys.stdout.write(value)
    sys.stdout.flush()


def _read_masked(read_character: Callable[[], str], write: Callable[[str], None]) -> str:
    characters: list[str] = []
    try:
        while True:
            character = read_character()
            if character in {"\r", "\n"}:
                write("\n")
                return "".join(characters)
            if character == "\x03":
                raise KeyboardInterrupt
            if character == "\x04":
                if not characters:
                    raise EOFError
                continue
            if character in {"\b", "\x7f"}:
                if characters:
                    characters.pop()
                    write("\b \b")
                continue
            if character and character.isprintable():
                characters.append(character)
                write("*")
    except (EOFError, KeyboardInterrupt):
        write("\n")
        raise
