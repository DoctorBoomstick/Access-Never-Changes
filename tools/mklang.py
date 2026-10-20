#!/usr/bin/env python3
"""Make lang/english.ini from the code.

    python tools/mklang.py           write lang/english.ini
    python tools/mklang.py --check   say whether it is up to date, change nothing

Every `tr("section.key", "English", ...)` in the mod, and every entry of a
`script_words({...})` table, becomes a line of the file, grouped by section.
The English lives in the code, beside the thing that says it; this file is the
copy translators start from, and tests/test_locale.py fails when the two
disagree, so it cannot quietly fall behind.
"""

from __future__ import annotations

import ast
import os
import re
import sys
from typing import Dict, List, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from fallout2_access.i18n import slug  # noqa: E402

OUT = os.path.join(ROOT, "lang", "english.ini")
SOURCES = [os.path.join(ROOT, "fallout2_access"), os.path.join(ROOT, "f2access.py")]

KEY = re.compile(r"^[a-z0-9_]+\.[a-z0-9_]+$")

# One line per paragraph: translators read this in Notepad, often with a screen
# reader, where a line broken mid-sentence is read as two.
HEADER = """\
; Access Never Changes: the mod's own words, in English.
; This file is made from the code by tools/mklang.py. Do not edit this copy by hand; edit the code.
; To translate: copy this file and name the copy after the language the way the game's fallout2.cfg spells it, such as german.ini, french.ini or polish.ini. Then change the words after each "=", and save the file as UTF-8.
; Keep the part before "=" exactly as it is. It is how the mod finds the line.
; Keep every word in braces, like {points}, spelt exactly as it is. The mod fills those in. You may move them anywhere in the line.
; A line you leave out, or leave empty, is said in English, so a translation can be partial.
; Only the mod's own words are here. Everything the game says, such as items, dialogue and skills, already comes from the game in the game's language.
"""


def _files() -> List[str]:
    out = []
    for src in SOURCES:
        if os.path.isfile(src):
            out.append(src)
            continue
        for folder, _dirs, names in os.walk(src):
            out += [os.path.join(folder, n) for n in names if n.endswith(".py")]
    return sorted(out)


def _name(func) -> str:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def collect() -> Tuple[Dict[str, str], List[str]]:
    """key -> English, and every problem found on the way."""
    found: Dict[str, str] = {}
    where: Dict[str, str] = {}
    problems: List[str] = []

    def add(key, english, at):
        if not KEY.match(key):
            problems.append("{}: bad key {!r}".format(at, key))
            return
        if english != english.strip():
            problems.append("{}: {} starts or ends with a space, which an ini "
                            "file cannot keep".format(at, key))
        if "\n" in english:
            problems.append("{}: {} has a line break".format(at, key))
        if key in found and found[key] != english:
            problems.append("{}: {} is also {!r} at {}".format(
                at, key, found[key], where[key]))
            return
        found[key], where[key] = english, at

    for path in _files():
        with open(path, encoding="utf-8") as fh:
            tree = ast.parse(fh.read(), path)
        rel = os.path.relpath(path, ROOT)
        for node in ast.walk(tree):
            if (isinstance(node, ast.Assign) and len(node.targets) == 1
                    and isinstance(node.targets[0], ast.Name)
                    and node.targets[0].id == "TITLE"
                    and isinstance(node.value, ast.Constant) and node.value.value):
                # A screen's name for F1 -- see Watcher.help_title.
                add("screen." + slug(node.value.value), node.value.value,
                    "{}:{}".format(os.path.relpath(path, ROOT), node.lineno))
                continue
            if not isinstance(node, ast.Call):
                continue
            name = _name(node.func)
            at = "{}:{}".format(rel, node.lineno)
            if name == "tr":
                args = node.args
                if (len(args) >= 2 and isinstance(args[0], ast.Constant)
                        and isinstance(args[1], ast.Constant)
                        and isinstance(args[0].value, str)
                        and isinstance(args[1].value, str)):
                    add(args[0].value, args[1].value, at)
                elif rel != os.path.join("fallout2_access", "i18n.py"):
                    problems.append("{}: tr() needs a literal key and English".format(at))
            elif name == "Binding":
                # F1's tables: the keys and what they do, keyed by their own
                # English -- see i18n.tr_text and controls.help_text.
                for section, arg in zip(("keys", "help"), node.args[:2]):
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        add("{}.{}".format(section, slug(arg.value)), arg.value, at)
                    else:
                        problems.append("{}: Binding needs literal words".format(at))
            elif name == "script_words" and node.args and isinstance(node.args[0], ast.Dict):
                for k, v in zip(node.args[0].keys, node.args[0].values):
                    if isinstance(k, ast.Constant) and isinstance(v, ast.Constant):
                        add(k.value, v.value, at)
                    else:
                        problems.append("{}: script_words needs literals".format(at))
    return found, problems


def render(found: Dict[str, str]) -> str:
    sections: Dict[str, List[Tuple[str, str]]] = {}
    for key in sorted(found):
        section, name = key.split(".", 1)
        sections.setdefault(section, []).append((name, found[key]))
    out = [HEADER]
    for section in sorted(sections):
        out.append("\n[{}]\n".format(section))
        for name, english in sections[section]:
            out.append("{} = {}\n".format(name, english))
    return "".join(out)


def main(argv) -> int:
    found, problems = collect()
    for p in problems:
        print(p)
    if problems:
        return 1
    text = render(found)
    try:
        with open(OUT, encoding="utf-8") as fh:
            current = fh.read()
    except OSError:
        current = ""
    if "--check" in argv:
        if current != text:
            print("lang/english.ini is out of date: run tools/mklang.py")
            return 1
        print("lang/english.ini is up to date ({} lines)".format(len(found)))
        return 0
    with open(OUT, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    print("wrote {} lines to {}".format(len(found), os.path.relpath(OUT, ROOT)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
