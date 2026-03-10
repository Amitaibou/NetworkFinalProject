import json
import socket
import time

from protocol.config import SERVER_HOST, DNS_PORT, BUFFER_SIZE


class DNSServer:
    def __init__(self):
        # יצירת UDP socket עבור שרת ה-DNS
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        # השרת מאזין על ה-IP והפורט שהוגדרו בקובץ ההגדרות
        self.sock.bind((SERVER_HOST, DNS_PORT))

        # רשומות DNS סטטיות
        # לכל domain יש כתובת IP ו-TTL
        self.records = {
            "video.local": {"ip": SERVER_HOST, "ttl": 300},
            "app.local": {"ip": SERVER_HOST, "ttl": 300},
            "ariel.local": {"ip": "147.235.16.64", "ttl": 600},
            "amitai-home.local": {"ip": "10.0.0.10", "ttl": 600},
            "ofri-home.local": {"ip": "10.0.0.11", "ttl": 600},
            "daniel-home.local": {"ip": "10.0.0.12", "ttl": 600},
            "anna-home.local": {"ip": "10.0.0.13", "ttl": 600},
        }

        print(f"[DNS] Server running on {SERVER_HOST}:{DNS_PORT}")

    def _send_json(self, payload, addr):
        # שולח תשובת JSON ללקוח
        self.sock.sendto(json.dumps(payload).encode(), addr)

    def _recv_json(self):
        # מקבל הודעת UDP, ממיר מ-JSON ומחזיר גם את הכתובת של השולח
        data, addr = self.sock.recvfrom(BUFFER_SIZE)
        return json.loads(data.decode()), addr

    def handle_query(self, addr, domain):
        """
        מטפל בבקשת DNS עבור domain מסוים.

        אם ה-domain קיים בטבלת הרשומות:
        מחזירים תשובה עם status=OK, ה-IP וה-TTL.

        אם הוא לא קיים:
        מחזירים תשובה עם status=NOT_FOUND.
        """
        record = self.records.get(domain)

        if record:
            response = {
                "type": "RESPONSE",
                "status": "OK",
                "domain": domain,
                "ip": record["ip"],
                "ttl": record["ttl"],
                "resolved_at": int(time.time()),
            }
        else:
            response = {
                "type": "RESPONSE",
                "status": "NOT_FOUND",
                "domain": domain,
                "ip": None,
                "ttl": 0,
                "resolved_at": int(time.time()),
            }

        self._send_json(response, addr)

        print(
            f"[DNS] Query for {domain} -> "
            f"{response['status']} ({response['ip']}) ttl={response['ttl']}"
        )

    def start(self):
        """
        הלולאה הראשית של השרת.

        השרת כל הזמן מחכה להודעות UDP מהלקוחות.
        אם הגיעה הודעה מסוג QUERY:
        הוא שולף את שם ה-domain ומנסה לפתור אותו דרך טבלת הרשומות.
        """
        while True:
            try:
                message, addr = self._recv_json()
            except Exception:
                continue

            if message.get("type") == "QUERY":
                # מנקים רווחים וממירים ל-lower כדי למנוע חוסר התאמה
                domain = message.get("domain", "").strip().lower()
                self.handle_query(addr, domain)


if __name__ == "__main__":
    server = DNSServer()
    server.start()