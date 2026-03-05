import socket
import os
import json

from protocol.config import SERVER_HOST, APP_PORT, BUFFER_SIZE
from protocol.rudp import RUDP


BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE_PATH = os.path.join(BASE_DIR, "assets", "gallery")

class AppServer:

    def __init__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((SERVER_HOST, APP_PORT))

        self.rudp = RUDP(self.sock)

        print(f"[APP] Server running on {SERVER_HOST}:{APP_PORT}")

    def start(self):

        while True:

            try:
                data, addr = self.sock.recvfrom(BUFFER_SIZE)

            except TimeoutError:
                continue

            message = json.loads(data.decode())

            if message["type"] == "MANIFEST":
                self.send_manifest(addr)

            elif message["type"] == "GET_IMAGE":
                quality = message["quality"]
                self.send_image(addr, quality)

    def send_manifest(self, addr):

        qualities = os.listdir(BASE_PATH)

        manifest = {
            "type": "MANIFEST_RESPONSE",
            "qualities": qualities
        }

        self.sock.sendto(json.dumps(manifest).encode(), addr)

        print("[APP] Manifest sent")

    def send_image(self, addr, quality):

        path = os.path.join(BASE_PATH, quality)

        files = os.listdir(path)

        if not files:
            return

        image_path = os.path.join(path, files[0])

        with open(image_path, "rb") as f:
            data = f.read()

        print(f"[APP] Sending image ({quality}) size={len(data)} bytes")

        CHUNK_SIZE = 1024

        for i in range(0, len(data), CHUNK_SIZE):
            chunk = data[i:i + CHUNK_SIZE]
            self.rudp.send(chunk, addr)

        # סימון סוף הסטרים
        self.rudp.send(b"END", addr)

        print("[APP] Image streaming completed")
if __name__ == "__main__":

    server = AppServer()
    server.start()