import json
import socket
import threading
import time
from typing import Any, Dict, List, Optional


class DAMXClient:
    """Python API client for communicating with the DAMX Daemon over a Unix domain socket."""

    def __init__(self, socket_path: str = "/var/run/DAMX.sock"):
        self.socket_path = socket_path
        self._socket: Optional[socket.socket] = None
        self.is_connected: bool = False
        self._available_features: set[str] = set()

        # Lock to ensure thread safety when sending/receiving data concurrently
        self._lock = threading.Lock()

        self.max_retry_attempts = 3
        self.retry_delay_seconds = 0.5

    def connect(self) -> bool:
        """Connects to the DAMX daemon Unix socket and fetches supported features."""
        if self.is_connected and self.validate_connection():
            return True

        self._reset_connection()

        try:
            self._socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self._socket.connect(self.socket_path)
            self.is_connected = True

            # Populate feature cache upon connection
            self.refresh_available_features()
            return True
        except (OSError, Exception) as ex:
            print(f"Failed to connect to daemon: {ex}")
            self.is_connected = False
            return False

    def validate_connection(self) -> bool:
        """Validates connection status by sending a ping command."""
        if not self.is_connected:
            return False
        try:
            response = self.send_command("ping")
            return response.get("success", False)
        except Exception:
            self.is_connected = False
            return False

    def is_feature_available(self, feature_name: str) -> bool:
        """Checks if a feature is supported on the current device."""
        return feature_name in self._available_features

    def send_command(
        self, command: str, parameters: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Sends a JSON command to the daemon with automatic retry logic on network drops."""
        attempt = 0

        while attempt < self.max_retry_attempts:
            if not self.is_connected:
                self.connect()
                if not self.is_connected:
                    raise ConnectionError("Not connected to DAMX daemon")

            with self._lock:
                try:
                    payload = {
                        "command": command,
                        "params": parameters if parameters is not None else {},
                    }

                    # Serialize and send
                    request_json = json.dumps(payload)
                    self._socket.sendall(request_json.encode("utf-8"))

                    # Receive response buffer
                    response_data = self._socket.recv(4096)
                    if not response_data:
                        self._reset_connection()
                        attempt += 1
                        time.sleep(self.retry_delay_seconds)
                        continue

                    # Parse response
                    response_str = response_data.decode("utf-8")
                    return json.loads(response_str)

                except (socket.error, json.JSONDecodeError) as ex:
                    print(f"Communication/Parse error (Attempt {attempt + 1}): {ex}")
                    self._reset_connection()
                    attempt += 1
                    time.sleep(self.retry_delay_seconds)
                except Exception as ex:
                    print(f"Error communicating with daemon: {ex}")
                    raise ex

        raise IOError(
            f"Failed to communicate with daemon after {self.max_retry_attempts} attempts."
        )

    def refresh_available_features(self) -> None:
        """Refreshes available daemon features cache."""
        try:
            response = self.send_command("get_supported_features")
            if response.get("success"):
                features = response.get("data", {}).get("available_features", [])
                self._available_features = set(features)
                print(f"Available features: {', '.join(self._available_features)}")
        except Exception as ex:
            print(f"Failed to get available features: {ex}")

    def get_all_settings(self) -> Dict[str, Any]:
        """Gets all settings and updates available features."""
        response = self.send_command("get_all_settings")
        if response.get("success"):
            data = response.get("data", {})
            if "available_features" in data:
                self._available_features = set(data["available_features"])
            return data

        error_msg = response.get("error", "Unknown error")
        raise RuntimeError(f"Failed to get settings: {error_msg}")

    # --- Feature Specific Helper Methods ---

    def set_thermal_profile(self, profile: str) -> bool:
        if not self.is_feature_available("thermal_profile"):
            print("Thermal profile feature is not available on this device")
            return False
        response = self.send_command("set_thermal_profile", {"profile": profile})
        return response.get("success", False)

    def set_fan_speed(self, cpu: int, gpu: int) -> bool:
        if not self.is_feature_available("fan_speed"):
            print("Fan speed control is not available on this device")
            return False
        response = self.send_command("set_fan_speed", {"cpu": cpu, "gpu": gpu})
        return response.get("success", False)

    def set_battery_limiter(self, enabled: bool) -> bool:
        if not self.is_feature_available("battery_limiter"):
            print("Battery limiter feature is not available on this device")
            return False
        response = self.send_command("set_battery_limiter", {"enabled": enabled})
        return response.get("success", False)

    def disconnect(self) -> None:
        """Closes the socket connection gracefully."""
        self._reset_connection()

    def _reset_connection(self) -> None:
        """Internal helper to clean up closed or broken sockets."""
        self.is_connected = False
        if self._socket:
            try:
                self._socket.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            try:
                self._socket.close()
            except Exception:
                pass
            self._socket = None

    def __enter__(self):
        """Allows context manager support (`with DAMXClient() as client:`)."""
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()
