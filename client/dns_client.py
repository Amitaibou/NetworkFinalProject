import json
import socket
import time

from protocol.config import SERVER_HOST, DNS_PORT, BUFFER_SIZE


class DNSClient:
    """
    הלקוח הזה מדמה DNS client בסיסי.
    הוא שולח שאילתת domain לשרת DNS, מקבל כתובת IP,
    וגם שומר תשובות ב-cache לפי TTL כדי לא לשלוח כל פעם שוב.
    """

    def __init__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.settimeout(3)

        # cache מקומי של תשובות DNS:
        # לכל domain נשמור IP וזמן תפוגה
        self.cache = {}

    def _send_json(self, payload, addr):
        # פונקציית עזר לשליחת הודעת JSON
        self.sock.sendto(json.dumps(payload).encode(), addr)

    def _recv_json(self):
        # פונקציית עזר לקבלת הודעת JSON
        data, addr = self.sock.recvfrom(BUFFER_SIZE)
        return json.loads(data.decode()), addr

    def _cache_valid(self, domain):
        # בודק אם יש תשובה שמורה ל-domain הזה ואם היא עדיין לא פגה
        if domain not in self.cache:
            return False

        entry = self.cache[domain]
        return time.time() < entry["expires_at"]

    def resolve(self, domain):
        # מנקים את הקלט כדי שהחיפוש יהיה עקבי
        domain = domain.strip().lower()

        # אם כבר יש תשובה תקפה ב-cache, נחזיר אותה בלי לפנות לשרת
        if self._cache_valid(domain):
            entry = self.cache[domain]
            ttl_left = max(0, int(entry["expires_at"] - time.time()))
            print(f"[DNS CLIENT] Cache hit | {domain} -> {entry['ip']} (ttl={ttl_left})")
            return entry["ip"]

        query = {
            "type": "QUERY",
            "domain": domain,
        }

        # שולחים את השאילתה לשרת ה-DNS
        self._send_json(query, (SERVER_HOST, DNS_PORT))
        response, _ = self._recv_json()

        if response.get("status") == "OK":
            ip = response["ip"]
            ttl = int(response.get("ttl", 300))

            # שומרים ב-cache כדי שבקשות חוזרות יהיו מהירות יותר
            self.cache[domain] = {
                "ip": ip,
                "expires_at": time.time() + ttl,
            }

            print(f"[DNS CLIENT] {domain} -> {ip} (ttl={ttl})")
            return ip

        print(f"[DNS CLIENT] {domain} not found")
        return None


if __name__ == "__main__":
    client = DNSClient()
    client.resolve("video.local")