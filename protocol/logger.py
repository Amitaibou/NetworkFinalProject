import time


class C:
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
    def __init__(self, debug=False, use_colors=True):
        self.debug = debug
        self.use_colors = use_colors

    def _paint(self, text, color):
        if not self.use_colors:
            return text
        return f"{color}{text}{C.RESET}"

    def _line(self, level, msg, color):
        now = time.strftime("%H:%M:%S")
        tag = self._paint(f"[{level} {now}]", color)
        print(f"{tag} {msg}")

    def section(self, title, width=64):
        line = "=" * width
        print(f"\n{line}")
        print(title)
        print(line)

    def info(self, msg):
        self._line("INFO", msg, C.CYAN)

    def success(self, msg):
        self._line("OK", msg, C.GREEN)

    def warn(self, msg):
        self._line("WARN", msg, C.YELLOW)

    def error(self, msg):
        self._line("ERR", msg, C.RED)

    def debug_log(self, msg):
        if self.debug:
            self._line("DBG", msg, C.GRAY)

    def metric(self, msg):
        self._line("STAT", msg, C.MAGENTA)