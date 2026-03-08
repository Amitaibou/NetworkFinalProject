import json
import socket
import time

from protocol.config import SERVER_HOST, DHCP_PORT, BUFFER_SIZE


class DHCPServer:
    LEASE_TIME = 120

    def __init__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((SERVER_HOST, DHCP_PORT))

        self.available_ips = [f"10.0.0.{i}" for i in range(2, 100)]
        self.pending_offers = {}   # client_id -> ip
        self.leases = {}           # client_id -> {"ip": ..., "expires_at": ...}

        print(f"[DHCP] Server running on {SERVER_HOST}:{DHCP_PORT}")

    def cleanup_expired_leases(self):
        now = time.time()
        expired_clients = []

        for client_id, lease in self.leases.items():
            if lease["expires_at"] <= now:
                expired_clients.append(client_id)

        for client_id in expired_clients:
            ip = self.leases[client_id]["ip"]
            if ip not in self.available_ips:
                self.available_ips.append(ip)
                self.available_ips.sort(key=lambda x: list(map(int, x.split("."))))
            del self.leases[client_id]
            print(f"[DHCP] Lease expired for client_id={client_id}, returned {ip} to pool")

    def start(self):
        while True:
            self.cleanup_expired_leases()

            data, addr = self.sock.recvfrom(BUFFER_SIZE)

            try:
                message = json.loads(data.decode())
            except Exception:
                continue

            msg_type = message.get("type")
            client_id = message.get("client_id", str(addr))

            if msg_type == "DISCOVER":
                self.handle_discover(addr, client_id)

            elif msg_type == "REQUEST":
                self.handle_request(addr, client_id, message.get("ip"))

            elif msg_type == "RELEASE":
                self.handle_release(addr, client_id, message.get("ip"))

    def handle_discover(self, addr, client_id):
        if client_id in self.leases:
            leased_ip = self.leases[client_id]["ip"]
            response = {
                "type": "OFFER",
                "ip": leased_ip,
                "lease_time": self.LEASE_TIME,
                "server_id": SERVER_HOST
            }
            self.sock.sendto(json.dumps(response).encode(), addr)
            print(f"[DHCP] Re-offered existing lease {leased_ip} to client_id={client_id}")
            return

        if not self.available_ips:
            response = {
                "type": "NAK",
                "message": "No IPs available"
            }
            self.sock.sendto(json.dumps(response).encode(), addr)
            print(f"[DHCP] No IP available for client_id={client_id}")
            return

        offered_ip = self.available_ips[0]
        self.pending_offers[client_id] = offered_ip

        response = {
            "type": "OFFER",
            "ip": offered_ip,
            "lease_time": self.LEASE_TIME,
            "server_id": SERVER_HOST
        }

        self.sock.sendto(json.dumps(response).encode(), addr)
        print(f"[DHCP] Offered {offered_ip} to client_id={client_id} addr={addr}")

    def handle_request(self, addr, client_id, ip):
        if client_id in self.leases and self.leases[client_id]["ip"] == ip:
            self.leases[client_id]["expires_at"] = time.time() + self.LEASE_TIME

            response = {
                "type": "ACK",
                "ip": ip,
                "lease_time": self.LEASE_TIME,
                "server_id": SERVER_HOST
            }

            self.sock.sendto(json.dumps(response).encode(), addr)
            print(f"[DHCP] Renewed {ip} for client_id={client_id}")
            return

        offered_ip = self.pending_offers.get(client_id)

        if offered_ip != ip:
            response = {
                "type": "NAK",
                "message": "Requested IP does not match offered IP"
            }
            self.sock.sendto(json.dumps(response).encode(), addr)
            print(f"[DHCP] Rejected request from client_id={client_id} for ip={ip}")
            return

        if ip not in self.available_ips:
            response = {
                "type": "NAK",
                "message": "Requested IP is no longer available"
            }
            self.sock.sendto(json.dumps(response).encode(), addr)
            print(f"[DHCP] IP {ip} no longer available for client_id={client_id}")
            return

        self.available_ips.remove(ip)
        self.leases[client_id] = {
            "ip": ip,
            "expires_at": time.time() + self.LEASE_TIME
        }
        self.pending_offers.pop(client_id, None)

        response = {
            "type": "ACK",
            "ip": ip,
            "lease_time": self.LEASE_TIME,
            "server_id": SERVER_HOST
        }

        self.sock.sendto(json.dumps(response).encode(), addr)
        print(f"[DHCP] Assigned {ip} to client_id={client_id}")

    def handle_release(self, addr, client_id, ip):
        lease = self.leases.get(client_id)
        if not lease:
            return

        if lease["ip"] != ip:
            return

        del self.leases[client_id]

        if ip not in self.available_ips:
            self.available_ips.append(ip)
            self.available_ips.sort(key=lambda x: list(map(int, x.split("."))))

        print(f"[DHCP] Released {ip} from client_id={client_id}")


if __name__ == "__main__":
    server = DHCPServer()
    server.start()