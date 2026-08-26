# Tokimeki Memorial ONLINE — local server

A from-scratch server for *Tokimeki Memorial ONLINE* (KONAMI, 2006–2007, service ended),
written so that a surviving copy of the original client has something to connect to again.

Run it on your own machine, point your own copy of the client at it, and you can log in,
create a character, go to school, sit through a lesson, and play a club match against
somebody on a second machine.

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
four small tables of integers, read mechanically out of the client's data files, because
there are decisions this server is asked to make that it cannot make without them — see
[Reference data](#reference-data). Message names, map names and structure offsets appear
here because they are the identifiers the protocol itself uses; a client will not accept any
other wording for them.

*Tokimeki Memorial* is a trademark of KONAMI. This project is not affiliated with, endorsed
by, or connected to KONAMI in any way.

## What works

Every line below is something a client has been watched doing against this server. What
they do *not* add up to is the first bullet of the next section.

**Getting in.** The update check, the authentication step, the login-server lookup, and the
login, game and school servers behind it. Registration codes are issued here and bound to a
KONAMI ID; an account keeps its own characters and its own saves, and several accounts can
be on the server at once. Choosing a school, making a character, deleting one, going to
school, logging out from the options window, and coming back to the square you left.

**The campus.** Walking, the doorways and staircases between the 78 maps, and both your
position and your map kept across a logout. Two players standing on the same map see each
other and share the chat bar along the bottom, and either can right-click the other for the
six-slot interaction menu behind it: the address book (ask, accept, decline, remove), the
friendly group (found one, invite, accept, expel, leave, disband, hand the leadership on,
set its catchphrase and whether it is listed), a name card, the career card with an
achievement list under it, and a report card that opens only if the person it belongs to
ticked the box for it.

**School.** The timetable is the client's own, and the bells ring off it without being
asked — a warning bell, a start bell, and if you are sitting in your own classroom when the
second one goes, you are in the lesson. Ten questions, true-or-false and multiple choice,
the eight help skills, the separate chat bar a lesson has of its own, and a result screen at
the end. An exam period puts a twenty-question paper with a ten-minute clock through the
same doorway, and the marks land on the report card. Behind all of it: the six ability
parameters, stress and condition, and the injury that comes of training while carrying too
much of both.

**Clubs.** Joining one of the eight and leaving it, the club-deck window's three lists —
keywords, club skills with the level each has reached, and the three decks they go into —
and the item window's six tabs, where a thing can be worn, used, thrown away, or put in the
locker the whole account shares. A training room goes up on the noticeboard, other players
join it, and the match that follows runs its full eight turns: the cards each side plays,
the order they resolve in, the effects and reactions they draw, status ailments that outlast
the turn that caused them, a result screen, and a player who drops out halfway carried to
the end rather than stranding everybody else.

**Scripted events.** The client plays a cut-scene out of its own copy of the game and stops
at every branch to ask this end which way to go — which is how the original worked, since
the client's own arithmetic instructions are logging stubs that evaluate nothing. So the
register file is here, and with it: right-click conversations with the candidates who have
appeared, the choice boxes inside them and the intimacy each answer is worth, the opening
tutorial, the letter in the classroom lockers, the drama events, and the ending with its
staff roll. Two of the scripts running here are the *original server's* own — the pair
behind the row of lockers that decides whether a letter is waiting — read out of the game's
data and run on this side, which is the side they always ran on.

## What this is not

- **Not a restored game.** [What works](#what-works) is a list of subsystems, and a list of
  subsystems is not a game. A good deal of it now happens through the client's own windows —
  the bells ring by themselves, a lesson runs from the seat to the result screen, a whole
  club match is played without touching the console — but the campus is still populated by
  hand, every scripted event is still started by hand, and whatever decided *when* a story
  happened has no counterpart here. The original server's own logic — how NPCs moved, what
  fired an event, what advanced the dating-sim progression — did not survive alongside the
  client, and none of it is reimplemented here. What you get is a school you can walk into
  and spend an afternoon in, not a game you can play through.
- **Not a service.** This repository is the software, and nothing here is or will be sold.
  It does not hand out a server to join: running one is something you do on your own
  machine, which is what the whole of *Connecting a client* is about.
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

It also decides what the server listens on, so that is not a second thing to get right:
without it the listeners are on `127.0.0.1` and a game on another machine reaches nothing;
with it they are on every interface. `--bind` overrides that when the derivation is wrong for
you. [Ports](#ports) has the detail, including the two rows that stay on `127.0.0.1` either
way.

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

### All three at once

`play.py` does exactly those three and then starts the game. On Windows it is a double-click
on **`Play.cmd`**, which is the same thing with the administrator prompt in front of it;
elsewhere it is `python3 play.py`. It asks where the server is the first time and remembers
the answer, so the second time is the double-click and nothing else.

This folder has to be on the **machine the game is on**, which on a two-computer setup is not
the one running the server. Copying the whole folder there is fine, and so is copying only
`play.py`, `Play.cmd` and `set_auth_address.py`.

```sh
python3 play.py --server 192.168.1.5   # say it outright instead of being asked
python3 play.py --dry-run              # what it would change, writing nothing
python3 play.py --revert               # put the hosts file and the four bytes back
python3 play.py --no-launch            # set everything up, start nothing
```

Nothing it does is one-way. The hosts file is copied before it is first written and a line
of yours that points one of these two names elsewhere is commented out rather than deleted,
with the whole original line kept after the marker; `--revert` puts it back and takes the
four bytes back to what the disc shipped. It also knocks on the server's ports before
starting the game, so a server that is not running says so instead of becoming a client that
sits there.

On Windows it needs administrator rights and says so — the game already required them, and
the hosts file needs the same, so `Play.cmd` asks once and does both inside it. On macOS and
Linux only the hosts file does, and only that one step goes through `sudo`; the game is not
started as root. There, `--launch-with` names the command that runs Windows programs
(`wine` by default).

The rest of this section is the same three steps by hand, and why each of them is there.

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

Plain HTTP unless you give it something better, and the certificate the game insists on is
no help: 1024-bit RSA signed with SHA-1, which no current browser will open. So by default
the personal key crosses that connection in the clear — nothing when the browser is on the
server's own machine, a password in plaintext when it is not. **Pick one you do not use
anywhere else.** A server people reach over the internet can put an ordinary modern
certificate in front of that one page with `--registration-cert fullchain.pem
--registration-key privkey.pem`; it is a separate certificate from the one the game speaks
to, and it changes nothing about the game's own connection.

Originally the code came printed in the box and the player bound it to their KONAMI ID on
KONAMI's website, and both halves are still here separately: `issue_code.py` is the
printing, and **http://127.0.0.1:12013/register** is the binding. That is the way in for a
code somebody issued by hand and gave you.

```sh
python3 issue_code.py --unregistered      # prints something like WJUH-RTDC-M39X-HCDN-U26X
```

Two limits sit on that page, and only one of them ever says so. Answers to an address that
has asked a lot in the last hour, or been given a lot of codes today, start arriving a few
seconds late and are otherwise unchanged — an address can be a whole building, so nothing
here refuses on the strength of one. The exception is fifty self-issued codes in a day,
which closes the self-serve form until tomorrow and tells you it has; `/register` and
`issue_code.py` are unaffected, so a code issued by hand still works on the day it happens.
Login answers slow down the same way after five wrong personal keys in a row for the same
account, and the right key is never held back for a moment. Through a held login the client
shows the same 「接続処理を行っています」 it shows through an ordinary one, so this reads as
a slow network rather than as anything having gone wrong — see `server/throttle.py`, which
also explains why none of this is a security boundary.

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

| Port | Service | Reached by |
|---|---|---|
| 12000 | update check the client performs at startup | the game |
| 35573 | login-server lookup — answers "which host do I log in to" | the game |
| 25573 | login | the game |
| 25574 | game | the game |
| 25575 | school | the game |
| 443 | account auth, TLS | the game |
| 12013 | the registration page | a browser |
| 50, 8011, 12011 | the same auth service on other ports, TLS | nothing, ever |
| 80, 12012 | the same auth service, plaintext | nothing, ever |
| 12010, 12020 | early stubs; the current login flow does not use them | nothing, ever |

**The last three rows have never had a connection**, across every log this project has kept,
and the client's authentication URL has no port in it, so it uses 443 and only 443. They stay
bound to `127.0.0.1` whatever `--bind` says: they exist for this project's own tests, and
there is no configuration under which somebody else should reach them.

The rest follow `--bind`, which is derived from `--advertise-ip` rather than being a second
thing to remember. Advertising `127.0.0.1` tells every client to dial its own machine, so a
socket open to the network under that setting serves nobody — the default therefore listens
on `127.0.0.1` alone, and giving `--advertise-ip` opens the six above along with it. Then
25573, 25574, 25575, 35573, 12000 and 443 have to be reachable from the game's machine, so
open those on any firewall in between.

Ports below 1024 need privileges on Linux, and none on Windows. **macOS is stranger than
either**: an ordinary user may bind `0.0.0.0:443` but *not* `127.0.0.1:443` — the wildcard is
the permitted one, which is the opposite of the intuition that a narrower bind asks for less.
So on macOS the default configuration opens 443 wide because it has no choice, and closes any
connection that is not from this machine without reading it; the log says so at startup. A
port that cannot be bound at all is not fatal — `[authhttp] skip :443 (...)` and the server
carries on.

## Commands

Typed into the game's own chat bar and handled by this server. They are a console for driving
the protocol rather than gameplay: most of them exist because sending a message by hand was
the only way to find out what the client would do with it. `/cmds` prints the whole list
inside the game, which is the copy that cannot go stale; the tables below are the same list,
grouped.

**Where you are.**

| Command | Effect |
|---|---|
| `/go <map name or id> [x y]` | move to a map |
| `/pos` | print where you are |
| `/maps <name>` | search the map table |
| `/dirs` | drop a marker for each of the sixteen direction values |
| `/act [<first>]` | the same ruler for the `action` field, sixteen values at a time |

**What a character has.** Each of these reads a sheet the client draws somewhere and writes
it back to the save.

| Command | Effect |
|---|---|
| `/rom [name] [debut\|talk\|ev\|p <n>]` | read and move the romance state |
| `/couple [<charaId>\|clear]` | the couple flag, and who the partner is |
| `/card [ruler\|clear\|<subject> …]` | the report card |
| `/ab [ruler\|clear\|p <six values>\|<ability> <n>]` | ability parameters, stress, condition, days |
| `/opt [<row> on\|off\|clear]` | the four options rows, per character |
| `/career [title\|visits\|hours\|add\|del\|probe …]` | the career card and the achievements under it |
| `/post [class <key>\|club <n>\|clear]` | the two posts printed on the name card |
| `/buka [<1-8>\|part\|clear]` | join a club, or leave one |
| `/kw [n <count>\|add\|del\|deck <0-2> …]` | keywords owned, and what sits in each deck |
| `/cs [n <count>\|add\|del\|deck <0-2> …]` | club skills owned, and how complete each one is |
| `/item [sample\|n <count>\|add\|del\|probe]` | the inventory, by tab |
| `/locker [n <count>\|add\|del\|clear]` | the locker the whole account shares |
| `/group [create\|join\|leave\|disband\|hand\|qual]` | the friendly-group store |

**School.**

| Command | Effect |
|---|---|
| `/jikan [day]` | the timetable |
| `/bell [<subject>\|ready\|force\|ng <n>\|imp <n>]` | ring the warning and start bells by hand |
| `/lopt [seats\|speech\|words\|lunch] <n>` | knobs on the lesson message |
| `/quiz [sec <n>\|wait <n>\|ab …]` | the question in progress and which choice is right; timers |
| `/skill [<refusal> <reason>\|clear]` | what a refused help skill puts on screen |
| `/exam [on\|off\|ready\|force\|ans\|sec <n>]` | the exam period, its bell, the answers, the clock |

**NPCs, scripts and events.**

| Command | Effect |
|---|---|
| `/npc <cat>:<id> [<cat>:<id>]` | put an NPC on the map; a second key names a script |
| `/npca [<first> <last> [category]]` | place every romance candidate who has appeared |
| `/npcx` | stop replacing them |
| `/nev [<cat>:<id>]` | set the conversation-event key |
| `/smenu [<key>]` | which sub-menu a map object opens |
| `/evend [auto\|manual]` | how the end of an NPC event is answered |
| `/sc <name or id> [ctrl] [actor:npcId]` | start a script |
| `/sc next <name\|off>` | swap the script the next conversation asks for |
| `/scn`, `/sce`, `/scl` | step it on, end it, list what has been exported |
| `/scb [<scriptId> <ip> <target>\|clear]` | force a branch to go somewhere |
| `/sel [<select> [timer]]` | ask a choice box again |
| `/pwt [on\|off]` | whether the wait-for-players instruction is released |
| `/de [<genre>:<index>]` | the drama-event list |
| `/dms` | open the matching screen |
| `/raw <msgid16> [hex]` | send one message by hand, by number |

**Probes.** These are for reading the client rather than for playing: `/cb` drives a club
battle a piece at a time, and `/seq` replies with a sequence number that goes backwards, to
find out what the client makes of it.

The client intercepts a number of words itself — `/help` and `/where` among them — and never
puts them on the wire, so those names are unavailable no matter what the server does.

## Reference data

`reference/` holds four tables of integers, and each is something this server has to know in
order to decide something.

**`mapgraph.json`** — grid size, collision and doorways for the 78 maps. Without it the map
graph is empty, the log says `warps go unchecked`, and moving between maps stops working.

All four come out of the client's own data files. `mapgraph.json` is the one the wire can
confirm — the client decides where a door leads and this end only agrees, so the graph is a
check on that agreement rather than the source of it. The other three are here because
watching the protocol cannot recover what they hold at all:

**`branches.json`** — where a cut-scene goes when the player picks option k, for the 209
scripts that ask. Branch targets sit in an instruction's operands, and operands never travel
on the wire. Without it every branch falls through: scenes still play, choices stop mattering.
It holds 5125 of the game's 15586 branches, and the other two thirds are left out on purpose:
their conditions are script variables this end will always answer no to, and a no needs no
target. It carries no text, no option wording, no cast and no instruction stream.

**`intimacy.json`** — under 9 KiB: what one conversation with a romance candidate is worth.
The game has 327 of them and this end has to keep the score, because intimacy never crosses
the wire: the client asks for a conversation by number, plays it, and says only that it
finished. It holds two tables keyed the same way. `gains` is the values a conversation can
add — most add a flat 12, 22 of them add nothing at all, and the ones that offer the player
an answer add 10, 12 or 15 depending on which. `byChoice` is which answer adds which, for
the 96 conversations where that is a question worth asking; the client reports the line the
player clicked, numbered the way the script numbers it, so this end can credit the right one.
One of the 327 names a script the client archive does not contain and is left out rather than
guessed at, because absent and worthless are not the same thing. Without the file every
conversation is credited 12, including the ones worth nothing. It carries no dialogue, no
answer wording and no character names.

A conversation that asks a question this end has no row for is credited the smallest of its
values instead — a floor rather than a reading. That happens when the answer never arrives,
and for the five conversations that ask something and pay nothing whichever line is taken.

**`quizkeys.json`** — about 6 KiB: how many questions each of the 80 lesson categories holds,
and the answers to the true-or-false half of the bank. A lesson message carries three numbers
and no text, and it is this end that picks the question and marks the answer, so a key is the
whole of what it needs; the four-choice half needs nothing at all, because this server
shuffles those itself and already knows where it dealt the right one. Without the file a
lesson draws the room and then asks nothing. It carries no question text, no choice wording
and no subject names.

None of them means anything without your own copy of the game. What is deliberately not here
is the other half of each: script text, choice prompts, the cast, event keys. Those are the
game's content rather than a rule this server applies, so `/scl` and `/sc <name>` need an
export you make yourself and say so when there is none, and `/de` cannot name an event without
its file, though a key given directly as `<genre>:<index>` is still sent.

There is a second kind of export, for the same reason. `branches.json` answers a branch out
of a table; `server/gs3vm.py` answers one by running the script's own arithmetic alongside
the client, which is where that arithmetic always ran — the client's instructions for it are
logging stubs that evaluate nothing. Running it needs the instruction stream rather than a
lookup, so it is an export too, and optional in the same way: without one, every branch of
that kind falls through and the scene keeps whichever backdrop it opened with — and a scene
that opens with none stays black. What the interpreter cannot work out it declines to answer
rather than guessing at.

Two gaps are worth naming rather than leaving to be found. What `branches.json` leaves out is
nothing you can see. What is missing from a lesson is: the six ability parameters it should
move, stress and the breakdown that follows it, the reward items, and the hint skills. The
result screen reports no change to any of them because there is nothing there to change, and
the grade it awards is this server's own curve over the running score.

## Repository layout

| Path | |
|---|---|
| `start_servers.py`, `stop_servers.py` | start and stop everything |
| `Play.cmd`, `play.py` | the client half in one run: hosts, the four bytes, and the game started. `Play.cmd` is the Windows double-click and asks for the rights the other one needs |
| `set_auth_address.py` | the four-byte address change described above |
| `issue_code.py` | issue, list, revoke and unbind registration codes |
| `server/` | the services themselves; `run_all.py` binds them all in one asyncio loop and `mps_session.py`, the packet layer, is the bulk of it |
| `reference/` | the four tables above |
| `runtime/` | created on the first run: the log, the certificate, your characters, any script exports you make, and the answers `play.py` remembers |
| `screenshots/` | the four pictures above; captures of a running client, not game files |
| `LICENSE`, `NOTICE` | Apache 2.0, and the attribution that redistribution has to carry |

## Troubleshooting

| Symptom | Cause |
|---|---|
| 「レジストレーションコードは存在しません」 | the code was not issued here — `issue_code.py`, step 4 |
| 「レジストレーションコードが登録されていません」 | the code exists but nobody has bound it on port 12013 |
| 「ユーザ情報が正しくありません」 | that code is registered to a different KONAMI ID, or the personal key is wrong |
| the game starts but the log stays completely empty | `BootFirst.exe` was not run as administrator |
| `play.py` cannot find the game | give it `--game-dir`, or drag the folder into the window when it asks |
| a name still leads somewhere else after `play.py` wrote the hosts file | something is answering ahead of it — a VPN, or a router handing out its own answers |
| `アップデートクライアントの起動に失敗しました` | the same thing, said by the client |
| the log stops after `[updater]`, no `[llb35573]` | only one of the two hosts lines is there, or it is on the wrong machine |
| the log stops after `[llb35573]`, no `[authhttp]` | the four bytes were not written, or were written to a different copy of `tmo.exe`; if the log also says `[authhttp] skip :443`, that port was refused or taken |
| the log stops after `[authhttp]`, no `[mpslogin25573]` | the game could not reach port 25573 at the address the lookup gave it: a firewall in between, or the server was started without the right `--advertise-ip` |
| every remote player is sent back to their own computer | the server was started without `--advertise-ip` |
| a game on another machine reaches nothing at all, and the server's log is empty | the same cause: without `--advertise-ip` the listeners are on `127.0.0.1` only, which the startup log says |
| `ssl.SSLError: ('No cipher can be selected.',)` | the LibreSSL-backed Python; see [macOS](#macos) |
| `openssl is not on PATH` | nothing to generate the authentication certificate with |
| `openssl did not produce the auth certificate` | it refused, and the retry did too — usually a crypto policy that forbids SHA-1; see [Linux](#linux) |
| `already running pid=N` | a previous instance is still up; leave it, or run `stop_servers.py` |
| `[WinError 10013]` on a bind, and the server exits | that port is reserved or already held; see [Windows](#windows) |
| `warps go unchecked` in the log | `reference/mapgraph.json` missing |
| every branch logs `fall-through`, choices do nothing | `reference/branches.json` missing |
| `no question bank, no questions`, a lesson asks nothing | `reference/quizkeys.json` missing |
| every conversation credits the same 12 intimacy, whichever one played and whichever answer | `reference/intimacy.json` missing |
| a scene plays on a black screen, or never changes its backdrop | that script has no export under `runtime/scripts/`, so every background branch falls through |

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
