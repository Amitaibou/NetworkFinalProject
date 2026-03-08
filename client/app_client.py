import json
import os
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


logger = Logger(debug=DEBUG_MODE, use_colors=USE_COLORS)


class AppClient:
    def recv_exact(self, sock, n):
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
        tcp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        tcp.settimeout(5)
        tcp.connect((SERVER_HOST, APP_TCP_PORT))

        request = {"type": "GET_MANIFEST"}
        msg = json.dumps(request).encode()

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
        tcp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        tcp.settimeout(10)
        tcp.connect((SERVER_HOST, APP_TCP_PORT))

        request = {
            "type": "GET_SEGMENT",
            "video": video,
            "quality": quality,
            "segment": segment,
        }

        msg = json.dumps(request).encode()
        tcp.sendall(len(msg).to_bytes(4, "big") + msg)

        raw_header_len = self.recv_exact(tcp, 4)
        header_len = int.from_bytes(raw_header_len, "big")

        header = self.recv_exact(tcp, header_len)
        header = json.loads(header.decode())

        if header.get("type") == "ERROR":
            tcp.close()
            return None, 0.0, {}

        size = header["size"]

        data = bytearray()
        start = time.time()

        while len(data) < size:
            chunk = tcp.recv(4096)
            if not chunk:
                break
            data.extend(chunk)

        end = time.time()
        tcp.close()

        elapsed = end - start
        bw = (len(data) / 1024 / elapsed) if elapsed > 0 else 0.0

        stats = {
            "transport": "TCP",
            "bytes": len(data),
            "elapsed": round(elapsed, 3),
            "bandwidth_kb_s": round(bw, 2),
        }

        return bytes(data), bw, stats

    # =========================
    # RUDP DOWNLOAD
    # =========================

    def download_segment_rudp(self, video, quality, segment, protocol):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

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

        sock.sendto(json.dumps(request).encode(), (SERVER_HOST, APP_PORT))

        data = bytearray()
        start = time.time()

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
        try:
            result = subprocess.run(
                ["ffmpeg", "-y", "-i", ts_path, "-c", "copy", mp4_path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            return result.returncode == 0
        except Exception as e:
            logger.warn(f"FFMPEG conversion failed: {e}")
            return False


    def open_video_file(self, path):
        try:
            if sys.platform.startswith("win"):
                os.startfile(path)
            elif sys.platform == "darwin":
                subprocess.run(["open", path], check=False)
            else:
                subprocess.run(["xdg-open", path], check=False)
        except Exception as e:
            logger.warn(f"Could not open file automatically: {e}")


def choose_from_list(prompt, items):
    print()
    for i, item in enumerate(items, start=1):
        print(f"{i}. {item}")
    idx = int(input(f"\n{prompt}: ").strip())
    return items[idx - 1]


if __name__ == "__main__":
    logger.section("DASH VIDEO CLIENT")

    client = AppClient()

    try:
        manifest = client.get_manifest()
    except Exception as e:
        logger.error(f"Manifest failed: {e}")
        raise SystemExit(1)

    qualities = manifest["qualities"]
    videos = list(manifest["videos"].keys())
    segments_map = manifest["videos"]

    if not videos:
        logger.error(f"No videos found in manifest: {manifest}")
        raise SystemExit(1)

    print("Available videos:")
    video = choose_from_list("Choose video", videos)
    total_segments = segments_map[video]

    print("\nTransport protocol:")
    print("1. TCP")
    print("2. RUDP")
    transport_choice = input("Choice: ").strip()
    transport = "TCP" if transport_choice == "1" else "RUDP"

    protocol = "SR"
    if transport == "RUDP":
        print("\nRUDP mode:")
        print("1. Stop & Wait")
        print("2. Go Back N")
        print("3. Selective Repeat")
        p = input("Choice: ").strip()

        protocol = {
            "1": "STOP_WAIT",
            "2": "GBN",
            "3": "SR",
        }.get(p, "SR")

    print("\nAdaptive streaming mode:")
    print("1. Auto")
    print("2. Manual")
    mode = input("Choice: ").strip()

    quality = "low"
    if mode == "2":
        quality = choose_from_list("Choose quality", qualities)

    output_ts = "output_video.ts"
    output_mp4 = "output_video.mp4"

    for path in (output_ts, output_mp4):
        if os.path.exists(path):
            os.remove(path)

    download_stats = []
    completed_all_segments = True

    logger.info(
        f"Session start | video={video} | total_segments={total_segments} | transport={transport} "
        f"| mode={protocol if transport == 'RUDP' else 'TCP'} | adaptive={'AUTO' if mode == '1' else 'MANUAL'}"
    )

    for segment in range(total_segments):
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

        if mode == "1":
            quality = client.choose_quality(bw, qualities)

    logger.section("VIDEO COMPLETE")

    if not completed_all_segments:
        print("Download stopped before all segments were received.")
        print(f"Partial file saved as: {output_ts}")
        raise SystemExit(1)

    total_bytes = sum(x["bytes"] for x in download_stats)
    avg_bw = (
        sum(x["bandwidth_kb_s"] for x in download_stats) / len(download_stats)
        if download_stats else 0.0
    )

    quality_hist = {}
    for x in download_stats:
        q = x["quality"]
        quality_hist[q] = quality_hist.get(q, 0) + 1

    logger.success(f"Saved as: {output_ts}")
    logger.metric(
        f"Summary | downloaded_segments={len(download_stats)}/{total_segments} | "
        f"total_bytes={total_bytes} | avg_bw={avg_bw:.2f} KB/s"
    )
    logger.metric(f"Quality usage: {quality_hist}")

    if client.convert_ts_to_mp4(output_ts, output_mp4):
        logger.success(f"Converted successfully to: {output_mp4}")
        client.open_video_file(output_mp4)
    else:
        logger.warn("Could not convert to MP4, opening TS file instead")
        client.open_video_file(output_ts)