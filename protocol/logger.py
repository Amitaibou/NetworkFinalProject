import time


class C:
    # מחלקת עזר שמרכזת את קודי הצבעים/העיצוב של הטרמינל
    RESET = "\033[0m"
    BOLD = "\033[1m"

    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    GRAY = "\033[90m"
    WHITE = "\033[97m"


class Logger:
    """
    לוגר פשוט של הפרויקט.
    המטרה שלו היא לאחד את כל ההדפסות למסך בפורמט קבוע,
    עם שעה, רמת הודעה, ואפשרות לצבעים.
    """

    def __init__(self, debug=False, use_colors=True):
        # debug קובע אם להציג הודעות DBG
        # use_colors קובע אם להדפיס עם צבעים או כפלט רגיל
        self.debug = debug
        self.use_colors = use_colors

    def _paint(self, text, color):
        # אם צבעים כבויים נחזיר את הטקסט כמו שהוא
        if not self.use_colors:
            return text
        return f"{color}{text}{C.RESET}"

    def _line(self, level, msg, color):
        # פונקציית עזר פנימית:
        # בונה שורת לוג אחידה עם timestamp ותג רמה
        now = time.strftime("%H:%M:%S")
        tag = self._paint(f"[{level} {now}]", color)
        print(f"{tag} {msg}")

    def section(self, title, width=64):
        # מדפיס כותרת ברורה שמפרידה בין חלקים בריצה
        line = "=" * width
        print(f"\n{line}")
        print(title)
        print(line)

    def info(self, msg):
        # הודעת מידע כללית
        self._line("INFO", msg, C.CYAN)

    def success(self, msg):
        # הודעת הצלחה / פעולה תקינה
        self._line("OK", msg, C.GREEN)

    def warn(self, msg):
        # אזהרה - לא בהכרח שגיאה, אבל משהו שכדאי לשים לב אליו
        self._line("WARN", msg, C.YELLOW)

    def error(self, msg):
        # שגיאה
        self._line("ERR", msg, C.RED)

    def debug_log(self, msg):
        # הודעות debug יודפסו רק אם מצב debug פעיל
        if self.debug:
            self._line("DBG", msg, C.GRAY)

    def metric(self, msg):
        # משמש לסטטיסטיקות, מדדים וסיכומים
        self._line("STAT", msg, C.MAGENTA)