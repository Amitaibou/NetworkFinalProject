SERVER_HOST = "127.0.0.1"

DHCP_PORT = 5000
DNS_PORT = 5001
APP_PORT = 5002
APP_TCP_PORT = 5003

BUFFER_SIZE = 65536
TIMEOUT = 0.5
WINDOW_SIZE = 5

# ===============================
# APP LOGGING / DISPLAY
# ===============================

DEBUG_MODE = True
USE_COLORS = True

# אם רוצים דיבאג עמוק של RUDP
RUDP_LOG_ACK = False
RUDP_LOG_SEND = False
RUDP_LOG_CC = False
RUDP_LOG_TIMEOUT =False
RUDP_LOG_LOSS = False
RUDP_LOG_WINDOW = False

# סימולציית איבוד
PACKET_LOSS_RATE = 0.02

# RUDP tuning
CHUNK_SIZE = 1024
DUP_ACK_THRESHOLD = 3
MAX_TIMEOUT_RETRIES = 30

# Adaptive streaming thresholds (KB/s)
AUTO_LOW_THRESHOLD = 500
AUTO_MID_THRESHOLD = 2000