import json
import socket
import time

from protocol.config import SERVER_HOST, DNS_PORT, BUFFER_SIZE


class DNSServer:
    def __init__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((SERVER_HOST, DNS_PORT))

        # zone records
        self.records = {
            "video.local": {"ip": SERVER_HOST, "ttl": 300},
            "app.local": {"ip": SERVER_HOST, "ttl": 300},
            "ariel.local": {"ip": "147.235.16.64", "ttl": 600},
            "amitai-home.local": {"ip": "10.0.0.10", "ttl": 600},
            "ofri-home.local": {"ip": "10.0.0.11", "ttl": 600},
            "daniel-home.local": {"ip": "10.0.0.12", "ttl": 600},
            "anna-home.local": {"ip": "10.0.0.13", "ttl": 600},
        }

        print(f"[DNS] Server running on {SERVER_HOST}:{DNS_PORT}")

    def _send_json(self, payload, addr):
        self.sock.sendto(json.dumps(payload).encode(), addr)

    def _recv_json(self):
        data, addr = self.sock.recvfrom(BUFFER_SIZE)
        return json.loads(data.decode()), addr

    def handle_query(self, addr, domain):
        record = self.records.get(domain)

        if record:
            response = {
                "type": "RESPONSE",
                "status": "OK",
                "domain": domain,
                "ip": record["ip"],
                "ttl": record["ttl"],
                "resolved_at": int(time.time()),
            }
        else:
            response = {
                "type": "RESPONSE",
                "status": "NOT_FOUND",
                "domain": domain,
                "ip": None,
                "ttl": 0,
                "resolved_at": int(time.time()),
            }

        self._send_json(response, addr)
        print(
            f"[DNS] Query for {domain} -> "
            f"{response['status']} ({response['ip']}) ttl={response['ttl']}"
        )

    def start(self):
        while True:
            try:
                message, addr = self._recv_json()
            except Exception:
                continue

            if message.get("type") == "QUERY":
                domain = message.get("domain", "").strip().lower()
                self.handle_query(addr, domain)


if __name__ == "__main__":
    server = DNSServer()
    server.start()