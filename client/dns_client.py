import json
import socket

from protocol.config import SERVER_HOST, DNS_PORT, BUFFER_SIZE, DEBUG_MODE, USE_COLORS
from protocol.logger import Logger


logger = Logger(debug=DEBUG_MODE, use_colors=USE_COLORS)


class DNSClient:
    def __init__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.settimeout(3)

    def resolve(self, domain):
        try:
            query = {
                "type": "QUERY",
                "domain": domain
            }

            logger.info(f"Resolving domain: {domain}")
            self.sock.sendto(json.dumps(query).encode(), (SERVER_HOST, DNS_PORT))

            data, _ = self.sock.recvfrom(BUFFER_SIZE)
            response = json.loads(data.decode())

            status = response.get("status")
            ip = response.get("ip")
            ttl = response.get("ttl")

            if status == "OK":
                print(f"[DNS CLIENT] {domain} -> {ip} (ttl={ttl})")
                return ip

            logger.warn(f"DNS lookup failed for {domain}: {status}")
            return None

        except socket.timeout:
            logger.warn(f"DNS request timed out for {domain}")
            return None
        except Exception as e:
            logger.error(f"DNS resolve failed: {e}")
            return None

    def register(self, domain, ip, ttl=300):
        try:
            request = {
                "type": "REGISTER",
                "domain": domain,
                "ip": ip,
                "ttl": ttl
            }

            self.sock.sendto(json.dumps(request).encode(), (SERVER_HOST, DNS_PORT))

            data, _ = self.sock.recvfrom(BUFFER_SIZE)
            response = json.loads(data.decode())

            if response.get("status") == "OK":
                logger.success(f"DNS registered {domain} -> {ip} (ttl={ttl})")
                return True

            logger.warn(f"DNS register failed: {response}")
            return False

        except socket.timeout:
            logger.warn("DNS register timed out")
            return False
        except Exception as e:
            logger.error(f"DNS register failed: {e}")
            return False


if __name__ == "__main__":
    client = DNSClient()
    client.resolve("video.local")