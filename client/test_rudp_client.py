import socket
from protocol.config import SERVER_HOST, APP_PORT
from protocol.rudp import RUDP


sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

rudp = RUDP(sock)

rudp.send(b"Hello RUDP!", (SERVER_HOST, APP_PORT))