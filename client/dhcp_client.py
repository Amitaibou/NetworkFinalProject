import json
import socket
import time
import uuid

from protocol.config import SERVER_HOST, DHCP_PORT, BUFFER_SIZE


class DHCPClient:
    def __init__(self, lease_file=None):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self.sock.settimeout(3)

        # bind ל-port זמני מקומי כדי לקבל תשובות
        self.sock.bind(("", 0))

        self.client_id = str(uuid.uuid4())
        self.ip = None
        self.server_id = None
        self.lease_time = 0
        self.lease_start = 0.0

        self.lease_file = lease_file

    def _send_json(self, payload, addr):
        self.sock.sendto(json.dumps(payload).encode(), addr)

    def _recv_json(self):
        data, addr = self.sock.recvfrom(BUFFER_SIZE)
        return json.loads(data.decode()), addr

    def _now(self):
        return time.time()

    def _lease_valid(self):
        if not self.ip or not self.lease_start or not self.lease_time:
            return False
        return (self._now() - self.lease_start) < self.lease_time

    def _save_lease(self):
        if not self.lease_file:
            return
        try:
            payload = {
                "client_id": self.client_id,
                "ip": self.ip,
                "server_id": self.server_id,
                "lease_time": self.lease_time,
                "lease_start": self.lease_start,
            }
            with open(self.lease_file, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
        except Exception:
            pass

    def _broadcast_discover(self):
        xid = str(uuid.uuid4())
        discover = {
            "type": "DISCOVER",
            "xid": xid,
            "client_id": self.client_id,
        }

        # קודם ברודקאסט אמיתי
        try:
            self._send_json(discover, ("255.255.255.255", DHCP_PORT))
            return xid
        except Exception:
            # fallback ליוניקאסט מקומי כדי לא להיתקע בסביבת פיתוח
            self._send_json(discover, (SERVER_HOST, DHCP_PORT))
            return xid

    def request_ip(self):
        xid = self._broadcast_discover()

        offer = None
        server_addr = None

        while True:
            message, addr = self._recv_json()
            if message.get("type") != "OFFER":
                continue
            if message.get("xid") != xid:
                continue
            if message.get("client_id") != self.client_id:
                continue

            offer = message
            server_addr = addr
            break

        requested_ip = offer["ip"]
        self.server_id = offer.get("server_id", server_addr[0])

        request = {
            "type": "REQUEST",
            "xid": xid,
            "client_id": self.client_id,
            "ip": requested_ip,
            "server_id": self.server_id,
        }

        self._send_json(request, server_addr)

        while True:
            message, _ = self._recv_json()
            if message.get("xid") != xid:
                continue
            if message.get("client_id") != self.client_id:
                continue

            if message.get("type") == "ACK":
                self.ip = message["ip"]
                self.server_id = message.get("server_id", self.server_id)
                self.lease_time = int(message.get("lease_time", 120))
                self.lease_start = self._now()
                self._save_lease()

                print(
                    f"[DHCP CLIENT] Lease acquired | "
                    f"ip={self.ip} | lease_time={self.lease_time}s | server={self.server_id}"
                )
                return self.ip

            if message.get("type") == "NAK":
                print("[DHCP CLIENT] Request rejected by server")
                return None

    def renew_lease(self):
        if not self.ip or not self.server_id:
            print("[DHCP CLIENT] No active lease to renew")
            return None

        xid = str(uuid.uuid4())
        renew = {
            "type": "RENEW",
            "xid": xid,
            "client_id": self.client_id,
            "ip": self.ip,
            "server_id": self.server_id,
        }

        self._send_json(renew, (self.server_id, DHCP_PORT))

        try:
            while True:
                message, _ = self._recv_json()
                if message.get("xid") != xid:
                    continue
                if message.get("client_id") != self.client_id:
                    continue

                if message.get("type") == "ACK":
                    self.ip = message["ip"]
                    self.lease_time = int(message.get("lease_time", self.lease_time or 120))
                    self.lease_start = self._now()
                    self._save_lease()

                    print(
                        f"[DHCP CLIENT] Lease renewed | "
                        f"ip={self.ip} | lease_time={self.lease_time}s"
                    )
                    return self.ip

                if message.get("type") == "NAK":
                    print("[DHCP CLIENT] Lease renewal rejected")
                    return None
        except socket.timeout:
            print("[DHCP CLIENT] Renew timeout")
            return None

    def release_ip(self):
        if not self.ip or not self.server_id:
            return

        release = {
            "type": "RELEASE",
            "client_id": self.client_id,
            "ip": self.ip,
            "server_id": self.server_id,
        }

        try:
            self._send_json(release, (self.server_id, DHCP_PORT))
            print(f"[DHCP CLIENT] Released IP {self.ip}")
        except Exception:
            pass
        finally:
            self.ip = None
            self.lease_time = 0
            self.lease_start = 0.0

    def request_or_renew(self):
        if self._lease_valid():
            return self.ip

        if self.ip:
            renewed = self.renew_lease()
            if renewed:
                return renewed

        return self.request_ip()


if __name__ == "__main__":
    client = DHCPClient()
    try:
        client.request_ip()
    finally:
        client.sock.close()