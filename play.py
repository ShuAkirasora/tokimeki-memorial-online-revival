#!/usr/bin/env python3
"""Everything between an installed game and its login screen, in one run.

The three steps this performs are the three the README describes by hand, in
the same order and with the same effects: the two hostnames into your `hosts`
file, the four bytes into your copy of `tmo.exe`, and `BootFirst.exe` started.
Nothing here can do anything the README cannot talk you through; what it saves
is the part where each of those has its own way of going wrong quietly.

  Why this exists at all
  ----------------------
  ⭐ The server is one command and the client is a page and a half, and that is
  the wrong way round for what actually keeps people out. Someone who has
  already found this project, obtained the disc and installed a 2006 game on a
  current Windows is plainly willing; what stops them next is a ritual with
  three separate silent failures in it -- a hosts file edited on the wrong
  machine, an executable patched in the wrong copy, a game started by the wrong
  program -- and each of them looks the same from the player's chair, which is
  a client that sits there and does nothing.

  So this is not automation for its own sake. It is the one place where every
  one of those can be *checked* rather than assumed, and told apart when it is
  wrong.

  One elevation, because the game needs it anyway
  -----------------------------------------------
  ⚠️ On Windows the game itself has to be started as administrator -- not a
  choice this project makes, and the README explains whose it is -- and the
  hosts file has to be written by somebody allowed to write it. Those are the
  same privilege, so `Play.cmd` asks for it once, at the start, and everything
  below happens inside it. One prompt, at a moment when it is obvious what is
  being asked for and why.

  On macOS and Linux nothing needs privilege except `/etc/hosts`, so only that
  one step is run through `sudo`, and the game is not started as root.

  Nothing here is unrecoverable
  -----------------------------
  `--revert` undoes both halves: the hosts file goes back, and so do the four
  bytes -- which, since they are the only bytes ever written, leaves `tmo.exe`
  identical to the copy you installed. Before either is first written a copy is
  kept beside it, and an existing copy is never overwritten. Lines already in
  your hosts file are not deleted; a line that points one of these two names
  somewhere else is commented out with a marker saying so, and `--revert` puts
  it back as it was.

  `-n` says what it would do to both and writes neither.

  What it does not do
  -------------------
  It does not start the server. That half is genuinely one command, it may well
  be on a different machine, and starting it from here would start it with
  administrator rights it has no use for. What this does instead is knock on
  the ports before starting the game, so "the server is not running" arrives as
  a sentence rather than as a client that hangs.
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import socket
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

try:
    import set_auth_address as auth
except ImportError:  # pragma: no cover - only if the file was moved away
    print(
        "set_auth_address.py has to be in the same folder as this script;\n"
        "it is the half that writes the four bytes.",
        file=sys.stderr,
    )
    raise SystemExit(1)

WINDOWS = os.name == "nt"

#: Remembered between runs so that the second time is a double-click and
#: nothing else. Deleting it costs one round of questions.
CONFIG = HERE / "runtime" / "launcher.json"

#: The two names your resolver has to answer for. They come from the patcher so
#: that there is one list of them rather than two that can drift apart.
NAMES = tuple(name.lower() for name in auth.CLIENT_NAMES)

#: What the game runs. BootFirst starts the updater, which starts the game --
#: running either of the other two directly fails in its own way, and the
#: README says how.
LAUNCHER_EXE = "BootFirst.exe"
GAME_EXE = "tmo.exe"

BEGIN = "# >>> tokimeki-memorial-online-revival >>>"
END = "# <<< tokimeki-memorial-online-revival <<<"
#: Prefix on a line of yours that pointed one of the two names elsewhere. The
#: whole original line follows it verbatim, which is what makes --revert exact.
REPLACED = "# tokimeki-memorial-online-revival replaced this line: "

#: Knocked on before the game starts. Not the whole port table -- these four
#: are the ones the client reaches in order, so the first closed one names the
#: step that is about to fail.
PREFLIGHT = (
    (12000, "the update check"),
    (35573, "the login-server lookup"),
    (25573, "login"),
    (443, "account authentication"),
)


# --------------------------------------------------------------- small things


def say(text: str = "") -> None:
    print(text, flush=True)


def is_privileged() -> bool:
    if WINDOWS:
        import ctypes

        try:
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except OSError:
            return False
    return os.geteuid() == 0


def hosts_file() -> Path:
    if WINDOWS:
        root = os.environ.get("SystemRoot", r"C:\Windows")
        return Path(root) / "System32" / "drivers" / "etc" / "hosts"
    return Path("/etc/hosts")


def ask(question: str, default: str = "") -> str:
    """A prompt that tolerates having no keyboard.

    Double-clicked, there is always a console. Run from a scheduler or a pipe
    there is not, and an EOF there should pick the default rather than end in a
    traceback about stdin.
    """
    suffix = f" [{default}]" if default else ""
    try:
        answer = input(f"{question}{suffix}: ").strip()
    except (EOFError, KeyboardInterrupt):
        say()
        return default
    return answer or default


def load_config() -> dict:
    try:
        return json.loads(CONFIG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_config(**values) -> None:
    kept = load_config()
    kept.update({k: v for k, v in values.items() if v})
    try:
        CONFIG.parent.mkdir(parents=True, exist_ok=True)
        CONFIG.write_text(json.dumps(kept, indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        # Not worth stopping for: it only means the next run asks again.
        say(f"  (could not remember these answers: {exc})")


# ------------------------------------------------------------- finding things


def looks_like_the_game(folder: Path) -> bool:
    return (folder / LAUNCHER_EXE).is_file() and (folder / GAME_EXE).is_file()


def guess_game_folders() -> list[Path]:
    """A short list of places the game plausibly is. Cheap, and never certain.

    Bounded on purpose, and the depths below are not uniform: four levels under
    a program-files directory is a handful of listings, while four levels under
    a drive root is most of the disk. Anything deeper or stranger than these is
    what the prompt is for -- a wrong guess here costs one question, and a slow
    one costs the double-click.
    """
    roots: list[tuple[Path, int]] = [(HERE, 0), (HERE.parent, 1)]
    home = Path.home()
    if WINDOWS:
        for var in ("ProgramFiles(x86)", "ProgramFiles"):
            value = os.environ.get(var)
            if value:
                roots.append((Path(value), 4))
        drive = os.environ.get("SystemDrive", "C:")
        roots += [(Path(drive + "\\"), 2), (Path(drive + "\\") / "Games", 3)]
    else:
        roots += [
            (home / "Library" / "Application Support" / "CrossOver" / "Bottles", 5),
            (home / ".wine" / "drive_c", 5),
            (home / ".local" / "share" / "wineprefixes", 6),
        ]

    found: list[Path] = []
    for root, depth in roots:
        if looks_like_the_game(root):
            found.append(root)
        if not root.is_dir():
            continue
        for level in range(1, depth + 1):
            pattern = "/".join(["*"] * level) + f"/{LAUNCHER_EXE}"
            try:
                for hit in root.glob(pattern):
                    if looks_like_the_game(hit.parent):
                        found.append(hit.parent)
            except OSError:
                continue
    # Ordered, deduplicated: the earliest root wins and the caller sees why.
    seen: list[Path] = []
    for folder in found:
        if folder not in seen:
            seen.append(folder)
    return seen


def resolve_game_folder(given: str | None, remembered: str | None) -> Path | None:
    for candidate in (given, remembered):
        if not candidate:
            continue
        folder = Path(candidate).expanduser()
        if looks_like_the_game(folder):
            return folder
        if candidate == given:
            say(f"  {folder} has no {LAUNCHER_EXE} and {GAME_EXE} in it")
            return None
        say(f"  the folder remembered from last time is gone: {folder}")

    guesses = guess_game_folders()
    if len(guesses) == 1:
        say(f"  found the game at {guesses[0]}")
        return guesses[0]
    if guesses:
        say("  more than one copy of the game is installed:")
        for n, folder in enumerate(guesses, 1):
            say(f"    {n}. {folder}")
        answer = ask("  which one", "1")
        if answer.isdigit() and 1 <= int(answer) <= len(guesses):
            return guesses[int(answer) - 1]

    say("  the game is not where this script knows to look.")
    say(f"  Give the folder that holds {LAUNCHER_EXE} -- on Windows you can drag")
    say("  it from Explorer into this window and press Enter.")
    typed = ask("  game folder")
    if not typed:
        return None
    folder = Path(typed.strip().strip('"').strip("'")).expanduser()
    if not looks_like_the_game(folder):
        say(f"  that folder has no {LAUNCHER_EXE} and {GAME_EXE} in it")
        return None
    return folder


# ---------------------------------------------------------------- the address


def resolve_server(given: str | None, remembered: str | None) -> str | None:
    chosen = given or remembered
    if not chosen:
        say("  Which machine runs the server?")
        say("    - the same one as the game (including the game under Wine): 127.0.0.1")
        say("    - a different machine from the game: that machine's")
        say("      local address, usually starting 192.168. or 10.")
        chosen = ask("  server address", "127.0.0.1")
    try:
        auth.parse_ipv4(chosen)
    except ValueError as exc:
        say(f"  {exc}")
        say("  It has to be an address rather than a name: the client's")
        say("  authentication step never performs a lookup.")
        return None
    return chosen


# ------------------------------------------------------------------ the hosts


def _hosts_text(path: Path) -> tuple[str, str]:
    raw = path.read_bytes().decode("utf-8", "surrogateescape")
    return raw, ("\r\n" if "\r\n" in raw else "\n")


def _write_hosts(path: Path, lines: list[str], newline: str) -> None:
    """Replace the hosts file, having kept a copy of it first.

    Written beside itself and renamed over, so an interrupted write leaves the
    old file rather than half of a new one -- this is a file the machine needs
    in order to resolve anything at all.
    """
    backup = path.with_name(path.name + ".tmo-revival.orig")
    if not backup.exists():
        backup.write_bytes(path.read_bytes())
        say(f"  kept a copy of the original as {backup.name}")
    body = newline.join(lines)
    if body and not body.endswith(newline):
        body += newline
    payload = body.encode("utf-8", "surrogateescape")
    temporary = path.with_name(path.name + ".tmo-revival.new")
    try:
        temporary.write_bytes(payload)
        os.replace(temporary, path)
    except OSError:
        # Some machines will not let anything be renamed over the hosts file.
        # Writing through it is the fallback, and the copy above is why that is
        # allowed to be the fallback.
        temporary.unlink(missing_ok=True)
        path.write_bytes(payload)


def plan_hosts(raw: str, target: str | None) -> tuple[list[str], list[str]]:
    """The hosts file as it should be, and a sentence for each change.

    `target` is the address the two names must reach, or None to take this
    script's entries back out again.
    """
    lines: list[str] = []
    notes: list[str] = []
    had_block = False
    inside = False
    for line in raw.splitlines():
        stripped = line.strip()
        if stripped == BEGIN:
            inside = True
            had_block = True
            continue
        if stripped == END:
            inside = False
            continue
        if inside:
            continue
        if line.startswith(REPLACED):
            original = line[len(REPLACED) :]
            if target is None:
                lines.append(original)
                notes.append(f"put back your own line: {original.strip()}")
            else:
                lines.append(line)
            continue
        lines.append(line)

    if target is None:
        if had_block:
            notes.append("took this script's two lines back out")
        return lines, notes

    covered: set[str] = set()
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        fields = stripped.split("#", 1)[0].split()
        if len(fields) < 2:
            continue
        address, names = fields[0], [name.lower() for name in fields[1:]]
        ours = [name for name in names if name in NAMES]
        if not ours:
            continue
        if address == target:
            covered.update(ours)
            continue
        lines[index] = REPLACED + line
        notes.append(f"commented out a line pointing {', '.join(ours)} at {address}")

    missing = [name for name in NAMES if name not in covered]
    if missing:
        lines += [BEGIN] + [f"{target}  {name}" for name in missing] + [END]
        notes.append(f"pointed {', '.join(missing)} at {target}")
    return lines, notes


def apply_hosts(target: str | None, dry_run: bool) -> bool:
    """Bring the hosts file into the wanted state. True if it is there now."""
    path = hosts_file()
    try:
        raw, newline = _hosts_text(path)
    except OSError as exc:
        say(f"  cannot read {path}: {exc}")
        return False

    lines, notes = plan_hosts(raw, target)
    # ⚠️ What decides is the file, not the list of notes. Planning strips this
    # script's own block and puts it back, so a run that changes nothing still
    # produces the note that says it added one; only the comparison knows the
    # difference between the first run and the tenth.
    if lines == raw.splitlines():
        say("  already right, nothing to change")
        return True
    for note in notes:
        say(f"  {note}")
    if dry_run:
        say("  dry run, nothing written")
        return True

    if not is_privileged():
        if WINDOWS:
            say("  this needs administrator rights; see the note at the end")
            return False
        return _sudo_hosts_step(target)

    try:
        _write_hosts(path, lines, newline)
    except OSError as exc:
        say(f"  cannot write {path}: {exc}")
        say("  Nothing was changed. The two lines to add by hand are:")
        for name in NAMES:
            say(f"      {target}  {name}")
        return False
    flush_dns()
    return True


def _sudo_hosts_step(target: str | None) -> bool:
    """Run this one step again as root, and nothing else as root.

    The game is started by the unprivileged half that called this, which is the
    point of splitting it out: a game started by sudo would write its files as
    root and the next ordinary run would not be able to read them.
    """
    step = ["--hosts-step", "clear" if target is None else target]
    command = ["sudo", sys.executable, str(Path(__file__).resolve()), *step]
    say(f"  {' '.join(shlex.quote(part) for part in command)}")
    try:
        return subprocess.run(command).returncode == 0
    except OSError as exc:
        say(f"  cannot run sudo: {exc}")
        return False


def flush_dns() -> None:
    """Forget the previous answer, so the check below is about the new one.

    Every one of these is the command the README tells you to run by hand when
    a name still resolves to yesterday's address. None of them is load-bearing:
    a failure here costs a stale line in the report, not a broken step.
    """
    if WINDOWS:
        commands = [["ipconfig", "/flushdns"]]
    elif sys.platform == "darwin":
        commands = [
            ["dscacheutil", "-flushcache"],
            ["killall", "-HUP", "mDNSResponder"],
        ]
    else:
        commands = [["resolvectl", "flush-caches"]]
    for command in commands:
        try:
            subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            pass


def report_names(expected: str | None) -> bool:
    """Where the two names lead now. This is the step proving itself."""
    everything_right = True
    for name in NAMES:
        try:
            answer: str | None = socket.gethostbyname(name)
        except OSError:
            answer = None
        verdict = ""
        if expected is not None:
            verdict = "  ok" if answer == expected else "  <- not your server"
            everything_right &= answer == expected
        say(f"    {name:26s} -> {answer or 'no answer':15s}{verdict}".rstrip())
    return everything_right


# ------------------------------------------------------------- the four bytes


def current_auth_address(exe: Path) -> str | None:
    try:
        data = exe.read_bytes()
    except OSError as exc:
        say(f"  cannot read {exe}: {exc}")
        return None
    try:
        return auth.read_address(data, auth.find_site(data))
    except LookupError as exc:
        say(f"  {exe.name}: {exc}")
        return None


def apply_auth_address(exe: Path, target: str | None, dry_run: bool) -> bool:
    """Hand the four bytes to the script that owns them.

    Called rather than reimplemented, and called only when something has to
    change. Everything that makes writing to somebody's executable defensible
    -- scanning for the instruction shape instead of trusting an offset,
    stopping when it is not found exactly once, the copy taken before the first
    write -- lives in that one file and is verified there.
    """
    current = current_auth_address(exe)
    if current is None:
        return False
    wanted = auth.ORIGINAL_ADDRESS if target is None else target
    if current == wanted:
        say(f"  already {current}, nothing to change")
        return True
    say(f"  {current} -> {wanted}")
    if dry_run:
        say("  dry run, nothing written")
        return True

    command = [sys.executable, str(HERE / "set_auth_address.py"), str(exe)]
    command += ["--revert"] if target is None else [target]
    command += ["--no-lookup"]
    try:
        done = subprocess.run(command, capture_output=True, text=True)
    except OSError as exc:
        say(f"  cannot run set_auth_address.py: {exc}")
        return False
    for line in (done.stdout + done.stderr).splitlines():
        say(f"  | {line}")
    return done.returncode == 0


# ----------------------------------------------------------------- the server


def knock(host: str) -> bool:
    """Which of the four ports answer. True if the game has somewhere to go."""
    answered = {}
    for port, what in PREFLIGHT:
        try:
            with socket.create_connection((host, port), timeout=1.5):
                answered[port] = True
        except OSError:
            answered[port] = False
        say(f"    {port:<6} {what:<28} {'answers' if answered[port] else 'silent'}")
    if all(answered.values()):
        return True
    if not any(answered.values()):
        say("  Nothing there at all. On the server's machine:")
        say("      python3 start_servers.py"
            + ("" if host.startswith("127.") else f" --advertise-ip {host}"))
        say("  and if it is already running, a firewall is in between.")
        return False
    if not answered[443]:
        say("  Authentication has no port. On Linux that is the privilege on")
        say("  ports below 1024; the server's log says [authhttp] skip :443.")
    else:
        say("  Some of it is there and some is not, which is usually a firewall")
        say("  with only part of the port list open.")
    return False


# ----------------------------------------------------------------- the launch


def start_game(folder: Path, launch_with: str | None) -> bool:
    boot = folder / LAUNCHER_EXE
    if WINDOWS:
        try:
            subprocess.Popen([str(boot)], cwd=str(folder))
        except OSError as exc:
            say(f"  cannot start {boot}: {exc}")
            return False
        say(f"  started {LAUNCHER_EXE} as administrator")
        return True

    if not launch_with:
        launch_with = "wine"
    parts = shlex.split(launch_with)
    command = (
        [part.replace("{}", str(boot)) for part in parts]
        if any("{}" in part for part in parts)
        else parts + [str(boot)]
    )
    try:
        subprocess.Popen(command, cwd=str(folder))
    except OSError as exc:
        say(f"  cannot start it with {parts[0]!r}: {exc}")
        say("  Give the command that runs Windows programs here, for instance")
        say('      --launch-with "wine"')
        say("  and start it yourself this once:")
        say(f"      {boot}")
        return False
    say(f"  started {' '.join(shlex.quote(part) for part in command)}")
    return True


# ------------------------------------------------------------------------ run


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Point your copy of the client at a server and start it.",
    )
    parser.add_argument("--server", help="address of the machine running the server")
    parser.add_argument("--game-dir", help=f"the folder holding {LAUNCHER_EXE}")
    parser.add_argument(
        "--launch-with",
        help="command that runs Windows programs, on macOS and Linux (default: wine)",
    )
    parser.add_argument(
        "--revert",
        action="store_true",
        help="put the hosts file and the four bytes back, and start nothing",
    )
    parser.add_argument(
        "--no-launch", action="store_true", help="set everything up but do not start the game"
    )
    parser.add_argument(
        "-n", "--dry-run", action="store_true", help="say what would change, write nothing"
    )
    parser.add_argument("--hosts-step", help=argparse.SUPPRESS)
    args = parser.parse_args()

    # The re-entry sudo uses. It does one thing and returns; see _sudo_hosts_step.
    if args.hosts_step:
        target = None if args.hosts_step == "clear" else args.hosts_step
        return 0 if apply_hosts(target, dry_run=False) else 1

    remembered = load_config()
    say("Tokimeki Memorial ONLINE -- pointing the client at a local server")
    say()

    folder = resolve_game_folder(args.game_dir, remembered.get("game_dir"))
    if folder is None:
        return hold(1)
    server = None
    if not args.revert:
        server = resolve_server(args.server, remembered.get("server"))
        if server is None:
            return hold(1)
    launch_with = args.launch_with or remembered.get("launch_with")

    say()
    say(f"  game    {folder}")
    say(f"  server  {server or 'putting everything back'}")

    launching = not (args.revert or args.no_launch or args.dry_run)
    if WINDOWS and not is_privileged() and not args.dry_run:
        say()
        say("This needs administrator rights -- the hosts file is written by")
        say("one, and the game refuses to start without one. Use Play.cmd,")
        say("which asks for them, or an elevated Command Prompt.")
        return hold(1)

    say()
    say(f"1. the four bytes in {GAME_EXE}")
    if not apply_auth_address(folder / GAME_EXE, None if args.revert else server, args.dry_run):
        return hold(1)

    say()
    say("2. the two hostnames")
    if not apply_hosts(None if args.revert else server, args.dry_run):
        return hold(1)
    say("  they lead to (unchanged, nothing was written):" if args.dry_run
        else "  they now lead to:")
    resolved = report_names(server)

    if args.revert:
        say()
        say("Back as it was. Your copy of the game is byte-for-byte the one you")
        say("installed, and the hosts file has none of this in it.")
        return hold(0)

    if not resolved and not args.dry_run:
        say()
        say("  ⚠️ One of the names still leads somewhere else. Something with a")
        say("  say in name resolution is answering ahead of the hosts file --")
        say("  a VPN, or a router handing out its own answers.")

    say()
    say(f"3. is the server at {server} listening")
    # Knocked on even in a dry run: it is the one step that writes nothing in
    # any mode, and it is most of the value of asking what would happen.
    reachable = knock(server)

    if args.dry_run:
        say()
        say("Dry run. Nothing was written and nothing was started -- including")
        say("the answers above, which are not remembered either.")
        return hold(0)
    save_config(game_dir=str(folder), server=server, launch_with=launch_with)

    if args.no_launch:
        say()
        say(f"Set up. Start {LAUNCHER_EXE} when you want to play"
            + (" -- as administrator." if WINDOWS else "."))
        return hold(0)
    if not reachable:
        say()
        say("Not starting the game: it would reach nothing. Everything above")
        say("this line is done and stays done, so start the server and run")
        say("this again.")
        return hold(1)

    say()
    say(f"4. starting {LAUNCHER_EXE}")
    if not start_game(folder, launch_with):
        return hold(1)

    say()
    say("The login screen wants a KONAMI ID, a personal key and a registration")
    say(f"code. Get all three at  http://{server}:12013/  in a browser.")
    say("The server's log has a line for every step: runtime/run_all.log")
    return hold(0)


def hold(code: int) -> int:
    """Keep a double-clicked window open long enough to be read.

    A window that closes on its own has taken the whole report with it, and the
    report is most of what this is for. Play.cmd pauses for the same reason and
    says so in the environment, so that the two of them do not both ask.
    """
    if os.environ.get("TMO_PLAY_WRAPPER"):
        return code
    if WINDOWS and sys.stdin is not None and sys.stdin.isatty():
        try:
            input("\nPress Enter to close. ")
        except (EOFError, KeyboardInterrupt):
            pass
    return code


if __name__ == "__main__":
    sys.exit(main())
