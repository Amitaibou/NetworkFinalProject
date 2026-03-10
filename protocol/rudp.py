import pickle
import random
import socket
import time
from dataclasses import dataclass

from protocol.config import (
    BUFFER_SIZE,
    TIMEOUT,
    WINDOW_SIZE,
    PACKET_LOSS_RATE,
    CHUNK_SIZE,
    DUP_ACK_THRESHOLD,
    MAX_TIMEOUT_RETRIES,
    DEBUG_MODE,
    USE_COLORS,
    RUDP_LOG_ACK,
    RUDP_LOG_SEND,
    RUDP_LOG_CC,
    RUDP_LOG_TIMEOUT,
    RUDP_LOG_LOSS,
    RUDP_LOG_WINDOW,
)
from protocol.logger import Logger


logger = Logger(debug=DEBUG_MODE, use_colors=USE_COLORS)


@dataclass
class SenderStats:
    # סטטיסטיקות של צד השולח, כדי שיהיה אפשר להציג בסוף תמונה כללית
    sent_packets: int = 0
    dropped_packets: int = 0
    retransmissions: int = 0
    fast_retransmissions: int = 0
    ack_count: int = 0
    timeout_events: int = 0


class RUDP:
    """
    מימוש של Reliable UDP עבור הפרויקט.
    הרעיון כאן הוא לבנות שכבת אמינות מעל UDP ולתמוך ב-3 מצבים:
    - Stop & Wait
    - Go-Back-N
    - Selective Repeat

    בנוסף יש כאן גם לוגיקה בסיסית של congestion/window handling,
    סטטיסטיקות, ויכולת סימולציה של איבוד פאקטות.
    """

    def __init__(self, sock):
        self.sock = sock
        self.mode = "SR"

        # משתנים שקשורים לניהול חלון וגודש
        self.cwnd = 1.0
        self.ssthresh = 16.0
        self.rwnd = WINDOW_SIZE

        # send_base = הסיקוונס הכי ישן שעדיין לא אושר
        # next_seq = הסיקוונס הבא שנשלח
        self.send_base = 0
        self.next_seq = 0

        # expected_seq = הסיקוונס הבא שהמקבל מחכה לו לפי הסדר
        self.expected_seq = 0
        self.recv_buffer = {}

        self.stats = SenderStats()

    # =========================
    # MODE / RESET
    # =========================

    def set_mode(self, mode):
        # בחירת מצב העבודה של RUDP
        self.mode = mode
        logger.debug_log(f"RUDP mode = {mode}")

    def reset_sender(self):
        # איפוס מצב השולח לפני שליחת סגמנט חדש
        self.cwnd = 1.0
        self.ssthresh = 16.0
        self.rwnd = WINDOW_SIZE
        self.send_base = 0
        self.next_seq = 0
        self.stats = SenderStats()

    def reset_receiver(self):
        # איפוס מצב המקבל לפני קבלת סגמנט חדש
        self.expected_seq = 0
        self.recv_buffer = {}

    # =========================
    # HELPERS
    # =========================

    def get_sender_stats(self):
        # מחזיר מילון סטטיסטיקות שאפשר להציג בלוגים או לשמור לסיכום
        return {
            "mode": self.mode,
            "sent_packets": self.stats.sent_packets,
            "dropped_packets": self.stats.dropped_packets,
            "retransmissions": self.stats.retransmissions,
            "fast_retransmissions": self.stats.fast_retransmissions,
            "ack_count": self.stats.ack_count,
            "timeout_events": self.stats.timeout_events,
            "final_cwnd": round(self.cwnd, 2),
            "final_ssthresh": round(self.ssthresh, 2),
        }

    def make_packet(self, seq, data, fin=False):
        # ייצוג פשוט של פאקט בתור dict
        return {"seq": seq, "data": data, "fin": fin}

    def send_raw(self, raw, addr, seq, is_retx=False, is_fast=False):
        # כאן מתבצעת גם סימולציית packet loss:
        # אם "נפל" לפי ההגרלה, הפאקט כאילו אבד ולא נשלח בפועל
        if random.random() < PACKET_LOSS_RATE:
            self.stats.dropped_packets += 1
            if RUDP_LOG_LOSS:
                logger.warn(f"LOSS seq={seq}")
            return

        self.sock.sendto(raw, addr)
        self.stats.sent_packets += 1

        if is_retx:
            self.stats.retransmissions += 1

        if is_fast:
            self.stats.fast_retransmissions += 1

        if RUDP_LOG_SEND:
            logger.debug_log(f"SEND seq={seq} retx={is_retx} fast={is_fast}")

    def recv_ack(self, expected_addr):
        # מחכה ל-ACK חוקי מה-peer הנכון
        # אם מגיע מידע לא קשור / לא בפורמט הנכון פשוט מתעלמים וממשיכים
        while True:
            try:
                data, addr = self.sock.recvfrom(BUFFER_SIZE)
            except ConnectionResetError:
                raise ConnectionAbortedError("peer closed UDP socket")

            if addr != expected_addr:
                continue

            try:
                ack = pickle.loads(data)
            except Exception:
                continue

            if not isinstance(ack, dict):
                continue

            if "ack" not in ack:
                continue

            return ack

    def _send_fin(self, addr, fin_seq):
        # בסוף הסטרים שולחים FIN כדי לסמן "אין יותר דאטה"
        # וגם עליו מחכים לאישור, כדי לסיים בצורה מסודרת
        fin_pkt = self.make_packet(fin_seq, b"", True)
        fin_raw = pickle.dumps(fin_pkt)

        retries = 0
        self.sock.settimeout(TIMEOUT)

        while retries < MAX_TIMEOUT_RETRIES:
            self.send_raw(fin_raw, addr, fin_seq)

            try:
                ack = self.recv_ack(addr)
                if ack.get("ack") == fin_seq:
                    if RUDP_LOG_ACK:
                        logger.debug_log(f"FIN ack={fin_seq}")
                    return
            except ConnectionAbortedError:
                return
            except socket.timeout:
                retries += 1
                self.stats.timeout_events += 1
                if RUDP_LOG_TIMEOUT:
                    logger.warn(f"FIN timeout retry seq={fin_seq}")

        raise TimeoutError("FIN retransmission limit reached")

    # =========================
    # DISPATCH
    # =========================

    def send_bytes(self, data, addr):
        # dispatcher מרכזי לפי מצב העבודה שנבחר
        if self.mode == "STOP_WAIT":
            return self.send_stop_wait(data, addr)
        if self.mode == "GBN":
            return self.send_gbn(data, addr)
        return self.send_sr(data, addr)

    # =========================
    # STOP & WAIT
    # =========================

    def send_stop_wait(self, data, addr):
        # במצב הזה שולחים פאקט אחד ומחכים ל-ACK לפני שממשיכים
        # זה המצב הכי פשוט, אבל גם הכי איטי
        chunks = [data[i:i + CHUNK_SIZE] for i in range(0, len(data), CHUNK_SIZE)]
        self.sock.settimeout(TIMEOUT)

        seq = 0
        for chunk in chunks:
            pkt = self.make_packet(seq, chunk)
            raw = pickle.dumps(pkt)

            retries = 0
            while retries < MAX_TIMEOUT_RETRIES:
                self.send_raw(raw, addr, seq, retries > 0)

                try:
                    ack = self.recv_ack(addr)
                    if ack.get("ack") == seq:
                        self.stats.ack_count += 1
                        if RUDP_LOG_ACK:
                            logger.debug_log(f"ACK seq={seq}")
                        break
                except ConnectionAbortedError:
                    return
                except socket.timeout:
                    retries += 1
                    self.stats.timeout_events += 1
                    if RUDP_LOG_TIMEOUT:
                        logger.warn(f"Timeout seq={seq}")

            if retries >= MAX_TIMEOUT_RETRIES:
                raise TimeoutError(f"Stop&Wait failed on seq {seq}")

            seq += 1

        self._send_fin(addr, seq)

    # =========================
    # GO BACK N
    # =========================

    def send_gbn(self, data, addr):
        # ב-GBN אפשר לשלוח חלון של כמה פאקטים קדימה,
        # אבל אם יש איבוד/timeout חוזרים מה-packet הלא מאושר הראשון
        chunks = [data[i:i + CHUNK_SIZE] for i in range(0, len(data), CHUNK_SIZE)]
        total = len(chunks)

        window = {}
        timer = None
        timeout_rounds = 0

        self.sock.settimeout(0.05)

        while self.send_base < total:
            # ממלאים את החלון כל עוד יש מקום
            while self.next_seq < total and self.next_seq < self.send_base + WINDOW_SIZE:
                pkt = self.make_packet(self.next_seq, chunks[self.next_seq])
                raw = pickle.dumps(pkt)

                window[self.next_seq] = raw
                self.send_raw(raw, addr, self.next_seq)

                # הטיימר מתייחס לפאקט הישן ביותר שלא אושר
                if self.send_base == self.next_seq:
                    timer = time.time()

                self.next_seq += 1

            try:
                ack = self.recv_ack(addr)
                ack_seq = ack.get("ack")

                # ACK ב-GBN הוא cumulative
                if ack_seq is not None and ack_seq >= self.send_base:
                    self.stats.ack_count += 1
                    self.send_base = ack_seq + 1
                    timeout_rounds = 0

                    # מנקים מהחלון כל מה שכבר אושר
                    for s in list(window.keys()):
                        if s < self.send_base:
                            del window[s]

                    if self.send_base < self.next_seq:
                        timer = time.time()

                    if RUDP_LOG_ACK:
                        logger.debug_log(f"GBN cumulative ack={ack_seq}")

            except ConnectionAbortedError:
                return
            except socket.timeout:
                if timer and (time.time() - timer) >= TIMEOUT:
                    timeout_rounds += 1
                    self.stats.timeout_events += 1

                    if timeout_rounds >= MAX_TIMEOUT_RETRIES:
                        raise TimeoutError("GBN retransmission limit reached")

                    if RUDP_LOG_TIMEOUT:
                        logger.warn(f"GBN timeout window={self.send_base}..{self.next_seq - 1}")

                    # ב-GBN משדרים מחדש את כל החלון מהבסיס
                    for s in range(self.send_base, self.next_seq):
                        raw = window.get(s)
                        if raw:
                            self.send_raw(raw, addr, s, True)

                    timer = time.time()

        self._send_fin(addr, self.next_seq)

    # =========================
    # SELECTIVE REPEAT
    # =========================

    def send_sr(self, data, addr):
        # ב-SR כל פאקט מטופל יותר "אישית":
        # אפשר לאשר חלקים מהחלון ולשדר מחדש רק את מה שבאמת חסר
        chunks = [data[i:i + CHUNK_SIZE] for i in range(0, len(data), CHUNK_SIZE)]
        total = len(chunks)

        acked = set()
        send_times = {}
        timeout_counts = {}
        window = {}

        last_ack = -1
        dup_count = 0

        self.sock.settimeout(0.05)

        while self.send_base < total:
            # גודל חלון אפקטיבי לפי congestion window, receiver window והגדרות הפרויקט
            effective = int(min(self.cwnd, self.rwnd, WINDOW_SIZE))
            effective = max(effective, 1)

            if RUDP_LOG_WINDOW:
                logger.debug_log(
                    f"WIN base={self.send_base} next={self.next_seq} "
                    f"cwnd={self.cwnd:.2f} ssthresh={self.ssthresh:.2f} "
                    f"rwnd={self.rwnd} eff={effective}"
                )

            # שולחים כל מה שנכנס כרגע בחלון
            while self.next_seq < total and self.next_seq < self.send_base + effective:
                pkt = self.make_packet(self.next_seq, chunks[self.next_seq])
                raw = pickle.dumps(pkt)

                window[self.next_seq] = raw
                send_times[self.next_seq] = time.time()
                timeout_counts.setdefault(self.next_seq, 0)

                self.send_raw(raw, addr, self.next_seq)
                self.next_seq += 1

            try:
                ack = self.recv_ack(addr)

                cum_ack = ack.get("ack")
                self.rwnd = int(ack.get("rwnd", WINDOW_SIZE))

                if cum_ack is None:
                    continue

                self.stats.ack_count += 1

                # מסמנים כל מה שאושר עד ה-cumulative ack
                for s in range(self.send_base, cum_ack + 1):
                    acked.add(s)

                if RUDP_LOG_ACK:
                    logger.debug_log(f"SR ack={cum_ack} rwnd={self.rwnd}")

                # ספירת duplicate ACK כדי לאפשר fast retransmit
                if cum_ack == last_ack:
                    dup_count += 1
                else:
                    last_ack = cum_ack
                    dup_count = 0

                # מקדמים את בסיס החלון כל עוד יש ACK רציף
                while self.send_base in acked:
                    window.pop(self.send_base, None)
                    send_times.pop(self.send_base, None)
                    timeout_counts.pop(self.send_base, None)
                    self.send_base += 1

                # עדכון congestion window בסיסי:
                # slow start ואז גדילה עדינה יותר
                if self.cwnd < self.ssthresh:
                    self.cwnd += 1.0
                else:
                    self.cwnd += 1.0 / self.cwnd

                if RUDP_LOG_CC:
                    logger.debug_log(f"CC+ cwnd={self.cwnd:.2f} ssthresh={self.ssthresh:.2f}")

                # Fast retransmit אחרי כמה duplicate ACKs
                if dup_count >= DUP_ACK_THRESHOLD:
                    missing = cum_ack + 1
                    if missing < self.next_seq and missing not in acked:
                        raw = window.get(missing)
                        if raw is not None:
                            self.ssthresh = max(self.cwnd / 2.0, 2.0)
                            self.cwnd = self.ssthresh

                            if RUDP_LOG_CC:
                                logger.debug_log(
                                    f"FAST-RTX seq={missing} cwnd={self.cwnd:.2f} ssthresh={self.ssthresh:.2f}"
                                )

                            self.send_raw(raw, addr, missing, True, True)
                            send_times[missing] = time.time()

                    dup_count = 0

            except ConnectionAbortedError:
                return
            except socket.timeout:
                now = time.time()
                timeout_happened = False

                # ב-SR בודקים timeout לכל פאקט בנפרד
                for seq in range(self.send_base, self.next_seq):
                    if seq in acked:
                        continue

                    if now - send_times.get(seq, 0) >= TIMEOUT:
                        timeout_counts[seq] = timeout_counts.get(seq, 0) + 1

                        if timeout_counts[seq] >= MAX_TIMEOUT_RETRIES:
                            raise TimeoutError(f"SR retransmission limit reached on seq {seq}")

                        raw = window.get(seq)
                        if raw is not None:
                            self.stats.timeout_events += 1

                            if RUDP_LOG_TIMEOUT:
                                logger.warn(f"SR timeout seq={seq}")

                            self.send_raw(raw, addr, seq, True)
                            send_times[seq] = now
                            timeout_happened = True

                # timeout נחשב סימן לעומס / בעיה, אז מקטינים חלון
                if timeout_happened:
                    self.ssthresh = max(self.cwnd / 2.0, 2.0)
                    self.cwnd = 1.0
                    if RUDP_LOG_CC:
                        logger.debug_log(f"CC reset cwnd={self.cwnd:.2f} ssthresh={self.ssthresh:.2f}")

        self._send_fin(addr, self.next_seq)

    # =========================
    # RECEIVE
    # =========================

    def receive(self):
        # צד המקבל:
        # מקבל פאקטים, שומר מה שהגיע, מחזיר ACK,
        # ומוסר החוצה רק מידע שהפך להיות רציף מהנקודה הצפויה
        while True:
            data, addr = self.sock.recvfrom(BUFFER_SIZE)

            try:
                pkt = pickle.loads(data)
            except Exception:
                continue

            seq = pkt["seq"]
            payload = pkt.get("data", b"")
            fin = pkt.get("fin", False)

            if fin:
                ack = {
                    "ack": seq,
                    "rwnd": max(WINDOW_SIZE - len(self.recv_buffer), 0)
                }
                self.sock.sendto(pickle.dumps(ack), addr)
                return b"", addr, True

            # נשמור את הפאקט רק אם עדיין לא קיבלנו אותו
            if seq not in self.recv_buffer:
                self.recv_buffer[seq] = payload

            out = bytearray()

            # כל עוד יש לנו רצף מלא מהנקודה הצפויה - נוציא אותו החוצה
            while self.expected_seq in self.recv_buffer:
                out.extend(self.recv_buffer[self.expected_seq])
                del self.recv_buffer[self.expected_seq]
                self.expected_seq += 1

            ack_packet = {
                "ack": self.expected_seq - 1,
                "rwnd": max(WINDOW_SIZE - len(self.recv_buffer), 0)
            }

            self.sock.sendto(pickle.dumps(ack_packet), addr)
            return bytes(out), addr, False