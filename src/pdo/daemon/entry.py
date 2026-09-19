"""Internal foreground entry point for detached daemon subprocesses."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from pdo.config import load_config
from pdo.daemon.server import DaemonServer
from pdo.daemon.startup import notify_launcher


def main(arguments: list[str] | None = None) -> int:
    """Run the daemon in a subprocess started by the client launcher.

    Args:
        arguments: Command-line arguments, or ``sys.argv[1:]`` by default.

    Returns:
        Exit status after the daemon stops.
    """
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--daemon-process", action="store_true")
    parser.add_argument("--daemon-config", required=True)
    parser.add_argument("--daemon-data-dir", required=True)
    parser.add_argument("--daemon-log-dir", required=True)
    parser.add_argument("--ready-port", type=int)
    parser.add_argument("--ready-token")
    options = parser.parse_args(arguments)
    try:
        config = load_config(
            config_file=Path(options.daemon_config),
            overrides={
                "data_dir": options.daemon_data_dir,
                "log_dir": options.daemon_log_dir,
            },
        )
        DaemonServer(config).start(
            on_ready=lambda: notify_launcher(options.ready_port, options.ready_token)
        )
    except Exception as exc:
        notify_launcher(options.ready_port, options.ready_token, error=str(exc))
        raise
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
