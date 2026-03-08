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


BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VIDEOS_PATH = os.path.join(BASE_DIR, "assets", "videos")

logger = Logger(debug=DEBUG_MODE, use_colors=USE_COLORS)


class AppServer:
    def __init__(self):
        self.udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.udp_sock.bind((SERVER_HOST, APP_PORT))

        if hasattr(socket, "SIO_UDP_CONNRESET"):
            try:
                self.udp_sock.ioctl(socket.SIO_UDP_CONNRESET, False)
            except Exception:
                pass

        self.rudp = RUDP(self.udp_sock)

        self.tcp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.tcp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.tcp_sock.bind((SERVER_HOST, APP_TCP_PORT))
        self.tcp_sock.listen(5)

        logger.section("VIDEO DASH SERVER STARTED")
        logger.success(f"UDP  : {SERVER_HOST}:{APP_PORT}")
        logger.success(f"TCP  : {SERVER_HOST}:{APP_TCP_PORT}")
        logger.info(f"PATH : {VIDEOS_PATH}")
        logger.info(f"DEBUG: {DEBUG_MODE}")

    def build_manifest(self):
        videos = {}

        if not os.path.exists(VIDEOS_PATH):
            return {
                "type": "MANIFEST_RESPONSE",
                "videos": {},
                "qualities": ["low", "mid", "high"],
            }

        for video in os.listdir(VIDEOS_PATH):
            v_path = os.path.join(VIDEOS_PATH, video)
            if not os.path.isdir(v_path):
                continue

            low_path = os.path.join(v_path, "low")
            if not os.path.isdir(low_path):
                continue

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
        path = os.path.join(VIDEOS_PATH, video, quality, f"seg{segment}.ts")
        if not os.path.exists(path):
            return None
        with open(path, "rb") as f:
            return f.read()

    def recv_exact(self, conn, n):
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

            try:
                message = json.loads(data.decode())
            except Exception:
                continue

            msg_type = message.get("type")

            if msg_type == "GET_MANIFEST":
                manifest = self.build_manifest()
                self.udp_sock.sendto(json.dumps(manifest).encode(), addr)
                logger.success(f"UDP manifest sent to {addr}")

            elif msg_type == "GET_SEGMENT":
                video = message.get("video")
                quality = message.get("quality")
                segment = message.get("segment")
                protocol = message.get("protocol", "SR")

                self.rudp.set_mode(protocol)
                self.rudp.reset_sender()

                segment_data = self.load_segment(video, quality, segment)
                if segment_data is None:
                    logger.error(f"UDP missing segment: {video}/{quality}/seg{segment}.ts")
                    continue

                logger.info(f"UDP stream start | {video} | {quality} | seg{segment} | mode={protocol}")

                start = time.time()
                try:
                    self.rudp.send_bytes(segment_data, addr)
                except Exception as e:
                    logger.error(f"RUDP send failed: {e}")
                    continue
                end = time.time()

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
        logger.section("TCP STREAM LOOP")
        while True:
            conn, addr = self.tcp_sock.accept()
            thread = threading.Thread(
                target=self.handle_tcp_client,
                args=(conn, addr),
                daemon=True,
            )
            thread.start()

    def handle_tcp_client(self, conn, addr):
        try:
            raw_len = self.recv_exact(conn, 4)
            (msg_len,) = struct.unpack("!I", raw_len)

            raw = self.recv_exact(conn, msg_len)
            message = json.loads(raw.decode())

            msg_type = message.get("type")

            if msg_type == "GET_MANIFEST":
                manifest = self.build_manifest()
                payload = json.dumps(manifest).encode()
                conn.sendall(struct.pack("!I", len(payload)) + payload)
                logger.success(f"TCP manifest -> {addr}")

            elif msg_type == "GET_SEGMENT":
                video = message.get("video")
                quality = message.get("quality")
                segment = message.get("segment")

                data = self.load_segment(video, quality, segment)
                if data is None:
                    err = {
                        "type": "ERROR",
                        "message": f"segment not found: {video}/{quality}/seg{segment}.ts",
                    }
                    payload = json.dumps(err).encode()
                    conn.sendall(struct.pack("!I", len(payload)) + payload)
                    logger.error(f"TCP missing segment: {video}/{quality}/seg{segment}.ts")
                    return

                header = json.dumps({
                    "type": "OK",
                    "size": len(data),
                }).encode()

                conn.sendall(struct.pack("!I", len(header)) + header)

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
        threading.Thread(target=self.tcp_loop, daemon=True).start()
        self.udp_loop()


if __name__ == "__main__":
    AppServer().start()