import tempfile
import unittest
from pathlib import Path
from subprocess import CompletedProcess

from src.network.provisioning import NetworkProvisioner, ProvisioningConfig


class FakeRunner:
    def __init__(self, connected=False, connect_fails=False):
        self.connected = connected
        self.connect_fails = connect_fails
        self.hotspot_started = False
        self.commands = []

    def run(self, args, check=True, timeout=30):
        self.commands.append(args)
        joined = " ".join(args)
        if "device status" in joined:
            state = "connected" if self.connected else "disconnected"
            connection = "HomeWiFi" if self.connected else "--"
            return CompletedProcess(args, 0, f"wlan0:wifi:{state}:{connection}\n", "")
        if "connection show" in joined:
            return CompletedProcess(args, 0, "HomeWiFi:802-11-wireless\n", "")
        if "connection up" in joined:
            if not self.connect_fails:
                self.connected = True
                return CompletedProcess(args, 0, "ok", "")
            return CompletedProcess(args, 10, "", "bad password")
        if "wifi hotspot" in joined:
            self.hotspot_started = True
            self.connected = False
            return CompletedProcess(args, 0, "hotspot", "")
        if "connection down" in joined:
            self.hotspot_started = False
            return CompletedProcess(args, 0, "down", "")
        if "wifi connect" in joined:
            if self.connect_fails:
                return CompletedProcess(args, 10, "", "bad password")
            self.connected = True
            return CompletedProcess(args, 0, "connected", "")
        if "wifi list" in joined:
            return CompletedProcess(args, 0, "HomeWiFi:80:WPA2\nGuest:20:--\n", "")
        return CompletedProcess(args, 0, "", "")


class WifiProvisioningTest(unittest.TestCase):
    def _config(self, tmp_dir):
        base = Path(tmp_dir)
        return ProvisioningConfig(
            interface="wlan0",
            ap_password="setup-password",
            state_dir=base / "state",
            status_path=base / "network_status.json",
            setup_trigger_path=base / "wifi_setup_mode",
            portal_port=8080,
        )

    def test_known_wifi_with_internet_keeps_client_mode(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            runner = FakeRunner(connected=True)
            provisioner = NetworkProvisioner(
                config=self._config(tmp_dir),
                runner=runner,
                sleep=lambda _: None,
            )
            provisioner.internet_reachable = lambda: True

            status = provisioner.ensure_client_mode()

            self.assertEqual(status["mode"], "client")
            self.assertTrue(status["internet_reachable"])
            self.assertFalse(runner.hotspot_started)

    def test_no_wifi_starts_ap_on_boot(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            runner = FakeRunner(connected=False, connect_fails=True)
            provisioner = NetworkProvisioner(
                config=self._config(tmp_dir),
                runner=runner,
                sleep=lambda _: None,
            )
            provisioner.internet_reachable = lambda: False

            mode = provisioner.run_boot_flow()

            self.assertEqual(mode, "ap")
            self.assertTrue(runner.hotspot_started)

    def test_wrong_password_returns_to_ap_mode(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            runner = FakeRunner(connected=False, connect_fails=True)
            provisioner = NetworkProvisioner(
                config=self._config(tmp_dir),
                runner=runner,
                sleep=lambda _: None,
            )
            provisioner.internet_reachable = lambda: False

            status = provisioner.connect_wifi("HomeWiFi", "wrong-password")

            self.assertEqual(status["mode"], "ap")
            self.assertIn("bad password", status["last_error"])
            self.assertTrue(runner.hotspot_started)

    def test_correct_password_connects_client_mode(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            runner = FakeRunner(connected=False, connect_fails=False)
            provisioner = NetworkProvisioner(
                config=self._config(tmp_dir),
                runner=runner,
                sleep=lambda _: None,
            )
            provisioner.internet_reachable = lambda: True

            status = provisioner.connect_wifi("HomeWiFi", "correct-password")

            self.assertEqual(status["mode"], "client")
            self.assertTrue(status["internet_reachable"])
            self.assertEqual(status["connected_ssid"], "HomeWiFi")


if __name__ == "__main__":
    unittest.main()
