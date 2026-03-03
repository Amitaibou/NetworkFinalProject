import socket
import json
from protocol.config import SERVER_HOST, DHCP_PORT, BUFFER_SIZE


class DHCPClient:
    def __init__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.ip = None

    def request_ip(self):
        discover = {"type": "DISCOVER"}
        self.sock.sendto(json.dumps(discover).encode(), (SERVER_HOST, DHCP_PORT))

        data, _ = self.sock.recvfrom(BUFFER_SIZE)
        offer = json.loads(data.decode())

        if offer["type"] == "OFFER":
            requested_ip = offer["ip"]

            request = {
                "type": "REQUEST",
                "ip": requested_ip
            }

            self.sock.sendto(json.dumps(request).encode(), (SERVER_HOST, DHCP_PORT))

            data, _ = self.sock.recvfrom(BUFFER_SIZE)
            ack = json.loads(data.decode())

            if ack["type"] == "ACK":
                self.ip = ack["ip"]
                print(f"[CLIENT] Received IP: {self.ip}")


if __name__ == "__main__":
    client = DHCPClient()
    client.request_ip()