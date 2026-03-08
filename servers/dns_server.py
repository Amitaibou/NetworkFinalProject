import json
import socket
import time

from protocol.config import SERVER_HOST, DNS_PORT, BUFFER_SIZE


class DNSServer:
    DEFAULT_TTL = 300

    def __init__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((SERVER_HOST, DNS_PORT))

        self.records = {
            "video.local": {
                "ip": SERVER_HOST,
                "ttl": self.DEFAULT_TTL,
                "created_at": time.time()
            }
        }

        print(f"[DNS] Server running on {SERVER_HOST}:{DNS_PORT}")

    def cleanup_expired_records(self):
        now = time.time()
        expired = []

        for domain, record in self.records.items():
            if domain == "video.local":
                continue

            created_at = record.get("created_at", now)
            ttl = record.get("ttl", self.DEFAULT_TTL)

            if now - created_at >= ttl:
                expired.append(domain)

        for domain in expired:
            del self.records[domain]
            print(f"[DNS] Expired record removed: {domain}")

    def start(self):
        while True:
            self.cleanup_expired_records()

            data, addr = self.sock.recvfrom(BUFFER_SIZE)

            try:
                message = json.loads(data.decode())
            except Exception:
                continue

            msg_type = message.get("type")

            if msg_type == "QUERY":
                self.handle_query(addr, message.get("domain"))

            elif msg_type == "REGISTER":
                self.handle_register(
                    addr,
                    message.get("domain"),
                    message.get("ip"),
                    message.get("ttl", self.DEFAULT_TTL)
                )

    def handle_query(self, addr, domain):
        if not domain:
            response = {
                "type": "RESPONSE",
                "status": "BAD_REQUEST",
                "ip": None,
                "ttl": 0
            }
            self.sock.sendto(json.dumps(response).encode(), addr)
            return

        record = self.records.get(domain)

        if record:
            age = int(time.time() - record["created_at"])
            ttl_left = max(record["ttl"] - age, 0)

            response = {
                "type": "RESPONSE",
                "status": "OK",
                "ip": record["ip"],
                "ttl": ttl_left
            }
        else:
            response = {
                "type": "RESPONSE",
                "status": "NOT_FOUND",
                "ip": None,
                "ttl": 0
            }

        self.sock.sendto(json.dumps(response).encode(), addr)
        print(f"[DNS] Query for {domain} -> {response['status']} ({response['ip']}) ttl={response['ttl']}")

    def handle_register(self, addr, domain, ip, ttl):
        if not domain or not ip:
            response = {
                "type": "RESPONSE",
                "status": "BAD_REQUEST"
            }
            self.sock.sendto(json.dumps(response).encode(), addr)
            return

        try:
            ttl = int(ttl)
            if ttl <= 0:
                ttl = self.DEFAULT_TTL
        except Exception:
            ttl = self.DEFAULT_TTL

        self.records[domain] = {
            "ip": ip,
            "ttl": ttl,
            "created_at": time.time()
        }

        response = {
            "type": "RESPONSE",
            "status": "OK"
        }

        self.sock.sendto(json.dumps(response).encode(), addr)
        print(f"[DNS] Registered {domain} -> {ip} ttl={ttl}")


if __name__ == "__main__":
    server = DNSServer()
    server.start()