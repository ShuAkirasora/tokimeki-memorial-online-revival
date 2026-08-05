from __future__ import annotations

import asyncio
import os
import shutil
import ssl
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import parse_qs

from common import ServiceConfig, ensure_runtime_dirs, write_packet_log


def _windows_openssl() -> list[Path]:
    """Where an openssl.exe is likely to be sitting, unannounced.

    Windows ships none, and unlike macOS and Linux there is no package manager
    that will have put one on PATH as a side effect of something else. What is
    on these machines is Git for Windows -- which carries a complete openssl in
    its own bin directories and adds neither to PATH -- so look there before
    telling anyone to go and install something they already have.
    """
    if os.name != "nt":
        return []
    roots = [
        os.environ.get("ProgramFiles"),
        os.environ.get("ProgramFiles(x86)"),
        os.environ.get("ProgramW6432"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs"),
    ]
    relative = [
        Path("Git") / "usr" / "bin" / "openssl.exe",
        Path("Git") / "mingw64" / "bin" / "openssl.exe",
        Path("OpenSSL-Win64") / "bin" / "openssl.exe",
    ]
    return [Path(root) / rel for root in roots if root for rel in relative]


def openssl_path() -> str:
    """The openssl to run, or a failure that says what to do about it.

    This is the one thing outside the standard library, and it is needed once:
    the client will not accept a certificate that is not 1024-bit RSA signed
    with SHA-1 (see _ensure_cert), and the ssl module can read such a thing but
    not produce one.
    """
    found = shutil.which("openssl")
    if found:
        return found
    for candidate in _windows_openssl():
        if candidate.exists():
            return str(candidate)
    hint = (
        " Git for Windows ships one; add its usr\\bin directory to PATH, or"
        " install OpenSSL for Windows."
        if os.name == "nt"
        else ""
    )
    raise RuntimeError(
        "openssl is not on PATH, and the auth endpoint's certificate cannot be"
        f" generated without it.{hint}"
    )


# An openssl configuration that says SHA-1 signatures are allowed, for the
# distributions that say they are not. See _generate_cert; it is handed to one
# openssl process through OPENSSL_CONF and changes nothing about the machine.
#
# The [req] section is here because naming a configuration file replaces the
# system one entirely, and openssl req wants that section to exist. It can be
# empty: the subject and the extensions are on the command line.
SHA1_OPENSSL_CONF = """\
openssl_conf = openssl_init

[openssl_init]
alg_section = evp_properties

[evp_properties]
rh-allow-sha1-signatures = yes

[req]
distinguished_name = req_distinguished_name

[req_distinguished_name]
"""


class _TlsAcceptor(asyncio.Protocol):
    """Holds a new connection still until TLS has been put underneath it.

    connection_made always runs before any data_received, so pausing the
    transport here means the ClientHello cannot be handed to the wrong protocol:
    it stays in the kernel until start_tls has the SSL layer in place and resumes
    reading. That is this class's whole job.

    ⚠️ Why it exists at all. This used to accept with asyncio.start_server and
    upgrade inside the handler with ``writer.start_tls()``, and that is a race
    against the client that the client wins whenever its ClientHello arrives
    before the handler is scheduled: the bytes go to the StreamReader, which is
    not the TLS layer and cannot give them back, and the handshake then waits out
    its timeout for a hello that has already been and gone. On Linux it is not a
    race but a certainty -- epoll reports the accept and the data together, the
    handler is always second, and *every* connection to 443 timed out. macOS had
    been winning the same race on scheduling, which is luck reading as
    correctness.
    """

    def __init__(self, server: "AuthHttpServer") -> None:
        self._server = server
        self._upgrade: asyncio.Task | None = None

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        transport.pause_reading()
        # Kept on the instance because the loop holds only a weak reference to a
        # bare task, and this one must outlive the callback that made it.
        self._upgrade = asyncio.get_running_loop().create_task(
            self._server.upgrade_and_serve(transport)  # type: ignore[arg-type]
        )


class AuthHttpServer:
    """Konami ID auth stub.

    A TLS port is accepted plain and upgraded before a byte of it is read (see
    _TlsAcceptor), which keeps what the upgrade was there for -- a connection
    that arrives and a handshake that fails are two different log lines -- and
    loses the race that the obvious form of it has. Handing the context to the
    listener instead would also be race-free, but asyncio then reports a failed
    handshake to nobody at all: not to the handler, which never runs, and not to
    the loop's exception handler, which was asked and receives nothing. A
    client that cannot get through this step is exactly the case the log is
    read for.
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
        self._generate_cert(
            [
                openssl_path(),
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
            ]
        )
        # The file holds the private key as well as the certificate. On Windows
        # chmod reaches only the read-only bit and this does nothing; the key is
        # protected there by whatever the runtime\certs directory inherits,
        # which for a directory under a user profile is that user alone.
        self.cert.chmod(0o600)

    def _generate_cert(self, argv: list[str]) -> None:
        """Run openssl, and if the refusal is about SHA-1, ask once more.

        SHA-1 is not a preference here (see _ensure_cert), and it is precisely
        what a current Linux distribution has arranged for openssl to refuse:
        RHEL, Fedora and their derivatives put every OpenSSL process under a
        system-wide crypto policy that since RHEL 9 declines to *produce* a
        SHA-1 signature, so this command exits non-zero on a stock install and
        the server cannot start. Their setting for it lives in the openssl
        configuration, and naming a configuration file in the environment
        applies it to this one process: the machine's own policy is untouched,
        and nothing else on the host will accept anything it did not before.

        The override is a retry rather than the first attempt because the
        setting is theirs -- an OpenSSL that never had the restriction rejects
        the name outright, so passing it everywhere would break generation on
        the platforms that were working. If the retry fails too, the error
        reported is the *first* one, that being the one this machine gave to the
        command as it is normally run.

        Both attempts are judged by the file rather than by the exit status,
        because neither failure looks the way it should. A run that stops after
        the key is written leaves half a PEM, since key and certificate go to
        the same path -- keep it and the next start finds a file, skips
        generation, and hands the ssl module something with nothing to serve.
        And an openssl given a configuration file it does not understand (a
        LibreSSL, say) prints its complaint, writes nothing at all, and still
        exits 0. Asking what is on disk covers both without having to know which
        openssl this is.
        """
        first = subprocess.run(argv, capture_output=True, text=True, errors="replace")
        if first.returncode == 0 and self._cert_complete():
            return
        self.cert.unlink(missing_ok=True)
        with tempfile.TemporaryDirectory() as tmp:
            conf = Path(tmp) / "sha1.cnf"
            conf.write_text(SHA1_OPENSSL_CONF, encoding="ascii")
            retry = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                errors="replace",
                env={**os.environ, "OPENSSL_CONF": str(conf)},
            )
        if retry.returncode == 0 and self._cert_complete():
            return
        self.cert.unlink(missing_ok=True)
        raise RuntimeError(
            f"openssl did not produce the auth certificate (exit {first.returncode})."
            " It has to be 1024-bit RSA signed with SHA-1, which is all this"
            " client will accept, and a distribution crypto policy that forbids"
            " SHA-1 signatures refuses to make one; that was retried with the"
            " policy overridden for the one command, and it also failed."
            f" openssl said: {(first.stderr or '').strip()}"
        )

    def _cert_complete(self) -> bool:
        """Is there a PEM on disk with both halves in it?"""
        try:
            text = self.cert.read_text(encoding="ascii", errors="replace")
        except OSError:
            return False
        return "PRIVATE KEY-----" in text and "CERTIFICATE-----" in text

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
                [openssl_path(), "genrsa", "-out", str(path), "1024"],
                check=True, capture_output=True,
            )
            path.chmod(0o600)
        return [ln for ln in path.read_text(encoding="ascii").splitlines() if ln]

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
        # Reaching here at all means the handshake is done, so this says what was
        # agreed rather than what is about to be attempted.
        tls = writer.get_extra_info("ssl_object")
        how = f"{tls.version()} {tls.cipher()[0]}" if tls else "plain"
        print(f"[authhttp] ACCEPT port={self.config.port} peer={peer} ({how})")
        write_packet_log(self.packet_dir, "authhttp", f"accept-{self.config.port}", b"")

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

    async def upgrade_and_serve(self, transport: asyncio.Transport) -> None:
        """Put TLS under a held connection, then serve it as ordinary streams.

        The streams are built by hand because start_tls is what creates the
        transport they have to sit on. Whether it also announces that transport
        to the protocol differs between Python versions -- it passes
        call_connection_made=False today, and the flag is not ours -- so the
        callback records that it ran and the announcement is made here only if
        it did not happen already. Either way handle() is entered exactly once.
        """
        loop = asyncio.get_running_loop()
        peer = transport.get_extra_info("peername")
        reader = asyncio.StreamReader(loop=loop)
        served = False

        def connected(r: asyncio.StreamReader, w: asyncio.StreamWriter):
            nonlocal served
            served = True
            return self.handle(r, w)

        protocol = asyncio.StreamReaderProtocol(reader, connected, loop=loop)
        try:
            tls_transport = await loop.start_tls(
                transport, protocol, self.ssl_ctx, server_side=True, ssl_handshake_timeout=20.0
            )
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
            transport.close()
            return
        if tls_transport is None:
            # start_tls hands back the SSL protocol's own transport, and that
            # attribute is cleared the instant the connection is lost -- so a
            # peer that finishes the handshake and hangs up in the same breath,
            # which is what a port scan or a health check looks like, arrives
            # here as None rather than as an exception.
            print(
                f"[authhttp] TLS-GONE port={self.config.port} peer={peer}: "
                "peer closed as the handshake completed"
            )
            transport.close()
            return
        if not served:
            protocol.connection_made(tls_transport)

    async def run(self) -> asyncio.AbstractServer:
        if self.ssl_ctx is not None:
            loop = asyncio.get_running_loop()
            server = await loop.create_server(
                lambda: _TlsAcceptor(self), self.config.host, self.config.port
            )
        else:
            server = await asyncio.start_server(
                self.handle, self.config.host, self.config.port
            )
        mode = "tcp+tls" if self.use_tls else "plain"
        print(f"[authhttp] listening on {self.config.host}:{self.config.port} ({mode})")
        return server
