from __future__ import annotations

import asyncio
import ssl
import subprocess
from pathlib import Path
from urllib.parse import parse_qs

from common import ServiceConfig, ensure_runtime_dirs, write_packet_log


class AuthHttpServer:
    """Konami ID auth stub.

    Accepts TCP first (so failed TLS handshakes are still logged), then
    optionally upgrades with start_tls.
    """

    def __init__(
        self,
        root: Path,
        config: ServiceConfig,
        *,
        use_tls: bool = True,
        advertise_ip: str = "127.0.0.1",
    ) -> None:
        self.root = root
        self.config = config
        self.use_tls = use_tls
        self.advertise_ip = advertise_ip
        _, self.packet_dir = ensure_runtime_dirs(root)
        self.cert = root / "runtime" / "certs" / "auth.pem"
        if use_tls:
            self._ensure_cert()
            self.ssl_ctx = self._make_ssl_ctx()
        else:
            self.ssl_ctx = None

    def _ensure_cert(self) -> None:
        """Generate the auth certificate once, and never touch it again.

        Never regenerating is the point, not laziness. The client does not check
        the certificate — no chain validation, no CRL fetch — so nothing in this
        file has to match the deployment, and a cert that already works is worth
        more than a cert whose names are tidy. It is also the file a person is
        most likely to have replaced by hand.

        What the client *does* care about is the key: 1024-bit RSA signed with
        SHA-1. Its TLS predates anything else; handed a 2048/SHA-256 cert it
        aborts the handshake with a decrypt_error alert and the login screen
        shows 「初期化エラー」 ff0c:01.
        """
        self.cert.parent.mkdir(parents=True, exist_ok=True)
        if self.cert.exists():
            return
        # The names are cosmetic (see above), so the SAN just covers both the
        # loopback case and whatever this deployment advertises.
        addresses = ["127.0.0.1"]
        if self.advertise_ip not in addresses:
            addresses.append(self.advertise_ip)
        san = ",".join(f"IP:{addr}" for addr in addresses)
        subprocess.run(
            [
                "openssl",
                "req",
                "-x509",
                "-newkey",
                "rsa:1024",
                "-sha1",
                "-keyout",
                str(self.cert),
                "-out",
                str(self.cert),
                "-days",
                "3650",
                "-nodes",
                "-subj",
                f"/CN={self.advertise_ip}",
                "-addext",
                f"subjectAltName={san},DNS:localhost,DNS:sctrl01.game.konaminet.jp",
            ],
            check=True,
            capture_output=True,
        )
        self.cert.chmod(0o600)

    def _make_ssl_ctx(self) -> ssl.SSLContext:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        try:
            ctx.minimum_version = ssl.TLSVersion.SSLv3
        except (ValueError, AttributeError):
            try:
                ctx.minimum_version = ssl.TLSVersion.TLSv1
            except ValueError:
                pass
        try:
            ctx.maximum_version = ssl.TLSVersion.TLSv1_2
        except ValueError:
            pass
        try:
            ctx.set_ciphers("ALL:@SECLEVEL=0")
        except ssl.SSLError:
            ctx.set_ciphers("DEFAULT:@SECLEVEL=0")
        # Old clients may choke on TLS1.3-only defaults / session tickets.
        ctx.options |= ssl.OP_NO_TICKET
        try:
            ctx.options |= ssl.OP_LEGACY_SERVER_CONNECT  # type: ignore[attr-defined]
        except AttributeError:
            pass
        ctx.load_cert_chain(self.cert)
        return ctx

    def _http_response(self, body: bytes, status: bytes = b"200 OK") -> bytes:
        # Content-Length and the blank line are both load-bearing: the client's
        # receive loop (0x8A8DF0) keeps reading until it can find
        # "Content-Length: ", parse the number, find "\r\n\r\n", and see at
        # least that many bytes after it.
        return (
            b"HTTP/1.1 "
            + status
            + b"\r\n"
            + b"Server: TokimekiOL-Local-Auth\r\n"
            + b"Content-Type: text/plain; charset=Shift_JIS\r\n"
            + b"Cache-Control: no-cache\r\n"
            + b"Connection: Keep-Alive\r\n"
            + b"Content-Length: "
            + str(len(body)).encode("ascii")
            + b"\r\n\r\n"
            + body
        )

    # The KONAMI-ID exchange, read off the client's own parsers (tmo_orig.exe):
    #
    #   0x8A9EA0 runs three steps in order, each has to return 0:
    #     0x8A9720  /getkeylen.php   wants request_kind, msgno, response_code, key_len
    #     0x8A9B10  /getkey.php      wants request_kind, msgno, response_code, index,
    #                                csk -- and feeds csk to a PEM "PRIVATE KEY" parser
    #     0x8A9BF0  /login.php       wants request_kind, msgno, response_code, session_id
    #
    # Bodies are query strings: '&' between fields (0xBE93AC), '=' inside (0xBE93B0).
    # The checks at 0x8A9803-0x8A9852 are exact:
    #   request_kind   length 1, and the byte must be 'A'   (the request sends 'R')
    #   msgno          parses to the msgno the request carried
    #   response_code  length exactly 3, and parses to 0    -> "000", never "0"
    #
    # An earlier version of this stub answered newline-separated "response_code=0",
    # which fails all three, and the client shows "初期化エラー ... ff0c:01".
    #
    # msgno is per step and the client checks it against its own request:
    # getkeylen 10, getkey 11 (0x8A99B8), login 12 (0x8A9D05), logout 13.
    # Echoing the request's msgno satisfies all of them.
    #
    # getkey runs TWICE, with index=1 then index=2, and the two csk values are
    # concatenated (0x8A9B41-0x8A9BA8) before being base64-decoded into one key.
    # csk is not read like the other fields: 0x8A99EB takes it as "everything
    # from the value to the end of the response", then 0x8A9A37 splits that on
    # CR/LF and drops any line containing "PRIVATE KEY".  So csk must come last,
    # it may contain real newlines, and a plain PEM is exactly the right shape --
    # the armour lines are stripped and the base64 in between is kept.
    SESSION_ID = "localsession0001"

    def _reply_fields(self, form: dict[str, list[str]], **extra: str) -> bytes:
        fields = {
            "request_kind": "A",
            "msgno": (form.get("msgno") or ["10"])[0],
            "response_code": "000",
        }
        fields.update(extra)
        return "&".join(f"{k}={v}" for k, v in fields.items()).encode("ascii", "ignore")

    def _client_key(self) -> list[str]:
        """The PEM the client collects as ``csk``, as a list of lines."""
        path = self.cert.parent / "csk.pem"
        if not path.exists():
            subprocess.run(
                ["openssl", "genrsa", "-out", str(path), "1024"],
                check=True, capture_output=True,
            )
            path.chmod(0o600)
        return [ln for ln in path.read_text().splitlines() if ln]

    def _csk_half(self, index: str) -> str:
        """Half the key PEM, keeping the armour line that belongs with it.

        The client strips "PRIVATE KEY" lines from both halves and concatenates
        what is left, so any split of the base64 lines works as long as each
        half is whole lines.
        """
        lines = self._client_key()
        body = [ln for ln in lines if "PRIVATE KEY" not in ln]
        cut = (len(body) + 1) // 2
        if index == "2":
            return "\n".join(body[cut:] + [lines[-1]]) + "\n"
        return "\n".join([lines[0]] + body[:cut]) + "\n"

    def _build_body(self, path: str, form: dict[str, list[str]], seq: dict) -> bytes:
        if path.endswith("getkeylen.php"):
            # The client parses key_len and then throws it away (0x8A9720 keeps
            # it in a local and returns), so this number is informational only.
            payload = "".join(
                ln for ln in self._client_key() if "PRIVATE KEY" not in ln
            )
            return self._reply_fields(form, key_len=str(len(payload)))
        if path.endswith("getkey.php"):
            # The real client sends the two getkey requests byte-for-byte
            # identical -- no index field, despite 0x8A9570 appearing to append
            # one.  It tracks the halves itself (first reply -> ctx+0x7C, second
            # -> ctx+0x80, 0x8A9AD3), so the only thing that tells the two apart
            # is their order on the connection.  Count them.
            seq["getkey"] = seq.get("getkey", 0) + 1
            index = "2" if seq["getkey"] >= 2 else "1"
            return self._reply_fields(form, index=index, csk=self._csk_half(index))
        if path.endswith("login.php"):
            return self._reply_fields(form, session_id=self.SESSION_ID)
        if path.endswith("logout.php"):
            return self._reply_fields(form)
        # CRL / unknown paths
        if "crl" in path.lower():
            return b""
        return self._reply_fields(form)

    def _parse(self, raw: bytes) -> tuple[str, dict[str, list[str]]]:
        path = "/"
        form: dict[str, list[str]] = {}
        if not raw:
            return path, form
        try:
            head, _, body = raw.partition(b"\r\n\r\n")
            req_line = head.split(b"\r\n", 1)[0].decode("latin1", errors="ignore")
            parts = req_line.split(" ")
            if len(parts) >= 2:
                target = parts[1]
                path = target.split("?", 1)[0]
                if "?" in target:
                    form = parse_qs(target.split("?", 1)[1])
            if body:
                form.update(parse_qs(body.decode("latin1", errors="ignore")))
        except Exception as exc:
            print(f"[authhttp] parse error: {exc}")
        return path, form

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peer = writer.get_extra_info("peername")
        print(f"[authhttp] ACCEPT port={self.config.port} peer={peer} tls_pending={self.use_tls}")
        write_packet_log(self.packet_dir, "authhttp", f"accept-{self.config.port}", b"")

        if self.use_tls and self.ssl_ctx is not None:
            try:
                # Server-side upgrade: context is PROTOCOL_TLS_SERVER (no server_side kw).
                await asyncio.wait_for(writer.start_tls(self.ssl_ctx), timeout=20.0)
                print(f"[authhttp] TLS-OK port={self.config.port} peer={peer}")
            except Exception as exc:
                print(
                    f"[authhttp] TLS-FAIL port={self.config.port} peer={peer}: "
                    f"{type(exc).__name__}: {exc}"
                )
                write_packet_log(
                    self.packet_dir,
                    "authhttp",
                    f"tls-fail-{self.config.port}",
                    str(exc).encode("utf-8", errors="replace"),
                )
                writer.close()
                try:
                    await writer.wait_closed()
                except Exception:
                    pass
                return

        # The client runs the whole KONAMI-ID sequence -- getkeylen, getkey x2,
        # login -- down ONE connection, and it does not reconnect.  Closing
        # after the first reply makes step 2's SSL_write fail with no socket
        # traffic at all, which reads exactly like a rejected reply.  So serve
        # requests in a loop and let the client hang up.
        seq: dict[str, int] = {}
        try:
            while True:
                try:
                    head = await asyncio.wait_for(
                        reader.readuntil(b"\r\n\r\n"), timeout=60.0
                    )
                except (asyncio.TimeoutError, asyncio.IncompleteReadError):
                    break
                except Exception:
                    break
                # Requests carry their fields in the query string; the client
                # never sends a body, so headers are the whole request.
                write_packet_log(self.packet_dir, "authhttp", "in", head)
                path, form = self._parse(head)
                resp = self._http_response(self._build_body(path, form, seq))
                write_packet_log(self.packet_dir, "authhttp", "out", resp)
                writer.write(resp)
                await writer.drain()
                print(
                    f"[authhttp] {peer} port={self.config.port} tls={self.use_tls} "
                    f"path={path} recv={len(head)} send={len(resp)}"
                )
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
            print(f"[authhttp] CLOSE port={self.config.port} peer={peer}")

    async def run(self) -> asyncio.AbstractServer:
        # Always bind plain TCP; TLS is applied per-connection in handle().
        server = await asyncio.start_server(self.handle, self.config.host, self.config.port)
        mode = "tcp+tls" if self.use_tls else "plain"
        print(f"[authhttp] listening on {self.config.host}:{self.config.port} ({mode})")
        return server
