import socket
import os
import json
import threading
import struct
import time

from protocol.config import SERVER_HOST, APP_PORT, APP_TCP_PORT, BUFFER_SIZE
from protocol.rudp import RUDP

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE_PATH = os.path.join(BASE_DIR, "assets", "gallery")


class AppServer:
    def __init__(self):
        # --- UDP (RUDP) ---
        self.udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp_sock.bind((SERVER_HOST, APP_PORT))
        self.rudp = RUDP(self.udp_sock)

        # --- TCP ---
        self.tcp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.tcp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.tcp_sock.bind((SERVER_HOST, APP_TCP_PORT))
        self.tcp_sock.listen(5)

        print(f"[APP] UDP Server running on {SERVER_HOST}:{APP_PORT}")
        print(f"[APP] TCP Server running on {SERVER_HOST}:{APP_TCP_PORT}")

    # ---------- Common helpers ----------
    def build_manifest(self):
        qualities = sorted([
            q for q in os.listdir(BASE_PATH)
            if os.path.isdir(os.path.join(BASE_PATH, q))
        ])

        files_sets = []
        for q in qualities:
            q_path = os.path.join(BASE_PATH, q)
            files = [
                f for f in os.listdir(q_path)
                if f.lower().endswith((".jpg", ".jpeg", ".png"))
            ]
            files_sets.append(set(files))

        common_files = sorted(list(set.intersection(*files_sets))) if files_sets else []

        return {
            "type": "MANIFEST_RESPONSE",
            "qualities": qualities,
            "files": common_files
        }

    def load_image_bytes(self, quality, filename):
        image_path = os.path.join(BASE_PATH, quality, filename)
        if not os.path.exists(image_path):
            return None
        with open(image_path, "rb") as f:
            return f.read()

    # ---------- UDP loop ----------
    def udp_loop(self):
        while True:
            try:
                data, addr = self.udp_sock.recvfrom(BUFFER_SIZE)
            except TimeoutError:
                continue

            message = json.loads(data.decode())

            if message["type"] == "MANIFEST":
                manifest = self.build_manifest()
                self.udp_sock.sendto(json.dumps(manifest).encode(), addr)
                print(f"[APP][UDP] Manifest sent (qualities={manifest['qualities']}, files={len(manifest['files'])})")

            elif message["type"] == "GET_IMAGE":
                quality = message["quality"]
                filename = message["filename"]

                # protocol mode for RUDP
                protocol = message.get("protocol", "SR")  # STOP_WAIT / GBN / SR
                self.rudp.set_mode(protocol)

                img = self.load_image_bytes(quality, filename)
                if img is None:
                    err = {"type": "ERROR", "message": f"File not found: {quality}/{filename}"}
                    self.udp_sock.sendto(json.dumps(err).encode(), addr)
                    print(f"[APP][UDP] ERROR: {err['message']}")
                    continue

                print(f"[APP][UDP] Sending image ({quality}/{filename}) size={len(img)} bytes, RUDP={protocol}")

                self.rudp.reset_sender()
                start = time.time()
                self.rudp.send_bytes(img, addr)
                end = time.time()

                stats = self.rudp.get_sender_stats()
                transfer_time = end - start
                throughput = (len(img) / 1024) / transfer_time if transfer_time > 0 else 0.0
                total_attempts = stats["sent"] + stats["dropped"]
                loss_rate = (stats["dropped"] / total_attempts) * 100 if total_attempts else 0.0

                print("[APP][UDP] Image streaming completed")
                print("\n========== RUDP STATISTICS (SENDER) ==========")
                print(f"Packets sent:             {stats['sent']}")
                print(f"Simulated loss:           {stats['dropped']}")
                print(f"Retransmissions:          {stats['retransmissions']}")
                print(f"Fast retransmissions:     {stats['fast_retransmissions']}")
                print(f"Loss rate:                {loss_rate:.2f}%")
                print(f"Transfer time:            {transfer_time:.2f} sec")
                print(f"Throughput:               {throughput:.2f} KB/s")
                print("==============================================\n")

    # ---------- TCP server ----------
    def tcp_loop(self):
        while True:
            conn, addr = self.tcp_sock.accept()
            t = threading.Thread(target=self.handle_tcp_client, args=(conn, addr), daemon=True)
            t.start()

    def recv_exact(self, conn, n):
        buf = b""
        while len(buf) < n:
            chunk = conn.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("TCP connection closed")
            buf += chunk
        return buf

    def handle_tcp_client(self, conn, addr):
        try:
            # 1) read length-prefixed JSON request
            raw_len = self.recv_exact(conn, 4)
            (msg_len,) = struct.unpack("!I", raw_len)
            raw = self.recv_exact(conn, msg_len)
            message = json.loads(raw.decode())

            if message["type"] == "MANIFEST":
                manifest = self.build_manifest()
                payload = json.dumps(manifest).encode()
                conn.sendall(struct.pack("!I", len(payload)) + payload)
                print(f"[APP][TCP] Manifest sent to {addr}")

            elif message["type"] == "GET_IMAGE":
                quality = message["quality"]
                filename = message["filename"]

                img = self.load_image_bytes(quality, filename)
                if img is None:
                    err = {"type": "ERROR", "message": f"File not found: {quality}/{filename}"}
                    payload = json.dumps(err).encode()
                    conn.sendall(struct.pack("!I", len(payload)) + payload)
                    print(f"[APP][TCP] ERROR to {addr}: {err['message']}")
                    return

                print(f"[APP][TCP] Sending image ({quality}/{filename}) size={len(img)} bytes to {addr}")

                # Send header: OK + size
                header = json.dumps({"type": "OK", "size": len(img)}).encode()
                conn.sendall(struct.pack("!I", len(header)) + header)

                # Then send bytes
                conn.sendall(img)
                print(f"[APP][TCP] Image sent to {addr}")

        except Exception as e:
            print(f"[APP][TCP] Client {addr} error: {e}")
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def start(self):
        # run TCP in background thread, UDP in main
        threading.Thread(target=self.tcp_loop, daemon=True).start()
        self.udp_loop()


if __name__ == "__main__":
    AppServer().start()