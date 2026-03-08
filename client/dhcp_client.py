import json
import socket
import uuid

from protocol.config import SERVER_HOST, DHCP_PORT, BUFFER_SIZE, DEBUG_MODE, USE_COLORS
from protocol.logger import Logger


logger = Logger(debug=DEBUG_MODE, use_colors=USE_COLORS)


class DHCPClient:
    def __init__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.settimeout(3)
        self.ip = None
        self.lease_time = None
        self.server_id = None
        self.client_id = str(uuid.uuid4())

    def request_ip(self):
        try:
            discover = {
                "type": "DISCOVER",
                "client_id": self.client_id
            }

            logger.info("Starting DHCP request...")
            self.sock.sendto(json.dumps(discover).encode(), (SERVER_HOST, DHCP_PORT))

            data, _ = self.sock.recvfrom(BUFFER_SIZE)
            offer = json.loads(data.decode())

            if offer.get("type") != "OFFER":
                logger.error(f"Unexpected DHCP response: {offer}")
                return None

            requested_ip = offer.get("ip")
            lease_time = offer.get("lease_time", 0)
            server_id = offer.get("server_id", SERVER_HOST)

            logger.debug_log(
                f"DHCP OFFER | ip={requested_ip} | lease_time={lease_time}s | server={server_id}"
            )

            request = {
                "type": "REQUEST",
                "client_id": self.client_id,
                "ip": requested_ip
            }

            self.sock.sendto(json.dumps(request).encode(), (SERVER_HOST, DHCP_PORT))

            data, _ = self.sock.recvfrom(BUFFER_SIZE)
            ack = json.loads(data.decode())

            if ack.get("type") == "ACK":
                self.ip = ack.get("ip")
                self.lease_time = ack.get("lease_time")
                self.server_id = ack.get("server_id", SERVER_HOST)

                print(
                    f"[DHCP CLIENT] Lease acquired | ip={self.ip} | "
                    f"lease_time={self.lease_time}s | server={self.server_id}"
                )
                return self.ip

            if ack.get("type") == "NAK":
                logger.warn(f"DHCP request rejected: {ack.get('message', 'unknown error')}")
                return None

            logger.error(f"Unexpected DHCP ACK/NAK response: {ack}")
            return None

        except socket.timeout:
            logger.warn("DHCP request timed out")
            return None
        except Exception as e:
            logger.error(f"DHCP failed: {e}")
            return None

    def renew_ip(self):
        if not self.ip:
            logger.warn("Cannot renew DHCP lease before acquiring IP")
            return None

        try:
            renew = {
                "type": "REQUEST",
                "client_id": self.client_id,
                "ip": self.ip
            }

            logger.info(f"Renewing DHCP lease for {self.ip}...")
            self.sock.sendto(json.dumps(renew).encode(), (SERVER_HOST, DHCP_PORT))

            data, _ = self.sock.recvfrom(BUFFER_SIZE)
            response = json.loads(data.decode())

            if response.get("type") == "ACK":
                self.lease_time = response.get("lease_time", self.lease_time)
                logger.success(
                    f"DHCP lease renewed | ip={self.ip} | lease_time={self.lease_time}s"
                )
                return self.ip

            logger.warn(f"DHCP renew failed: {response}")
            return None

        except socket.timeout:
            logger.warn("DHCP renew timed out")
            return None
        except Exception as e:
            logger.error(f"DHCP renew failed: {e}")
            return None

    def release_ip(self):
        if not self.ip:
            return

        try:
            release = {
                "type": "RELEASE",
                "client_id": self.client_id,
                "ip": self.ip
            }

            self.sock.sendto(json.dumps(release).encode(), (SERVER_HOST, DHCP_PORT))
            logger.info(f"Released DHCP IP: {self.ip}")
            self.ip = None
            self.lease_time = None

        except Exception as e:
            logger.warn(f"DHCP release failed: {e}")


if __name__ == "__main__":
    client = DHCPClient()
    client.request_ip()