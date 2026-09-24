# Tokimeki Memorial ONLINE — server

A from-scratch server for *Tokimeki Memorial ONLINE* (KONAMI, 2006–2007, service ended),
written so that a surviving copy of the original client has something to connect to again.

Run it on your own machine, point your own copy of the client at it, and you can log in, make
a character, go to school, sit through a lesson, talk to the people on campus, and play a club
match or a drama event — alone, or with somebody on a second machine.

<!-- HTML rather than markdown for the width="50%": a markdown table would size its columns
     from the caption text instead. The shots are 800x600, which is what the client draws
     at; the four oldest were kept at the 1280x960 they were captured at. -->
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

![Another player and the menu behind them](screenshots/interaction-menu.jpg)

</td>
</tr>
<tr>
<td valign="top"><b>Standing in the courtyard.</b> The player is put into the scene by the server, the NPC by one of the <code>/npc</code> commands.</td>
<td valign="top"><b>Somebody else on the same map.</b> Two clients, one server; right-clicking the other player opens the six slots, and the card underneath is filled in from their save.</td>
</tr>
<tr>
<td valign="top">

![A lesson under way](screenshots/lesson.jpg)

</td>
<td valign="top">

![A conversation](screenshots/conversation.jpg)

</td>
</tr>
<tr>
<td valign="top"><b>A lesson under way.</b> The message that opened it carried three numbers and no text: the client holds the questions, and this end picks which one and marks the answer.</td>
<td valign="top"><b>A scripted scene.</b> The client plays the cut-scene out of its own copy of the game; this end only answers the questions it stops on.</td>
</tr>
<tr>
<td valign="top">

![The club-deck window](screenshots/club-deck.jpg)

</td>
<td valign="top">

![A club match](screenshots/club-match.jpg)

</td>
</tr>
<tr>
<td valign="top"><b>The club deck.</b> The keywords a character owns, and the deck they are dealt into — both lists read back out of the save.</td>
<td valign="top"><b>A club match.</b> Eight turns, and this is the sixty seconds a side gets to choose a card; the order they resolve in is settled at this end.</td>
</tr>
</table>

## About

The servers went away; the client did not. This is the half that vanished, rebuilt from the
outside by watching what the client asks for: an independent implementation of the game's
network protocol, produced by analysing how the client communicates, for the purpose of
interoperability — letting an existing client program reach a server again.

It contains no code, artwork, audio or text taken from KONAMI's software. It does contain
tables of integers, read mechanically out of the client's data files, because there are
decisions this server is asked to make that it cannot make without them. Sixteen are files
under `reference/`, the smallest are literals in the modules that read them, and
[Reference data](#reference-data) accounts for each. A few hold words rather than numbers —
the banned-word list, and the names of the ten stand-in NPCs, the fourteen game masters and
the ten schools, which the client never loads for itself and draws exactly as this end sends
them. Message names, map names and structure offsets appear because they are the identifiers
the protocol itself uses; a client accepts no other wording for them.

*Tokimeki Memorial* is a trademark of KONAMI. This project is not affiliated with, endorsed
by, or connected to KONAMI in any way.

## What works

Every line below is something a client has been watched doing against this server. What they
do *not* add up to is the first bullet of the next section.

- **Getting in.** The update check, authentication, the login-server lookup, and the login,
  game and school servers behind it. Registration codes are issued here and bound to a
  KONAMI ID; several accounts can be on at once, each with its own characters and saves.
  Choosing a school, making a character, deleting one (what it carried goes into the
  account's locker, as the manual says), going to school, logging out, coming back to the
  square you left, and re-enrolling after a confession — that one candidate forgotten, the
  rest kept. A login is refused the three ways the client has words for.
- **The campus.** Walking, the doorways between the 78 maps, and your map and position kept
  across a logout. The 44 teachers and members of staff stand where the game's own tables put
  them, and a right-click on one opens their menu — joining a club, the leader's exam, the
  同好会 and 多目的室 doors, with what the exam plays decided by that person's own script.
  The romance candidates who have appeared stand on their maps too. Other players on the same
  map are seen, share the chat bar, and can be right-clicked for the six-slot menu: the
  address book, the friendly group (found one, invite, expel, leave, hand it on, disband, and
  the thirty days an ex-leader waits before founding another), a name card, the career card,
  and a report card that opens only if its owner ticked the box. Chat can be addressed to one
  person, to a friend off the map, or to the whole group; `/ignore` and `/refer` keep a list
  of your own. A changed catchphrase shows on everybody else's next right-click, expressions
  reach everyone in sight, and the icon over a character's head changes in place.
- **School.** The timetable is the client's own and the bells ring off it: a warning bell, a
  start bell, and if you are in your classroom you are in the lesson — ten questions, the
  eight help skills, the lesson's own chat bar, a result screen. An exam period puts a
  twenty-question paper with a ten-minute clock through the same door, and the marks land on
  the report card. Behind it: the six ability parameters, stress and condition, and the
  injury that comes of training while carrying too much of both.
- **Clubs.** Joining one of the eight and leaving it; the club-deck window's keywords, skills
  and three decks; the item window's six tabs and the locker the account shares. A training
  room goes up on the noticeboard, others join, and the match runs its eight turns — the
  cards, the order they resolve in, effects and reactions, ailments that outlast a turn, a
  result screen, and a drop-out carried to the end. Club special moves are made by the recipe
  and fire in a match like any other card.
- **Between players.** A notice planted on the ground and read by right-clicking the icon
  over its owner's head; a chat room opened the same way; the school newspaper; a
  face-to-face trade with two confirmations each; and the two-person conversation behind the
  right-click menu, waist-up, with a row of expressions.
- **Scripted events.** The client plays a cut-scene out of its own copy of the game and stops
  at every branch to ask this end which way to go — which is where that decision always
  belonged, since the client's own arithmetic instructions compute nothing. Answers come off
  the branch table, or from `server/gs3vm.py`, which runs the script's arithmetic alongside
  the client and so holds the register file the client never had. Between them: conversations
  with the candidates and the intimacy each answer is worth, the tutorial, the letter in the
  lockers, the main events and the confession they lead to, the drama events, and the ending
  with its staff roll. With the exports present a scenario remembers what the original let it
  remember — the day it last played, how many times, what you answered, what you said — and
  asks for your name, your school's and your birthday, and is answered; a box that runs out of
  time closes on its own. A drama can be played by two people: a party, both ready, a part
  each; a choice waits until both have answered; an empty or abandoned part is taken by the
  stand-in NPC the script names, and this end walks its cursor; the result goes up on screen
  and into the save. A growing share of the scripts running here are the *original server's*
  own, read out of the game's data and run on the side they always ran on: the letter pair,
  each candidate's placement, conversation-choice and bookkeeping scripts, and the one
  behind each staff member's menu.
- **The server's own voice.** A system message on every screen, a shutdown that says so first
  and keeps to the time it promised, GM chat spoken as one of the fourteen game masters in
  the game's roster, and the GM's two notices. All typed at the [console](#commands).

## What this is not

- **Not a restored game.** A list of subsystems is not a game. Much now happens through the
  client's own windows and the game's own scripts, but the people on campus stand still,
  because nothing that survived says how they moved; some numbers a lesson or a match turns on
  were made up, and say so; and whatever the original decided on a clock of its own, beyond
  what its scripts decide, has no counterpart here. A school you can spend an afternoon in,
  not a game you can play through.
- **Not the game as it ended.** The disc holds the launch client — `update.ini` reports
  `2006012300` — and a year of updates went out through a server that is gone. None of it is
  here.
- **Not a service.** This repository is the software, and nothing here is or will be sold. It
  hands out no server to join: running one is something you do on your own machine.
- **Not a source of game files.** No client, no assets, no patched executable. You supply
  your own copy.

Not every number here is a fact. The wire format — message ids, layouts, offsets — was read
off the protocol and is verifiable. Some values exist only because the client needs
*something* there: movement speed, spawn positions, the school list. Those are marked
`INVENTED` in the source, and `/knob list` prints every one.

## Requirements

- **Python 3**, standard library only. Run here on 3.11 and 3.14. It must be built against
  real OpenSSL, which rules out the `python3` that ships with macOS; see below.
- **`openssl` on PATH**, used once to generate the certificate the authentication endpoint
  needs, into `runtime/certs/`.
- **Your own copy of the original client.** This repository distributes no part of it. The
  disc has been publicly archived on the Internet Archive as
  [tokimekimemorialonlinejapan](https://archive.org/details/tokimekimemorialonlinejapan);
  whether you may obtain and use a copy is a question of the law where you are, not one this
  project answers.

The server runs on Windows, macOS or Linux. The game is a Windows program and also works
under Wine. Run end to end here in two shapes: game and server on one Windows 11 machine, and
the game under Wine on macOS talking to a server on a Debian 12 machine.

## Installation

```sh
git clone https://github.com/ShuAkirasora/tokimeki-memorial-online-revival.git
cd tokimeki-memorial-online-revival
```

Or **Code → Download ZIP**. There is nothing to build; the folder is the program.

- **Windows** — the [python.org](https://www.python.org/downloads/) installer with **Add
  python.exe to PATH** ticked. **Every `python3` in this README is `py` here.** `openssl`
  comes with Git for Windows and this server looks there; failing that, `winget install
  openssl`.
- **macOS** — `brew install python` or the python.org installer, **not the system `python3`**,
  which is built against LibreSSL and cannot start the TLS listeners.
  `python3 -c "import ssl; print(ssl.OPENSSL_VERSION)"` says which one is first on your PATH.
- **Linux** — your distribution's `python3` and `openssl`.

Three things about the first start, none fatal. A firewall asks once on Windows and macOS;
saying no leaves only a game on this machine working. Ports 443, 80 and 50 are often already
held, and `[authhttp] skip :443 (...)` in the log says so rather than failing — on Linux they
are also privileged, so start as root or `sudo sysctl -w net.ipv4.ip_unprivileged_port_start=50`.
And Windows with Hyper-V or WSL reserves blocks of ports at boot; one covering 25573–25575
stops the server dead, and `netsh int ipv4 show excludedportrange protocol=tcp` lists them.

The authentication certificate has to be SHA-1, which RHEL, Fedora and their derivatives
refuse under their crypto policy. The first run notices the refusal and repeats that one
command with the policy overridden, changing nothing about the machine.

## Running the server

```sh
python3 start_servers.py                              # game on this same machine
python3 start_servers.py --advertise-ip 192.168.1.5   # game on another machine
python3 stop_servers.py
```

It runs detached; `[system] all services started` in `runtime/run_all.log` means it is up.

**`--advertise-ip` is needed whenever the game is not on the server's own machine.** Logging
in is a chain of hops, each answering with the address of the next; unset, those answers are
`127.0.0.1`, which sends every remote player back to their own computer. The same flag decides
what the server listens on — `127.0.0.1` alone by default, the network when given.
`TMO_ADVERTISE_IP` in the environment does the same, and `--bind` overrides the listening half.

**The chat bar is not a console unless you ask for it.** `--console`, or `TMO_CONSOLE=1`, lets
a player's chat bar run the [commands](#commands) below; without it a `/word` goes out as
ordinary chat, which is what the game does with a word it does not know. Every one of those
commands is this project's own, several rewrite a save, and a server with players on it has no
reason to hand them out. Lines appended to `runtime/console.txt` run either way — writing there
takes a shell on the server's machine — and that file is also the only way to reach a command
while a script has the client's input locked.

## Japanese, and one Windows setting

**The game is a Japanese program from 2006.** It, its installer, and everything you type into
it go through one machine-wide Windows setting — the *language for non-Unicode programs* — and
it wants Japanese, code page 932:

> Settings → Time & language → Language & region → Administrative language settings →
> Change system locale → **Japanese (Japan)**, then restart from the Start menu.

Or, from an administrator PowerShell, `Set-WinSystemLocale ja-JP`. On a Japanese Windows the
same line reads **Unicode 対応ではないプログラムの言語**. Making Windows Japanese in every
visible way — display language, region, keyboard — does not set it. One command says what you
have:

```
reg query "HKLM\SYSTEM\CurrentControlSet\Control\Nls\CodePage" /v ACP
```

`932` is the answer. Anything else is the cause of both symptoms below, and `65001` means
**Beta: Use Unicode UTF-8 for worldwide language support** is ticked on the same dialog — it
makes this game worse, so untick it.

**When it is wrong**, the installer's text and every error box the client puts up are garbled
(they are ordinary Windows dialogs; the game's own screens hold out longer), and Japanese typed
into a character's name arrives blank: the game reads the IME through the ANSI half of `IMM32`
and draws with its own bitmap fonts, so under the wrong code page the glyph looked up does not
exist. Installing fonts changes nothing, and it is not the IME — the stock Windows 11 Microsoft
IME works as it is. If you suspect it anyway, *Use previous version of Microsoft IME* under its
options is the compatibility switch for programs of this age.

**One program instead of the machine.**
[Locale_Remulator](https://github.com/InWILL/Locale_Remulator) puts a single program into a
Japanese locale and works on Windows 11 on Arm; the older Locale Emulator does not. It does
not reach the installer, whose wizard is a separate process, but only that text is affected.

## Installing the game

The disc installs the game; this repository installs nothing. The archived copy comes as a
`.7z` holding the disc image: unpack it with [7-Zip](https://www.7-zip.org/), mount the `.iso`
with a double-click, and run the installer on that drive. **Give it an ASCII destination**,
such as `C:\TMO` — the default path is Japanese text and becomes a garbled folder on a machine
that is not. **If you installed before fixing the code page, install again**: the game reaches
its own files through the same ANSI calls, and a folder named under the old code page can stop
being found. Then `Play.cmd`, below, is what starts it.

## Connecting a client

Three destinations inside the client have to end up here: two hostnames, which your `hosts`
file redirects, and one fixed numeric address, which is four bytes inside `tmo.exe`.

**None of it has to be done by hand.** On Windows, double-click **`Play.cmd`**: it asks for
the administrator rights the game already needed, asks once where the server is, writes the
two hosts lines, patches the four bytes, checks that the server answers, and starts the game.
Everywhere else the same thing is `python3 play.py`. This folder has to be on the machine the
*game* is on; copying only `play.py`, `Play.cmd` and `set_auth_address.py` there is enough.

```sh
python3 play.py --server 192.168.1.5   # say it outright instead of being asked
python3 play.py --dry-run              # what it would change, writing nothing
python3 play.py --revert               # put the hosts file and the four bytes back
python3 play.py --no-launch            # set everything up, start nothing
```

Nothing it does is one-way: the hosts file is copied first, a line of yours that points one of
the two names elsewhere is commented out rather than deleted, and `--revert` puts both back. On
macOS and Linux only the hosts step goes through `sudo`, and `--launch-with` names the command
that runs Windows programs (`wine` by default).

### The same steps by hand

**1. The address.** Server and game on one machine, Wine included: `127.0.0.1`. Two machines:
the server machine's local address — `ipconfig` on Windows, `ipconfig getifaddr en0` on macOS,
`hostname -I` on Linux. The examples use `192.168.1.5`.

**2. The two hostnames**, in the `hosts` file of the machine the *game* runs on — under Wine
that is the Mac's or Linux box's `/etc/hosts`, not anything inside the prefix:

```
192.168.1.5  tmollb.tokimekionline.com
192.168.1.5  tmoupd.tokimekionline.com
```

Windows: Notepad run as administrator, open `C:\Windows\System32\drivers\etc\hosts` with the
file type set to *All Files*, add the lines, save. macOS and Linux: `sudo nano /etc/hosts`.

**3. The address inside `tmo.exe`.** The client also opens a connection straight to a fixed
numeric address that was KONAMI's, which no name resolution can redirect:

```sh
python3 set_auth_address.py /path/to/tmo.exe 192.168.1.5
```

Run it wherever `tmo.exe` is. It keeps a copy as `tmo.exe.orig` before writing, then reports
where the two hostnames currently lead — two `ok` lines mean step 2 is done as well, and an old
answer means a cached lookup (`ipconfig /flushdns`; `sudo dscacheutil -flushcache; sudo killall
-HUP mDNSResponder`; `sudo resolvectl flush-caches`). With no address it only reports;
`--revert` restores KONAMI's; `-n` writes nothing.

**4. A registration code and a KONAMI ID.** The login screen asks for three things, and one
page gives all three. Open **http://127.0.0.1:12013/** on the server's machine, or
`http://<server>:12013/` from anywhere that reaches it; type a KONAMI ID (up to 64 of
`A-Z a-z 0-9 . _ -`) and a personal key twice (4 to 64 of `A-Z a-z 0-9`, case-sensitive);
**Create**. Back comes a twenty-character code already bound to that id. **Write it down**:
nothing mails it, and the page stops working fifteen minutes later — though the same id and key
give the same code back rather than a second one. A code that was made up rather than issued
is refused in the client's own words, 「入力されたレジストレーションコードは存在しません」.

The two halves also exist apart, at **http://127.0.0.1:12013/register** — one form makes a
KONAMI ID, the other binds a code to one — which is the way in for a code an operator issued
by hand:

```sh
python3 issue_code.py --unregistered   # a code for /register to bind
python3 issue_code.py                  # a code with no owner — anybody can log in with it
python3 issue_code.py --list           # every code, its state, and who registered it
python3 issue_code.py --revoke CODE    # withdraw one, leaving its characters saved
```

The page is plain HTTP unless you give it a certificate — it cannot borrow the game's, which is
1024-bit RSA under SHA-1 and no current browser will open — so away from the server's own
machine the personal key crosses in the clear. **Pick a key you use nowhere else**, or serve
the page over TLS with an ordinary modern certificate:

```sh
python3 start_servers.py --registration-cert fullchain.pem --registration-key privkey.pem
```

An address that sends many forms in an hour is answered a few seconds late; fifty codes a day
from the form closes it until tomorrow, and says so; five wrong keys in a row slow that
account's logins. `/register` and `issue_code.py` count towards nothing. `server/throttle.py`
has the numbers.

**5. Start the game** with `BootFirst.exe`, not `tmo.exe` — **as administrator** on Windows.
Without that you get `アップデートクライアントの起動に失敗しました` and nothing reaches this
server: `UpdateClient.exe` is a 32-bit binary with "Update" in its name and no manifest, which
Windows decides needs elevation, and `BootFirst.exe` cannot elevate it. Under Wine this has not
come up.

**6. Check that it worked** in `runtime/run_all.log` — `tail -f`, or `Get-Content
runtime\run_all.log -Wait -Tail 20`. Each line is one step proving itself, and the first one
missing says where to go back:

| A line like this | Means |
|---|---|
| `[system] all services started` | the server is up |
| `[updater] … sent UPDATE_DONE` | `tmoupd` resolves — step 2 |
| `[llb35573] -> MsgSvResultLoginServer` | `tmollb` resolves — step 2 |
| `[authhttp] ACCEPT port=443` | the four bytes are right — step 3 |
| `[mpslogin25573] … login: code …` | the code and the KONAMI ID were accepted |
| `[mpsgame25574] …`, `[mpsschool25575] …` | you are in |

Steps 2–4 stay done unless you reinstall the game, which puts the original `tmo.exe` back, or
the server's address changes.

## What changes in your copy of the client

**One thing: where it looks for a server. Nothing about how it behaves.** Its connections are
Blowfish-enciphered, and this server speaks that layer as the protocol's other endpoint; no
check is bypassed, no encryption is switched off, and every piece of code in the binary is the
code that runs.

| | How the client finds it | How it is redirected |
|---|---|---|
| `tmoupd.tokimekionline.com` | hostname — the update check | name resolution |
| `tmollb.tokimekionline.com` | hostname — the login-server lookup | name resolution |
| `133.221.34.229` | a fixed numeric address, straight to `connect()` | the four bytes |

The login, game and school servers follow from whatever the lookup hands back. The third
destination is built one octet at a time onto the stack and handed to `connect()`:

```
mov byte [esp+0x28], 133
mov byte [esp+0x29], 221
mov byte [esp+0x2a], 34
mov byte [esp+0x2b], 229
```

Those four immediates are all the script writes. It scans for that instruction shape and
requires it to occur exactly once rather than trusting an offset, copies the original to
`tmo.exe.orig` before the first write, and never overwrites an existing backup, so reverting
leaves the file byte-for-byte as it was. The client's small trust store is not enforced, so a
locally generated certificate is accepted, and nothing has to be disabled to get through
authentication.

## Ports

| Port | Service | Reached by |
|---|---|---|
| 12000 | the update check | the game |
| 35573 | login-server lookup | the game |
| 25573 / 25574 / 25575 | login / game / school | the game |
| 443 | account auth, TLS | the game |
| 12013 | the registration page | a browser |
| 50, 8011, 12011, 80, 12012 | the same auth service on other ports | nothing, ever |

The last row has never had a connection in any log this project has kept — the client's
authentication URL has no port in it — and stays bound to `127.0.0.1` whatever `--bind` says.
The rest follow `--advertise-ip`: `127.0.0.1` alone by default, the network when one is given,
and then 25573–25575, 35573, 12000 and 443 have to be reachable from the game's machine. Ports
below 1024 need privileges on Linux and none on Windows; on macOS an ordinary user may bind
`0.0.0.0:443` but *not* `127.0.0.1:443`, so there the default opens 443 wide and closes any
connection that is not from this machine without reading it. A port that cannot be bound is
skipped, not fatal.

## Commands

Typed into the game's chat bar when the server was started with `--console`, or appended to
`runtime/console.txt` at any time. They drive the protocol rather than play the game — most
exist because sending a message by hand was the only way to find out what the client would do
with it. `/cmds` prints the list inside the game, which is the copy that cannot go stale. The
client keeps `/help`, `/where` and a few other words for itself and never puts them on the wire.

**Where you are.**

| Command | Effect |
|---|---|
| `/go <map name or id> [x y]` | move to a map |
| `/pos` | print where you are |
| `/maps <name>` | search the map table |
| `/dirs` | drop a marker for each of the sixteen direction values |
| `/act [<first>]` | the same ruler for the `action` field, sixteen values at a time |
| `/cid <cat>:<id> …` | stand somebody up by roster id — and say first what the client will draw for it, and whether a right-click will offer anything |

**What a character has.** Each of these reads a sheet the client draws somewhere and writes
it back to the save.

| Command | Effect |
|---|---|
| `/rom [name] [debut\|talk\|ev\|ed\|x\|p <n>\|i <n>]` | read and move the romance state |
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
| `/shop [out <n>\|in <n>]` | the school store's counter, and which rows are sold out |
| `/group [create\|join\|leave\|disband\|hand\|qual\|wait\|exam]` | the friendly-group store, the thirty-day wait, and the リーダー試験 tour record |

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
| `/npca [<first> <last> [category]]` | place every romance candidate who has appeared — done for you when a map loads |
| `/npcx` | stop replacing them |
| `/nev [<cat>:<id>]` | set the conversation-event key |
| `/smenu [<key>]` | which sub-menu a map object opens |
| `/evend [auto\|manual]` | how the end of an NPC event is answered |
| `/sc <name or id> [ctrl] [actor:npcId]` | start a script |
| `/sc next <name\|off>` | swap the script the next conversation asks for |
| `/scn`, `/sce`, `/scl` | step it on, end it, list what has been exported |
| `/scb [<scriptId> <ip> <target>\|clear]` | force a branch to go somewhere |
| `/sel [<select> [timer]]` | ask a choice box again |
| `/inp [timerCount]` | the time limit a text box is given |
| `/pcinfo [0\|1\|off]` | which part of a two-part script to put yourself in |
| `/tutorial on\|off` | arm the first-day tutorial again |
| `/season [clock\|script\|0-3]` | where the season a backdrop switch asks about comes from |
| `/pwt [on\|off]` | whether the wait-for-players instruction is released |
| `/de [<genre>:<index>]` | the drama-event list |
| `/dms` | open the matching screen |
| `/raw <msgid16> [hex]` | send one message by hand, by number |
| `/knob [<name> [<value>\|reset]\|list [word]\|changed\|reset\|save]` | turn one of the invented numbers, without a restart |

**Tuning.** Every number this server made up rather than read off the game — a damage
scale, a drop chance, how long a question stays open — is marked `INVENTED` in the source,
and `/knob` finds them by that mark. `/knob list` prints them with their current and factory
values, `/knob DAMAGE_SCALE 0.6` changes one in place, `/knob changed` shows what differs from
stock, `/knob save` writes those to `runtime/knobs.json` so the next start picks them up, and
`/knob reset` puts everything back. A number without the mark was read off the game and cannot
be reached from here at all: tuning is confined to what was invented. The `TMO_*` environment
variables some of these also answer to keep working as before.

**Operator.** These say something to players rather than read anything back.

| Command | Effect |
|---|---|
| `/sys <text>`, `/sys to <charaId> <text>`, `/sys lvl <n> <text>` | a system message, to everybody at school or to one of them, with an importance byte the client has not been seen to act on |
| `/shutdown <seconds> <text>`, `/shutdown cancel [<text>]`, `/shutdown` | say it, wait exactly that long, and stop; neither the delay nor the sentence has a default |
| `/gm [take\|free\|done] [charaId]` | the GM call queue |
| `/gm chat [<family> <given>\|<charaId>]`, `/gm say <text>` | GM chat with one player |
| `/gm as [row]` | which of the fourteen game masters this connection speaks as |
| `/gm msg [to <charaId>] <text>`, `/gm logout [charaId]` | the GM's two notices: a message, and a forced logout that says so before the socket closes |

**Tuning.** Every number this server made up rather than read off the game is marked
`INVENTED` in the source, and `/knob` finds them by that mark: `list` prints them with current
and factory values, `/knob DAMAGE_SCALE 0.6` changes one in place, `changed` shows what differs
from stock, `save` writes those to `runtime/knobs.json`, `reset` puts everything back. A number
without the mark was read off the game and cannot be reached from here.

**Probes.** `/cb` drives a club battle a piece at a time and `/seq` replies with a sequence
number that goes backwards, to find out what the client makes of it.

## Reference data

`reference/` holds sixteen tables, each something this server has to know in order to decide
something, and each read out of the client's own data files. Most are integers and table keys.
None carries dialogue, prompts, cast lists or titles: that half is the game's content, and
[`export_scripts.py`](#exporting-the-scripts) makes it out of your own copy, on your own disk.

| File | What it holds | Without it |
|---|---|---|
| `mapgraph.json` | grid, collision and doorways for the 78 maps — the one table the wire can confirm, since the client decides where a door leads and this end only agrees | `warps go unchecked`; moving between maps stops |
| `branches.json` | where a cut-scene goes when the player picks option k, for the 209 scripts that ask: 5125 of the game's 15586 branches, the rest left out because their conditions this end always answers no to | every branch falls through; choices stop mattering |
| `season_switch.json` | which arm of five scenarios' backdrop switch is which season — the default arm plays debug output the developers left in the shipped data | those scenes show it |
| `intimacy.json` | what each of 327 conversations is worth, flat and per answer; a check on the scenario's own arithmetic when the exports are present, the whole of it when they are not | every conversation credits 12 |
| `quizkeys.json` | how many questions each of the 80 lesson categories holds, and the true-or-false answers; no question text | a lesson asks nothing |
| `npc_events.json` | which event key belongs to which NPC and which script it starts; `.ssb` stems as identifiers | events cannot be resolved |
| `menu_items.json` | each menu key's kind, and whether the game leaves it enabled | nothing is refused |
| `reserved_names.json` | SHA-256 digests of the names a new character may not be given; no names | none are refused |
| `clubbattle.json` | 166 KiB of rule values a club match is fought by — what keywords hit and block for, the 144 practice opponents, every skill's cost and rate, every recipe; no name, not even the opponents' | 練習 is unavailable; 自主トレ still runs |
| `drama_events.json` | the 22 drama events: key, script stem, and per cast slot the sex and keyword it requires | every 登場人物 button reads 「入れません」 |
| `ngwords.json` | the game's own 禁止用語 dictionary, 1355 banned and 85 exemptions — words, because the client never loads it and the exemptions are what stop 「アホウ」 refusing 「アホウドリ」 | `禁止用語 is not enforced` |
| `npc_spawns.json` | the 44 teachers and staff: roster id, map, cell and script stem, read out of the game's tables and placement scripts, which agree row for row; every club, exam and drama door is a right-click on one of them | `no spawn table`; the campus stands empty |
| `proxy_npcs.json` | the ten stand-in NPCs, with name, nickname, blood type and appearance — the client asks this end for the whole record and waits | a stand-in is refused |
| `script_ids.json` | the 717 numbers the game names a script by, without the file each belongs to; both event doors check an id against it, so a refusal means 「no such script」 rather than 「no export here」 | every id is taken on trust |
| `gm_pcs.json` | the fourteen game masters, id and name; the client ships that table and never loads it | GM chat has nobody to speak as |
| `schools.json` | the ten schools, id and name; which one this server is stays `INVENTED` | those lines print a blank |

A few tables are literals in the module that reads them: the week's timetable in
`server/curriculum.py`, item key ranges in `server/item.py`, the store's five rows in
`server/shop.py`. `reserved_names.json`, `ngwords.json`, `clubbattle.json` and
`drama_events.json` each merge with a same-shaped file under `runtime/` if you put one there,
row by row, so the shipped ones never need editing.

Two gaps are worth naming. Without the script exports every arithmetic branch falls through:
a scene keeps the backdrop it opened with, a candidate's conversations stop moving with her
story, the tutorial's walk home takes the wrong stairs, and what a script writes at its end —
a debut, the keywords it hands out — is not written. And a lesson's effect is only half read:
*which* abilities a subject touches is the game's own table, *how much* is an invented step,
marked as such, and reward items, hint skills and the biorhythm are not modelled at all.

## Exporting the scripts

```
python3 export_scripts.py
```

It finds the game the way `play.py` does (`--game-dir` overrides), reads the archives under
`Data/script/`, and writes the 683 client scenarios and the 95 the original server ran into
`runtime/scripts/` — untracked, about 50 MiB, a few seconds, standard library only. Naming
scripts on the command line exports only those; `--list` prints what your copy holds. Two
files per scenario: `<name>.json`, which `/sc` drives a scene from — the parts and their
stand-ins, the cast, the instruction stream written out to be read, the branch targets, each
box's prompt and options — and `<name>.gs3.json`, which `server/gs3vm.py` runs.
`reference/ssc_ops.tsv` is the one thing the exporter takes from here: the 209 commands, their
lengths, and the names the client's own decoder logs them under — a table about the bytecode
rather than any of it.

The archives are enciphered, and neither the key nor the IV is written down in this repository.
Both are in your copy of the game and the exporter takes them from there: the key from the
shape of the code that builds it, tried against a payload you already have, and the IV from the
one block whose plaintext is known in advance, every script beginning with its own version
string. If that search comes out ambiguous on a differently built copy the exporter stops and
says so, and `--key` and `--iv` are the way past it. Nothing that comes out belongs to this
repository and none of it is redistributed here.

## Repository layout

| Path | |
|---|---|
| `start_servers.py`, `stop_servers.py` | start and stop everything |
| `Play.cmd`, `play.py` | the client half in one run: hosts, the four bytes, the game started |
| `set_auth_address.py` | the four-byte address change |
| `export_scripts.py` | the script exports, out of your own copy of the game |
| `issue_code.py` | issue, list, revoke and unbind registration codes |
| `server/` | the services; `run_all.py` binds them in one asyncio loop, `mps_session.py` is the packet layer and the bulk of it |
| `reference/` | the tables above, and the opcode table the exporter reads |
| `runtime/` | created on the first run: the log, the certificate, your characters, your script exports, `console.txt` if you write one, and any tables you override |
| `screenshots/` | the eight pictures above — captures of a running client, not game files |
| `.github/workflows/ci.yml` | on every push: compile, start, check the ports answer, stop — on Python 3.11 and 3.14 |
| `LICENSE`, `NOTICE` | Apache 2.0, and the attribution redistribution has to carry |

## Troubleshooting

| Symptom | Cause |
|---|---|
| the installer's text is garbled, or the client's error boxes are | the system locale is not Japanese; see [Japanese, and one Windows setting](#japanese-and-one-windows-setting) |
| Japanese typed into a character's name shows as blank | the same setting. It is not the IME, and not a missing font |
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
| `ssl.SSLError: ('No cipher can be selected.',)` | the LibreSSL-backed Python; see [Installation](#installation) |
| `openssl is not on PATH` | nothing to generate the authentication certificate with |
| `openssl did not produce the auth certificate` | it refused, and the retry did too — usually a crypto policy that forbids SHA-1; see [Installation](#installation) |
| `already running pid=N` | a previous instance is still up; leave it, or run `stop_servers.py` |
| `[WinError 10013]` on a bind, and the server exits | that port is reserved or already held; see [Installation](#installation) |
| `warps go unchecked` in the log | `reference/mapgraph.json` missing |
| every branch logs `fall-through`, choices do nothing | `reference/branches.json` missing |
| `no question bank, no questions`, a lesson asks nothing | `reference/quizkeys.json` missing |
| every conversation credits the same 12 intimacy, whichever one played and whichever answer | `reference/intimacy.json` missing |
| `no club tables`, and 練習 offers no opponents | `reference/clubbattle.json` missing |
| every 登場人物 button on the party screen reads 「入れません」, and `/de` lists nothing | `reference/drama_events.json` missing |
| `no word list; 禁止用語 is not enforced`, and a scenario's text box accepts anything | `reference/ngwords.json` missing |
| `no spawn table`, and no teacher stands anywhere | `reference/npc_spawns.json` missing |
| `no roster … 代行ＮＰＣ unavailable`, and 「ＮＰＣに変更」 is refused | `reference/proxy_npcs.json` missing |
| `no GM roster`, and `/gm chat` has nobody to speak as | `reference/gm_pcs.json` missing |
| a `/command` typed into the chat bar goes out as ordinary chat | the server was started without `--console`; see [Running the server](#running-the-server) |
| 「既にログインしています」 at login | that account still has a live connection on this server |
| a scene plays on a black screen, or never changes its backdrop | that script has no export under `runtime/scripts/`, so every background branch falls through; see [Exporting the scripts](#exporting-the-scripts) |

The log is verbose and includes hex dumps of unrecognised packets. `no reply implemented`
marks a message this server has seen but does not answer yet.

## License

[Apache License 2.0](LICENSE). Copyright 2026 Shu Akirasora and contributors.
