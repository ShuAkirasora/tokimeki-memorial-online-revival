# Tokimeki Memorial ONLINE — local server

A from-scratch server for *Tokimeki Memorial ONLINE* (KONAMI, 2006–2007, service ended),
written so that a surviving copy of the original client has something to connect to again.

Run it on your own machine, point your own copy of the client at it, and you can log in,
create a character, and walk around the school.

## What it looks like

An original client, with nothing changed about it but where it looks for a server,
talking to this one.

<!-- An HTML table rather than a markdown one for the width="50%": all four shots are
     1280x960, but a markdown table sizes its columns from their content, and the longer
     captions on the right would take the extra width and stretch those two pictures. -->
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
<td valign="top">

**Choosing a school.** Ten of them, each with a student count that this server reports as zero.

</td>
<td valign="top">

**Making a character.** The client's own creation sheet, kept verbatim by the server. Three characters per account is the client's limit, not a policy.

</td>
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
<td valign="top">

**Standing in the courtyard.** Neither figure is there on the client's own initiative: the player is put into the scene by the server, the NPC by one of the `/npc` commands below.

</td>
<td valign="top">

**A scripted scene.** The client plays the cut-scene out of its own copy of the game and reports where it has got to; this end only answers the questions it stops on.

</td>
</tr>
</table>

## About this project

The servers went away; the client did not. The campus, the characters and the scripts
are all still on the disc, intact and unreachable. This is the half that vanished,
rebuilt from the outside by watching what the client asks for.

This is an independent implementation of the game's network protocol, produced by
analysing how the client communicates, for the purpose of interoperability: letting an
existing client program reach a server again.

It contains no code, artwork, audio or text taken from KONAMI's software. It does
contain two small tables of integers, read mechanically out of the client's data files,
because there are decisions this server is asked to make that it cannot make without
them — "Reference data" says which and why. Message names, map names and structure
offsets appear here because they are the identifiers the protocol itself uses; a client
will not accept any other wording for them.

*Tokimeki Memorial* is a trademark of KONAMI. This project is not affiliated with,
endorsed by, or connected to KONAMI in any way.

## What this is not

- **Not a restored game.** What works today: logging in, creating a character, walking
  around, moving between maps, position persistence, chat, putting NPCs on the map, a
  report card and a timetable, the class bells, and a romance state stored per character.
  Nearly all of it is driven by hand from the chat console; there is no game loop tying it
  together. The original server's own logic — how NPCs behaved, when events fired, what
  actually advanced the dating-sim progression — did not survive alongside the client, and
  none of it is reimplemented here. What you get is a campus you can walk into and a set of
  levers, not a game you can play through.
- **Not a public service.** There is no server to join, this repository will never run
  one, and nothing here is or will be sold.
- **Not a source of game files.** No client, no assets, no patched executable. You supply
  your own copy. The two files here that were read out of the game rather than off the wire
  are described under "Reference data", and both are integers only.

Not every number in this server is a fact. The wire format — message ids, structure
layouts, field offsets — was read off the protocol and is verifiable. Some values only
exist because the client needs *something* there: movement speed, spawn positions, the
school list. Those are inventions, and the comments say so where they appear.

## Requirements

Only the standard library is used — no third-party packages, nothing to install, no
virtualenv to create. Two things have to be true of the machine:

- **A Python with a real OpenSSL.** Tested on 3.14. On macOS the system `python3` is built
  against LibreSSL and cannot start the TLS listeners; use a python.org, Homebrew or pyenv
  build instead. The python.org build for Windows and a distribution's own `python3` on
  Linux are both fine as they come.
- **An `openssl` binary — once.** The certificate for the auth endpoint is generated on the
  first run, into `runtime/certs/`, and never regenerated, so this only matters when
  starting from an empty `runtime/certs/`. macOS and Linux have one already, though on some
  Linux distributions it needs persuading — see "On Linux". Windows ships none, but Git for
  Windows carries a complete one and its install location is searched directly, so **if you
  have Git you need do nothing**; failing that, winget, scoop and chocolatey all have a
  package.

Written and run on macOS and on Linux (Debian 12, Python 3.11), and the Windows paths have
been run on Windows. Every command below is the same on all three, with `py` in place of
`python3` on Windows; where that is not enough, it says so.

## Running the server

```sh
python3 start_servers.py
```

frees the ports it needs, starts every service in one detached process, writes the pid to
`runtime/run_all.pid` and appends to `runtime/run_all.log`. `[system] all services started`
in the log means it is up.

```sh
python3 stop_servers.py
```

stops it again. That goes by the ports rather than the pidfile, so it still works when the
pidfile is stale or was never written.

### On Windows

The same two commands. Three things worth knowing:

- **Stopping is a hard kill** — and no less hard anywhere else. Windows has no SIGTERM, and
  a process detached from every console cannot be sent a Ctrl-Break either. Nothing is lost
  to that: no service writes its state on the way out, and `runtime/characters.json` is
  rewritten at every change, so what is on disk is everything the server knew.
- **Low ports are free, and taken anyway.** Binding 443, 80 or 50 needs no privileges here,
  so `[authhttp] skip` means something else already has the port — usually IIS or another
  HTTP.sys service. Hyper-V and WSL also reserve blocks of ports at boot, and a block
  covering 25573–25575 stops the server dead rather than being skipped; list them with
  `netsh int ipv4 show excludedportrange protocol=tcp`.
- **The firewall asks once.** Answering no leaves a client on this machine working and
  every client anywhere else unable to arrive.

### On Linux

The same two commands, and still nothing to install: what holds a port is read out of
`/proc`, not out of `lsof`, which is not on a Linux machine unless somebody put it there.
Two things are worth knowing before the first run.

**Low ports are privileged, and 443 and 50 are the two the auth step is most likely to
want.** `[authhttp] skip :443 (...)` in the log is exactly that, and the server carries on
without them. Either start it as root, or lift the restriction for everyone once:

```sh
sudo sysctl -w net.ipv4.ip_unprivileged_port_start=50
```

The startup log suggests the same line when it is the reason a port was skipped, and a file
in `/etc/sysctl.d/` makes it survive a reboot; with it applied, an ordinary user's server
takes all three. Check what already holds 80 and 443 before blaming privileges — on a
machine with a web server installed, something usually does.

**The auth certificate has to be SHA-1, and your distribution may refuse to make one.** The
client accepts no other kind (see "Connecting a client"), while RHEL, Fedora and their
derivatives run every OpenSSL process under a system-wide crypto policy that since RHEL 9
will not *produce* a SHA-1 signature. The first run notices that refusal and repeats the
command with the policy overridden for that one process — nothing about the machine's own
policy changes, and nothing else on it will accept anything it did not accept before. If
even that fails, the server stops and prints what openssl said, rather than coming up with
an auth endpoint that cannot complete a handshake.

Firewalls are the last thing: if `ufw` or `firewalld` is running, the ports under "Playing
from another machine" have to be opened there too.

### Ports

| Port | Service |
|---|---|
| 12000 | update check the client performs at startup |
| 35573 | login-server lookup — answers "which host do I log in to" |
| 25573 | login |
| 25574 | game |
| 25575 | school |
| 443, 50, 8011, 12011 | account auth stub, TLS |
| 80, 12012 | account auth stub, plaintext |
| 12010, 12020 | early stubs; the current login flow does not use them |

Ports below 1024 need privileges, except on Windows. Either way it is not fatal: the server
logs `[authhttp] skip :443 (...)` and carries on. Whether you need them depends on which
endpoint your client asks for, and on Linux there is a way to have them without running as
root — see "On Linux".

## Connecting a client

You need your own copy of the original client; this repository neither distributes it nor
points at where to find one.

**One thing about your copy of the client changes: where it looks for the server. Nothing
about how it behaves does.** Its connections are Blowfish-enciphered, and this server
implements that layer and speaks it as the protocol's other endpoint. No check is
bypassed, no encryption is switched off, and every piece of code that ships in the binary
is the code that runs.

So the whole job is addressing, and the client has three starting points. Two are
hostnames:

| Hostname | What it is |
|---|---|
| `tmoupd.tokimekionline.com` | the update check — also plainly configurable, as `SERVER_ADDRESS` in the client's own `update.ini` |
| `tmollb.tokimekionline.com` | login-server lookup, the first thing the game does after the update check |

Resolve those to the machine running the server — a hosts-file entry each, or a local
resolver for the domain. The client is a Windows program, so the file to edit is the one on
the machine it runs on: `C:\Windows\System32\drivers\etc\hosts`, which needs an editor
started as administrator. Under Wine the machine it runs on is the Linux one and Wine has
no resolver of its own, so the file is that host's `/etc/hosts` — though running the client
that way has not been tried here.

Everything after those two follows along on its own: the login, game and school servers are
reached at whatever address the login-server lookup hands back, and this server hands back
the one it was started with.

### The third one is an address, not a name

The client opens TLS straight to a fixed `133.221.34.229`. The hostname
`sctrl01.game.konaminet.jp` travels along only as request metadata, in the `Host:` header,
and takes no part in deciding where to connect — so no amount of name resolution reaches an
address that was never looked up. This one is told to the client directly:

```sh
python3 set_auth_address.py /path/to/tmo.exe 192.168.1.5
```

with the address of the machine running the server. Run it with no address to see what your
copy currently points at, and `--revert` to put the original address back.

**What that changes, exactly.** The client builds the address one octet at a time, straight
onto the stack, and hands the result to `connect()`:

```
mov byte [esp+0x28], 133
mov byte [esp+0x29], 221
mov byte [esp+0x2a], 34
mov byte [esp+0x2b], 229
```

Those four immediates are the whole of the target, and they are all the script writes to.
It changes no instruction, removes no check, disables nothing, and every octet is an
independent byte so any address fits. Reverting restores the original four, which — since
nothing else was ever touched — leaves the file byte-for-byte as it was. It also refuses to
work blind: rather than trusting a hardcoded offset it scans for that instruction shape and
requires it to occur exactly once, copies the original to `tmo.exe.orig` before the first
write, never overwrites an existing backup, and takes `-n` to print what would change
without writing anything.

Everything past that point is the client's own code doing its own thing, and two things
that looked like obstacles turned out not to be: the client carries a small trust store but
does not enforce it, so a locally generated self-signed certificate is accepted; and no
part of the client has to be disabled to get through this step, including its encryption,
which stays on from the first packet to the last.

### Starting the game

The entry point is `BootFirst.exe`, not `tmo.exe`. It starts `UpdateClient.exe`, which
performs the update check on port 12000, and that in turn starts `tmo.exe`.

On Windows, run `BootFirst.exe` **as administrator**. Without it you get

```
アップデートクライアントの起動に失敗しました
```

and nothing at all reaches this server, because nothing was ever started. The cause is on
the client's side and no server can answer it: `UpdateClient.exe` is a 32-bit binary with
no manifest and "Update" in its name, which is exactly what Windows' installer detection
looks for, so the system decides it requires elevation — and `BootFirst.exe` starts it with
`CreateProcess`, which cannot elevate. Beginning the chain already elevated is the whole of
the fix.

### Playing from another machine

The listeners are on `0.0.0.0`, so a client elsewhere can reach them. What it cannot do is
*find* them: logging in is a chain of hops, and each one answers with the address of the
next. Those answers default to `127.0.0.1`, which is right for a client on this machine and
sends every remote player back to their own computer. So tell the server the address
clients reach it at:

```sh
python3 start_servers.py --advertise-ip 203.0.113.7
```

or set `TMO_ADVERTISE_IP`. The startup log says which one is in use. It is not worked out
from the socket because it cannot be: behind NAT, the address a client must dial is not one
this machine can see on any interface of its own. It is also not the same thing as the
address you gave `set_auth_address.py`, which covers the authentication step only, though
on a single-box deployment both are the same address.

Ports 25573, 25574, 25575 and 35573 have to be reachable from the client in addition to
whichever auth port it uses, so open them on any firewall in between.

## Commands

Typed into the game's own chat bar and handled by this server. They are a console for
driving the protocol rather than gameplay: most of them exist because sending a message by
hand was the only way to find out what the client would do with it.

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
| `/quiz [sec <n>\|wait <n>]` | the question in progress and which choice is right; question and grading timers |
| `/sc`, `/scn`, `/sce`, `/scl`, `/sel` | script playback |
| `/de [<genre>:<index>]` | the drama-event list |
| `/dms` | open the matching screen |

The client intercepts a number of words itself — `/help` and `/where` among them — and
never puts them on the wire, so those names are unavailable no matter what the server does.

## Reference data

`reference/` holds three tables of integers, and each is something this server has to know
in order to decide something.

**`mapgraph.json`** — grid size, collision and doorways for the 78 maps. Without it the map
graph is empty, the log says `warps go unchecked`, and moving between maps stops working.

The other two were read out of the client's own data files rather than off the wire, and
are here because watching the protocol cannot recover what they hold:

**`branches.json`** — where a cut-scene goes when the player picks option k, for the 209
scripts that ask. Branch targets sit in an instruction's operands, and operands never travel
on the wire. Without it every branch falls through: scenes still play, choices stop
mattering. It holds 5125 of the game's 15586 branches, and the other two thirds are left out
on purpose rather than for tidiness: their conditions are script variables this end will
always answer no to, and a no needs no target. It carries no text, no option wording, no
cast and no instruction stream.

**`quizkeys.json`** — about 6 KiB: how many questions each of the 80 lesson categories
holds, and the answers to the true-or-false half of the bank. A lesson message carries three
numbers and no text, and it is this end that picks the question and marks the answer, so a
key is the whole of what it needs; the four-choice half needs nothing at all, because this
server shuffles those itself and already knows where it dealt the right one. Without the
file a lesson draws the room and then asks nothing, because a question this server cannot
mark is one it should not ask. It carries no question text, no choice wording and no subject
names.

Neither means anything without your own copy of the game. What is deliberately not here is
the other half of each: script text, choice prompts, the cast, event keys. Those are the
game's content rather than a rule this server applies, so `/scl` and `/sc <name>` need an
export you make yourself and say so when there is none, and `/de` cannot name an event
without its file, though a key given directly as `<genre>:<index>` is still sent.

Two gaps are worth naming rather than leaving to be found. What is missing from a cut-scene
is nothing you can see. What is missing from a lesson is: the six ability parameters it
should move, stress and the breakdown that follows it, the reward items, and the hint
skills. The result screen reports no change to any of them because there is nothing there
to change, and the grade it awards is this server's own curve over the running score.

## Layout

| Path | |
|---|---|
| `start_servers.py`, `stop_servers.py` | start and stop everything |
| `set_auth_address.py` | the four-byte address change described above |
| `server/` | the services themselves; `run_all.py` binds them all in one asyncio loop and `mps_session.py`, the packet layer, is the bulk of it |
| `reference/` | the three tables above |
| `screenshots/` | the four pictures above; captures of a running client, not game files |
| `LICENSE`, `NOTICE` | Apache 2.0, and the attribution that redistribution has to carry |

## Troubleshooting

| Symptom | Cause |
|---|---|
| `ssl.SSLError: ('No cipher can be selected.',)` | LibreSSL-backed Python; see Requirements |
| `warps go unchecked` in the log | `reference/mapgraph.json` missing |
| every branch logs `fall-through`, choices do nothing | `reference/branches.json` missing |
| `no question bank, no questions`, a lesson asks nothing | `reference/quizkeys.json` missing |
| `already running pid=N` | a previous instance is still up; leave it, or `stop_servers.py` |
| `[authhttp] skip :443` | no privileges to bind a low port — or, on Windows, something else has it |
| `openssl is not on PATH` | nothing to generate the auth certificate with; see Requirements |
| `openssl did not produce the auth certificate` | it refused, and the retry did too — usually a crypto policy that forbids SHA-1; see "On Linux" |
| `[WinError 10013]` on a bind, and the server exits | that port is reserved or already held; see "On Windows" |
| `アップデートクライアントの起動に失敗しました`, and the log stays empty | `BootFirst.exe` was not run as administrator; see "Starting the game" |

The log is verbose and includes hex dumps of unrecognised packets. `no reply implemented`
marks a message this server has seen but does not answer yet.

## License

[Apache License 2.0](LICENSE). Copyright 2026 Shu Akirasora and contributors.

That covers this repository's own code and documentation, and nothing else. It grants no
rights in *Tokimeki Memorial ONLINE* or in any KONAMI property, and section 6 of the
license says as much about trademarks.

[`NOTICE`](NOTICE) carries the attribution, and the statement of what here does and does
not come out of KONAMI's software — no code, artwork, audio or text; two tables of
integers, and why a server cannot arbitrate without them. Section 4(d) of the license
makes that travel: if you redistribute this or anything derived from it, that text has to
go along.
Which is the point — those are the sentences that should still be attached to this code
after it has passed through hands that never read this README.
