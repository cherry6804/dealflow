"""A stand-in ClamAV daemon for the test session (DFR1-035 hardening).

It speaks the clamd INSTREAM protocol over TCP, so the real scanner client runs end to end. It is not a malware engine: it
reports the EICAR standard antivirus test string as a finding and everything else as clean. Its behaviour can be switched
per test through ``FAKE_CLAMD.mode``. No test contacts a real scanner or a real malware sample.
"""

from __future__ import annotations

import socket
import struct
import threading

EICAR_SIGNATURE = b"EICAR-STANDARD-ANTIVIRUS-TEST-FILE"
EICAR_NAME = "Eicar-Test-Signature"
MODES = frozenset({"normal", "silent", "garbage", "size_limit"})


def _recv_exact(conn: socket.socket, count: int) -> bytes:
    data = bytearray()
    while len(data) < count:
        piece = conn.recv(count - len(data))
        if not piece:
            raise ConnectionError("client closed the stream early")
        data.extend(piece)
    return bytes(data)


def _recv_command(conn: socket.socket) -> bytes:
    data = bytearray()
    while True:
        byte = conn.recv(1)
        if not byte or byte == b"\0":
            return bytes(data)
        data.extend(byte)
        if len(data) > 64:
            return bytes(data)


class FakeClamd:
    def __init__(self) -> None:
        self.mode = "normal"
        self.scans = 0
        self.port = 0
        self._listener: socket.socket | None = None
        self._lock = threading.Lock()

    def start(self) -> int:
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 0))
        listener.listen(16)
        self._listener = listener
        self.port = listener.getsockname()[1]
        threading.Thread(target=self._accept_loop, name="fake-clamd", daemon=True).start()
        return self.port

    def _accept_loop(self) -> None:
        assert self._listener is not None
        while True:
            try:
                conn, _address = self._listener.accept()
            except OSError:
                return
            threading.Thread(target=self._handle, args=(conn,), daemon=True).start()

    def _handle(self, conn: socket.socket) -> None:
        with conn:
            conn.settimeout(10)
            try:
                if _recv_command(conn) != b"zINSTREAM":
                    conn.sendall(b"UNKNOWN COMMAND\0")
                    return
                with self._lock:
                    self.scans += 1
                mode = self.mode
                data = bytearray()
                while True:
                    length = struct.unpack("!I", _recv_exact(conn, 4))[0]
                    if length == 0:
                        break
                    data.extend(_recv_exact(conn, length))
                if mode == "silent":
                    return  # Close without a reply: the client must treat this as unavailable.
                if mode == "garbage":
                    conn.sendall(b"something unexpected\0")
                elif mode == "size_limit":
                    conn.sendall(b"INSTREAM size limit exceeded. ERROR\0")
                elif EICAR_SIGNATURE in data:
                    conn.sendall(f"stream: {EICAR_NAME} FOUND\0".encode())
                else:
                    conn.sendall(b"stream: OK\0")
            except OSError:
                return


FAKE_CLAMD = FakeClamd()
