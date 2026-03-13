import json
import os
import socket
import struct
import threading
import time

from protocol.config import (
    SERVER_HOST,
    APP_PORT,
    APP_TCP_PORT,
    BUFFER_SIZE,
    DEBUG_MODE,
    USE_COLORS,
)
from protocol.logger import Logger
from protocol.rudp import RUDP


# הנתיב הראשי של הפרויקט
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# כאן נשמרים כל הסרטונים והסגמנטים לפי תיקיות ואיכויות
VIDEOS_PATH = os.path.join(BASE_DIR, "assets", "videos")

# אובייקט לוגים כדי להדפיס הודעות יפות וברורות למסך
logger = Logger(debug=DEBUG_MODE, use_colors=USE_COLORS)


class AppServer:
    def __init__(self):
        # -----------------------------
        # יצירת socket ל-UDP
        # -----------------------------
        self.udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.udp_sock.bind((SERVER_HOST, APP_PORT))

        # ב-Windows לפעמים UDP זורק ConnectionResetError בגלל ICMP,
        # אז מנסים לבטל את זה אם קיים
        if hasattr(socket, "SIO_UDP_CONNRESET"):
            try:
                self.udp_sock.ioctl(socket.SIO_UDP_CONNRESET, False)
            except Exception:
                pass

        # שכבת RUDP שיושבת מעל UDP ומטפלת בשליחה אמינה
        self.rudp = RUDP(self.udp_sock)

        # -----------------------------
        # יצירת socket ל-TCP
        # -----------------------------
        self.tcp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.tcp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.tcp_sock.bind((SERVER_HOST, APP_TCP_PORT))
        self.tcp_sock.listen(5)

        # הודעות התחלה כדי לראות שהשרת רץ
        logger.section("VIDEO DASH SERVER STARTED")
        logger.success(f"UDP  : {SERVER_HOST}:{APP_PORT}")
        logger.success(f"TCP  : {SERVER_HOST}:{APP_TCP_PORT}")
        logger.info(f"PATH : {VIDEOS_PATH}")
        logger.info(f"DEBUG: {DEBUG_MODE}")

    def build_manifest(self):
        """
        בונה manifest של כל הסרטונים הקיימים במערכת.

        הרעיון:
        הלקוח מבקש רשימת סרטונים זמינים,
        והשרת מחזיר עבור כל סרטון כמה סגמנטים יש,
        וגם אילו איכויות נתמכות.
        """
        videos = {}

        # אם התיקייה בכלל לא קיימת, מחזירים manifest ריק
        if not os.path.exists(VIDEOS_PATH):
            return {
                "type": "MANIFEST_RESPONSE",
                "videos": {},
                "qualities": ["low", "mid", "high"],
            }

        # עוברים על כל הסרטונים שבתיקייה
        for video in os.listdir(VIDEOS_PATH):
            v_path = os.path.join(VIDEOS_PATH, video)

            # אם זה לא תיקייה של סרטון, מדלגים
            if not os.path.isdir(v_path):
                continue

            # בודקים לפי תיקיית low כמה סגמנטים יש לסרטון
            # (מניחים שכל האיכויות מחולקות לאותו מספר סגמנטים)
            low_path = os.path.join(v_path, "low")
            if not os.path.isdir(low_path):
                continue

            # סופרים קבצים מהצורה segX.ts
            segments = len([
                f for f in os.listdir(low_path)
                if f.startswith("seg") and f.endswith(".ts")
            ])

            videos[video] = segments

        logger.debug_log(f"Manifest videos = {videos}")

        return {
            "type": "MANIFEST_RESPONSE",
            "videos": videos,
            "qualities": ["low", "mid", "high"],
        }

    def load_segment(self, video, quality, segment):
        """
        טוען מהדיסק סגמנט מסוים של סרטון מסוים ובאיכות מסוימת.

        לדוגמה:
        assets/videos/barcelona/high/seg3.ts
        """
        path = os.path.join(VIDEOS_PATH, video, quality, f"seg{segment}.ts")

        if not os.path.exists(path):
            return None

        with open(path, "rb") as f:
            return f.read()

    def recv_exact(self, conn, n):
        """
        קורא בדיוק n בתים מחיבור TCP.

        ב-TCP אין הבטחה ש-recv אחד יחזיר את כל המידע,
        לכן ממשיכים לקרוא עד שמקבלים בדיוק את כמות הבתים שרצינו.
        """
        buf = b""
        while len(buf) < n:
            chunk = conn.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("TCP connection closed")
            buf += chunk
        return buf

    # =========================
    # UDP
    # =========================

    def udp_loop(self):
        """
        הלולאה הראשית של UDP.

        מקבלת בקשות מהלקוח:
        1. GET_MANIFEST
        2. GET_SEGMENT

        אם מבקשים manifest -> מחזירים JSON פשוט.
        אם מבקשים segment -> שולחים את הסגמנט דרך RUDP.
        """
        logger.section("UDP STREAM LOOP")

        while True:
            self.udp_sock.settimeout(None)

            try:
                data, addr = self.udp_sock.recvfrom(BUFFER_SIZE)
            except ConnectionResetError:
                logger.warn("UDP ConnectionResetError ignored")
                continue
            except Exception as e:
                logger.error(f"UDP recv error: {e}")
                continue

            # מנסים לפענח את ההודעה שהגיעה כ-JSON
            try:
                message = json.loads(data.decode())
            except Exception:
                continue

            msg_type = message.get("type")

            # הלקוח מבקש רשימת סרטונים זמינים
            if msg_type == "GET_MANIFEST":
                manifest = self.build_manifest()
                self.udp_sock.sendto(json.dumps(manifest).encode(), addr)
                logger.success(f"UDP manifest sent to {addr}")

            # הלקוח מבקש סגמנט מסוים
            elif msg_type == "GET_SEGMENT":
                video = message.get("video")
                quality = message.get("quality")
                segment = message.get("segment")
                protocol = message.get("protocol", "SR")

                # בוחרים איזה מצב RUDP להפעיל (למשל SR / GBN / SW)
                self.rudp.set_mode(protocol)

                # מאפסים סטטיסטיקות ושדות של השולח לפני שליחה חדשה
                self.rudp.reset_sender()

                # טוענים את הסגמנט המבוקש מהדיסק
                segment_data = self.load_segment(video, quality, segment)
                if segment_data is None:
                    logger.error(f"UDP missing segment: {video}/{quality}/seg{segment}.ts")
                    continue

                logger.info(f"UDP stream start | {video} | {quality} | seg{segment} | mode={protocol}")

                # שולחים את המידע בעזרת RUDP
                start = time.time()
                try:
                    self.rudp.send_bytes(segment_data, addr)
                except Exception as e:
                    logger.error(f"RUDP send failed: {e}")
                    # שולחים הודעת שגיאה פשוטה ללקוח כדי שלא ייתקע בלולאת
                    # "continue" בלי לדעת מה קרה

                    err = {"type": "ERROR", "reason": "MISSING_SEGMENT"}
                    self.udp_sock.sendto(json.dumps(err).encode(), addr)
                    continue
                end = time.time()

                # חישוב מהירות שליחה וסטטיסטיקות
                elapsed = end - start
                speed = (len(segment_data) / 1024 / elapsed) if elapsed > 0 else 0.0
                stats = self.rudp.get_sender_stats()

                logger.success(
                    f"UDP stream done  | seg{segment} | {len(segment_data)} bytes | {speed:.2f} KB/s"
                )
                logger.metric(
                    f"mode={stats['mode']} sent={stats['sent_packets']} "
                    f"retx={stats['retransmissions']} fast_retx={stats['fast_retransmissions']} "
                    f"timeouts={stats['timeout_events']} dropped={stats['dropped_packets']} "
                    f"final_cwnd={stats['final_cwnd']}"
                )

            else:
                logger.warn(f"UDP unknown message type: {msg_type}")

    # =========================
    # TCP
    # =========================

    def tcp_loop(self):
        """
        הלולאה הראשית של TCP.

        כל לקוח שמתחבר מקבל thread נפרד,
        כדי שיהיה אפשר לטפל בכמה חיבורים במקביל.
        """
        logger.section("TCP STREAM LOOP")
        while True:
            conn, addr = self.tcp_sock.accept()

            # לכל לקוח חדש פותחים thread נפרד
            thread = threading.Thread(
                target=self.handle_tcp_client,
                args=(conn, addr),
                daemon=True,
            )
            thread.start()

    def handle_tcp_client(self, conn, addr):
        """
        מטפל בלקוח TCP יחיד.

        הפרוטוקול כאן עובד כך:
        1. קודם קוראים 4 בתים שמכילים את אורך ההודעה
        2. אחר כך קוראים בדיוק את ההודעה עצמה
        3. מפענחים JSON ופועלים לפי סוג הבקשה
        """
        try:
            # קריאת אורך ההודעה
            raw_len = self.recv_exact(conn, 4)
            (msg_len,) = struct.unpack("!I", raw_len)

            # קריאת גוף ההודעה לפי האורך שקיבלנו
            raw = self.recv_exact(conn, msg_len)
            message = json.loads(raw.decode())

            msg_type = message.get("type")

            # הלקוח מבקש manifest
            if msg_type == "GET_MANIFEST":
                manifest = self.build_manifest()
                payload = json.dumps(manifest).encode()

                # שולחים קודם את אורך ההודעה ואז את המידע עצמו
                conn.sendall(struct.pack("!I", len(payload)) + payload)
                logger.success(f"TCP manifest -> {addr}")

            # הלקוח מבקש סגמנט מסוים
            elif msg_type == "GET_SEGMENT":
                video = message.get("video")
                quality = message.get("quality")
                segment = message.get("segment")

                data = self.load_segment(video, quality, segment)

                # אם הסגמנט לא קיים, מחזירים הודעת שגיאה
                if data is None:
                    err = {
                        "type": "ERROR",
                        "message": f"segment not found: {video}/{quality}/seg{segment}.ts",
                    }
                    payload = json.dumps(err).encode()
                    conn.sendall(struct.pack("!I", len(payload)) + payload)
                    logger.error(f"TCP missing segment: {video}/{quality}/seg{segment}.ts")
                    return

                # קודם שולחים header קטן עם סטטוס וגודל הקובץ
                header = json.dumps({
                    "type": "OK",
                    "size": len(data),
                }).encode()

                conn.sendall(struct.pack("!I", len(header)) + header)

                # אחר כך שולחים את כל הסגמנט עצמו
                start = time.time()
                conn.sendall(data)
                end = time.time()

                speed = (len(data) / 1024 / (end - start)) if end > start else 0.0
                logger.success(f"TCP stream done | {video}/{quality}/seg{segment} | {speed:.2f} KB/s")

            else:
                logger.warn(f"TCP unknown request type: {msg_type}")

        except Exception as e:
            logger.error(f"TCP error: {e}")
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def start(self):
        """
        מפעיל את השרת.

        הרעיון:
        - TCP רץ ב-thread נפרד
        - UDP רץ בלולאה הראשית
        """
        threading.Thread(target=self.tcp_loop, daemon=True).start()
        self.udp_loop()


if __name__ == "__main__":
    AppServer().start()