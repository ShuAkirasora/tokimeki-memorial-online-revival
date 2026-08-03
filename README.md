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

It contains no code, artwork, audio, text or data files taken from KONAMI's software.
Message names, map names and structure offsets appear here because they are the
identifiers the protocol itself uses — a client will not accept any other wording for
them.

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
  your own copy.

Not every number in this server is a fact. The wire format — message ids, structure
layouts, field offsets — was read off the protocol and is verifiable. Some values only
exist because the client needs *something* there: movement speed, spawn positions, the
school list. Those are inventions, and the comments say so where they appear.

## Requirements

- **Python with a real OpenSSL.** Tested on 3.14. Only the standard library is used — no
  third-party packages.

  On macOS, the system `python3` is built against LibreSSL and cannot start the TLS
  listeners; it dies with `ssl.SSLError: ('No cipher can be selected.',)`. Use a
  python.org, Homebrew or pyenv build.
- **`openssl` on PATH.** A self-signed certificate for the auth endpoint is generated on
  first run, into `runtime/certs/`.

## Running the server

```sh
python3 -m venv .venv
.venv/bin/python start_servers.py
```

`start_servers.py` frees the ports it needs, starts the services in a detached session,
writes the pid to `runtime/run_all.pid` and appends to `runtime/run_all.log`. To stop:

```sh
kill "$(cat runtime/run_all.pid)"
```

Everything runs in one process. `[system] all services started` in the log means it is up.

If the pidfile is gone, or the process was started by hand and never wrote one,
`stop_servers.py` finds the server by the ports it listens on instead:

```sh
.venv/bin/python stop_servers.py
```

It also removes the pidfile, which the `kill` above does not: a pidfile left pointing at
a dead process is harmless until that number gets recycled, at which point
`start_servers.py` sees a live pid and refuses to start.

### Serving players on other machines

The listeners are on `0.0.0.0` and always were, so a client elsewhere can reach them. What
it cannot do is *find* them, because logging in is a chain of hops: the login-server lookup
answers with the address of the login server, and the login and school servers each answer
with the address of the next connection. Those answers default to `127.0.0.1`, which is
correct for a client on this machine and useless for one anywhere else — it sends every
remote player back to their own computer.

So tell the server the address clients reach it at:

```sh
.venv/bin/python start_servers.py --advertise-ip 203.0.113.7
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

Ports below 1024 need privileges. If they cannot be bound, that is not fatal — the server
logs `[authhttp] skip :443 (...)` and carries on. Whether you need them depends on which
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
resolver for the domain, whichever your setup makes easier. Everything after them follows
along on its own: the login, game and school servers are reached at whatever address the
login-server lookup hands back, and this server hands back the one it was started with
(`--advertise-ip`, default `127.0.0.1` — see "Serving players on other machines").

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
| `/sc`, `/scn`, `/sce`, `/scl`, `/sel` | script playback — see the next section |
| `/de [<genre>:<index>]` | the drama-event list — likewise |
| `/dms` | open the matching screen |

The client intercepts a number of words itself — `/help` and `/where` among them — and
never puts them on the wire, so those names are unavailable no matter what the server
does.

### What needs data this repository does not ship

`/sc` plays one of the game's own cut-scene scripts back to the client instruction by
instruction, and `/de` sends the list of drama events. Both read JSON out of `runtime/`,
and that JSON is made from the game's own content — so neither the files nor a way to
produce them is included here.

With `runtime/scripts/` empty, `/scl` reports that there are no scripts and `/sc` cannot
find one; with no `runtime/drama_events.json`, `/de` cannot name an event, though it will
still send a key given directly as `<genre>:<index>`. Nothing else on the list above
depends on either file. This is a gap, and it is stated here as one rather than left for
you to discover.

## Layout

| Path | |
|---|---|
| `start_servers.py` | launcher; the supported way to start everything |
| `stop_servers.py` | stop by port when the pidfile is missing or stale |
| `set_auth_address.py` | the four-byte address change described under "Connecting a client" |
| `server/run_all.py` | binds every service in one asyncio loop |
| `server/mps_session.py` | packet layer, key exchange, message dispatch — the bulk of it |
| `server/mps_cipher.py` | the Blowfish variant the session layer speaks |
| `server/characters.py` | character creation, listing, entering the world, movement, map changes |
| `server/chat.py` | chat broadcast, and the server-side commands above |
| `server/mapgraph.py` | map geometry and doorway table |
| `server/romance.py` | the five romance candidates and the state kept for each |
| `server/curriculum.py`, `lesson.py` | report card and timetable; bells, classroom entry, school clock |
| `server/script.py` | cut-scene playback — see "What needs data this repository does not ship" |
| `server/facing.py` | the four-bit direction mask |
| `server/message_names.py` | message id to name |
| `server/state.py`, `common.py` | session state and shared service plumbing |
| `server/llb_server.py`, `login_server.py`, `updater_server.py`, `auth_http_server.py`, `world_server.py` | the smaller services |
| `reference/mapgraph.json` | grid size, collision and doorways for the 78 maps |
| `LICENSE`, `NOTICE` | Apache 2.0, and the attribution that redistribution has to carry |

`reference/mapgraph.json` is the only data file. Without it the map graph is empty, the
server says `warps go unchecked`, and moving between maps stops working.

## Troubleshooting

| Symptom | Cause |
|---|---|
| `ssl.SSLError: ('No cipher can be selected.',)` | LibreSSL-backed Python; see Requirements |
| `warps go unchecked` in the log | `reference/mapgraph.json` missing |
| `already running pid=N` | a previous instance is still up; leave it, or `stop_servers.py` |
| `[authhttp] skip :443` | not running with the privileges to bind a low port |

The log is verbose and includes hex dumps of unrecognised packets. `no reply implemented`
marks a message this server has seen but does not answer yet.

## License

[Apache License 2.0](LICENSE). Copyright 2026 Shu Akirasora and contributors.

That covers this repository's own code and documentation, and nothing else. It grants no
rights in *Tokimeki Memorial ONLINE* or in any KONAMI property, and section 6 of the
license says as much about trademarks.

[`NOTICE`](NOTICE) carries the attribution, and the statement that nothing here comes
out of KONAMI's software. Section 4(d) of the license makes that travel: if you
redistribute this or anything derived from it, that text has to go along. Which is the
point — those are the sentences that should still be attached to this code after it has
passed through hands that never read this README.
