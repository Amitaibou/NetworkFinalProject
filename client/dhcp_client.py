import json
import socket
import time
import uuid

from protocol.config import SERVER_HOST, DHCP_PORT, BUFFER_SIZE


class DHCPClient:
    """
    הלקוח הזה מדמה התנהגות בסיסית של DHCP client.
    הוא יודע:
    - לבקש כתובת IP חדשה
    - לחדש lease קיים
    - לשחרר כתובת
    - ולעבוד מול שרת DHCP דרך UDP
    """

    def __init__(self, lease_file=None):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self.sock.settimeout(3)

        # bind לפורט זמני מקומי כדי שהלקוח יוכל לקבל תשובות מהשרת
        self.sock.bind(("", 0))

        # מזהה לוגי של הלקוח בתוך הסימולציה
        self.client_id = str(uuid.uuid4())

        # פרטי lease נוכחי, אם יש
        self.ip = None
        self.server_id = None
        self.lease_time = 0
        self.lease_start = 0.0

        # אופציונלי: אפשר לשמור lease לקובץ לצורך בדיקה/דיבאג
        self.lease_file = lease_file

    def _send_json(self, payload, addr):
        # פונקציית עזר לשליחת הודעת JSON
        self.sock.sendto(json.dumps(payload).encode(), addr)

    def _recv_json(self):
        # פונקציית עזר לקבלת הודעת JSON
        data, addr = self.sock.recvfrom(BUFFER_SIZE)
        return json.loads(data.decode()), addr

    def _now(self):
        return time.time()

    def _lease_valid(self):
        # בודק אם יש lease פעיל שעדיין לא פג
        if not self.ip or not self.lease_start or not self.lease_time:
            return False
        return (self._now() - self.lease_start) < self.lease_time

    def _save_lease(self):
        # אם הוגדר קובץ lease, נשמור אליו את המידע
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
            # אם השמירה נכשלה זה לא קריטי לזרימת העבודה
            pass

    def _broadcast_discover(self):
        # בכל בקשה חדשה ניצור transaction id חדש
        # זה עוזר להתאים בין תשובות לבקשה הנכונה
        xid = str(uuid.uuid4())

        discover = {
            "type": "DISCOVER",
            "xid": xid,
            "client_id": self.client_id,
        }

        # קודם מנסים ברודקאסט "אמיתי"
        try:
            self._send_json(discover, ("255.255.255.255", DHCP_PORT))
            return xid
        except Exception:
            # fallback ליוניקאסט מקומי כדי שהמערכת עדיין תעבוד בסביבת פיתוח
            self._send_json(discover, (SERVER_HOST, DHCP_PORT))
            return xid

    def request_ip(self):
        # שלב 1: DISCOVER
        xid = self._broadcast_discover()

        offer = None
        server_addr = None

        # מחכים ל-OFFER שמתאים גם ל-xid וגם ל-client_id שלנו
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

        # שלב 2: REQUEST
        request = {
            "type": "REQUEST",
            "xid": xid,
            "client_id": self.client_id,
            "ip": requested_ip,
            "server_id": self.server_id,
        }

        self._send_json(request, server_addr)

        # מחכים ל-ACK או NAK
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
        # ניסיון לחדש כתובת קיימת מול אותו שרת שחילק אותה
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
        # שחרור יזום של הכתובת בחזרה לשרת
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
            # גם אם השחרור לא הצליח, מנקים לוקלית את מצב הלקוח
            self.ip = None
            self.lease_time = 0
            self.lease_start = 0.0

    def request_or_renew(self):
        # אם ה-lease עדיין תקף, פשוט נחזיר אותו
        if self._lease_valid():
            return self.ip

        # אם יש לנו IP ישן אבל ה-lease פג, ננסה קודם renew
        if self.ip:
            renewed = self.renew_lease()
            if renewed:
                return renewed

        # אם אין lease תקף ואין renew מוצלח, נבקש כתובת חדשה
        return self.request_ip()


if __name__ == "__main__":
    client = DHCPClient()
    try:
        client.request_ip()
    finally:
        client.sock.close()