import socket
import pickle

from protocol.config import BUFFER_SIZE, TIMEOUT


class RUDP:

    def __init__(self, sock: socket.socket):
        self.sock = sock
        self.seq = 0

    def send(self, data: bytes, addr):

        packet = {
            "seq": self.seq,
            "data": data
        }

        raw = pickle.dumps(packet)

        while True:

            self.sock.sendto(raw, addr)

            self.sock.settimeout(TIMEOUT)

            try:
                ack_data, _ = self.sock.recvfrom(BUFFER_SIZE)
                ack = pickle.loads(ack_data)

                if ack.get("ack") == self.seq:
                    print(f"[RUDP] ACK received for seq {self.seq}")
                    self.seq += 1
                    break

            except socket.timeout:
                print(f"[RUDP] Timeout, retransmitting seq {self.seq}")

    def receive(self):

        data, addr = self.sock.recvfrom(BUFFER_SIZE)

        packet = pickle.loads(data)

        seq = packet["seq"]
        payload = packet["data"]

        ack_packet = {
            "ack": seq
        }

        self.sock.sendto(pickle.dumps(ack_packet), addr)

        print(f"[RUDP] Packet {seq} received, ACK sent")

        return payload, addr