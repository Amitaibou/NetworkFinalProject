import socket
import time
import pickle
import random

from protocol.config import BUFFER_SIZE, TIMEOUT

# ---------------- CONFIG ----------------
PACKET_LOSS_RATE = 0.1
WINDOW_SIZE = 5
CHUNK_SIZE = 1024
DUP_ACK_THRESHOLD = 3

# ---------------- LOGGING ----------------
DEBUG = True

def log(msg):
    if DEBUG:
        print(msg)


class RUDP:

    def __init__(self, sock: socket.socket):

        self.sock = sock
        self.mode = "SR"

        # Congestion control
        self.cwnd = 1
        self.ssthresh = 16
        self.dup_ack_count = 0

        # Flow control
        self.rwnd = WINDOW_SIZE

        # sender state
        self.send_base = 0
        self.next_seq = 0

        # receiver state
        self.expected_seq = 0
        self.recv_buffer = {}

        # stats
        self.stats_sent = 0
        self.stats_dropped = 0
        self.stats_retx = 0
        self.stats_fast_retx = 0

        # cwnd graph
        self.cwnd_history = []
        self.time_history = []
        self.start_time = None


    def set_mode(self, mode):
        self.mode = mode
        log(f"[RUDP] Protocol mode = {mode}")


    # ---------- Reset ----------

    def reset_sender(self):

        self.cwnd = 1
        self.ssthresh = 16
        self.dup_ack_count = 0

        self.send_base = 0
        self.next_seq = 0

        self.stats_sent = 0
        self.stats_dropped = 0
        self.stats_retx = 0
        self.stats_fast_retx = 0

        self.cwnd_history = []
        self.time_history = []


    def reset_receiver(self):

        self.expected_seq = 0
        self.recv_buffer = {}

    def get_sender_stats(self):

        return {
            "sent": self.stats_sent,
            "dropped": self.stats_dropped,
            "retransmissions": self.stats_retx,
            "fast_retransmissions": self.stats_fast_retx
        }

    def get_receiver_stats(self):

        return {
            "buffer_size": len(self.recv_buffer),
            "expected_seq": self.expected_seq
        }


    # ---------- Helpers ----------

    def _make_packet(self, seq: int, payload: bytes, fin: bool = False):
        return {"seq": seq, "data": payload, "fin": fin}


    def _send_raw(self, raw: bytes, addr, seq: int, is_retx: bool, is_fast=False):

        if random.random() < PACKET_LOSS_RATE:
            self.stats_dropped += 1
            log(f"[RUDP] Simulated packet loss for seq {seq}")
            return

        self.sock.sendto(raw, addr)
        self.stats_sent += 1

        if is_retx:
            self.stats_retx += 1

        if is_fast:
            self.stats_fast_retx += 1


    # =========================================================
    # DISPATCHER
    # =========================================================

    def send_bytes(self, data: bytes, addr, chunk_size: int = CHUNK_SIZE):

        if self.mode == "STOP_WAIT":
            return self.send_stop_and_wait(data, addr, chunk_size)

        elif self.mode == "GBN":
            return self.send_gbn(data, addr, chunk_size)

        elif self.mode == "SR":
            return self.send_selective_repeat(data, addr, chunk_size)


    # =========================================================
    # STOP AND WAIT
    # =========================================================

    def send_stop_and_wait(self, data, addr, chunk_size=CHUNK_SIZE):

        chunks = [data[i:i + chunk_size] for i in range(0, len(data), chunk_size)]
        seq = 0

        for chunk in chunks:

            pkt = self._make_packet(seq, chunk)
            raw = pickle.dumps(pkt)

            while True:

                self._send_raw(raw, addr, seq, False)

                try:

                    self.sock.settimeout(TIMEOUT)
                    ack_data, _ = self.sock.recvfrom(BUFFER_SIZE)
                    ack = pickle.loads(ack_data)

                    if ack.get("ack") == seq:
                        log(f"[RUDP] ACK received for seq {seq}")
                        break

                except socket.timeout:
                    log(f"[RUDP] Timeout retransmitting seq {seq}")

            seq += 1

        log("[RUDP] Stop&Wait stream completed")


    # =========================================================
    # GO BACK N
    # =========================================================

    def send_gbn(self, data, addr, chunk_size=CHUNK_SIZE):

        log("[RUDP] Using Go-Back-N")

        chunks = [data[i:i + chunk_size] for i in range(0, len(data), chunk_size)]
        total_packets = len(chunks)

        window_pkts = {}
        self.sock.settimeout(0.05)

        timer_start = None

        while self.send_base < total_packets:

            while self.next_seq < total_packets and self.next_seq < self.send_base + WINDOW_SIZE:

                pkt = self._make_packet(self.next_seq, chunks[self.next_seq])
                raw = pickle.dumps(pkt)

                window_pkts[self.next_seq] = raw
                self._send_raw(raw, addr, self.next_seq, False)

                if self.send_base == self.next_seq:
                    timer_start = time.time()

                self.next_seq += 1

            try:

                ack_data, _ = self.sock.recvfrom(BUFFER_SIZE)
                ack = pickle.loads(ack_data)

                ack_seq = ack.get("ack")

                if ack_seq >= self.send_base:

                    self.send_base = ack_seq + 1

                    for s in list(window_pkts.keys()):
                        if s < self.send_base:
                            del window_pkts[s]

                    if self.send_base < self.next_seq:
                        timer_start = time.time()

                    log(f"[RUDP] ACK cumulative {ack_seq}")

            except socket.timeout:

                if timer_start and (time.time() - timer_start) >= TIMEOUT:

                    log("[RUDP] Timeout -> retransmit window")

                    for s in range(self.send_base, self.next_seq):

                        raw = window_pkts.get(s)

                        if raw:
                            self._send_raw(raw, addr, s, True)

                    timer_start = time.time()

        log("[RUDP] GBN stream completed")


    # =========================================================
    # SELECTIVE REPEAT + CC + FLOW CONTROL
    # =========================================================

    def send_selective_repeat(self, data, addr, chunk_size=CHUNK_SIZE):

        chunks = [data[i:i + chunk_size] for i in range(0, len(data), chunk_size)]
        total_packets = len(chunks)

        acked = set()
        send_times = {}
        window_pkts = {}

        last_ack = -1
        dup_ack_count = 0

        self.sock.settimeout(0.05)

        self.start_time = time.time()

        while self.send_base < total_packets:

            self.cwnd_history.append(self.cwnd)
            self.time_history.append(time.time() - self.start_time)

            effective_window = int(min(self.cwnd, self.rwnd, WINDOW_SIZE))

            while self.next_seq < total_packets and self.next_seq < self.send_base + effective_window:

                pkt = self._make_packet(self.next_seq, chunks[self.next_seq])
                raw = pickle.dumps(pkt)

                window_pkts[self.next_seq] = raw

                self._send_raw(raw, addr, self.next_seq, False)

                send_times[self.next_seq] = time.time()
                self.next_seq += 1


            try:

                ack_data, _ = self.sock.recvfrom(BUFFER_SIZE)
                ack = pickle.loads(ack_data)

                ack_seq = ack.get("ack")
                self.rwnd = ack.get("rwnd", WINDOW_SIZE)

                if ack_seq is None:
                    continue


                for s in range(self.send_base, ack_seq + 1):
                    acked.add(s)


                if ack_seq == last_ack:
                    dup_ack_count += 1
                else:
                    last_ack = ack_seq
                    dup_ack_count = 0


                while self.send_base in acked:
                    window_pkts.pop(self.send_base, None)
                    send_times.pop(self.send_base, None)
                    self.send_base += 1


                log(f"[RUDP] ACK cumulative {ack_seq}")


                if self.cwnd < self.ssthresh:
                    self.cwnd += 1
                else:
                    self.cwnd += 1 / self.cwnd


                log(f"[RUDP][CC] cwnd={self.cwnd:.2f} ssthresh={self.ssthresh}")


                if dup_ack_count >= DUP_ACK_THRESHOLD:

                    missing = ack_seq + 1

                    if missing < self.next_seq and missing not in acked:

                        raw = window_pkts.get(missing)

                        if raw:

                            self.ssthresh = max(int(self.cwnd / 2), 2)
                            self.cwnd = self.ssthresh

                            log(f"[RUDP] FAST RETRANSMIT seq {missing}")

                            self._send_raw(raw, addr, missing, True, True)

                            send_times[missing] = time.time()

                    dup_ack_count = 0


            except socket.timeout:

                now = time.time()
                timeout_happened = False

                for seq in range(self.send_base, self.next_seq):

                    if seq in acked:
                        continue

                    if now - send_times.get(seq, 0) >= TIMEOUT:

                        raw = window_pkts.get(seq)

                        if raw:

                            log(f"[RUDP] Timeout retransmit seq {seq}")

                            self._send_raw(raw, addr, seq, True)

                            send_times[seq] = now

                            timeout_happened = True


                if timeout_happened:

                    self.ssthresh = max(int(self.cwnd / 2), 2)
                    self.cwnd = 1

                    log(f"[RUDP] Timeout -> cwnd reset")


        # FIN

        fin_seq = self.next_seq
        fin_pkt = self._make_packet(fin_seq, b"", True)
        fin_raw = pickle.dumps(fin_pkt)

        while True:

            self._send_raw(fin_raw, addr, fin_seq, False)

            self.sock.settimeout(TIMEOUT)

            try:

                ack_data, _ = self.sock.recvfrom(BUFFER_SIZE)
                ack = pickle.loads(ack_data)

                if ack.get("ack") == fin_seq:
                    log(f"[RUDP] FIN ACK received for seq {fin_seq}")
                    break

            except socket.timeout:
                log(f"[RUDP] Timeout waiting FIN ACK")


        log("[RUDP] SR stream completed")

        self.plot_cwnd()


    # =========================================================
    # RECEIVER
    # =========================================================

    def receive(self):

        data, addr = self.sock.recvfrom(BUFFER_SIZE)
        pkt = pickle.loads(data)

        seq = pkt["seq"]
        fin = pkt.get("fin", False)
        payload = pkt.get("data", b"")

        if fin:

            ack_packet = {
                "ack": seq,
                "rwnd": WINDOW_SIZE - len(self.recv_buffer)
            }

            self.sock.sendto(pickle.dumps(ack_packet), addr)

            return b"", addr, True


        if seq not in self.recv_buffer:
            self.recv_buffer[seq] = payload


        data_out = bytearray()

        while self.expected_seq in self.recv_buffer:

            data_out.extend(self.recv_buffer[self.expected_seq])

            del self.recv_buffer[self.expected_seq]

            self.expected_seq += 1


        last_in_order = self.expected_seq - 1

        ack_packet = {
            "ack": last_in_order,
            "rwnd": WINDOW_SIZE - len(self.recv_buffer)
        }

        self.sock.sendto(pickle.dumps(ack_packet), addr)

        return bytes(data_out), addr, False


    # =========================================================
    # CWND GRAPH
    # =========================================================

    def plot_cwnd(self):

        try:

            import matplotlib.pyplot as plt

            plt.plot(self.time_history, self.cwnd_history)

            plt.title("Congestion Window (cwnd)")
            plt.xlabel("Time (seconds)")
            plt.ylabel("cwnd (packets)")
            plt.grid(True)

            plt.show()

        except:
            pass