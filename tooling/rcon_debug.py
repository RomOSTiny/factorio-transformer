"""Diagnostic probe for the Factorio RCON handshake — prints every raw
packet exchanged so we can see exactly where the protocol assumption in
rcon_client.py breaks, instead of guessing."""
import json
import os
import socket
import struct

CFG = json.load(open(os.path.join(os.path.dirname(__file__), "rcon_config.json"), encoding="utf-8"))


def send(sock, req_id, pkt_type, body):
    payload = struct.pack("<ii", req_id, pkt_type) + body.encode("utf-8") + b"\x00\x00"
    packet = struct.pack("<i", len(payload)) + payload
    print(f">>> send id={req_id} type={pkt_type} body={body!r} raw={packet!r}")
    sock.sendall(packet)


def try_recv(sock, timeout):
    sock.settimeout(timeout)
    try:
        header = sock.recv(4)
        if not header:
            print("<<< connection closed (empty recv)")
            return None
        while len(header) < 4:
            header += sock.recv(4 - len(header))
        (length,) = struct.unpack("<i", header)
        data = b""
        while len(data) < length:
            chunk = sock.recv(length - len(data))
            if not chunk:
                break
            data += chunk
        req_id, pkt_type = struct.unpack("<ii", data[:8])
        body = data[8:-2].decode("utf-8", errors="replace")
        print(f"<<< recv id={req_id} type={pkt_type} body={body!r} raw_len={length}")
        return req_id, pkt_type, body
    except TimeoutError:
        print(f"<<< TIMEOUT after {timeout}s waiting for a packet")
        return None


sock = socket.create_connection((CFG["host"], CFG["port"]), timeout=10)
print("connected")

send(sock, 1, 3, CFG["password"])  # SERVERDATA_AUTH
print("--- reading auth response(s), up to 2 packets ---")
try_recv(sock, 5)
try_recv(sock, 5)

print("--- sending exec command WITH leading slash ---")
send(sock, 2, 2, '/c game.print("rcon probe A")')
try_recv(sock, 8)

print("--- sending exec command WITHOUT leading slash ---")
send(sock, 3, 2, 'c game.print("rcon probe B")')
try_recv(sock, 8)

print("--- sending plain silent-command form ---")
send(sock, 4, 2, 'silent-command game.print("rcon probe C")')
try_recv(sock, 8)

sock.close()

sock2 = socket.create_connection((CFG["host"], CFG["port"]), timeout=10)
send(sock2, 1, 3, CFG["password"])
try_recv(sock2, 5)
print("--- sending EMPTY command ---")
send(sock2, 2, 2, '')
try_recv(sock2, 8)
print("--- sending another real command right after, same connection ---")
send(sock2, 3, 2, '/c rcon.print("after empty")')
try_recv(sock2, 8)
sock2.close()
