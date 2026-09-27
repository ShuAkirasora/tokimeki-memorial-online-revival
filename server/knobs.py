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
    load()               apply config/knobs.toml at startup
    save()               write the turned ones back into it (`/knob save`)
    render(values)       the file itself: every knob, commented out, with a label

⭐ The file is the way to run a server that differs from stock. It is TOML so
that it can carry the labels, and it holds only what differs: a line left
commented out is the factory value, and the factory value moves with the code
when it is revised -- a copy of it written into the file would not. Start one
with `python3 server/knobs.py init` and uncomment what you mean to change;
`python3 server/knobs.py check` says what it would do.

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
not to the literal behind it. A knob set both there and in the file takes the
environment's value, and the start says so: the variable is the narrower act
(one run, one shell), so it is the one that was meant.

⚠️ A knob whose comment carries `knobs:secret` is an operator's secret rather
than a game number (a salt, say). The file refuses it and `save` leaves it out:
it belongs in the environment only, where no copy of the tree can carry it.

Reached from the chat console as `/knob`; see chat.py.
"""
from __future__ import annotations

import ast
import importlib
import json
import os
import re
import sys
import textwrap
import tomllib
from pathlib import Path
from typing import Any, NamedTuple

MARK = "INVENTED"  # inventions:skip -- this line names the marker, it is not one
#: A line that carries the marker but is not a knob (a closing rule, a sentence
#: about something NOT being invented) opts out with this word on the same line.
SKIP = "inventions:skip"
#: A knob that is an operator's secret, not a number to share (see above).
SECRET = "knobs:secret"
SERVER = Path(__file__).resolve().parent
#: The knobs this server starts with. config/ is not tracked: what is in it is
#: this machine's choice, not the program's, and a pull never touches it.
CONFIG_PATH = SERVER.parent / "config" / "knobs.toml"
#: Where `/knob save` used to write before the file was a config file. It is no
#: longer read; finding one is reported, so that nothing in it is lost quietly.
LEGACY_PATH = SERVER.parent / "runtime" / "knobs.json"

#: `os.environ.get("TMO_X"` or `os.environ.get(SOME_NAME`, the name being a
#: module-level string constant in the same file (chat.CONSOLE_ENV).
_ENV = re.compile(r'os\.environ(?:\.get)?\(\s*(?:"([A-Z0-9_]+)"|([A-Z][A-Z0-9_]*)\b)')


class Knob(NamedTuple):
    module: str          # file stem, e.g. "clubbattle"
    name: str            # the constant's name
    line: int            # where the assignment is
    factory: str         # the RHS exactly as written in the source
    env: str | None      # TMO_* if the factory reads the environment
    summary: str         # the one line after the marker, if there is one
    secret: bool = False # carries SECRET: environment only, never in a file
    label: str = ""      # the summary's whole sentence, for the file

    @property
    def key(self) -> str:
        return f"{self.module}.{self.name}"


_catalogue: list[Knob] | None = None
#: key -> value, for the knobs turned since startup (or loaded from the file).
_turned: dict[str, Any] = {}


def _summary(comment_lines: list[str], limit: int | None = 110) -> str:
    """The one-line label written as `INVENTED — <label>` or `INVENTED: <label>`.

    Continued onto following comment lines up to the first full stop, the same
    way the marker is read for the ledger; if no such label exists the summary
    is empty and the chat listing shows the factory value alone. `limit` is for
    the chat line; the file takes the whole sentence (limit None).
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
            if re.search(r"[。.]\s*$", tag) or (limit and len(tag) > limit):
                break
            body = re.sub(r"^\s*#:?\s?", "", cont).strip()
            if not body or MARK in body or body.startswith(("⚠", "⭐", "⛔")):
                break
            tag = f"{tag} {body}"
        tag = re.sub(r"[─━=]{2,}.*$", "", tag)
        tag = re.sub(r"[*`⚠⭐⛔️️]+", "", tag)
        first = re.split(r"(?<=。)|(?<=\. )|(?<=；)", tag)[0]
        return " ".join(first.split())[:limit]
    return ""


def _scan_file(path: Path) -> list[Knob]:
    src = path.read_text(encoding="utf-8")
    lines = src.splitlines()
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []
    assigns: dict[int, tuple[str, ast.AST]] = {}
    strings: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name) \
                and isinstance(node.value, ast.Constant) \
                and isinstance(node.value.value, str):
            strings[node.targets[0].id] = node.value.value
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
        env = (m.group(1) or strings.get(m.group(2))) if m else None
        out.append(Knob(path.stem, name, j + 1, factory, env,
                        _summary(lines[k:j]),
                        any(SECRET in c for c in lines[k:j]),
                        _summary(lines[k:j], None)))
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


def env_value(knob: Knob) -> str | None:
    """What the knob's TMO_* variable says, when it says anything at all."""
    if not knob.env:
        return None
    return os.environ.get(knob.env, "").strip() or None


def stock_value(knob: Knob) -> Any:
    """The factory value as it ships: the RHS with its TMO_* variable unset.

    This, not factory_value, is what "differs from stock" is measured against,
    and what the file's commented-out lines show.
    """
    if not knob.env or knob.env not in os.environ:
        return factory_value(knob)
    saved = os.environ.pop(knob.env)
    try:
        return factory_value(knob)
    finally:
        os.environ[knob.env] = saved


def _plain(value: Any) -> Any:
    """Tuples as lists, all the way down, so that a curve read back out of the
    file compares equal to the one written in the source."""
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return value


def is_stock(knob: Knob, value: Any) -> bool:
    return _plain(value) == _plain(stock_value(knob))


def coerce(knob: Knob, value: Any) -> Any:
    """A value already read -- off the console, or out of the file -- in the
    type the knob already has."""
    old = current(knob)
    if isinstance(old, bool):
        if isinstance(value, bool):
            return value
        raise ValueError(f"{knob.key} is on/off (true/false)")
    if old is None or isinstance(old, (list, tuple)):
        # A ruler whose factory value is None may go back to None; a curve
        # that was born a tuple may not, since its readers index into it.
        if value is None:
            if old is None or knob.factory.strip() == "None":
                return None
            raise ValueError(f"{knob.key} takes a list, e.g. [1, 2, 3]")
        if isinstance(value, (list, tuple)):
            if not isinstance(old, tuple):
                return list(value)
            # A curve of rows keeps its rows as tuples, as the source wrote them.
            rows = bool(old) and isinstance(old[0], tuple)
            return tuple(tuple(v) if rows and isinstance(v, list) else v
                         for v in value)
        raise ValueError(f"{knob.key} takes a list, e.g. [1, 2, 3]")
    if isinstance(old, float):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{knob.key} is a number")
        return float(value)
    if isinstance(old, int):
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{knob.key} is a whole number")
        return int(value)
    if isinstance(old, str):
        if isinstance(value, str):
            return value
        raise ValueError(f"{knob.key} is a word, in quotes in the file")
    raise ValueError(f"{knob.key} has a type this console cannot set ({type(old).__name__})")


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
    if (old is None or isinstance(old, (list, tuple))) \
            and low in ("none", "off", "clear"):
        return coerce(knob, None)
    try:
        value = ast.literal_eval(word)
    except (ValueError, SyntaxError):
        # A knob that holds a word takes it unquoted: `/knob CLASS_ASSIGNMENT
        # balanced` is what somebody types, and refusing it for want of quotes
        # would be this console's own invention.
        if isinstance(old, str):
            return word
        raise ValueError(f"{knob.key} takes a literal, e.g. 3 or 0.5")
    if isinstance(old, str) and not isinstance(value, str):
        value = str(value)
    return coerce(knob, value)


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


def _toml(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(int(value))
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_toml(v) for v in value) + "]"
    raise ValueError(f"no TOML for {type(value).__name__}")


def _assignment(name: str, value: Any, prefix: str) -> list[str]:
    """`NAME = value`, one line or -- for a long curve -- one row a line."""
    text = _toml(value)
    if len(text) <= 88 or not isinstance(value, (list, tuple)):
        return [f"{prefix}{name} = {text}"]
    return ([f"{prefix}{name} = ["]
            + [f"{prefix}    {_toml(v)}," for v in value]
            + [f"{prefix}]"])


# (The marker is spelled through MARK below so that this text is not itself
# read as one.)
HEADER = f"""\
# The invented numbers this server starts with.
#
# Every constant in server/ marked {MARK} is listed here, one to a paragraph:
# a label, the factory value, and the line that sets it. A line left commented
# out IS the factory value -- and it keeps following the code when a later
# version revises that value. Uncomment only what this server should do
# differently, and leave the rest alone.
#
# A TMO_* variable named next to a knob sets the same thing from the
# environment, and wins if both are set (the start says so). Knobs marked
# "environment only" are an operator's secret and are refused here.
#
# `/knob save` on the console rewrites this file: labels come back, anything
# else written by hand does not. `python3 server/knobs.py check` reads it
# without starting a server.
"""


def render(values: dict[str, Any] | None = None) -> str:
    """The whole file: `values` (key -> value) uncommented, everything else as
    its factory value, commented out."""
    values = values or {}
    out = [HEADER]
    module = None
    for knob in catalogue():
        if knob.module != module:
            module = knob.module
            out += ["", f"[{module}]"]
        out.append("")
        out += [f"# {row}" for row in textwrap.wrap(knob.label, 76)]
        stock = stock_value(knob)
        env = f"; also ${knob.env}" if knob.env else ""
        if knob.secret:
            out.append(f"# {knob.name}: environment only (${knob.env}) -- "
                       f"an operator's secret, not a number to share.")
            continue
        if stock is None:
            out.append(f"# {knob.name}: off by default; a list turns it on, "
                       f"e.g. [1, 2, 3]{env}")
        elif knob.key in values:
            out.append(f"# factory: {_toml(stock)}{env}")
        elif env:
            out.append(f"# {env[2:]}")
        if knob.key in values:
            out += _assignment(knob.name, values[knob.key], "")
        elif stock is not None:
            out += _assignment(knob.name, stock, "# ")
    return "\n".join(out) + "\n"


def differing() -> dict[str, Any]:
    """The turned knobs that are not stock, secrets left out."""
    out = {}
    for key, value in _turned.items():
        knob = find(key)
        if not knob.secret and not is_stock(knob, value):
            out[knob.key] = value
    return out


def save(path: Path = CONFIG_PATH) -> int:
    """Write the file: every knob, the ones that differ from stock uncommented.

    Knobs turned back to their factory value are left commented out rather
    than written down, for the reason the header gives.
    """
    values = differing()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(values), encoding="utf-8")
    return len(values)


def _flatten(data: dict, prefix: str = ""):
    for key, value in data.items():
        if isinstance(value, dict):
            yield from _flatten(value, f"{prefix}{key}.")
        else:
            yield f"{prefix}{key}", value


def read(path: Path = CONFIG_PATH) -> tuple[list[tuple[Knob, Any]], list[str]]:
    """What the file asks for, checked, and what is wrong with it.

    Returns (knob, value) for every line that will be applied, and one note per
    line that will not be or that deserves a look. Nothing is changed.
    """
    notes: list[str] = []
    if LEGACY_PATH.exists():
        notes.append(f"⚠️ {LEGACY_PATH.name} in runtime/ is no longer read; "
                     f"move what is in it to {path.parent.name}/{path.name}")
    if not path.exists():
        return [], notes
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [], notes + [f"⚠️ {path.name} unreadable ({exc}); ignored as a whole"]
    wanted: list[tuple[Knob, Any]] = []
    for key, value in _flatten(data):
        try:
            knob = find(key)
            value = coerce(knob, value)
        except (KeyError, ValueError) as exc:
            notes.append(f"⚠️ {str(exc).strip(chr(39))}; skipped")
            continue
        if knob.secret:
            notes.append(f"⚠️ {knob.key} is environment only ({knob.env}); "
                         f"skipped, and best taken out of the file")
            continue
        env = env_value(knob)
        if env is not None:
            notes.append(f"⚠️ {knob.key} is set twice: {knob.env}={env} and "
                         f"{path.name} {_toml(value)}; the environment wins")
            continue
        if is_stock(knob, value):
            notes.append(f"{knob.key} = {show(value)} is the factory value; the "
                         f"line pins it if a later version revises it")
        wanted.append((knob, value))
    return wanted, notes


def load(path: Path = CONFIG_PATH) -> list[tuple[Knob, Any, Any]]:
    """Apply config/knobs.toml, if there is one. Called once at startup.

    A key the catalogue no longer has, or a value of the wrong type, is
    reported and skipped rather than raised: a stale file must not keep the
    server from starting.
    """
    wanted, notes = read(path)
    for note in notes:
        print(f"[knobs] {note}")
    applied = []
    for knob, value in wanted:
        old = current(knob)
        setattr(_module(knob), knob.name, value)
        _turned[knob.key] = value
        applied.append((knob, old, value))
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


def _main(argv: list[str]) -> int:
    name = f"{CONFIG_PATH.parent.name}/{CONFIG_PATH.name}"
    usage = ("usage: python3 server/knobs.py init       "
             f"# write {name}: every knob, commented out\n"
             "       python3 server/knobs.py template   # the same, to stdout\n"
             f"       python3 server/knobs.py check      # what {name} would change")
    if argv == ["template"]:
        sys.stdout.write(render())
        return 0
    if argv == ["init"]:
        # Written here rather than through a shell redirect: Windows PowerShell
        # 5.1 writes `>` as UTF-16, which no TOML reader takes.
        if CONFIG_PATH.exists():
            print(f"{name} is already there; left alone "
                  f"(`template` prints a fresh one)", file=sys.stderr)
            return 1
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(render(), encoding="utf-8")
        print(f"wrote {name}: {len(catalogue())} knobs, all at their factory value")
        return 0
    if argv == ["check"]:
        wanted, notes = read()
        for note in notes:
            print(note)
        if not CONFIG_PATH.exists():
            print(f"no {CONFIG_PATH.parent.name}/{CONFIG_PATH.name}: every knob at its factory value")
        for knob, value in wanted:
            print(f"{knob.key} = {show(value)}  (factory {show(stock_value(knob))})")
        return 1 if any(n.startswith("⚠️") for n in notes) else 0
    print(usage, file=sys.stderr)
    return 2


if __name__ == "__main__":
    # Run as a script this file is `__main__`, and the modules it imports to
    # read their constants would import a second copy of it as `knobs`; hand
    # them this one instead.
    sys.modules.setdefault("knobs", sys.modules[__name__])
    raise SystemExit(_main(sys.argv[1:]))
