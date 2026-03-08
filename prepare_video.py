import os
import sys
import shutil
import subprocess
from pathlib import Path

# =========================
# PATHS
# =========================

BASE_DIR = Path(__file__).resolve().parent
VIDEO_SOURCES_DIR = BASE_DIR / "video_sources"
VIDEOS_OUTPUT_DIR = BASE_DIR / "assets" / "videos"

SEGMENT_TIME = 4

QUALITY_PRESETS = {
    "low": {
        "scale": "426:240",
        "video_bitrate": "400k",
        "maxrate": "500k",
        "bufsize": "800k",
        "audio_bitrate": "64k",
    },
    "mid": {
        "scale": "854:480",
        "video_bitrate": "1000k",
        "maxrate": "1200k",
        "bufsize": "2000k",
        "audio_bitrate": "96k",
    },
    "high": {
        "scale": "1280:720",
        "video_bitrate": "2500k",
        "maxrate": "3000k",
        "bufsize": "5000k",
        "audio_bitrate": "128k",
    },
}


# =========================
# LOGGING
# =========================

def log(msg: str):
    print(f"[INFO] {msg}")


def ok(msg: str):
    print(f"[OK] {msg}")


def warn(msg: str):
    print(f"[WARN] {msg}")


def err(msg: str):
    print(f"[ERR] {msg}")


# =========================
# HELPERS
# =========================

def check_ffmpeg():
    try:
        subprocess.run(
            ["ffmpeg", "-version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
            text=True
        )
    except Exception:
        err("ffmpeg לא מותקן או לא נמצא ב-PATH.")
        err("תתקין ffmpeg ואז תריץ שוב.")
        sys.exit(1)


def ensure_directories():
    VIDEO_SOURCES_DIR.mkdir(parents=True, exist_ok=True)
    VIDEOS_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def is_video_file(path: Path) -> bool:
    return path.suffix.lower() in {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}


def clean_output_folder(folder: Path):
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True, exist_ok=True)


def run_command(command: list[str]):
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "ffmpeg command failed")


def prepare_single_video(input_path: Path):
    if not input_path.exists():
        raise FileNotFoundError(f"Source file not found: {input_path}")

    if not is_video_file(input_path):
        raise ValueError(f"Unsupported video format: {input_path.name}")

    video_name = input_path.stem
    output_base = VIDEOS_OUTPUT_DIR / video_name

    log(f"Preparing video: {input_path.name}")
    log(f"Target folder: {output_base}")

    clean_output_folder(output_base)

    for quality_name, preset in QUALITY_PRESETS.items():
        quality_dir = output_base / quality_name
        quality_dir.mkdir(parents=True, exist_ok=True)

        segment_pattern = str(quality_dir / "seg%d.ts")
        playlist_path = str(quality_dir / "index.m3u8")

        cmd = [
            "ffmpeg",
            "-y",
            "-i", str(input_path),

            "-vf", f"scale={preset['scale']}",
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-b:v", preset["video_bitrate"],
            "-maxrate", preset["maxrate"],
            "-bufsize", preset["bufsize"],

            "-c:a", "aac",
            "-b:a", preset["audio_bitrate"],
            "-ac", "2",

            "-f", "hls",
            "-hls_time", str(SEGMENT_TIME),
            "-hls_list_size", "0",
            "-hls_segment_type", "mpegts",
            "-hls_segment_filename", segment_pattern,
            playlist_path,
        ]

        log(f"Creating quality '{quality_name}'...")
        run_command(cmd)

        # אפשר למחוק את קובץ הפלייליסט אם אתה לא צריך אותו
        if os.path.exists(playlist_path):
            os.remove(playlist_path)

        segment_count = len(list(quality_dir.glob("seg*.ts")))
        ok(f"{quality_name}: created {segment_count} segments")

    ok(f"Done: {video_name}")


def prepare_all_videos():
    files = [p for p in VIDEO_SOURCES_DIR.iterdir() if p.is_file() and is_video_file(p)]

    if not files:
        warn(f"No video files found in: {VIDEO_SOURCES_DIR}")
        return

    for file_path in files:
        try:
            prepare_single_video(file_path)
            print()
        except Exception as e:
            err(f"Failed on {file_path.name}: {e}")


def print_usage():
    print("Usage:")
    print("  python prepare_video.py --all")
    print("  python prepare_video.py video_sources/myvideo.mp4")
    print("  python prepare_video.py myvideo.mp4")
    print()
    print("Recommended folder for source videos:")
    print(f"  {VIDEO_SOURCES_DIR}")


def resolve_input_path(user_arg: str) -> Path:
    candidate = Path(user_arg)

    if candidate.is_absolute():
        return candidate

    if candidate.exists():
        return candidate.resolve()

    in_sources = VIDEO_SOURCES_DIR / user_arg
    if in_sources.exists():
        return in_sources.resolve()

    return candidate.resolve()


# =========================
# MAIN
# =========================

if __name__ == "__main__":
    check_ffmpeg()
    ensure_directories()

    if len(sys.argv) < 2:
        print_usage()
        sys.exit(0)

    arg = sys.argv[1].strip()

    try:
        if arg == "--all":
            prepare_all_videos()
        else:
            input_path = resolve_input_path(arg)
            prepare_single_video(input_path)
    except Exception as e:
        err(str(e))
        sys.exit(1)