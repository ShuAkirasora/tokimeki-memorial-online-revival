"""The invented numbers, as one set of knobs that can be turned while the server runs.

Every module-level constant in `server/` that carries an `INVENTED` marker is a
number this server made up -- a damage scale, a drop chance, how long a question
stays open. None of them came off the wire or out of a game file, so none of
them is fixed by anything but taste, and the manual's own rule for the rest of
the numbers (restored means untouchable) does not bind them. This module is
where they are found, read, changed and remembered:

    catalogue()          every invented constant, by scanning the source once
    current(knob)        its value right now, live in the module that owns it
    set_value(key, text) turn one, in place, without a restart
    reset(key)           back to the factory value (the RHS as written)
    save() / load()      keep the turned ones in runtime/knobs.json across restarts

⭐ The catalogue is read off the source, not written by hand. The rule is the
same one the `INVENTED` marker has always followed: the marker sits in a comment
directly above a module-level assignment, with nothing but comment lines in
between. A number without the marker is not a knob and cannot be turned from
here -- deliberately, since a restored number turned by hand quietly becomes an
invention nobody wrote down.

⭐ Turning a knob is `setattr` on the owning module. Every user of these
constants reads them as module globals at call time (none is captured into a
default argument or copied at import), so a change is seen by the next call.
The type is kept: an int stays an int, a float a float, a bool a bool; a knob
whose factory value is None (a measuring ruler) accepts a list or None.

⚠️ Env-variable knobs (`TMO_*`) keep working as they were: the factory value of
such a constant is whatever the environment said at import time, and `reset`
re-evaluates the same expression, so it comes back to the environment's value,
not to the literal behind it.

Reached from the chat console as `/knob`; see chat.py.
"""
from __future__ import annotations

import ast
import importlib
import json
import re
import sys
from pathlib import Path
from typing import Any, NamedTuple

MARK = "INVENTED"  # inventions:skip -- this line names the marker, it is not one
#: A line that carries the marker but is not a knob (a closing rule, a sentence
#: about something NOT being invented) opts out with this word on the same line.
SKIP = "inventions:skip"
SERVER = Path(__file__).resolve().parent
#: Where the turned knobs are kept between restarts. runtime/ is not tracked.
SAVE_PATH = SERVER.parent / "runtime" / "knobs.json"

_ENV = re.compile(r'os\.environ(?:\.get)?\(\s*"([A-Z0-9_]+)"')


class Knob(NamedTuple):
    module: str          # file stem, e.g. "clubbattle"
    name: str            # the constant's name
    line: int            # where the assignment is
    factory: str         # the RHS exactly as written in the source
    env: str | None      # TMO_* if the factory reads the environment
    summary: str         # the one line after the marker, if there is one

    @property
    def key(self) -> str:
        return f"{self.module}.{self.name}"


_catalogue: list[Knob] | None = None
#: key -> value, for the knobs turned since startup (or loaded from the file).
_turned: dict[str, Any] = {}


def _summary(comment_lines: list[str]) -> str:
    """The one-line label written as `INVENTED — <label>` or `INVENTED: <label>`.

    Continued onto following comment lines up to the first full stop, the same
    way the marker is read for the ledger; if no such label exists the summary
    is empty and the chat listing shows the factory value alone.
    """
    for n, raw in enumerate(comment_lines):
        if MARK not in raw:
            continue
        after = raw.split(MARK, 1)[1]
        m = re.match(r"\s*[—:：]\s*(\S.*)$", after)
        if not m:
            continue
        tag = m.group(1)
        for cont in comment_lines[n + 1:]:
            if re.search(r"[。.]\s*$", tag) or len(tag) > 110:
                break
            body = re.sub(r"^\s*#:?\s?", "", cont).strip()
            if not body or MARK in body or body.startswith(("⚠", "⭐", "⛔")):
                break
            tag = f"{tag} {body}"
        tag = re.sub(r"[─━=]{2,}.*$", "", tag)
        tag = re.sub(r"[*`⚠⭐⛔️️]+", "", tag)
        first = re.split(r"(?<=。)|(?<=\. )|(?<=；)", tag)[0]
        return " ".join(first.split())[:110]
    return ""


def _scan_file(path: Path) -> list[Knob]:
    src = path.read_text(encoding="utf-8")
    lines = src.splitlines()
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []
    assigns: dict[int, tuple[str, ast.AST]] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name):
            assigns[node.lineno] = (node.targets[0].id, node.value)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) \
                and node.value is not None:
            assigns[node.lineno] = (node.target.id, node.value)
    out: list[Knob] = []
    seen: set[int] = set()
    for i, line in enumerate(lines):
        if MARK not in line or SKIP in line:
            continue
        # Only comment lines may sit between the marker and the assignment. A
        # blank line ends the association: a paragraph about "every knob below"
        # must not attach itself to the first (possibly restored) constant after
        # the gap.
        j = i + 1
        while j < len(lines) and lines[j].lstrip().startswith("#"):
            j += 1
        if (j + 1) not in assigns or (j + 1) in seen:
            continue
        seen.add(j + 1)
        name, value = assigns[j + 1]
        k = i
        while k > 0 and lines[k - 1].lstrip().startswith("#"):
            k -= 1
        factory = ast.get_source_segment(src, value) or "?"
        m = _ENV.search(factory)
        out.append(Knob(path.stem, name, j + 1, factory, m.group(1) if m else None,
                        _summary(lines[k:j])))
    return out


def catalogue(refresh: bool = False) -> list[Knob]:
    """Every invented constant in `server/`, in file order. Scanned once."""
    global _catalogue
    if _catalogue is None or refresh:
        _catalogue = [k for p in sorted(SERVER.glob("*.py")) for k in _scan_file(p)]
    return _catalogue


def find(key: str) -> Knob:
    """`module.NAME`, or a bare NAME when only one module has it."""
    knobs = catalogue()
    if "." in key:
        hits = [k for k in knobs if k.key.lower() == key.lower()]
    else:
        hits = [k for k in knobs if k.name.lower() == key.lower()]
    if not hits:
        raise KeyError(f"no such knob: {key}")
    if len(hits) > 1:
        raise KeyError(f"{key} is in {len(hits)} modules: "
                       + " ".join(k.key for k in hits))
    return hits[0]


def _module(knob: Knob):
    mod = sys.modules.get(knob.module)
    if mod is None:
        mod = importlib.import_module(knob.module)
    return mod


def current(knob: Knob) -> Any:
    return getattr(_module(knob), knob.name)


def factory_value(knob: Knob) -> Any:
    """The RHS re-evaluated in the owning module's own namespace.

    That is the same expression the import ran, so an `os.environ.get(...)`
    factory comes back to what the environment says now, and a tuple literal
    comes back to the literal.
    """
    mod = _module(knob)
    return eval(compile(knob.factory, f"<knob {knob.key}>", "eval"), vars(mod))  # noqa: S307


def parse(knob: Knob, text: str) -> Any:
    """Read a value typed on the console, in the type the knob already has."""
    old = current(knob)
    word = text.strip()
    low = word.lower()
    if isinstance(old, bool):
        if low in ("on", "true", "1", "yes"):
            return True
        if low in ("off", "false", "0", "no"):
            return False
        raise ValueError(f"{knob.key} is on/off")
    if old is None or isinstance(old, (list, tuple)):
        # A ruler whose factory value is None may go back to None; a curve
        # that was born a tuple may not, since its readers index into it.
        nullable = old is None or knob.factory.strip() == "None"
        value = None if low in ("none", "off", "clear") else ast.literal_eval(word)
        if value is None:
            if nullable:
                return None
            raise ValueError(f"{knob.key} takes a list, e.g. [1, 2, 3]")
        if isinstance(value, (list, tuple)):
            return tuple(value) if isinstance(old, tuple) else list(value)
        raise ValueError(f"{knob.key} takes a list, e.g. [1, 2, 3]")
    value = ast.literal_eval(word)
    if isinstance(old, float):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{knob.key} is a number")
        return float(value)
    if isinstance(old, int):
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{knob.key} is a whole number")
        return int(value)
    if isinstance(old, str):
        return str(value)
    raise ValueError(f"{knob.key} has a type this console cannot set ({type(old).__name__})")


def set_value(key: str, text: str) -> tuple[Knob, Any, Any]:
    """Turn one knob. Returns (knob, old, new)."""
    knob = find(key)
    old = current(knob)
    new = parse(knob, text)
    setattr(_module(knob), knob.name, new)
    _turned[knob.key] = new
    return knob, old, new


def reset(key: str | None = None) -> list[tuple[Knob, Any, Any]]:
    """Back to the factory value -- one knob, or every turned one when key is None."""
    keys = [key] if key else list(_turned)
    out = []
    for k in keys:
        knob = find(k)
        old = current(knob)
        new = factory_value(knob)
        setattr(_module(knob), knob.name, new)
        _turned.pop(knob.key, None)
        out.append((knob, old, new))
    return out


def turned() -> dict[str, Any]:
    return dict(_turned)


def save(path: Path = SAVE_PATH) -> int:
    """Write the turned knobs down. An empty set removes the file."""
    if not _turned:
        if path.exists():
            path.unlink()
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_turned, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    return len(_turned)


def load(path: Path = SAVE_PATH) -> list[tuple[Knob, Any, Any]]:
    """Apply runtime/knobs.json, if there is one. Called once at startup.

    A key the catalogue no longer has, or a value of the wrong type, is
    reported and skipped rather than raised: a stale file must not keep the
    server from starting.
    """
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"[knobs] ⚠️ {path.name} unreadable ({exc}); ignored")
        return []
    applied = []
    for key, value in data.items():
        try:
            knob = find(key)
            old = current(knob)
            new = parse(knob, json.dumps(value))
        except (KeyError, ValueError, SyntaxError) as exc:
            print(f"[knobs] ⚠️ {key}: {exc}; skipped")
            continue
        setattr(_module(knob), knob.name, new)
        _turned[knob.key] = new
        applied.append((knob, old, new))
    return applied


def show(value: Any) -> str:
    text = repr(value)
    return text if len(text) <= 40 else text[:37] + "…"


def describe(knob: Knob) -> str:
    """One line for the chat: key = now (factory …) [TMO_…]."""
    now = current(knob)
    mark = "*" if knob.key in _turned else " "
    tail = f"  [{knob.env}]" if knob.env else ""
    return f"{mark}{knob.key} = {show(now)}  (factory {show(knob.factory)}){tail}"
