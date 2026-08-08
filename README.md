# Tokimeki Memorial ONLINE — local server

A from-scratch server for *Tokimeki Memorial ONLINE* (KONAMI, 2006–2007, service ended),
written so that a surviving copy of the original client has something to connect to again.

Run it on your own machine, point your own copy of the client at it, and you can log in,
create a character, and walk around the school.

<!-- HTML rather than markdown for the width="50%": all four shots are 1280x960, and a
     markdown table would size its columns from the caption text instead. -->
<table>
<tr>
<td width="50%" valign="top">

![School select](screenshots/school-select.jpg)

</td>
<td width="50%" valign="top">

![Character creation](screenshots/character-create.jpg)

</td>
</tr>
<tr>
<td valign="top"><b>Choosing a school.</b> Ten of them, each with a student count this server reports as zero.</td>
<td valign="top"><b>Making a character.</b> The client's own creation sheet, kept verbatim by the server.</td>
</tr>
<tr>
<td valign="top">

![On the map](screenshots/map.jpg)

</td>
<td valign="top">

![A conversation](screenshots/conversation.jpg)

</td>
</tr>
<tr>
<td valign="top"><b>Standing in the courtyard.</b> The player is put into the scene by the server, the NPC by one of the <code>/npc</code> commands.</td>
<td valign="top"><b>A scripted scene.</b> The client plays the cut-scene out of its own copy of the game; this end only answers the questions it stops on.</td>
</tr>
</table>

## About

The servers went away; the client did not. The campus, the characters and the scripts are
all still on the disc, intact and unreachable. This is the half that vanished, rebuilt from
the outside by watching what the client asks for.

This is an independent implementation of the game's network protocol, produced by analysing
how the client communicates, for the purpose of interoperability: letting an existing client
program reach a server again.

It contains no code, artwork, audio or text taken from KONAMI's software. It does contain
two small tables of integers, read mechanically out of the client's data files, because
there are decisions this server is asked to make that it cannot make without them — see
[Reference data](#reference-data). Message names, map names and structure offsets appear
here because they are the identifiers the protocol itself uses; a client will not accept any
other wording for them.

*Tokimeki Memorial* is a trademark of KONAMI. This project is not affiliated with, endorsed
by, or connected to KONAMI in any way.

## What this is not

- **Not a restored game.** What works today: logging in, creating a character, walking
  around, moving between maps, position persistence, chat, putting NPCs on the map, a report
  card and a timetable, the class bells, and a romance state stored per character. Nearly all
  of it is driven by hand from the chat console; there is no game loop tying it together. The
  original server's own logic — how NPCs behaved, when events fired, what advanced the
  dating-sim progression — did not survive alongside the client, and none of it is
  reimplemented here. What you get is a campus you can walk into and a set of levers, not a
  game you can play through.
- **Not a public service.** There is no server to join, this repository will never run one,
  and nothing here is or will be sold.
- **Not a source of game files.** No client, no assets, no patched executable. You supply
  your own copy.

Not every number in this server is a fact. The wire format — message ids, structure layouts,
field offsets — was read off the protocol and is verifiable. Some values only exist because
the client needs *something* there: movement speed, spawn positions, the school list. Those
are inventions, and the comments say so where they appear.

## Requirements

- **Python 3**, standard library only — no `pip install`, no virtualenv. Run here on 3.11
  and 3.14. It must be built against real OpenSSL; see the macOS note below.
- **`openssl` on PATH.** Used once, on the first run, to generate the certificate the
  authentication endpoint needs into `runtime/certs/`.
- **Your own copy of the original client.** This repository distributes no part of it. The
  original disc has been publicly archived on the Internet Archive; whether you may obtain
  and use a copy is a question of the law where you are, not one this project answers.

The server runs on Windows, macOS or Linux. The game is a Windows program and also works
under Wine.

Run end to end here in two shapes: the game on Windows 11 talking to a server on the same
host, and the game under Wine on macOS talking to a server on a different machine
(Debian 12).

## Installation

```sh
git clone https://github.com/ShuAkirasora/tokimeki-memorial-online-revival.git
cd tokimeki-memorial-online-revival
```

Without git, use the green **Code** button on that page → **Download ZIP** and unpack it
anywhere. There is nothing to build and nothing to install; the folder is the program, and
every command below is run from inside it.

Then install Python, which is the only per-platform part.

### Windows

Get the installer from [python.org](https://www.python.org/downloads/) and tick **Add
python.exe to PATH** on the first screen — without it the commands below are not found. Open
a *new* Command Prompt and check with `py --version`.

**On Windows, every `python3` in this README is `py`.** That is the only difference.

`openssl` is not part of Windows, but Git for Windows carries a complete copy and this server
looks there directly, **so if you have Git you need do nothing**. Failing that,
`winget install openssl` (or scoop, or chocolatey).

Two more things, neither of which stops the first run:

- **The firewall asks once**, at the first start. Answering no leaves a game on this machine
  working and every game anywhere else unable to arrive.
- **Low ports are free here, and taken anyway.** Binding 443, 80 or 50 needs no privileges on
  Windows, so `[authhttp] skip` means something else already holds the port — usually IIS or
  another HTTP.sys service. Hyper-V and WSL also reserve blocks of ports at boot, and a block
  covering 25573–25575 stops the server dead rather than being skipped; list them with
  `netsh int ipv4 show excludedportrange protocol=tcp`.

### macOS

```sh
brew install python
```

or the installer from [python.org](https://www.python.org/downloads/). `openssl` is already
there.

**Do not use the `python3` that comes with macOS.** It is built against LibreSSL and cannot
start this server's TLS listeners. To see which one you have:

```sh
python3 -c "import ssl; print(ssl.OPENSSL_VERSION)"
```

If that says `LibreSSL`, the wrong one is first in your PATH — call the one you just
installed by its full path, which the python.org installer reports at the end and Homebrew
prints under `brew --prefix python`.

### Linux

You almost certainly have Python; `python3 --version` says so. If not, your distribution's
own package (`sudo apt install python3`, `sudo dnf install python3`) is fine as it comes.
Check `openssl version` too. Nothing else has to be installed: what holds a port is read out
of `/proc`, not out of `lsof`.

**Low ports are privileged, and 443 and 50 are the two the authentication step is most likely
to want.** `[authhttp] skip :443 (...)` in the log is exactly that, and the server carries on
without them. Either start it as root, or lift the restriction once:

```sh
sudo sysctl -w net.ipv4.ip_unprivileged_port_start=50
```

A file in `/etc/sysctl.d/` makes that survive a reboot. Check what already holds 80 and 443
before blaming privileges — on a machine with a web server installed, something usually does.
If `ufw` or `firewalld` is running, open the [ports](#ports) there as well.

**The authentication certificate has to be SHA-1, and your distribution may refuse to make
one.** The client accepts no other kind, while RHEL, Fedora and their derivatives run every
OpenSSL process under a system-wide crypto policy that since RHEL 9 will not *produce* a
SHA-1 signature. The first run notices that refusal and repeats the command with the policy
overridden for that one process — nothing about the machine's own policy changes. If even
that fails, the server stops and prints what openssl said.

## Running the server

```sh
python3 start_servers.py                          # game on this same machine
python3 start_servers.py --advertise-ip 192.168.1.5   # game on another machine
python3 stop_servers.py
```

You should see `started pid=…` and a few lines of log ending in `[system] all services
started`. It runs detached, so the terminal can be closed; it keeps going until stopped.
Stopping goes by which ports are held rather than by the recorded process id, so it works
even if that record is stale or was never written.

**`--advertise-ip` is needed whenever the game is not on the server's own machine.** Logging
in is a chain of hops and each one answers with the address of the next. Those answers
default to `127.0.0.1`, which is right for a game on the same machine and sends every remote
player back to their own computer. The address cannot be worked out from the socket, because
behind a router the address a client must dial is not one this machine can see on any
interface of its own. `TMO_ADVERTISE_IP` in the environment does the same thing, and the
startup log says which is in use.

## Connecting a client

Three destinations inside the client have to end up here: two hostnames, which your `hosts`
file redirects, and one fixed numeric address, which is four bytes inside `tmo.exe`.

```sh
# 1. two lines in the hosts file of the machine the *game* runs on:
#      <server>  tmollb.tokimekionline.com
#      <server>  tmoupd.tokimekionline.com
# 2. python3 set_auth_address.py /path/to/tmo.exe <server>
# 3. run BootFirst.exe (as administrator on Windows)
```

### 1. Your server address

`<server>` above is the address the *game* has to dial, and which one it is depends on where
the game runs:

| Your setup | `<server>` |
|---|---|
| **One computer** — server and game on the same machine, including the game under Wine, since Wine uses that machine's own network | `127.0.0.1` |
| **Two computers** — a second PC, or another machine on your network | the server machine's local address, usually starting `192.168.` or `10.` |

To find it, ask the **machine that will run the server**: `ipconfig` on Windows and read the
`IPv4 Address` line; `ipconfig getifaddr en0` on macOS (try `en1` if that is empty);
`hostname -I` on Linux, first address. The examples below use `192.168.1.5`.

### 2. The two hostnames

The game looks for its update and login-server lookup by name, and nothing inside the client
decides where those lead — your computer's `hosts` file does:

```
192.168.1.5  tmollb.tokimekionline.com
192.168.1.5  tmoupd.tokimekionline.com
```

⚠️ **The file to edit is on the machine the *game* runs on, not the machine the server runs
on.** If the game runs on a different machine, it is that machine's file. If the game runs
under Wine, Wine has no name resolution of its own, so it is the Mac's or Linux box's
`/etc/hosts` — not anything inside the Wine folder.

- **Windows:** Start → type `notepad` → right-click **Notepad** → **Run as administrator**
  (opening the file any other way will not be allowed to save it). **File → Open**, paste
  `C:\Windows\System32\drivers\etc\hosts` into the filename box, Enter — set the file-type
  dropdown to **All Files** if the folder looks empty. Add the two lines at the end and save.
- **macOS and Linux:** `sudo nano /etc/hosts`, add the two lines at the end, `Ctrl-O` and
  `Enter` to save, `Ctrl-X` to leave.

Nothing inside the game's own folder has to be edited for this. The update check is also
configurable, as `SERVER_ADDRESS` in the client's `update.ini`, but that file ships with the
hostname in it — so the hosts entry covers it too.

### 3. The four bytes

The client's third destination is not a name at all: it opens a connection straight to a
fixed numeric address that was KONAMI's, and no amount of name resolution can redirect an
address that is never looked up. That one is told to the client directly:

```sh
python3 set_auth_address.py /path/to/tmo.exe 192.168.1.5
```

Run it on whichever machine holds `tmo.exe` — on a two-computer setup, install Python there
as well, or copy the file over, run the command, and copy it back. On Windows that looks like
`py set_auth_address.py "C:\Games\TokimekiOnline\tmo.exe" 192.168.1.5`; under Wine the file
sits inside the bottle or prefix and your Mac or Linux `python3` reaches it directly.

It prints what it is about to do, keeps a copy of the original as `tmo.exe.orig` before
writing anything, and then reports where the two hostnames currently lead:

```
  the two names the client resolves for itself:
    tmollb.tokimekionline.com  -> 192.168.1.5      ok
    tmoupd.tokimekionline.com  -> 192.168.1.5      ok
```

**Two `ok` lines means step 2 is done as well.** Anything else and it prints the lines you
are missing. If it still shows an old answer after you edited the file, the lookup is cached:
`ipconfig /flushdns` on Windows, `sudo dscacheutil -flushcache; sudo killall -HUP
mDNSResponder` on macOS, `sudo resolvectl flush-caches` on Linux.

Other arguments: no address at all reports what your copy currently points at without
changing anything, `--revert` puts KONAMI's original address back, `-n` says what it would do
and writes nothing, `--no-lookup` skips the hostname check.

### 4. A registration code and a KONAMI ID

The login screen asks for three things — a KONAMI ID, a personal key, and a twenty-character
registration code in five groups — and this server means all three. **Anything typed there
will not do:** a code it did not issue is refused with the client's own
「入力されたレジストレーションコードは存在しません」, which is the right answer and an
opaque one if you were not expecting it.

Open **http://127.0.0.1:12013/** in a browser on the machine running the *server* (or
`http://<server>:12013/` from elsewhere), pick a KONAMI ID and a personal key, and the page
hands back a code already bound to them. Type all three into the login screen and you are in.

Coming back to that page with the same id and key shows the same code again rather than
issuing a second one, so a lost code is not a lost account, and a reloaded page is not an
error.

Plain HTTP, and it has to be: the certificate the game insists on is 1024-bit RSA signed
with SHA-1, which no current browser will open. So the personal key crosses that connection
in the clear — nothing when the browser is on the server's own machine, a password in
plaintext when it is not. **Pick one you do not use anywhere else.**

Originally the code came printed in the box and the player bound it to their KONAMI ID on
KONAMI's website, and both halves are still here separately: `issue_code.py` is the
printing, and **http://127.0.0.1:12013/register** is the binding. That is the way in for a
code somebody issued by hand and gave you.

```sh
python3 issue_code.py --unregistered      # prints something like WJUH-RTDC-M39X-HCDN-U26X
```

Handing a code straight to somebody at the same machine is `issue_code.py` with no flag —
it comes out ready to use, but with no owner, and a code with no owner is one anybody can
log in with. `issue_code.py --list` shows every code, its state, and who registered it;
`--revoke` withdraws one without touching the characters saved under it.

### 5. Start the game

**The program to run is `BootFirst.exe`, not `tmo.exe`.** It starts `UpdateClient.exe`, which
performs the update check, and that in turn starts the game.

On Windows, run `BootFirst.exe` **as administrator** — right-click → *Run as administrator*.
Without that you get `アップデートクライアントの起動に失敗しました` and nothing at all
reaches this server, because nothing was ever started. The cause is on the client's side and
no server can answer it: `UpdateClient.exe` is a 32-bit binary with no manifest and "Update"
in its name, which is exactly what Windows' installer detection looks for, so the system
decides it requires elevation — and `BootFirst.exe` starts it with `CreateProcess`, which
cannot elevate. Beginning the chain already elevated is the whole of the fix. Under Wine this
has not come up: the same chain starts as it is.

### 6. Check that it worked

Everything the client does arrives in `runtime/run_all.log` in order — `tail -f
runtime/run_all.log`, or `Get-Content runtime\run_all.log -Wait -Tail 20` in PowerShell. Each
line below is one of the steps above proving itself, and the first one **missing** tells you
where to go back to:

| A line like this | Means |
|---|---|
| `[system] all services started` | the server is up |
| `[updater] … sent UPDATE_DONE` | `tmoupd` resolves — step 2 |
| `[llb35573] -> MsgSvResultLoginServer` | `tmollb` resolves — step 2 |
| `[authhttp] ACCEPT port=443` | the four bytes are right — step 3 |
| `[mpslogin25573] … login: code …` | the code and the KONAMI ID were accepted |
| `[mpsgame25574] …`, `[mpsschool25575] …` | the game and school servers; you are in |

After that you are at the school-select screen. Steps 2, 3 and 4 are done once and stay done —
unless you reinstall the game, which puts the original `tmo.exe` back, or the server machine's
address changes.

## What changes in your copy of the client

**One thing changes: where it looks for a server. Nothing about how it behaves does.** Its
connections are Blowfish-enciphered, and this server implements that layer and speaks it as
the protocol's other endpoint. No check is bypassed, no encryption is switched off, and every
piece of code that ships in the binary is the code that runs.

| | How the client finds it | How it is redirected |
|---|---|---|
| `tmoupd.tokimekionline.com` | hostname — the update check | name resolution |
| `tmollb.tokimekionline.com` | hostname — the login-server lookup | name resolution |
| `133.221.34.229` | a fixed numeric address, straight to `connect()` | the four bytes |

Everything after those three follows along on its own: the login, game and school servers are
reached at whatever address the login-server lookup hands back. The third one takes a
different route because it has to — the hostname `sctrl01.game.konaminet.jp` travels along
with that connection, but only as request metadata in the `Host:` header, and takes no part
in deciding where to connect.

**What the four bytes are, exactly.** The client builds the address one octet at a time,
straight onto the stack, and hands the result to `connect()`:

```
mov byte [esp+0x28], 133
mov byte [esp+0x29], 221
mov byte [esp+0x2a], 34
mov byte [esp+0x2b], 229
```

Those four immediates are the whole of the target, and they are all the script writes to. It
changes no instruction, removes no check, disables nothing, and every octet is an independent
byte so any address fits. Reverting restores the original four, which — since nothing else
was ever touched — leaves the file byte-for-byte as it was. It also refuses to work blind:
rather than trusting a hardcoded offset it scans for that instruction shape and requires it
to occur exactly once, copies the original to `tmo.exe.orig` before the first write, and
never overwrites an existing backup.

Two things that looked like obstacles turned out not to be: the client carries a small trust
store but does not enforce it, so a locally generated self-signed certificate is accepted;
and no part of the client has to be disabled to get through authentication, including its
encryption, which stays on from the first packet to the last.

## Ports

| Port | Service |
|---|---|
| 12000 | update check the client performs at startup |
| 35573 | login-server lookup — answers "which host do I log in to" |
| 25573 | login |
| 25574 | game |
| 25575 | school |
| 443, 50, 8011, 12011 | account auth stub, TLS |
| 80, 12012 | account auth stub, plaintext |
| 12013 | the registration page, for a browser |
| 12010, 12020 | early stubs; the current login flow does not use them |

The listeners are on `0.0.0.0`. Ports 25573, 25574, 25575 and 35573 have to be reachable from
the game's machine in addition to whichever authentication port it uses, so open those on any
firewall in between. Ports below 1024 need privileges, except on Windows; either way it is not
fatal — the server logs `[authhttp] skip :443 (...)` and carries on.

## Commands

Typed into the game's own chat bar and handled by this server. They are a console for driving
the protocol rather than gameplay: most of them exist because sending a message by hand was
the only way to find out what the client would do with it.

| Command | Effect |
|---|---|
| `/cmds` | list them in the game |
| `/go <map name or id> [x y]` | move to a map |
| `/pos` | print where you are |
| `/maps <name>` | search the map table |
| `/dirs` | drop a marker for each of the sixteen direction values |
| `/npc <cat>:<id> [<cat>:<id>]` | put an NPC on the map; a second key names a script |
| `/npca [<first> <last> [category]]` | place every romance candidate who has appeared |
| `/npcx` | stop replacing them |
| `/rom [name] [debut\|talk\|ev\|p <n>]` | read and move the romance state |
| `/nev [<cat>:<id>]` | set the conversation-event key |
| `/card [...]` | the report card |
| `/jikan [day]` | the timetable |
| `/bell [<subject>\|ready]` | ring the warning and start bells by hand |
| `/lopt [seats\|speech\|words] <n>` | knobs on the lesson message |
| `/quiz [sec <n>\|wait <n>]` | the question in progress and which choice is right; timers |
| `/sc`, `/scn`, `/sce`, `/scl`, `/sel` | script playback |
| `/de [<genre>:<index>]` | the drama-event list |
| `/dms` | open the matching screen |

The client intercepts a number of words itself — `/help` and `/where` among them — and never
puts them on the wire, so those names are unavailable no matter what the server does.

## Reference data

`reference/` holds three tables of integers, and each is something this server has to know in
order to decide something.

**`mapgraph.json`** — grid size, collision and doorways for the 78 maps. Without it the map
graph is empty, the log says `warps go unchecked`, and moving between maps stops working.

The other two were read out of the client's own data files rather than off the wire, and are
here because watching the protocol cannot recover what they hold:

**`branches.json`** — where a cut-scene goes when the player picks option k, for the 209
scripts that ask. Branch targets sit in an instruction's operands, and operands never travel
on the wire. Without it every branch falls through: scenes still play, choices stop mattering.
It holds 5125 of the game's 15586 branches, and the other two thirds are left out on purpose:
their conditions are script variables this end will always answer no to, and a no needs no
target. It carries no text, no option wording, no cast and no instruction stream.

**`quizkeys.json`** — about 6 KiB: how many questions each of the 80 lesson categories holds,
and the answers to the true-or-false half of the bank. A lesson message carries three numbers
and no text, and it is this end that picks the question and marks the answer, so a key is the
whole of what it needs; the four-choice half needs nothing at all, because this server
shuffles those itself and already knows where it dealt the right one. Without the file a
lesson draws the room and then asks nothing. It carries no question text, no choice wording
and no subject names.

Neither means anything without your own copy of the game. What is deliberately not here is
the other half of each: script text, choice prompts, the cast, event keys. Those are the
game's content rather than a rule this server applies, so `/scl` and `/sc <name>` need an
export you make yourself and say so when there is none, and `/de` cannot name an event without
its file, though a key given directly as `<genre>:<index>` is still sent.

Two gaps are worth naming rather than leaving to be found. What is missing from a cut-scene is
nothing you can see. What is missing from a lesson is: the six ability parameters it should
move, stress and the breakdown that follows it, the reward items, and the hint skills. The
result screen reports no change to any of them because there is nothing there to change, and
the grade it awards is this server's own curve over the running score.

## Repository layout

| Path | |
|---|---|
| `start_servers.py`, `stop_servers.py` | start and stop everything |
| `set_auth_address.py` | the four-byte address change described above |
| `issue_code.py` | issue, list, revoke and unbind registration codes |
| `server/` | the services themselves; `run_all.py` binds them all in one asyncio loop and `mps_session.py`, the packet layer, is the bulk of it |
| `reference/` | the three tables above |
| `runtime/` | created on the first run: the log, the certificate, and your characters |
| `screenshots/` | the four pictures above; captures of a running client, not game files |
| `LICENSE`, `NOTICE` | Apache 2.0, and the attribution that redistribution has to carry |

## Troubleshooting

| Symptom | Cause |
|---|---|
| 「レジストレーションコードは存在しません」 | the code was not issued here — `issue_code.py`, step 4 |
| 「レジストレーションコードが登録されていません」 | the code exists but nobody has bound it on port 12013 |
| 「ユーザ情報が正しくありません」 | that code is registered to a different KONAMI ID, or the personal key is wrong |
| the game starts but the log stays completely empty | `BootFirst.exe` was not run as administrator |
| `アップデートクライアントの起動に失敗しました` | the same thing, said by the client |
| the log stops after `[updater]`, no `[llb35573]` | only one of the two hosts lines is there, or it is on the wrong machine |
| the log stops after `[llb35573]`, no `[authhttp]` | the four bytes were not written, or were written to a different copy of `tmo.exe`; if the log also says `[authhttp] skip :443`, that port was refused or taken |
| the log stops after `[authhttp]`, no `[mpslogin25573]` | the game could not reach port 25573 at the address the lookup gave it: a firewall in between, or the server was started without the right `--advertise-ip` |
| every remote player is sent back to their own computer | the server was started without `--advertise-ip` |
| `ssl.SSLError: ('No cipher can be selected.',)` | the LibreSSL-backed Python; see [macOS](#macos) |
| `openssl is not on PATH` | nothing to generate the authentication certificate with |
| `openssl did not produce the auth certificate` | it refused, and the retry did too — usually a crypto policy that forbids SHA-1; see [Linux](#linux) |
| `already running pid=N` | a previous instance is still up; leave it, or run `stop_servers.py` |
| `[WinError 10013]` on a bind, and the server exits | that port is reserved or already held; see [Windows](#windows) |
| `warps go unchecked` in the log | `reference/mapgraph.json` missing |
| every branch logs `fall-through`, choices do nothing | `reference/branches.json` missing |
| `no question bank, no questions`, a lesson asks nothing | `reference/quizkeys.json` missing |

The log is verbose and includes hex dumps of unrecognised packets. `no reply implemented`
marks a message this server has seen but does not answer yet.

## License

[Apache License 2.0](LICENSE). Copyright 2026 Shu Akirasora and contributors.

That covers this repository's own code and documentation, and nothing else. It grants no
rights in *Tokimeki Memorial ONLINE* or in any KONAMI property, and section 6 of the license
says as much about trademarks.

[`NOTICE`](NOTICE) carries the attribution, and the statement of what here does and does not
come out of KONAMI's software. Section 4(d) of the license makes that travel: if you
redistribute this or anything derived from it, that text has to go along — those are the
sentences that should still be attached to this code after it has passed through hands that
never read this README.
