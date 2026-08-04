# Tokimeki Memorial ONLINE — local server

A from-scratch server for *Tokimeki Memorial ONLINE* (KONAMI, 2006–2007, service ended),
written so that a surviving copy of the original client has something to connect to again.

Run it on your own machine, point your own copy of the client at it, and you can log in,
create a character, and walk around the school.

## About this project

The servers went away; the client did not. The campus, the characters and the scripts
are all still on the disc, intact and unreachable. This is the half that vanished,
rebuilt from the outside by watching what the client asks for.

It does not bring the game back, and the next section is blunt about how much is gone
for good. What it does is make the part that survived reachable again, on your own
machine, for as long as you care to keep a copy.

This is an independent implementation of the game's network protocol, produced by
analysing how the client communicates, for the purpose of interoperability: letting an
existing client program reach a server again.

It contains no code, artwork, audio or text taken from KONAMI's software. It does
contain two small tables of integers, read mechanically out of the client's data files,
because there are decisions this server is asked to make that it cannot make without them;
"Cut-scenes, and the branch table" and "Lessons, and the answer key" say which and why,
one section each. Message names, map names and structure offsets appear here because they
are the identifiers the protocol itself uses — a client will not accept any other wording
for them.

*Tokimeki Memorial* is a trademark of KONAMI. This project is not affiliated with,
endorsed by, or connected to KONAMI in any way.

## What it looks like

An original client, with nothing changed about it but where it looks for a server,
talking to this one.

| | |
|---|---|
| ![School select](screenshots/school-select.jpg) | ![Character creation](screenshots/character-create.jpg) |
| **Choosing a school.** The ten entries come from `MsgSvResultSchoolList`, which pairs each id with a student count. This server sends zero for every one of them, and 生徒募集中 is what the client prints when the count is zero. | **Making a character.** The client sends the finished sheet as one 74-byte `MsgClRequestCharacterCreate`; the server keeps the block verbatim and answers with a charaId. Three per account is the client's own limit, not a policy. |
| ![On the map](screenshots/map.jpg) | ![A conversation](screenshots/conversation.jpg) |
| **Standing in the courtyard.** Neither figure is there on the client's own initiative: the player is put into the scene by `MsgSvNotifyCharacterAdd`, the NPC by one of the `/npc` commands below. Without those pushes the scene loads empty. | **A scripted scene.** The client runs the script out of its own copy of the game and reports where it has got to; this end only answers the questions it stops on. A fresh clone reaches this picture — walking up to an NPC is enough, and the script itself is never sent by this end. What a clone does carry is where each choice leads, which is the subject of "Cut-scenes, and the branch table". |

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
  your own copy. Two files here were read out of the game rather than off the wire —
  `reference/branches.json` and `reference/quizkeys.json` — and both are integers only.
  "Cut-scenes, and the branch table" and "Lessons, and the answer key" say what is in
  each and why neither could be left out.

Not every number in this server is a fact. The wire format — message ids, structure
layouts, field offsets — was read off the protocol and is verifiable, as are the branch
targets described above. Some values only exist because the client needs *something*
there: movement speed, spawn positions, the school list. Those are inventions, and the
comments say so where they appear.

## Requirements

Only the standard library is used — no third-party packages, nothing to install, no
virtualenv to create. Two things have to be true of the machine:

- **A Python with a real OpenSSL.** Tested on 3.14. On macOS the system `python3` is built
  against LibreSSL and cannot start the TLS listeners; it dies with
  `ssl.SSLError: ('No cipher can be selected.',)`. Use a python.org, Homebrew or pyenv
  build. The python.org build for Windows carries a real OpenSSL, so there is nothing to
  check for there.
- **An `openssl` binary — once.** A self-signed certificate for the auth endpoint is
  generated on the first run, into `runtime/certs/`, and deliberately never regenerated
  after that. A run that finds `auth.pem` and `csk.pem` already there never looks for
  openssl at all, so this is a requirement for starting from an empty `runtime/certs/` and
  for nothing else — the two files can equally be made on another machine and copied in.

  macOS and Linux either ship one or have a package manager that has already dropped one
  in. Windows has neither, but Git for Windows carries a complete openssl in `Git\usr\bin`
  and by default puts it on PATH inside Git Bash and nowhere else — so **if you have Git
  you have openssl and need do nothing**, because those install locations are searched
  directly whether PATH knows about them or not. Failing that, winget, scoop and
  chocolatey all carry a package, as does the Win64 OpenSSL installer.

**Which system.** Written and run on macOS, and written to run on Windows. The server
itself is plain asyncio with no assumption about the platform in it; the launcher has
three that matter — finding what holds a port, asking whether a pid is still alive, and
detaching the child — and each of those has a Windows path written against how Windows
does that thing, rather than a POSIX call that happens to compile. Every instruction below
is the same on both, `py` in place of `python3`. Where that is not enough, it says so.

## Running the server

```sh
python3 start_servers.py
```

`start_servers.py` frees the ports it needs, starts the services in a detached session,
writes the pid to `runtime/run_all.pid` and appends to `runtime/run_all.log`. Everything
runs in one process, and `[system] all services started` in the log means it is up.

To stop:

```sh
python3 stop_servers.py
```

That finds the server by the ports it is listening on rather than by the pidfile, so it
works when the pidfile was lost or was never written because `run_all.py` was started by
hand, and it removes the pidfile afterwards.

Killing the pid in `runtime/run_all.pid` ends the same process, and leaves the pidfile
behind:

```sh
kill "$(cat runtime/run_all.pid)"                     # macOS and Linux
Stop-Process -Id (Get-Content runtime\run_all.pid)    # Windows, from PowerShell
```

Which costs nothing now and something later: a pidfile pointing at a dead process is
harmless until the number gets recycled, at which point `start_servers.py` sees a live pid
and refuses to start.

### On Windows

The same two commands, `py` in place of `python3`. Three things differ underneath them.

**Stopping is a hard kill** — and no less hard anywhere else. Windows has no SIGTERM, and
a process detached from every console (which is what `start_servers.py` asks for, so that
closing the window it was started from does not take the server with it) cannot be sent a
Ctrl-Break either, so it is terminated outright. That reads like a downgrade and is not
one: nothing here installs a SIGTERM handler, and an unhandled SIGTERM ends a process just
as abruptly. Nothing is lost either way, because no service writes its state on the way
out — `runtime/characters.json` is rewritten at each change, so what is on disk when the
process stops is everything it knew.

**Low ports are free, and taken anyway.** Windows asks for no privileges to bind 443, 80
or 50, so `[authhttp] skip` means something else there — not "run me as an administrator"
but "something already has this". IIS, BranchCache and anything else built on HTTP.sys are
the usual holders of 80 and 443. Harder to diagnose, and not confined to low ports:
Hyper-V and WSL reserve blocks of ports at boot, and a block covering 25573–25575 stops
the server dead rather than being skipped. List those with
`netsh int ipv4 show excludedportrange protocol=tcp`.

**The firewall asks once.** Windows Defender Firewall wants to know, the first time,
whether Python may accept connections. Answering no leaves a client on the same machine
working and every client anywhere else unable to arrive.

### Serving players on other machines

The listeners are on `0.0.0.0` and always were, so a client elsewhere can reach them. What
it cannot do is *find* them, because logging in is a chain of hops: the login-server lookup
answers with the address of the login server, and the login and school servers each answer
with the address of the next connection. Those answers default to `127.0.0.1`, which is
correct for a client on this machine and useless for one anywhere else — it sends every
remote player back to their own computer.

So tell the server the address clients reach it at:

```sh
python3 start_servers.py --advertise-ip 203.0.113.7
```

or set `TMO_ADVERTISE_IP`. The startup log says which one is in use:

```
[system] bind 0.0.0.0, advertising 203.0.113.7 to clients
```

It is not worked out from the socket, because it cannot be: behind NAT the address a client
must dial is not one this machine can see on any interface of its own. It is also not the
same thing as the address you gave `set_auth_address.py` — that one is compiled into the
client and only covers the authentication step — though on a single-box deployment both are
the same address.

Ports 25573, 25574, 25575 and 35573 have to be reachable from the client in addition to
whichever auth port it uses, so open them on any firewall in between.

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

Ports below 1024 need privileges, except on Windows, which asks for none and tends to have
something else holding them instead. Either way it is not fatal: the server logs
`[authhttp] skip :443 (...)` and carries on. Whether you need them depends on which
endpoint your client asks for.

## Connecting a client

You need your own copy of the original client; this repository neither distributes it nor
points at where to find one.

**One thing about your copy of the client changes: where it looks for the server. Nothing
about how it behaves does.** Its connections are Blowfish-enciphered, and this server
implements that layer and speaks it as the protocol's other endpoint. No check is
bypassed, no encryption is switched off, and every piece of code that ships in the binary
is the code that runs.

So the whole job is addressing. The client was built to reach KONAMI's servers, which no
longer exist, and it has three starting points. Two are hostnames, redirected by
configuring your own machine. The third is an address compiled into the client, which
nothing outside it can redirect; that one is four bytes, and there is a script here to
change them and to change them back.

The two hostnames:

| Hostname | What it is |
|---|---|
| `tmoupd.tokimekionline.com` | the update check — also plainly configurable, as `SERVER_ADDRESS` in the client's own `update.ini` |
| `tmollb.tokimekionline.com` | login-server lookup, the first thing the game does after the update check |

Resolve those to the machine running the server — a hosts-file entry each, or a local
resolver for the domain, whichever your setup makes easier. The client is a Windows
program, so the file to edit is the one on the machine it runs on:
`C:\Windows\System32\drivers\etc\hosts`, which needs an editor started as administrator.

Everything after those two follows along on its own: the login, game and school servers
are reached at whatever address the login-server lookup hands back, and this server hands
back the one it was started with (`--advertise-ip`, default `127.0.0.1` — see "Serving
players on other machines").

### The third one is authentication, and it is an address, not a name

The client opens TLS straight to a fixed `133.221.34.229`. The hostname
`sctrl01.game.konaminet.jp` travels along only as request metadata — it is in the `Host:`
header and nowhere in the decision of where to connect. No amount of name resolution
reaches an address that was never looked up.

So this one is told to the client directly:

```sh
python3 set_auth_address.py /path/to/tmo.exe 192.168.1.5
```

with the address of the machine running the server. Run it with no address to see what
your copy currently points at, and `--revert` to put the original address back.

**What that changes, exactly.** The client builds the address one octet at a time,
straight onto the stack, and hands the result to `connect()`:

```
mov byte [esp+0x28], 133
mov byte [esp+0x29], 221
mov byte [esp+0x2a], 34
mov byte [esp+0x2b], 229
```

Those four immediates are the whole of the target, and they are all the script writes to.
It changes no instruction, removes no check, disables nothing, and every octet is an
independent byte so any address fits. Reverting restores the original four, which — since
nothing else was ever touched — leaves the file byte-for-byte as it was.

It also refuses to work blind. It does not trust a hardcoded offset: it scans the file for
that instruction shape and requires it to occur exactly once, and stops if it does not.
The original is copied to `tmo.exe.orig` before the first write, an existing backup is
never overwritten, and `-n` prints what would change without writing anything.

Everything past that point is the client's own code doing its own thing. This server
implements the KONAMI-ID exchange the client asks for, and the authentication routine that
ships in the binary runs it to completion — four requests down one TLS connection — and
proceeds into the game. Two things that looked like obstacles turned out not to be:

- **The certificate is not checked.** The client carries a small trust store but does not
  enforce it; a locally generated self-signed certificate is accepted, and the revocation
  list its certificates point at is never fetched.
- **No part of the client has to be disabled** to get through this step, including its
  encryption, which stays on from the first packet to the last.

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
| `/sc`, `/scn`, `/sce`, `/scl`, `/sel` | script playback — see the next section |
| `/de [<genre>:<index>]` | the drama-event list — likewise |
| `/dms` | open the matching screen |

The client intercepts a number of words itself — `/help` and `/where` among them — and
never puts them on the wire, so those names are unavailable no matter what the server
does.

### Cut-scenes, and the branch table

Walk up to an NPC, start a conversation, and the cut-scene plays. The client finds the
script id in its own tables and asks for it, reads the script out of its own copy of the
game, and runs it; this end is only asked to arbitrate. The client reports each instruction
as it passes and waits at the two it may not decide alone — a branch, and a choice box.

Almost none of that needs data from here. The same conversation was run twice, once with
the script exported to `runtime/scripts/` and once with that directory empty. Both reached
the script's own `OP_END`. The second was offered no cast at all and accepted it, because
the script already declares its own actors.

The exception is what a branch resolves to, and what that buys is consequence. Every branch
asks the same question — does the condition hold? — and the condition lives in a VM this end
does not run, so the standing answer is no. A scene plays through on that. A choice does not
survive it: the box is drawn and answered, the script then asks "was it option k?" once per
option, collects a no each time, and falls out of the chain into the end of the scene.
Branch targets sit in an instruction's operands, and operands never go on the wire, so this
is the one thing that watching a script run cannot recover.

So `reference/branches.json` ships. It is the answer to one question — when a player picks
option k, where does the script go? — for the 209 scripts that ask it: a scriptId, a code
offset, and two integers per branch. 5125 of them, out of the 15586 branches in the game.
The other two thirds are left out on purpose rather than for tidiness: their conditions are
script variables, this end will always answer no, and a no needs no target — it is the
reported ip plus the width of the instruction, which is arithmetic, not data. The file
carries no text, no option wording, no cast and no instruction stream, and it means nothing
without your own copy of the game to run against.

What is still not shipped is `runtime/scripts/*.json` and `runtime/drama_events.json`, and
those are a different kind of thing: script text, a choice box's own prompt and options, the
cast, the event keys — the game's content, not a rule this server applies. `/scl` and
`/sc <name>` need an export and say so when there is none; `/de` cannot name an event
without its file, though a key given directly as `<genre>:<index>` is still sent. Nothing
else on the command list depends on either. The gap is real and is stated here rather than
left for you to find; what is missing from a cut-scene now is nothing you can see.

`/sc <id>` starts from an id alone, which is what a client's own request looks like, and
picks up that script's branches from the table; `/sc <name>` reads an export and gets the
rest with them. Neither works cold — a script offered to a client that has not asked for one
is ignored — so both are for steering a conversation already under way.

### Lessons, and the answer key

A lesson is a quiz: ten questions, and the message that asks one carries three numbers and
no text at all — a type, a difficulty and an index. The questions are in the client, where
they have to be, and it is this end that picks which one is asked and this end that says
whether the answer was right. Marking is the whole of the server's part, so an answer key is
the whole of what it needs.

It needs less of one than that sounds like. For the four-choice half of the bank — 6320 of
the 9186 questions — nothing ships at all, because the client's own files always put the
right answer first and it is this server that shuffles them before sending the order to draw
them in. It already knows where it dealt the right one; there is nothing to look up. That
leaves the true-or-false half, 2866 questions, one bit each, which split almost evenly and
so are simply the answers. Alongside them: how many questions each of the 80 categories
holds, because an index past the end of a category is one the client cannot resolve.

`reference/quizkeys.json` is those two things and is about 6 KiB. Per category, a count and
— for true-or-false ones — a string of `0`s and `1`s, one character per question. No question
text, no choice wording, no subject names; nothing in it can show anyone a question, and
like the branch table it means nothing without your own copy of the game.

What is not modelled, and would be visible to anyone who knows the original: the six ability
parameters a lesson should move, stress and the breakdown that follows it, the reward items,
and the hint skills. The result screen reports no change to any of them because there is
nothing there to change, which is a gap stated rather than a number invented. The grade a
lesson awards is this server's own curve over the running score — the manual names the
inputs and never the arithmetic.

## Layout

| Path | |
|---|---|
| `start_servers.py` | launcher; the supported way to start everything |
| `stop_servers.py` | the way to stop it; goes by port, so it works with no pidfile or a stale one |
| `set_auth_address.py` | the four-byte address change described under "Connecting a client" |
| `server/run_all.py` | binds every service in one asyncio loop |
| `server/mps_session.py` | packet layer, key exchange, message dispatch — the bulk of it |
| `server/mps_cipher.py` | the Blowfish variant the session layer speaks |
| `server/characters.py` | character creation, listing, entering the world, movement, map changes |
| `server/chat.py` | chat broadcast, and the server-side commands above |
| `server/mapgraph.py` | map geometry and doorway table |
| `server/romance.py` | the five romance candidates and the state kept for each |
| `server/curriculum.py`, `lesson.py` | report card and timetable; bells, classroom entry, school clock |
| `server/script.py` | cut-scene playback — see "Cut-scenes, and the branch table" |
| `server/facing.py` | the four-bit direction mask |
| `server/message_names.py` | message id to name |
| `server/state.py`, `common.py` | session state and shared service plumbing |
| `server/llb_server.py`, `login_server.py`, `updater_server.py`, `auth_http_server.py`, `world_server.py` | the smaller services |
| `reference/mapgraph.json` | grid size, collision and doorways for the 78 maps |
| `reference/branches.json` | where a scenario branch goes when a choice is taken |
| `reference/quizkeys.json` | how many questions each lesson category holds, and the true-or-false answers |
| `screenshots/` | the four pictures above; captures of a running client, not game files |
| `LICENSE`, `NOTICE` | Apache 2.0, and the attribution that redistribution has to carry |

Those three are the only data files, and each is a table of integers the server needs in
order to decide something. Without `mapgraph.json` the map graph is empty, the server says
`warps go unchecked`, and moving between maps stops working. Without `branches.json` every
branch falls through, silently: scenes still play, choices stop mattering. Without
`quizkeys.json` a lesson draws the room and the teacher's opening line and then asks
nothing, because a question this server cannot mark is one it should not ask.

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
| `[WinError 10013]` on a bind, and the server exits | that port is reserved or already held; see "On Windows" |

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
