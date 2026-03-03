import socket
import json
from protocol.config import SERVER_HOST, DNS_PORT, BUFFER_SIZE


class DNSClient:
    def __init__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def resolve(self, domain):
        query = {
            "type": "QUERY",
            "domain": domain
        }

        self.sock.sendto(
            json.dumps(query).encode(),
            (SERVER_HOST, DNS_PORT)
        )

        data, _ = self.sock.recvfrom(BUFFER_SIZE)
        response = json.loads(data.decode())

        if response["status"] == "OK":
            print(f"[DNS CLIENT] {domain} → {response['ip']}")
            return response["ip"]
        else:
            print(f"[DNS CLIENT] {domain} not found")
            return None

if __name__ == "__main__":
    client = DNSClient()
    client.resolve("video.local")