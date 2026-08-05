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

## Setting it up

Two things have to be true before the game can reach this server: **the server has to be
running**, and **your copy of the client has to be told where it is**. The steps below do
both, in order, and assume nothing beyond being able to open a terminal window and type
into it.

Nothing here is bought, signed up for, or installed beyond Python itself. Everything the
server needs is in this repository, and every change made to your copy of the client is
four bytes that can be put back.

**What you need first:** your own copy of the original client — this repository does not
distribute it and does not point at where to find one — and a computer to run the server
on. Windows, macOS and Linux all work.

<details>
<summary><b>The short version</b>, if the words below are already familiar</summary>

```sh
python3 start_servers.py [--advertise-ip <server>]   # a Python with real OpenSSL
# two lines in the hosts file of the machine the *game* runs on:
#   <server>  tmollb.tokimekionline.com
#   <server>  tmoupd.tokimekionline.com
python3 set_auth_address.py /path/to/tmo.exe <server>
# then run BootFirst.exe (as administrator on Windows) and watch runtime/run_all.log
```

`<server>` is `127.0.0.1` when the game runs on the same machine as the server. The steps
below are the same four things, said in full.
</details>

### Step 0 — Which of the two shapes are you in?

Everything below asks for *your server address*, and which one it is depends on where the
game runs relative to the server. Decide this first and keep the answer to hand.

| Your setup | Your server address is |
|---|---|
| **One computer.** The server and the game run on the same machine — including the game running under Wine on a Mac or a Linux box, since Wine uses that machine's own network rather than one of its own. | `127.0.0.1` |
| **Two computers.** The server runs on one machine and the game on another: a second PC, or a Windows virtual machine on the same host. | the server machine's address on your local network, usually starting `192.168.` or `10.` |

To find that address, ask the **machine that will run the server** — not the one the game
is on, and not your public internet address:

| | |
|---|---|
| **Windows** | open Command Prompt, run `ipconfig`, and read the `IPv4 Address` line of the adapter you actually use |
| **macOS** | `ipconfig getifaddr en0` — if that prints nothing, try `en1`; or System Settings → Network → the connected service → Details |
| **Linux** | `hostname -I` and take the first address |

The examples below use `192.168.1.5` wherever your own address goes. If you are on one
computer, `127.0.0.1` goes in the same places.

### Step 1 — Install Python

Only the standard library is used: no `pip install`, no virtualenv, nothing to download
after Python itself. Any current Python 3 will do — this has been run on 3.11 and on 3.14.

**Windows.** Get the installer from [python.org](https://www.python.org/downloads/) and run
it. On the first screen tick **Add python.exe to PATH** before pressing *Install Now* —
without it the commands below will not be found. Then open a *new* Command Prompt and check:

```
py --version
```

**On Windows, every `python3` in this README is `py`.** That is the only difference.

**macOS.** Install from [python.org](https://www.python.org/downloads/), or with Homebrew:

```sh
brew install python
```

**Do not use the `python3` that comes with macOS.** It is built against LibreSSL and cannot
start this server's TLS listeners. To see which one you have:

```sh
python3 -c "import ssl; print(ssl.OPENSSL_VERSION)"
```

If that says `LibreSSL`, the wrong one is first in your PATH — the fix is to call the one
you just installed by its full path, which the python.org installer reports at the end and
Homebrew prints under `brew --prefix python`.

**Linux.** You almost certainly have it; `python3 --version` says so. If not, your
distribution's own package (`sudo apt install python3`, `sudo dnf install python3`) is
fine as it comes. Also make sure `openssl` is installed — most distributions have it, and
`openssl version` tells you.

> **What `openssl` is for.** The certificate this server's authentication endpoint needs is
> generated on the very first run, into `runtime/certs/`, and never again. macOS and Linux
> have the tool already. Windows does not, but Git for Windows carries a complete copy and
> this server looks there directly, **so if you have Git you need do nothing**. Failing
> that, `winget install openssl` (or scoop, or chocolatey) is enough. You will know it
> matters only if the first run says `openssl is not on PATH`.

### Step 2 — Get this server

With git:

```sh
git clone https://github.com/ShuAkirasora/tokimeki-memorial-online-revival.git
cd tokimeki-memorial-online-revival
```

Without it, use the green **Code** button on that page → **Download ZIP**, unpack it
anywhere you like, and open a terminal in the unpacked folder. There is nothing to build
and nothing to install; the folder is the program.

**Every command from here on is run from inside that folder.**

### Step 3 — Start the server

One computer:

```sh
python3 start_servers.py
```

Two computers — tell it the address players reach it at, from step 0:

```sh
python3 start_servers.py --advertise-ip 192.168.1.5
```

Either way you should see `started pid=…` followed by a few lines of log ending in

```
[system] all services started
```

That is the server up. It runs detached, so you can close the terminal; it keeps going
until you stop it.

> **Why the second form needs telling.** Logging in is a chain of hops and each one answers
> with the address of the next. Those answers default to `127.0.0.1`, which is correct for a
> game on the same machine and sends every remote player back to their own computer. The
> address cannot be worked out from the socket, because behind a router the address a client
> must dial is not one this machine can see on any interface of its own. `TMO_ADVERTISE_IP`
> in the environment does the same thing, and the startup log says which is in use.

Two platform-specific things can bite on the first run — **a Windows firewall prompt, and
low ports on Linux**. Both are under "Platform notes" below, and neither stops you getting
to step 4.

### Step 4 — Point the two hostnames at your server

The game looks for two of its three servers by name:

```
tmollb.tokimekionline.com
tmoupd.tokimekionline.com
```

Nothing inside the client decides where those two lead — your computer's `hosts` file does,
and two lines in it are the whole of this step.

⚠️ **The file to edit is on the machine the *game* runs on, not the machine the server runs
on.** If the game runs in a Windows virtual machine, it is that VM's file. If the game runs
under Wine, Wine has no name resolution of its own and uses the Mac's or Linux box's, so it
is that machine's `/etc/hosts` — not anything inside the Wine folder.

The two lines to add, with your address from step 0 in front:

```
192.168.1.5  tmollb.tokimekionline.com
192.168.1.5  tmoupd.tokimekionline.com
```

**On Windows:**

1. Press Start, type `notepad`, right-click **Notepad** in the results and choose **Run as
   administrator**. Answer *Yes*. (Opening the file any other way will not be allowed to
   save it.)
2. **File → Open**, paste `C:\Windows\System32\drivers\etc\hosts` into the filename box and
   press Enter. If the folder looks empty when you browse to it, set the file-type dropdown
   at the bottom right to **All Files**.
3. Go to the end of the file and add the two lines.
4. **File → Save**.

**On macOS and Linux:**

```sh
sudo nano /etc/hosts
```

It asks for your login password — nothing appears on screen while you type it, which is
normal. Move to the bottom of the file, add the two lines, then press `Ctrl-O` and `Enter`
to save and `Ctrl-X` to leave.

> **Nothing inside the game's own folder has to be edited for this.** The update check is
> also configurable, as `SERVER_ADDRESS` in the client's `update.ini`, but that file ships
> with the hostname in it — so the hosts entry covers it too and the file can be left alone.

Step 5 checks this step for you, so there is nothing to verify by hand yet.

### Step 5 — Point the authentication step at your server

The client's third destination is not a name at all: it opens a connection straight to a
fixed numeric address that was KONAMI's, and no amount of name resolution can redirect an
address that is never looked up. That one is told to the client directly, by changing the
four bytes of the address inside `tmo.exe`:

```sh
python3 set_auth_address.py /path/to/tmo.exe 192.168.1.5
```

`/path/to/tmo.exe` is your own copy, wherever the game is installed. On Windows that looks
like `py set_auth_address.py "C:\Games\TokimekiOnline\tmo.exe" 192.168.1.5`; under Wine the
file sits inside the bottle or prefix and your Mac or Linux `python3` can reach it there
directly.

> **Which machine to run this on.** Whichever one holds `tmo.exe` — so on a two-computer
> setup, install Python there as well (step 1), or copy `tmo.exe` to the server machine,
> run the command, and copy it back.

It prints what it is about to do, keeps a copy of the original as `tmo.exe.orig` before
writing anything, and then reports where the two hostnames from step 4 currently lead:

```
  the two names the client resolves for itself:
    tmollb.tokimekionline.com  -> 192.168.1.5      ok
    tmoupd.tokimekionline.com  -> 192.168.1.5      ok
```

**Two `ok` lines means step 4 is done as well.** Anything else and it prints the lines you
are missing. If it still shows an old answer after you have edited the file, your computer
has the previous lookup cached:

| | |
|---|---|
| **Windows** | `ipconfig /flushdns` |
| **macOS** | `sudo dscacheutil -flushcache; sudo killall -HUP mDNSResponder` |
| **Linux** | `sudo resolvectl flush-caches` |

Other things the script takes: no address at all to report what your copy currently points
at without changing anything, `--revert` to put KONAMI's original address back, `-n` to say
what it would do and write nothing, and `--no-lookup` to skip the hostname check. What
exactly those four bytes are, and why this is the only part of the client that changes, is
under "What changes in your copy of the client" below.

### Step 6 — Start the game

**The program to run is `BootFirst.exe`, not `tmo.exe`.** It starts `UpdateClient.exe`,
which performs the update check, and that in turn starts the game.

On Windows, run `BootFirst.exe` **as administrator** — right-click it and choose *Run as
administrator*. Without that you get

```
アップデートクライアントの起動に失敗しました
```

and nothing at all reaches this server, because nothing was ever started. The cause is on
the client's side and no server can answer it: `UpdateClient.exe` is a 32-bit binary with
no manifest and "Update" in its name, which is exactly what Windows' installer detection
looks for, so the system decides it requires elevation — and `BootFirst.exe` starts it with
`CreateProcess`, which cannot elevate. Beginning the chain already elevated is the whole of
the fix.

Under Wine this has not come up: the same chain starts as it is.

### Step 7 — Check that it worked

Everything the client does arrives in the log, `runtime/run_all.log`, in order. Watch it
while you start the game:

```sh
tail -f runtime/run_all.log
```

On Windows, in PowerShell:

```
Get-Content runtime\run_all.log -Wait -Tail 20
```

Each line below is one of the steps above proving itself, and the first one **missing**
tells you which step to go back to:

| A line like this | Means |
|---|---|
| `[system] all services started` | the server is up — step 3 |
| `[updater] … sent UPDATE_DONE` | the update check found you: `tmoupd` resolves — step 4 |
| `[llb35573] -> MsgSvResultLoginServer` | the login-server lookup found you: `tmollb` resolves — step 4 |
| `[authhttp] ACCEPT port=443` | authentication reached you: the four bytes are right — step 5 |
| `[mpslogin25573] …` | login accepted |
| `[mpsgame25574] …`, `[mpsschool25575] …` | the game and school servers; you are in |

After that you are at the school-select screen, and everything from there on is the game
itself. "Commands" below is what you can do once you are standing on the map.

### Stopping it, and starting it again later

```sh
python3 stop_servers.py
```

Starting it again is the same command as step 3. Steps 1, 2, 4 and 5 are done once and stay
done — unless you reinstall the game, which puts the original `tmo.exe` back, or your server
machine's address changes, which is worth pinning in your router if you are on the
two-computer setup.

Stopping goes by which ports are held rather than by the recorded process id, so it still
works if that record is stale or was never written.

## Platform notes

This server was written and run on macOS and on Linux (Debian 12), and the Windows paths
have been run on Windows. Every command above is the same on all three, with `py` in place
of `python3` on Windows. Neither list below is required reading before you start — each is
the small print for one platform, and the walkthrough points at them where they matter.

### On Windows

- **Stopping is a hard kill** — and no less hard anywhere else. Windows has no SIGTERM, and
  a process detached from every console cannot be sent a Ctrl-Break either. Nothing is lost
  to that: no service writes its state on the way out, and `runtime/characters.json` is
  rewritten at every change, so what is on disk is everything the server knew.
- **Low ports are free, and taken anyway.** Binding 443, 80 or 50 needs no privileges here,
  so `[authhttp] skip` means something else already has the port — usually IIS or another
  HTTP.sys service. Hyper-V and WSL also reserve blocks of ports at boot, and a block
  covering 25573–25575 stops the server dead rather than being skipped; list them with
  `netsh int ipv4 show excludedportrange protocol=tcp`.
- **The firewall asks once**, on the first start. Answering no leaves a game on this machine
  working and every game anywhere else unable to arrive.

### On Linux

Nothing has to be installed: what holds a port is read out of `/proc`, not out of `lsof`,
which is not on a Linux machine unless somebody put it there. Two things are worth knowing
before the first run.

**Low ports are privileged, and 443 and 50 are the two the authentication step is most
likely to want.** `[authhttp] skip :443 (...)` in the log is exactly that, and the server
carries on without them. Either start it as root, or lift the restriction for everyone once:

```sh
sudo sysctl -w net.ipv4.ip_unprivileged_port_start=50
```

The startup log suggests the same line when it is the reason a port was skipped, and a file
in `/etc/sysctl.d/` makes it survive a reboot; with it applied, an ordinary user's server
takes all three. Check what already holds 80 and 443 before blaming privileges — on a
machine with a web server installed, something usually does.

**The authentication certificate has to be SHA-1, and your distribution may refuse to make
one.** The client accepts no other kind, while RHEL, Fedora and their derivatives run every
OpenSSL process under a system-wide crypto policy that since RHEL 9 will not *produce* a
SHA-1 signature. The first run notices that refusal and repeats the command with the policy
overridden for that one process — nothing about the machine's own policy changes, and
nothing else on it will accept anything it did not accept before. If even that fails, the
server stops and prints what openssl said, rather than coming up with an authentication
endpoint that cannot complete a handshake.

Firewalls are the last thing: if `ufw` or `firewalld` is running, the ports below have to be
opened there too.

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

The listeners are on `0.0.0.0`, so a game on another machine can reach them. Ports 25573,
25574, 25575 and 35573 have to be reachable from it in addition to whichever authentication
port it uses, so open those on any firewall in between.

Ports below 1024 need privileges, except on Windows. Either way it is not fatal: the server
logs `[authhttp] skip :443 (...)` and carries on. Whether you need them depends on which
endpoint your client asks for, and on Linux there is a way to have them without running as
root — see "On Linux".

## What changes in your copy of the client

**One thing changes: where it looks for a server. Nothing about how it behaves does.** Its
connections are Blowfish-enciphered, and this server implements that layer and speaks it as
the protocol's other endpoint. No check is bypassed, no encryption is switched off, and
every piece of code that ships in the binary is the code that runs.

So the whole job is addressing, and the client has three starting points — which is why the
setup above has two separate steps for it:

| | How the client finds it | How it is redirected |
|---|---|---|
| `tmoupd.tokimekionline.com` | hostname — the update check | name resolution: step 4 |
| `tmollb.tokimekionline.com` | hostname — the login-server lookup, the first thing the game does after the update check | name resolution: step 4 |
| `133.221.34.229` | a fixed numeric address, straight to `connect()` | the four bytes: step 5 |

Everything after those three follows along on its own: the login, game and school servers
are reached at whatever address the login-server lookup hands back, and this server hands
back the one it was started with.

The third one takes a different route because it has to. The hostname
`sctrl01.game.konaminet.jp` travels along with that connection, but only as request
metadata in the `Host:` header, and takes no part in deciding where to connect — so no
amount of name resolution reaches an address that was never looked up.

**What the four bytes are, exactly.** The client builds the address one octet at a time,
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

The route in step 4 has been used here end to end: a client under Wine on macOS, two
entries in the host's `/etc/hosts`, and a server on a different machine — update check,
login-server lookup, authentication, login, game and school all arrived.

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
| `runtime/` | created on the first run: the log, the certificate, and your characters |
| `screenshots/` | the four pictures above; captures of a running client, not game files |
| `LICENSE`, `NOTICE` | Apache 2.0, and the attribution that redistribution has to carry |

## Troubleshooting

| Symptom | Cause |
|---|---|
| the game starts but the log stays completely empty | `BootFirst.exe` was not run as administrator — step 6 |
| `アップデートクライアントの起動に失敗しました` | the same thing, said by the client — step 6 |
| the log stops after `[updater]`, no `[llb35573]` | only one of the two hosts lines is there, or it is on the wrong machine — step 4 |
| the log stops after `[llb35573]`, no `[authhttp]` | the four bytes were not written, or were written to a different copy of `tmo.exe` — step 5; if the log also says `[authhttp] skip :443`, that port was refused or taken |
| the log stops after `[authhttp]`, no `[mpslogin25573]` | the game could not reach port 25573 at the address the lookup gave it: either a firewall in between, or the server was started without the right `--advertise-ip` — step 3 |
| every remote player is sent back to their own computer | the server was started without `--advertise-ip` — step 3 |
| `ssl.SSLError: ('No cipher can be selected.',)` | the LibreSSL-backed Python; see step 1 |
| `openssl is not on PATH` | nothing to generate the authentication certificate with; see step 1 |
| `openssl did not produce the auth certificate` | it refused, and the retry did too — usually a crypto policy that forbids SHA-1; see "On Linux" |
| `already running pid=N` | a previous instance is still up; leave it, or run `stop_servers.py` |
| `[WinError 10013]` on a bind, and the server exits | that port is reserved or already held; see "On Windows" |
| `warps go unchecked` in the log | `reference/mapgraph.json` missing |
| every branch logs `fall-through`, choices do nothing | `reference/branches.json` missing |
| `no question bank, no questions`, a lesson asks nothing | `reference/quizkeys.json` missing |

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
