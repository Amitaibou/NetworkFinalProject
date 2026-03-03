import socket
import json
from protocol.config import SERVER_HOST, DNS_PORT, BUFFER_SIZE


class DNSServer:
    def __init__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((SERVER_HOST, DNS_PORT))

        # רשימת דומיינים במערכת
        self.records = {
            "video.local": SERVER_HOST
        }

        print(f"[DNS] Server running on {SERVER_HOST}:{DNS_PORT}")

    def start(self):
        while True:
            data, addr = self.sock.recvfrom(BUFFER_SIZE)
            message = json.loads(data.decode())

            if message["type"] == "QUERY":
                domain = message["domain"]
                self.handle_query(addr, domain)

    def handle_query(self, addr, domain):
        if domain in self.records:
            response = {
                "type": "RESPONSE",
                "status": "OK",
                "ip": self.records[domain]
            }
        else:
            response = {
                "type": "RESPONSE",
                "status": "NOT_FOUND",
                "ip": None
            }

        self.sock.sendto(json.dumps(response).encode(), addr)

        print(f"[DNS] Query for {domain} → {response['status']} ({response['ip']})")

if __name__ == "__main__":
    server = DNSServer()
    server.start()