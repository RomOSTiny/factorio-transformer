"""Minimal Source-RCON client for Factorio (no external dependencies).

Factorio implements the same wire protocol as Source engine RCON. This
replaces the old clipboard+manual-paste workflow: commands are delivered
over a TCP socket with a synchronous, per-command response, so there is
never ambiguity about whether a command was received (unlike the banned
SendInput/keystroke-emulation approach, which failed silently and led to
a blind retry duplicating a build).

Requires the target save to be running via "Host Saved Game" (not plain
"Continue") with local-rcon-socket/local-rcon-password set in config.ini.
"""
import json
import os
import socket
import struct

SERVERDATA_AUTH = 3
SERVERDATA_EXECCOMMAND = 2
SERVERDATA_RESPONSE_VALUE = 0

DEFAULT_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "rcon_config.json")


class RconError(Exception):
    pass


class RconClient:
    def __init__(self, host, port, password, timeout=5.0):
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.sock.settimeout(timeout)
        self._next_id = 1
        self._auth(password)

    def _send_packet(self, pkt_type, body):
        req_id = self._next_id
        self._next_id += 1
        payload = struct.pack("<ii", req_id, pkt_type) + body.encode("utf-8") + b"\x00\x00"
        self.sock.sendall(struct.pack("<i", len(payload)) + payload)
        return req_id

    def _recvall(self, n):
        buf = b""
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise RconError("connection closed while reading")
            buf += chunk
        return buf

    def _recv_packet(self):
        (length,) = struct.unpack("<i", self._recvall(4))
        data = self._recvall(length)
        req_id, pkt_type = struct.unpack("<ii", data[:8])
        body = data[8:-2].decode("utf-8", errors="replace")
        return req_id, pkt_type, body

    def _auth(self, password):
        self._send_packet(SERVERDATA_AUTH, password)
        req_id, pkt_type, _ = self._recv_packet()
        if pkt_type == SERVERDATA_RESPONSE_VALUE:
            req_id, pkt_type, _ = self._recv_packet()
        if req_id == -1:
            raise RconError("RCON auth failed (wrong password?)")

    def command(self, cmd):
        """Send one console command, return its response body.

        One send, one blocking receive — confirmed empirically (see
        tooling/rcon_debug.py) that Factorio's RCON always replies with
        exactly one packet per command and, critically, does NOT reply at
        all to an empty-body command. An earlier version of this client
        sent a trailing empty command as an end-of-multi-packet marker
        (a technique from the general Source RCON protocol); Factorio
        silently drops that empty packet, which deadlocked every call
        waiting for a response that never arrives. Output text only
        comes through for `rcon.print(...)` — `game.print(...)` returns
        an empty body (goes to game chat, not the RCON channel).
        """
        self._send_packet(SERVERDATA_EXECCOMMAND, cmd)
        _req_id, _pkt_type, body = self._recv_packet()
        return body

    def close(self):
        self.sock.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def load_config(path=None):
    with open(path or DEFAULT_CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def connect(path=None, timeout=5.0):
    cfg = load_config(path)
    return RconClient(cfg["host"], cfg["port"], cfg["password"], timeout=timeout)


if __name__ == "__main__":
    import sys

    cmd = sys.argv[1] if len(sys.argv) > 1 else '/c game.print("rcon test ok")'
    with connect() as client:
        print(repr(client.command(cmd)))
