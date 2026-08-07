"""The local stand-in for the website 登録 happened on.

A registration code in the box did not work on its own. The player went to
KONAMI's site, signed in with their KONAMI ID, typed the code from the box, and
only then would the login screen let them in -- and the client still carries the
sentences that step produced, one for a code nobody has claimed and one for a
code that needs claiming again. codes.py sets out how those sentences are the
evidence for the step.

Nothing of that page survives to copy, and nothing needs to: what is being
reproduced is the step, not KONAMI's markup. So this is a plain form on a plain
port, with the two things their site did and nothing else --

    make a KONAMI ID          an id and a personal key, which is what the
                              client's login screen asks for
    登録 a code               bind one code to one KONAMI ID, which is what
                              turns it from `issued` into `active`

-- and no third thing. There is no email step, because there is nobody to mail:
the address on KONAMI's form existed to prove a person could be reached, and a
server for the room it is running in has no use for that proof. See the README
on why this is not meant to face a network.

  Language
  --------
  The page is written in English, and the field labels are in Japanese, and that
  split is deliberate rather than sloppy. A player is copying values between this
  page and the client's login screen, and that screen says KONAMI ID,
  パーソナルキー and レジストレーションコード; a label that does not match the
  box it corresponds to is a page that has to be decoded before it can be used.
  Everything the page says in its own voice is in English, as the rest of this
  tree is.
"""

from __future__ import annotations

import asyncio
import html
from pathlib import Path
from urllib.parse import parse_qs

import codes
import konami_id
from common import ServiceConfig

# Where the client's login screen splits the twenty characters. Reproduced here
# so that a code is typed the same way in both places -- and so that a player
# reading one off this page can follow it group by group.
GROUPS = codes.CODE_LEN // codes.GROUP_LEN

STYLE = """
:root { color-scheme: light dark; }
body { font: 16px/1.6 system-ui, "Hiragino Sans", "Yu Gothic", sans-serif;
       margin: 0 auto; max-width: 46rem; padding: 2rem 1.25rem 4rem; }
h1 { font-size: 1.4rem; margin: 0 0 .25rem; }
h2 { font-size: 1.1rem; margin: 2.5rem 0 .5rem; }
p.lede { color: #767676; margin: 0 0 2rem; }
form { border: 1px solid #8884; border-radius: .5rem; padding: 1.25rem; }
label { display: block; margin: .9rem 0 .25rem; font-weight: 600; }
label .en { font-weight: 400; color: #767676; margin-left: .5rem; }
label > input { display: block; margin-top: .3rem; }
input { font: inherit; padding: .4rem .5rem; border: 1px solid #8886;
        border-radius: .25rem; background: transparent; color: inherit; }
input[type=text], input[type=password] { width: 18rem; max-width: 100%; }
.code input { width: 4.5rem; text-align: center; text-transform: uppercase;
              font-family: ui-monospace, monospace; letter-spacing: .1em; }
.code { display: flex; flex-wrap: wrap; gap: .4rem; align-items: center; }
button { font: inherit; margin-top: 1.25rem; padding: .45rem 1.1rem;
         border-radius: .25rem; border: 1px solid #8886; cursor: pointer; }
.note { color: #767676; font-size: .9rem; }
.msg { border-radius: .5rem; padding: .75rem 1rem; margin: 0 0 1.5rem; }
.ok { border: 1px solid #3a3; background: #3a31; }
.bad { border: 1px solid #c44; background: #c441; }
code { font-family: ui-monospace, monospace; }
"""


def page(body: str, message: tuple[str, str] | None = None) -> bytes:
    banner = ""
    if message is not None:
        kind, text = message
        banner = f'<p class="msg {kind}">{text}</p>'
    return f"""<!DOCTYPE html>
<html lang="en">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Registration</title>
<style>{STYLE}</style>
<h1>Registration</h1>
<p class="lede">Local revival server. Register a code here before signing in
with the client.</p>
{banner}
{body}
""".encode("utf-8")


def code_boxes(values: list[str]) -> str:
    boxes = []
    for i in range(GROUPS):
        value = html.escape(values[i]) if i < len(values) else ""
        if i:
            boxes.append("<span>-</span>")
        boxes.append(
            f'<input name="code{i}" maxlength="{codes.GROUP_LEN}" '
            f'value="{value}" autocapitalize="characters" spellcheck="false">'
        )
    return '<div class="code">' + "".join(boxes) + "</div>"


def forms(form: dict[str, str] | None = None) -> str:
    """Both forms, with whatever the player last typed still in them.

    Keeping the values is not a nicety: a rejected 登録 is usually a mistyped
    group out of five, and a page that clears all five makes the player retype
    the four that were right.
    """
    form = form or {}
    got = lambda name: html.escape(form.get(name, ""))  # noqa: E731
    typed = [form.get(f"code{i}", "") for i in range(GROUPS)]
    return f"""
<h2>1. Make a KONAMI ID</h2>
<form method="post" action="/konami-id">
  <p class="note">Only needed once. This is what the client's login screen asks
  for at the top; the registration code goes underneath it.</p>
  <label>KONAMI ID <span class="en">up to 64 of A-Z a-z 0-9 . _ -</span>
    <input type="text" name="konami_id" value="{got('konami_id')}"
           autocapitalize="none" spellcheck="false"></label>
  <label>パーソナルキー <span class="en">personal key, at least
    {konami_id.KEY_MIN} characters</span>
    <input type="password" name="personal_key"></label>
  <label>パーソナルキー（確認） <span class="en">again</span>
    <input type="password" name="confirm"></label>
  <button type="submit">Create</button>
</form>

<h2>2. 登録 a registration code</h2>
<form method="post" action="/register">
  <p class="note">Binds one code to one KONAMI ID. Until this is done the login
  screen answers
  「レジストレーションコードが登録されていません」.</p>
  <label>KONAMI ID
    <input type="text" name="konami_id" value="{got('konami_id')}"
           autocapitalize="none" spellcheck="false"></label>
  <label>パーソナルキー
    <input type="password" name="personal_key"></label>
  <label>レジストレーションコード <span class="en">the five groups, as on the
    login screen</span></label>
  {code_boxes(typed)}
  <button type="submit">登録</button>
</form>
"""


# The client's own words for the refusals this page can run into, so that a
# player is told here exactly what the login screen would have told them. Taken
# from the client's MsgSvNgLoginServerLogin table; see codes.py for the reasons.
REASON_TEXT = {
    codes.REASON_UNKNOWN: "入力されたレジストレーションコードは存在しません。",
    codes.REASON_EXPIRED: "レジストレーションコードの有効期限が過ぎています。",
    codes.REASON_SUSPENDED: "アカウント停止期間中です。",
}


class RegistrationSite:
    """The 登録 form, on a port a browser can reach.

    Plain HTTP on purpose. The client's auth endpoints are TLS because the
    client insists on it, and that certificate is 1024-bit RSA signed with SHA-1
    -- which every current browser refuses outright, so serving this page over
    the same context would make it unreachable by the only thing that can render
    it. What crosses this connection is a personal key for a game server on the
    machine the browser is running on; see konami_id.py on what that is worth.
    """

    def __init__(
        self,
        root: Path,
        config: ServiceConfig,
        *,
        directory: konami_id.Directory,
        table: codes.CodeTable,
        advertise_ip: str = "127.0.0.1",
    ) -> None:
        self.root = root
        self.config = config
        self.directory = directory
        self.codes = table
        self.advertise_ip = advertise_ip

    # -- the two things the page does -------------------------------------

    def _create_id(self, form: dict[str, str]) -> tuple[str, str]:
        given = form.get("konami_id", "")
        key = form.get("personal_key", "")
        if key != form.get("confirm", ""):
            return "bad", "The two personal keys do not match."
        try:
            made = self.directory.create(given, key)
        except konami_id.InvalidId as exc:
            return "bad", html.escape(str(exc))
        print(f"[register] new KONAMI ID {made}")
        return "ok", (
            f"KONAMI ID <code>{html.escape(made)}</code> created. "
            "Now 登録 a registration code below."
        )

    def _register(self, form: dict[str, str]) -> tuple[str, str]:
        given = form.get("konami_id", "")
        typed = "".join(form.get(f"code{i}", "") for i in range(GROUPS))
        key = codes.normalise(typed)
        if not self.directory.verify(given, form.get("personal_key", "")):
            # One sentence for a wrong id and for a wrong key, which is the one
            # place on this page where being unhelpful is the point.
            return "bad", "ユーザ情報が正しくありません。 That KONAMI ID and personal key do not match."
        if not codes.is_wellformed(key):
            return "bad", (
                f"A registration code is {codes.CODE_LEN} characters in "
                f"{GROUPS} groups, and only uses "
                f"<code>{codes.ALPHABET}</code>."
            )
        owner = konami_id.normalise_id(given)
        already = self.codes.owner(key)
        if already == owner:
            return "ok", (
                f"<code>{codes.format_code(key)}</code> is already registered to "
                f"<code>{html.escape(owner)}</code>. Nothing to do."
            )
        reason = self.codes.register(key, owner)
        if reason is not None:
            return "bad", html.escape(REASON_TEXT.get(reason, f"reason {reason}"))
        print(f"[register] {codes.format_code(key)} registered to {owner}")
        return "ok", (
            f"<code>{codes.format_code(key)}</code> is registered to "
            f"<code>{html.escape(owner)}</code>. Sign in on the client with that "
            "KONAMI ID, that personal key, and this code."
        )

    # -- http -------------------------------------------------------------

    def _respond(self, body: bytes, status: bytes = b"200 OK") -> bytes:
        return (
            b"HTTP/1.1 " + status + b"\r\n"
            b"Server: TokimekiOL-Local-Registration\r\n"
            b"Content-Type: text/html; charset=utf-8\r\n"
            b"Cache-Control: no-store\r\n"
            b"Connection: close\r\n"
            b"Content-Length: " + str(len(body)).encode("ascii") + b"\r\n\r\n" + body
        )

    def _handle_request(self, method: str, path: str, form: dict[str, str]) -> bytes:
        if method != "POST":
            return self._respond(page(forms()))
        if path == "/konami-id":
            message = self._create_id(form)
        elif path == "/register":
            message = self._register(form)
        else:
            return self._respond(page(forms()), b"404 Not Found")
        # The personal key is never echoed back into the page; every other field
        # is, so a rejected form can be corrected rather than retyped.
        keep = {k: v for k, v in form.items() if "key" not in k and k != "confirm"}
        return self._respond(page(forms(keep), message))

    async def handle(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=30.0)
        except (asyncio.TimeoutError, asyncio.IncompleteReadError, ValueError):
            writer.close()
            return
        try:
            lines = head.decode("latin1").split("\r\n")
            method, target, *_ = lines[0].split(" ")
            path = target.split("?", 1)[0]
            length = 0
            for line in lines[1:]:
                name, _, value = line.partition(":")
                if name.strip().lower() == "content-length":
                    length = int(value.strip() or 0)
            # Bounded because this reads whatever the peer says is coming, and
            # the largest honest form here is a few hundred bytes.
            body = await reader.readexactly(min(length, 8192)) if length else b""
            form = {
                k: v[0]
                for k, v in parse_qs(body.decode("utf-8", "replace")).items()
            }
            response = self._handle_request(method, path, form)
        except Exception as exc:  # a malformed request is not a reason to die
            print(f"[register] bad request: {type(exc).__name__}: {exc}")
            response = self._respond(page(forms()), b"400 Bad Request")
        writer.write(response)
        try:
            await writer.drain()
        except Exception:
            pass
        writer.close()

    async def run(self) -> asyncio.AbstractServer:
        server = await asyncio.start_server(
            self.handle, self.config.host, self.config.port
        )
        print(
            f"[register] 登録 form on http://{self.advertise_ip}:{self.config.port}/"
        )
        return server
