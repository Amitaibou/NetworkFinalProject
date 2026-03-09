import json
import socket
import threading
import time
from collections import deque

from protocol.config import SERVER_HOST, DHCP_PORT, BUFFER_SIZE


class DHCPServer:
    def __init__(self, lease_time=120, pool_start=2, pool_end=99):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("", DHCP_PORT))

        self.server_id = SERVER_HOST
        self.lease_time = lease_time

        self.ip_pool = deque([f"10.0.0.{i}" for i in range(pool_start, pool_end + 1)])

        # client_id -> lease info
        self.leases = {}

        # client_id -> offered ip
        self.offers = {}

        self.lock = threading.Lock()

        print(f"[DHCP] Server running on {SERVER_HOST}:{DHCP_PORT}")

    def _send_json(self, payload, addr):
        self.sock.sendto(json.dumps(payload).encode(), addr)

    def _recv_json(self):
        data, addr = self.sock.recvfrom(BUFFER_SIZE)
        return json.loads(data.decode()), addr

    def _cleanup_expired_leases(self):
        now = time.time()
        expired_clients = []

        with self.lock:
            for client_id, lease in self.leases.items():
                if lease["expires_at"] <= now:
                    expired_clients.append(client_id)

            for client_id in expired_clients:
                ip = self.leases[client_id]["ip"]
                self.ip_pool.append(ip)
                del self.leases[client_id]
                print(f"[DHCP] Lease expired | client_id={client_id} | ip={ip}")

    def _allocate_ip_for_offer(self, client_id):
        with self.lock:
            # אם כבר יש lease פעיל, נחזיר אותו
            if client_id in self.leases:
                return self.leases[client_id]["ip"]

            # אם כבר הצענו בעבר ועדיין לא אישרו, נחזיר את אותה הצעה
            if client_id in self.offers:
                return self.offers[client_id]

            if not self.ip_pool:
                return None

            offered_ip = self.ip_pool[0]
            self.offers[client_id] = offered_ip
            return offered_ip

    def handle_discover(self, message, addr):
        client_id = message.get("client_id")
        xid = message.get("xid")

        if not client_id or not xid:
            return

        offered_ip = self._allocate_ip_for_offer(client_id)
        if not offered_ip:
            response = {
                "type": "NAK",
                "xid": xid,
                "client_id": client_id,
                "message": "No IPs available",
                "server_id": self.server_id,
            }
            self._send_json(response, addr)
            print(f"[DHCP] No available IP for client_id={client_id}")
            return

        response = {
            "type": "OFFER",
            "xid": xid,
            "client_id": client_id,
            "ip": offered_ip,
            "lease_time": self.lease_time,
            "server_id": self.server_id,
        }

        self._send_json(response, addr)
        print(f"[DHCP] Offered {offered_ip} to client_id={client_id} addr={addr}")

    def handle_request(self, message, addr):
        client_id = message.get("client_id")
        xid = message.get("xid")
        requested_ip = message.get("ip")

        if not client_id or not xid or not requested_ip:
            return

        with self.lock:
            # כבר קיים lease
            if client_id in self.leases and self.leases[client_id]["ip"] == requested_ip:
                self.leases[client_id]["expires_at"] = time.time() + self.lease_time
                response = {
                    "type": "ACK",
                    "xid": xid,
                    "client_id": client_id,
                    "ip": requested_ip,
                    "lease_time": self.lease_time,
                    "server_id": self.server_id,
                }
                self._send_json(response, addr)
                print(f"[DHCP] Re-ACK existing lease {requested_ip} to client_id={client_id}")
                return

            # חייב להתאים להצעה
            offered_ip = self.offers.get(client_id)
            if offered_ip != requested_ip:
                response = {
                    "type": "NAK",
                    "xid": xid,
                    "client_id": client_id,
                    "message": "Requested IP does not match active offer",
                    "server_id": self.server_id,
                }
                self._send_json(response, addr)
                print(f"[DHCP] NAK request | client_id={client_id} | requested_ip={requested_ip}")
                return

            # אם IP פנוי - נוציא מהבריכה
            if requested_ip in self.ip_pool:
                self.ip_pool.remove(requested_ip)

            self.leases[client_id] = {
                "ip": requested_ip,
                "addr": addr,
                "starts_at": time.time(),
                "expires_at": time.time() + self.lease_time,
            }

            self.offers.pop(client_id, None)

        response = {
            "type": "ACK",
            "xid": xid,
            "client_id": client_id,
            "ip": requested_ip,
            "lease_time": self.lease_time,
            "server_id": self.server_id,
        }

        self._send_json(response, addr)
        print(f"[DHCP] Assigned {requested_ip} to client_id={client_id}")

    def handle_renew(self, message, addr):
        client_id = message.get("client_id")
        xid = message.get("xid")
        ip = message.get("ip")

        if not client_id or not xid or not ip:
            return

        with self.lock:
            if client_id not in self.leases:
                response = {
                    "type": "NAK",
                    "xid": xid,
                    "client_id": client_id,
                    "message": "No active lease",
                    "server_id": self.server_id,
                }
                self._send_json(response, addr)
                print(f"[DHCP] Renew denied | no lease for client_id={client_id}")
                return

            if self.leases[client_id]["ip"] != ip:
                response = {
                    "type": "NAK",
                    "xid": xid,
                    "client_id": client_id,
                    "message": "IP mismatch on renew",
                    "server_id": self.server_id,
                }
                self._send_json(response, addr)
                print(f"[DHCP] Renew denied | ip mismatch for client_id={client_id}")
                return

            self.leases[client_id]["expires_at"] = time.time() + self.lease_time

        response = {
            "type": "ACK",
            "xid": xid,
            "client_id": client_id,
            "ip": ip,
            "lease_time": self.lease_time,
            "server_id": self.server_id,
        }

        self._send_json(response, addr)
        print(f"[DHCP] Renewed {ip} for client_id={client_id}")

    def handle_release(self, message, addr):
        client_id = message.get("client_id")
        ip = message.get("ip")

        if not client_id or not ip:
            return

        with self.lock:
            if client_id in self.leases and self.leases[client_id]["ip"] == ip:
                del self.leases[client_id]
                if ip not in self.ip_pool:
                    self.ip_pool.append(ip)
                print(f"[DHCP] Released {ip} from client_id={client_id}")

    def start(self):
        while True:
            self._cleanup_expired_leases()

            try:
                message, addr = self._recv_json()
            except Exception:
                continue

            msg_type = message.get("type")

            if msg_type == "DISCOVER":
                self.handle_discover(message, addr)
            elif msg_type == "REQUEST":
                self.handle_request(message, addr)
            elif msg_type == "RENEW":
                self.handle_renew(message, addr)
            elif msg_type == "RELEASE":
                self.handle_release(message, addr)


if __name__ == "__main__":
    server = DHCPServer()
    server.start()