import os
import sys
import shutil
import subprocess
from pathlib import Path

# =========================
# PATHS
# =========================

print("Preparing DASH video segments...")
print("Source videos directory: video_sources/")
print("Output directory: assets/videos/")

# התיקייה שבה נמצא הקובץ הנוכחי
BASE_DIR = Path(__file__).resolve().parent

# כאן שמים את קבצי הווידאו המקוריים לפני ההמרה
VIDEO_SOURCES_DIR = BASE_DIR / "video_sources"

# לכאן יישמרו התוצרים אחרי החלוקה לסגמנטים
VIDEOS_OUTPUT_DIR = BASE_DIR / "assets" / "videos"

# אורך כל סגמנט בשניות
SEGMENT_TIME = 4

# הגדרות איכות שונות לכל גרסה של הסרטון
# לכל איכות יש רזולוציה ו-bitrate שונים
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

# פונקציות עזר להדפסות מסודרות למסך

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
    """
    בודק אם ffmpeg מותקן וזמין ב-PATH.

    בלי ffmpeg אי אפשר להמיר את הסרטונים או לחלק אותם לסגמנטים.
    """
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
    """
    יוצר את התיקיות הדרושות אם הן עדיין לא קיימות.
    """
    VIDEO_SOURCES_DIR.mkdir(parents=True, exist_ok=True)
    VIDEOS_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def is_video_file(path: Path) -> bool:
    """
    בודק אם הקובץ הוא בפורמט וידאו נתמך.
    """
    return path.suffix.lower() in {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}


def clean_output_folder(folder: Path):
    """
    אם תיקיית היעד כבר קיימת, מוחקים אותה ובונים מחדש.
    ככה לא נשארים סגמנטים ישנים מהרצה קודמת.
    """
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True, exist_ok=True)


def run_command(command: list[str]):
    """
    מריץ פקודת shell (במקרה שלנו ffmpeg).

    אם הפקודה נכשלה - זורקים שגיאה עם הפלט של ffmpeg.
    """
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "ffmpeg command failed")


def prepare_single_video(input_path: Path):
    """
    מקבל קובץ וידאו אחד, ומכין ממנו 3 גרסאות איכות:
    low / mid / high

    לכל איכות:
    - משנה רזולוציה
    - משנה bitrate
    - מחלק לסגמנטים של 4 שניות
    - שומר את הסגמנטים בתיקייה מתאימה
    """
    if not input_path.exists():
        raise FileNotFoundError(f"Source file not found: {input_path}")

    if not is_video_file(input_path):
        raise ValueError(f"Unsupported video format: {input_path.name}")

    # שם הסרטון בלי הסיומת
    video_name = input_path.stem

    # תיקיית הפלט של הסרטון
    output_base = VIDEOS_OUTPUT_DIR / video_name

    log(f"Preparing video: {input_path.name}")
    log(f"Target folder: {output_base}")

    # מנקים את תיקיית הפלט כדי להתחיל מאפס
    clean_output_folder(output_base)

    # עוברים על כל האיכויות שהוגדרו
    for quality_name, preset in QUALITY_PRESETS.items():
        quality_dir = output_base / quality_name
        quality_dir.mkdir(parents=True, exist_ok=True)

        # ffmpeg ישמור את הסגמנטים בשם seg0.ts, seg1.ts, ...
        segment_pattern = str(quality_dir / "seg%d.ts")

        # ffmpeg גם יוצר playlist מסוג m3u8
        playlist_path = str(quality_dir / "index.m3u8")

        # פקודת ffmpeg:
        # 1. קוראת את הסרטון המקורי
        # 2. משנה איכות/רזולוציה
        # 3. מחלקת אותו לסגמנטים
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

        # אם אתה לא משתמש ב-playlist בקוד שלך, אפשר למחוק אותו
        if os.path.exists(playlist_path):
            os.remove(playlist_path)

        # ספירת כמות הסגמנטים שנוצרו
        segment_count = len(list(quality_dir.glob("seg*.ts")))
        ok(f"{quality_name}: created {segment_count} segments")

    ok(f"Done: {video_name}")


def prepare_all_videos():
    """
    עובר על כל קבצי הווידאו שבתיקיית video_sources
    ומכין כל אחד מהם.
    """
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
    """
    מדפיס למשתמש איך להשתמש בסקריפט.
    """
    print("Usage:")
    print("  python prepare_video.py --all")
    print("  python prepare_video.py video_sources/myvideo.mp4")
    print("  python prepare_video.py myvideo.mp4")
    print()
    print("Recommended folder for source videos:")
    print(f"  {VIDEO_SOURCES_DIR}")


def resolve_input_path(user_arg: str) -> Path:
    """
    מנסה להבין לאיזה קובץ המשתמש התכוון.

    תומך ב:
    - נתיב מלא
    - נתיב יחסי
    - שם קובץ שנמצא בתוך video_sources
    """
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
    # קודם בודקים ש-ffmpeg מותקן
    check_ffmpeg()

    # מוודאים שהתיקיות הדרושות קיימות
    ensure_directories()

    # אם המשתמש לא שלח ארגומנט - מציגים הוראות שימוש
    if len(sys.argv) < 2:
        print_usage()
        sys.exit(0)

    arg = sys.argv[1].strip()

    try:
        # אם נכתב --all, מכינים את כל הסרטונים שבתיקיית המקור
        if arg == "--all":
            prepare_all_videos()
        else:
            # אחרת מכינים רק קובץ יחיד
            input_path = resolve_input_path(arg)
            prepare_single_video(input_path)
    except Exception as e:
        err(str(e))
        sys.exit(1)