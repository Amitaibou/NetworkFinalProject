import json
import os
import re
import socket
import subprocess
import sys
import time

from protocol.config import (
    SERVER_HOST,
    APP_PORT,
    APP_TCP_PORT,
    AUTO_LOW_THRESHOLD,
    AUTO_MID_THRESHOLD,
    DEBUG_MODE,
    USE_COLORS,
)
from protocol.logger import Logger
from protocol.rudp import RUDP
from client.dhcp_client import DHCPClient
from client.dns_client import DNSClient


# לוגר מרכזי של הקליינט
logger = Logger(debug=DEBUG_MODE, use_colors=USE_COLORS)


class AppClient:
    """
    המחלקה הזאת אחראית על כל התקשורת מול שרת הווידאו.
    בפועל היא יודעת: להביא manifest
    - להוריד סגמנט דרך TCP - להוריד סגמנט דרך RUDP
- לבחור איכות במצב אדפטיבי - לשמור/להמיר/לפתוח את הקובץ בסוף
    """

    def __init__(self, server_host=SERVER_HOST):
        self.server_host = server_host

    def recv_exact(self, sock, n):
        # פונקציית עזר: קוראת בדיוק n בתים מהסוקט
        # שימושי כשאנחנו יודעים מראש מה אורך ההודעה
        data = b""
        while len(data) < n:
            chunk = sock.recv(n - len(data))
            if not chunk:
                raise ConnectionError("Connection closed")
            data += chunk
        return data

    # =========================
    # MANIFEST
    # =========================

    def get_manifest(self):
        # ה-manifest מתקבל דרך TCP ומכיל:
        # אילו סרטונים קיימים, כמה סגמנטים יש לכל אחד, ואילו איכויות זמינות
        tcp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        tcp.settimeout(5)
        tcp.connect((self.server_host, APP_TCP_PORT))

        request = {"type": "GET_MANIFEST"}
        msg = json.dumps(request).encode()

        # קודם שולחים את אורך ההודעה, ואז את ההודעה עצמה
        tcp.sendall(len(msg).to_bytes(4, "big") + msg)

        raw_len = self.recv_exact(tcp, 4)
        payload_len = int.from_bytes(raw_len, "big")

        payload = self.recv_exact(tcp, payload_len)
        manifest = json.loads(payload.decode())

        tcp.close()
        return manifest

    # =========================
    # TCP DOWNLOAD
    # =========================

    def download_segment_tcp(self, video, quality, segment):
        # הורדת סגמנט בודד דרך TCP
        # כאן האמינות מגיעה מהפרוטוקול TCP עצמו
        tcp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        tcp.settimeout(10)
        tcp.connect((self.server_host, APP_TCP_PORT))

        request = {
            "type": "GET_SEGMENT",
            "video": video,
            "quality": quality,
            "segment": segment,
        }

        msg = json.dumps(request).encode()
        tcp.sendall(len(msg).to_bytes(4, "big") + msg)

        # קודם מקבלים כותרת עם מידע על הסגמנט
        raw_header_len = self.recv_exact(tcp, 4)
        header_len = int.from_bytes(raw_header_len, "big")

        header = self.recv_exact(tcp, header_len)
        header = json.loads(header.decode())

        if header.get("type") == "ERROR":
            tcp.close()
            return None, 0.0, {}

        size = header["size"]

        data = bytearray()
        start = time.perf_counter()

        # מורידים את כל הסגמנט עד שנקבל את כל הגודל שהשרת הצהיר עליו
        while len(data) < size:
            chunk = tcp.recv(4096)
            if not chunk:
                break
            data.extend(chunk)

        end = time.perf_counter()
        tcp.close()

        # perf_counter נותן מדידה מדויקת יותר לזמני ריצה קצרים
        elapsed = max(end - start, 0.000001)
        bw = (len(data) / 1024) / elapsed

        stats = {
            "transport": "TCP",
            "bytes": len(data),
            "elapsed": round(elapsed, 6),
            "bandwidth_kb_s": round(bw, 2),
        }

        return bytes(data), bw, stats

    # =========================
    # RUDP DOWNLOAD
    # =========================

    def download_segment_rudp(self, video, quality, segment, protocol):
        # הורדת סגמנט דרך UDP + שכבת אמינות שבנינו בעצמנו
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        # תיקון מוכר ל-Windows כדי להימנע מ-UDP reset במצבים מסוימים
        if hasattr(socket, "SIO_UDP_CONNRESET"):
            try:
                sock.ioctl(socket.SIO_UDP_CONNRESET, False)
            except Exception:
                pass

        rudp = RUDP(sock)
        rudp.reset_receiver()

        request = {
            "type": "GET_SEGMENT",
            "video": video,
            "quality": quality,
            "segment": segment,
            "protocol": protocol,
        }

        # הבקשה עצמה נשלחת ב-UDP לשרת האפליקציה
        sock.sendto(json.dumps(request).encode(), (self.server_host, APP_PORT))

        data = bytearray()
        start = time.time()

        # מקבלים חתיכות מידע עד שמגיע FIN מהצד השני
        while True:
            chunk, _, fin = rudp.receive()

            if chunk:
                data.extend(chunk)

            if fin:
                break

        end = time.time()
        sock.close()

        elapsed = end - start
        bw = (len(data) / 1024 / elapsed) if elapsed > 0 else 0.0

        stats = {
            "transport": "RUDP",
            "mode": protocol,
            "bytes": len(data),
            "elapsed": round(elapsed, 3),
            "bandwidth_kb_s": round(bw, 2),
        }

        return bytes(data), bw, stats

    # =========================
    # ADAPTIVE
    # =========================

    def choose_quality(self, bw_kb_s, qualities):
        # בחירת איכות פשוטה לפי רוחב הפס שנמדד בסגמנט הקודם
        # זו לוגיקה בסיסית של adaptive streaming
        if bw_kb_s < AUTO_LOW_THRESHOLD and "low" in qualities:
            return "low"
        if bw_kb_s < AUTO_MID_THRESHOLD and "mid" in qualities:
            return "mid"
        if "high" in qualities:
            return "high"
        return qualities[0]

    # =========================
    # VIDEO FILES
    # =========================

    def convert_ts_to_mp4(self, ts_path, mp4_path):
        # בסוף ההורדה אנחנו מנסים להמיר את קובץ ה-TS ל-MP4
        # כדי שיהיה יותר נוח לנגן אותו
        try:
            result = subprocess.run(
                ["ffmpeg", "-y", "-i", ts_path, "-c", "copy", mp4_path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return result.returncode == 0
        except Exception as e:
            logger.warn(f"FFMPEG conversion failed: {e}")
            return False

    def open_video_file(self, path):
        # פתיחה אוטומטית של הקובץ לפי מערכת ההפעלה
        try:
            if sys.platform.startswith("win"):
                os.startfile(path)
            elif sys.platform == "darwin":
                subprocess.run(["open", path], check=False)
            else:
                subprocess.run(["xdg-open", path], check=False)
        except Exception as e:
            logger.warn(f"Could not open file automatically: {e}")


# =========================
# HELPERS
# =========================

def choose_from_list(prompt, items):
    # תפריט בחירה כללי מרשימה
    print()
    for i, item in enumerate(items, start=1):
        print(f"{i}. {item}")

    while True:
        raw = input(f"\n{prompt}: ").strip()
        if raw.isdigit():
            idx = int(raw)
            if 1 <= idx <= len(items):
                return items[idx - 1]
        print("Invalid choice, try again.")


def choose_transport():
    print("\nTransport protocol:")
    print("1. TCP")
    print("2. RUDP")

    while True:
        choice = input("Choice: ").strip()
        if choice == "1":
            return "TCP"
        if choice == "2":
            return "RUDP"
        print("Invalid choice, try again.")


def choose_rudp_mode():
    print("\nRUDP mode:")
    print("1. Stop & Wait")
    print("2. Go Back N")
    print("3. Selective Repeat")

    while True:
        choice = input("Choice: ").strip()
        if choice == "1":
            return "STOP_WAIT"
        if choice == "2":
            return "GBN"
        if choice == "3":
            return "SR"
        print("Invalid choice, try again.")


def choose_stream_mode():
    print("\nAdaptive streaming mode:")
    print("1. Auto")
    print("2. Manual")

    while True:
        choice = input("Choice: ").strip()
        if choice in {"1", "2"}:
            return choice
        print("Invalid choice, try again.")


def choose_dns_name():
    # כאן המשתמש בוחר איזה שם דומיין לפתור דרך DNS
    domains = [
        "video.local",
        "app.local",
        "ariel.local",
        "amitai-home.local",
        "ofri-home.local",
        "daniel-home.local",
        "anna-home.local",
    ]

    print("\nDNS options:")
    for i, domain in enumerate(domains, start=1):
        print(f"{i}. {domain}")

    while True:
        raw = input("Choose domain: ").strip()
        if raw.isdigit():
            idx = int(raw)
            if 1 <= idx <= len(domains):
                return domains[idx - 1]
        print("Invalid choice, try again.")


def ask_yes_no(prompt):
    # קלט פשוט של כן/לא
    while True:
        value = input(f"{prompt} ").strip().lower()
        if value in {"y", "yes", "1"}:
            return True
        if value in {"n", "no", "0"}:
            return False
        print("Please enter y/n.")


def safe_name(text):
    # מנקה שם קובץ/תיקייה כדי שלא יהיו תווים בעייתיים
    cleaned = re.sub(r"[^\w\-\.]+", "_", text.strip())
    return cleaned.strip("_") or "video"


def ensure_dir(path):
    # יוצר תיקייה אם היא לא קיימת
    os.makedirs(path, exist_ok=True)


def build_output_paths(video, transport, mode_label, quality_label):
    # בונה נתיבי פלט לפי שם הסרט והבחירות של המשתמש
    video_safe = safe_name(video)

    downloads_root = "downloads"
    video_dir = os.path.join(downloads_root, video_safe)
    ensure_dir(video_dir)

    base_name = f"{video_safe}_{transport}_{mode_label}_{quality_label}"
    ts_path = os.path.join(video_dir, f"{base_name}.ts")
    mp4_path = os.path.join(video_dir, f"{base_name}.mp4")

    return video_dir, ts_path, mp4_path


def remove_if_exists(path):
    # אם קובץ ישן כבר קיים, מוחקים אותו כדי לא לערבב ריצות
    if os.path.exists(path):
        os.remove(path)


def print_summary(download_stats, total_segments):
    # סיכום סטטיסטי כללי בסוף ההורדה
    total_bytes = sum(x["bytes"] for x in download_stats)
    avg_bw = (
        sum(x["bandwidth_kb_s"] for x in download_stats) / len(download_stats)
        if download_stats else 0.0
    )

    quality_hist = {}
    for x in download_stats:
        q = x["quality"]
        quality_hist[q] = quality_hist.get(q, 0) + 1

    logger.metric(
        f"Summary | downloaded_segments={len(download_stats)}/{total_segments} | "
        f"total_bytes={total_bytes} | avg_bw={avg_bw:.2f} KB/s"
    )
    logger.metric(f"Quality usage: {quality_hist}")


def run_single_download(client):
    # הרצה מלאה של הורדה אחת:
    # מביאים manifest, בוחרים פרמטרים, מורידים את כל הסגמנטים, ושומרים תוצאה
    try:
        manifest = client.get_manifest()
    except Exception as e:
        logger.error(f"Manifest failed: {e}")
        return

    qualities = manifest.get("qualities", [])
    videos = list(manifest.get("videos", {}).keys())
    segments_map = manifest.get("videos", {})

    if not videos:
        logger.error(f"No videos found in manifest: {manifest}")
        return

    print("Available videos:")
    video = choose_from_list("Choose video", videos)
    total_segments = segments_map[video]

    transport = choose_transport()
    protocol = "SR"

    if transport == "RUDP":
        protocol = choose_rudp_mode()

    mode = choose_stream_mode()

    quality = "low"
    selected_quality_label = "AUTO"

    if mode == "2":
        quality = choose_from_list("Choose quality", qualities)
        selected_quality_label = quality

    mode_label = protocol if transport == "RUDP" else "TCP"
    adaptive_label = "AUTO" if mode == "1" else "MANUAL"

    video_dir, output_ts, output_mp4 = build_output_paths(
        video=video,
        transport=transport,
        mode_label=f"{mode_label}_{adaptive_label}",
        quality_label=selected_quality_label,
    )

    remove_if_exists(output_ts)
    remove_if_exists(output_mp4)

    download_stats = []
    completed_all_segments = True

    logger.info(
        f"Session start | video={video} | total_segments={total_segments} | transport={transport} "
        f"| mode={mode_label} | adaptive={adaptive_label} | server={client.server_host}"
    )
    logger.info(f"Output directory: {video_dir}")

    for segment in range(total_segments):
        #  לתקן אינדקסים לספירה שתתחיל מ-1
        human_segment = segment + 1
        current_quality = quality

        if transport == "TCP":
            data, bw, stats = client.download_segment_tcp(video, current_quality, segment)
        else:
            data, bw, stats = client.download_segment_rudp(video, current_quality, segment, protocol)

        if not data:
            logger.error(f"Segment {human_segment}/{total_segments} not received")
            completed_all_segments = False
            break

        with open(output_ts, "ab") as f:
            # שומרים כל סגמנט בסוף הקובץ הקיים
            f.write(data)

        segment_stat = {
            "segment": human_segment,
            "segment_index": segment,
            "quality": current_quality,
            **stats,
        }
        download_stats.append(segment_stat)

        logger.success(
            f"SEG {human_segment}/{total_segments} | quality={current_quality} | "
            f"size={stats['bytes']} bytes | bw={bw:.2f} KB/s"
        )

        if DEBUG_MODE:
            logger.metric(str(segment_stat))

        # במצב אוטומטי האיכות של הסגמנט הבא תיקבע לפי הביצועים של הנוכחי
        if mode == "1":
            quality = client.choose_quality(bw, qualities)

    logger.section("VIDEO COMPLETE")

    if not completed_all_segments:
        print("Download stopped before all segments were received.")
        print(f"Partial file saved as: {output_ts}")
        return

    logger.success(f"Saved TS as: {output_ts}")
    print_summary(download_stats, total_segments)

    if client.convert_ts_to_mp4(output_ts, output_mp4):
        logger.success(f"Converted successfully to: {output_mp4}")
        client.open_video_file(output_mp4)
    else:
        logger.warn("Could not convert to MP4, opening TS file instead")
        client.open_video_file(output_ts)


if __name__ == "__main__":
    logger.section("DASH VIDEO CLIENT")

    # קודם כל הלקוח מנסה לקבל כתובת IP דרך DHCP
    dhcp_client = DHCPClient()
    dns_client = DNSClient()

    logger.info("Starting DHCP request...")
    client_ip = dhcp_client.request_ip()

    if client_ip:
        logger.success(f"DHCP assigned client IP: {client_ip}")
    else:
        logger.warn("DHCP did not return an IP, continuing without lease")

    # הלולאה הראשית: כל פעם אפשר לבחור דומיין, ואם זה שרת וידאו אז גם להוריד סרט
    while True:
        domain = choose_dns_name()

        logger.info(f"Resolving domain: {domain}")
        resolved_ip = dns_client.resolve(domain)

        if not resolved_ip:
            logger.error("DNS resolve failed")
            print()
            if not ask_yes_no("Do you want to try another domain? (y/n):"):
                logger.info("Exiting client.")
                break
            continue

        logger.success(f"DNS resolved {domain} -> {resolved_ip}")

        # אם זה לא הדומיין של שרת האפליקציה, רק מציגים את ה-IP ולא נכנסים למסך הורדה
        if domain not in {"video.local", "app.local"}:
            print(f"\nResolved {domain} -> {resolved_ip}")
            print("This domain is not the video application server.")
            print()
            if not ask_yes_no("Do you want to query another domain? (y/n):"):
                logger.info("Exiting client.")
                break
            continue

        client = AppClient(server_host=resolved_ip)
        run_single_download(client)

        print()
        if not ask_yes_no("Do you want to continue? (y/n):"):
            logger.info("Exiting client.")
            break