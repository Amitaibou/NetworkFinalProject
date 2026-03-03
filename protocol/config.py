# config.py

SERVER_HOST = "127.0.0.1"

DHCP_PORT = 5000
DNS_PORT = 5001
APP_PORT = 5002

BUFFER_SIZE = 65536  # 64KB (נגדיל בגלל UDP)
TIMEOUT = 0.5        # timeout לרה-טרנסמישן
WINDOW_SIZE = 5      # גודל חלון התחלתי