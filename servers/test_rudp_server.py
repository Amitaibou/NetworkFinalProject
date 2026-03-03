import socket
from protocol.config import SERVER_HOST, APP_PORT
from protocol.rudp import RUDP


sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind((SERVER_HOST, APP_PORT))

rudp = RUDP(sock)

print("[RUDP SERVER] Waiting...")

while True:
    data, addr = rudp.receive()
    print("Received:", data.decode())