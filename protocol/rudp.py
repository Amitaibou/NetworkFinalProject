import socket
import json
import time
from protocol.config import BUFFER_SIZE, TIMEOUT


class RUDP:
    def __init__(self, sock: socket.socket):
        self.sock = sock
        self.seq = 0

    def send(self, data: bytes, addr):
        packet = {
            "seq": self.seq,
            "data": data.decode()
        }

        while True:
            self.sock.sendto(json.dumps(packet).encode(), addr)

            self.sock.settimeout(TIMEOUT)

            try:
                ack_data, _ = self.sock.recvfrom(BUFFER_SIZE)
                ack = json.loads(ack_data.decode())

                if ack.get("ack") == self.seq:
                    print(f"[RUDP] ACK received for seq {self.seq}")
                    self.seq += 1
                    break

            except socket.timeout:
                print(f"[RUDP] Timeout, retransmitting seq {self.seq}")

    def receive(self):
        data, addr = self.sock.recvfrom(BUFFER_SIZE)
        packet = json.loads(data.decode())

        seq = packet["seq"]
        payload = packet["data"]

        ack_packet = {
            "ack": seq
        }

        self.sock.sendto(json.dumps(ack_packet).encode(), addr)

        print(f"[RUDP] Packet {seq} received, ACK sent")

        return payload.encode(), addr