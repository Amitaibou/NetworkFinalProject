import socket
import json
from protocol.config import SERVER_HOST, DHCP_PORT, BUFFER_SIZE


class DHCPServer:
    def __init__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((SERVER_HOST, DHCP_PORT))

        self.available_ips = [f"10.0.0.{i}" for i in range(2, 100)]
        self.leases = {}

        print(f"[DHCP] Server running on {SERVER_HOST}: {  DHCP_PORT}")

    def start(self):
        while True:
            data, addr = self.sock.recvfrom(BUFFER_SIZE)
            message = json.loads(data.decode())

            if message["type"] == "DISCOVER":
                self.handle_discover(addr)

            elif message["type"] == "REQUEST":
                self.handle_request(addr, message["ip"])

    def handle_discover(self, addr):
        if not self.available_ips:
            return

        offered_ip = self.available_ips[0]

        response = {
            "type": "OFFER",
            "ip": offered_ip
        }

        self.sock.sendto(json.dumps(response).encode(), addr)
        print(f"[DHCP] Offered {offered_ip} to {addr}")

    def handle_request(self, addr, ip):
        if ip in self.available_ips:
            self.available_ips.remove(ip)
            self.leases[addr] = ip

            response = {
                "type": "ACK",
                "ip": ip
            }

            self.sock.sendto(json.dumps(response).encode(), addr)
            print(f"[DHCP] Assigned {ip} to {addr}")


if __name__ == "__main__":
    server = DHCPServer()
    server.start()