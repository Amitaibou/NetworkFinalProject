import socket
import json
import time

from protocol.config import SERVER_HOST, APP_PORT, APP_TCP_PORT, BUFFER_SIZE
from protocol.rudp import RUDP


class AppClient:

    def __init__(self):

        # UDP socket (for RUDP)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.rudp = RUDP(self.sock)

    # ---------------- MANIFEST ----------------
    def get_manifest(self):

        request = {"type": "MANIFEST"}

        self.sock.sendto(
            json.dumps(request).encode(),
            (SERVER_HOST, APP_PORT)
        )

        data, _ = self.sock.recvfrom(BUFFER_SIZE)

        manifest = json.loads(data.decode())

        print("[CLIENT] Available qualities:", manifest["qualities"])
        print("[CLIENT] Available files:", manifest["files"])

        return manifest

    # ---------------- AUTO QUALITY ----------------
    def choose_quality_auto(self, qualities, bandwidth_kb_s):

        if bandwidth_kb_s < 500 and "low" in qualities:
            return "low"

        if bandwidth_kb_s < 2000 and "mid" in qualities:
            return "mid"

        return "high" if "high" in qualities else qualities[0]

    # =========================================================
    # TCP DOWNLOAD
    # =========================================================
    def download_image_tcp(self, quality, filename):

        tcp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

        tcp_sock.connect((SERVER_HOST, APP_TCP_PORT))

        request = {
            "type": "GET_IMAGE",
            "quality": quality,
            "filename": filename
        }

        msg = json.dumps(request).encode()

        tcp_sock.sendall(len(msg).to_bytes(4, "big") + msg)

        header_size = int.from_bytes(tcp_sock.recv(4), "big")

        header = tcp_sock.recv(header_size)

        header = json.loads(header.decode())

        size = header["size"]

        image_data = bytearray()

        start_time = time.time()

        while len(image_data) < size:
            chunk = tcp_sock.recv(4096)
            if not chunk:
                break
            image_data.extend(chunk)

        end_time = time.time()

        tcp_sock.close()

        download_time = end_time - start_time
        bandwidth = len(image_data) / download_time if download_time > 0 else 0

        print(f"[CLIENT][TCP] Download time: {download_time:.2f} seconds")
        print(f"[CLIENT][TCP] Size: {len(image_data)} bytes")
        print(f"[CLIENT][TCP] Bandwidth: {bandwidth/1024:.2f} KB/s")

        with open("downloaded.jpg", "wb") as f:
            f.write(image_data)

        print(f"[CLIENT][TCP] Image saved (TCP)")

        return download_time, (bandwidth / 1024)

    # =========================================================
    # RUDP DOWNLOAD
    # =========================================================
    def download_image_rudp(self, quality, filename, protocol):

        request = {
            "type": "GET_IMAGE",
            "quality": quality,
            "filename": filename,
            "protocol": protocol
        }

        self.sock.sendto(
            json.dumps(request).encode(),
            (SERVER_HOST, APP_PORT)
        )

        image_data = bytearray()

        start_time = time.time()

        self.rudp.reset_receiver()

        while True:

            chunk, _, fin = self.rudp.receive()

            if fin:
                break

            if chunk:
                image_data.extend(chunk)

        end_time = time.time()

        download_time = end_time - start_time
        size = len(image_data)

        bandwidth = size / download_time if download_time > 0 else 0

        print(f"[CLIENT][RUDP] Download time: {download_time:.2f} seconds")
        print(f"[CLIENT][RUDP] Size: {size} bytes")
        print(f"[CLIENT][RUDP] Estimated bandwidth: {bandwidth / 1024:.2f} KB/s")

        with open("downloaded.jpg", "wb") as f:
            f.write(image_data)

        print(f"[CLIENT][RUDP] Image saved ({quality}/{filename})")

        return download_time, (bandwidth / 1024)

    # =========================================================
    # TRANSPORT DISPATCHER
    # =========================================================
    def download_image(self, quality, filename, transport, protocol=None):

        if transport == "TCP":
            return self.download_image_tcp(quality, filename)

        else:
            return self.download_image_rudp(quality, filename, protocol)


# =========================================================
# MAIN
# =========================================================
if __name__ == "__main__":

    client = AppClient()

    manifest = client.get_manifest()

    qualities = manifest["qualities"]
    files = manifest["files"]

    if not files:
        print("[CLIENT] No files found")
        exit(1)

    # ---------------- FILE ----------------
    print("\nChoose a file:")
    for i, f in enumerate(files, start=1):
        print(f"{i}. {f}")

    choice = int(input("File number: "))
    filename = files[choice - 1]

    # ---------------- TRANSPORT ----------------
    print("\nChoose transport protocol:")
    print("1. TCP")
    print("2. RUDP")

    transport_choice = input("Protocol: ").strip()

    if transport_choice == "1":
        transport = "TCP"
    else:
        transport = "RUDP"

    protocol = None

    if transport == "RUDP":

        print("\nChoose RUDP algorithm:")
        print("1. Stop & Wait")
        print("2. Go Back N")
        print("3. Selective Repeat")

        proto_choice = input("RUDP Mode: ").strip()

        if proto_choice == "1":
            protocol = "STOP_WAIT"
        elif proto_choice == "2":
            protocol = "GBN"
        else:
            protocol = "SR"

        print(f"[CLIENT] Selected RUDP mode: {protocol}")

    # ---------------- MODE ----------------
    mode = input("\nChoose mode:\n1. AUTO (adaptive)\n2. MANUAL\nMode: ").strip()

    if mode == "2":

        print("\nChoose quality:")
        for i, q in enumerate(qualities, start=1):
            print(f"{i}. {q}")

        q_choice = int(input("Quality number: "))

        quality = qualities[q_choice - 1]

        client.download_image(quality, filename, transport, protocol)

    else:

        probe_quality = "low" if "low" in qualities else qualities[0]

        print(f"\n[AUTO] Probing network using quality: {probe_quality}")

        _, bw_kb_s = client.download_image(probe_quality, filename, transport, protocol)

        chosen = client.choose_quality_auto(qualities, bw_kb_s)

        if chosen != probe_quality:

            print(f"[AUTO] Based on bandwidth {bw_kb_s:.2f} KB/s -> choosing: {chosen}")

            client.download_image(chosen, filename, transport, protocol)

        else:

            print(f"[AUTO] Keeping probe quality: {probe_quality}")