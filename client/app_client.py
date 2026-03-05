import socket
import json

from protocol.config import SERVER_HOST, APP_PORT, BUFFER_SIZE
from protocol.rudp import RUDP


class AppClient:

    def __init__(self):

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.rudp = RUDP(self.sock)

    def get_manifest(self):

        request = {"type": "MANIFEST"}

        self.sock.sendto(
            json.dumps(request).encode(),
            (SERVER_HOST, APP_PORT)
        )

        data, _ = self.sock.recvfrom(BUFFER_SIZE)

        manifest = json.loads(data.decode())

        print("[CLIENT] Available qualities:", manifest["qualities"])

        return manifest["qualities"]

    def download_image(self, quality):

        request = {
            "type": "GET_IMAGE",
            "quality": quality
        }

        self.sock.sendto(
            json.dumps(request).encode(),
            (SERVER_HOST, APP_PORT)
        )

        image_data = b""

        while True:

            chunk, _ = self.rudp.receive()

            # END מסמן סוף סטרים
            if chunk == b"END":
                break

            image_data += chunk

        with open("downloaded.jpg", "wb") as f:
            f.write(image_data)

        print("[CLIENT] Image saved as downloaded.jpg")


if __name__ == "__main__":

    client = AppClient()

    qualities = client.get_manifest()

    client.download_image(qualities[0])