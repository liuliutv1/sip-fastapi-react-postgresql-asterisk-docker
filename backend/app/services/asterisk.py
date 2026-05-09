import socket
import time
import uuid
from dataclasses import dataclass

from app.core.config import settings


class AmiError(RuntimeError):
    pass


@dataclass(frozen=True)
class AmiChannel:
    channel: str
    unique_id: str | None
    linked_id: str | None
    state: str | None


class AsteriskAmiClient:
    def __init__(self, timeout: float = 5.0):
        self.timeout = timeout

    def originate(
        self,
        *,
        trunk_name: str,
        destination: str,
        caller_id: str,
        action_id: str,
        channel_id: str,
    ) -> dict[str, str]:
        channel = f"PJSIP/{destination}@{trunk_name}"
        return self._request(
            {
                "Action": "Originate",
                "ActionID": action_id,
                "Channel": channel,
                "Application": "Wait",
                "Data": str(settings.asterisk_outbound_hold_seconds),
                "CallerID": caller_id,
                "Async": "true",
                "Timeout": str(settings.asterisk_originate_timeout_ms),
                "ChannelId": channel_id,
            }
        )

    def find_channel_by_id(self, channel_id: str) -> AmiChannel | None:
        packets = self._request(
            {
                "Action": "CoreShowChannels",
                "ActionID": f"core-show-{uuid.uuid4().hex}",
            },
            complete_event="CoreShowChannelsComplete",
        )
        for packet in packets:
            if packet.get("Event") != "CoreShowChannel":
                continue
            unique_id = packet.get("Uniqueid")
            linked_id = packet.get("Linkedid")
            if channel_id in {unique_id, linked_id}:
                return AmiChannel(
                    channel=packet.get("Channel", ""),
                    unique_id=unique_id,
                    linked_id=linked_id,
                    state=packet.get("ChannelStateDesc"),
                )
        return None

    def hangup(self, channel: str) -> dict[str, str]:
        return self._request(
            {
                "Action": "Hangup",
                "ActionID": f"hangup-{uuid.uuid4().hex}",
                "Channel": channel,
            }
        )

    def start_mixmonitor(self, channel: str, file_path: str) -> dict[str, str]:
        return self._request(
            {
                "Action": "MixMonitor",
                "ActionID": f"mixmonitor-{uuid.uuid4().hex}",
                "Channel": channel,
                "File": file_path,
            }
        )

    def stop_mixmonitor(self, channel: str) -> dict[str, str]:
        return self._request(
            {
                "Action": "StopMixMonitor",
                "ActionID": f"stop-mixmonitor-{uuid.uuid4().hex}",
                "Channel": channel,
            }
        )

    def command(self, command: str) -> str:
        response = self._request(
            {
                "Action": "Command",
                "ActionID": f"command-{uuid.uuid4().hex}",
                "Command": command,
            }
        )
        if isinstance(response, list):
            output = "\n".join(packet.get("Output", "") for packet in response)
        else:
            output = response.get("Output", "")
        return "\n".join(line for line in output.splitlines() if line.strip() != "--END COMMAND--")

    def iter_events(self, event_names: set[str] | None = None):
        with socket.create_connection(
            (settings.asterisk_ami_host, settings.asterisk_ami_port),
            timeout=self.timeout,
        ) as sock:
            sock.settimeout(self.timeout)
            buffer = ""

            login_action_id = f"login-{uuid.uuid4().hex}"
            self._send_action(
                sock,
                {
                    "Action": "Login",
                    "ActionID": login_action_id,
                    "Username": settings.asterisk_ami_username,
                    "Secret": settings.asterisk_ami_password,
                    "Events": "on",
                },
            )
            buffer, login_response = self._read_response(sock, buffer, login_action_id)
            self._ensure_success(login_response, "AMI event listener login failed")
            sock.settimeout(1.0)

            try:
                while True:
                    try:
                        buffer, packet = self._read_packet(sock, buffer)
                    except AmiError as exc:
                        if "Timed out reading AMI packet" in str(exc):
                            continue
                        raise
                    event_name = packet.get("Event")
                    if event_name and (event_names is None or event_name in event_names):
                        yield packet
            finally:
                try:
                    self._send_action(sock, {"Action": "Logoff", "ActionID": f"logoff-{uuid.uuid4().hex}"})
                except OSError:
                    pass

    def _request(self, fields: dict[str, str], complete_event: str | None = None) -> dict[str, str] | list[dict[str, str]]:
        with socket.create_connection(
            (settings.asterisk_ami_host, settings.asterisk_ami_port),
            timeout=self.timeout,
        ) as sock:
            sock.settimeout(self.timeout)
            buffer = ""

            login_action_id = f"login-{uuid.uuid4().hex}"
            self._send_action(
                sock,
                {
                    "Action": "Login",
                    "ActionID": login_action_id,
                    "Username": settings.asterisk_ami_username,
                    "Secret": settings.asterisk_ami_password,
                    "Events": "off",
                },
            )
            buffer, login_response = self._read_response(sock, buffer, login_action_id)
            self._ensure_success(login_response, "AMI login failed")

            action_id = fields.get("ActionID") or f"action-{uuid.uuid4().hex}"
            fields = {**fields, "ActionID": action_id}
            self._send_action(sock, fields)
            try:
                if complete_event:
                    packets: list[dict[str, str]] = []
                    deadline = time.monotonic() + self.timeout
                    while time.monotonic() < deadline:
                        buffer, packet = self._read_packet(sock, buffer)
                        if not packet:
                            continue
                        if packet.get("ActionID") in {None, action_id} or packet.get("Event") == complete_event:
                            packets.append(packet)
                        if packet.get("Event") == complete_event and packet.get("ActionID") in {None, action_id}:
                            return packets
                    raise AmiError(f"Timed out waiting for AMI event {complete_event}")

                buffer, response = self._read_response(sock, buffer, action_id)
                self._ensure_success(response, f"AMI action {fields.get('Action')} failed")
                return response
            finally:
                try:
                    self._send_action(sock, {"Action": "Logoff", "ActionID": f"logoff-{uuid.uuid4().hex}"})
                except OSError:
                    pass

    def _read_response(self, sock: socket.socket, buffer: str, action_id: str) -> tuple[str, dict[str, str]]:
        deadline = time.monotonic() + self.timeout
        fallback: dict[str, str] | None = None
        while time.monotonic() < deadline:
            buffer, packet = self._read_packet(sock, buffer)
            if "Response" not in packet:
                continue
            if packet.get("ActionID") == action_id:
                return buffer, packet
            fallback = fallback or packet
        if fallback:
            return buffer, fallback
        raise AmiError("Timed out waiting for AMI response")

    def _read_packet(self, sock: socket.socket, buffer: str) -> tuple[str, dict[str, str]]:
        while "\r\n\r\n" not in buffer:
            try:
                chunk = sock.recv(4096)
            except TimeoutError as exc:
                raise AmiError("Timed out reading AMI packet") from exc
            if not chunk:
                raise AmiError("AMI connection closed")
            buffer += chunk.decode("utf-8", errors="replace")

        raw_packet, buffer = buffer.split("\r\n\r\n", 1)
        packet: dict[str, str] = {}
        for line in raw_packet.split("\r\n"):
            if not line:
                continue
            if ":" not in line:
                packet.setdefault("Banner", line)
                continue
            key, value = line.split(":", 1)
            key = key.strip()
            value = value.strip()
            if key in packet:
                packet[key] = f"{packet[key]}\n{value}"
            else:
                packet[key] = value
        return buffer, packet

    def _send_action(self, sock: socket.socket, fields: dict[str, str]) -> None:
        payload = "".join(f"{key}: {value}\r\n" for key, value in fields.items())
        sock.sendall(f"{payload}\r\n".encode("utf-8"))

    def _ensure_success(self, response: dict[str, str], message: str) -> None:
        if response.get("Response", "").lower() not in {"success", "follows"}:
            detail = response.get("Message") or response.get("Response") or "unknown AMI error"
            raise AmiError(f"{message}: {detail}")


def build_originate_preview(destination: str) -> dict[str, str]:
    return {
        "action": "Originate",
        "channel": f"PJSIP/{destination}@outbound-trunk",
        "application": "Wait",
        "data": str(settings.asterisk_outbound_hold_seconds),
        "caller_id": settings.app_name,
    }
