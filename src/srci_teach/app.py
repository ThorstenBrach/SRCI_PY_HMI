"""Start the teach pendant: ``srci-teach`` (or ``python -m srci_teach``)."""

from __future__ import annotations

import argparse
import contextlib
import logging
import secrets
from pathlib import Path

from srci_teach.i18n import t
from srci_teach.model import Program
from srci_teach.robot import RobotService, Target

log = logging.getLogger("srci_teach")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="srci-teach", description="Teach pendant for SRCI robots (web UI)")
    p.add_argument("--host", default="127.0.0.1",
                   help="address of the web server (0.0.0.0: reachable from a tablet in the network - "
                        "everybody who reaches the port can move the robot)")  # fmt: skip
    p.add_argument("--port", type=int, default=8080, help="port of the web server")
    p.add_argument("--programs", type=Path, default=Path("programs"), help="folder for the programs (JSON)")
    p.add_argument("--robot", default="192.168.2.10", help="IP address of the PLC gateway")
    p.add_argument("--robot-port", type=int, default=5000, help="TCP port of the PLC gateway")
    p.add_argument("--length", type=int, default=256, help="telegram length per direction [bytes]")
    p.add_argument("--simulator", action="store_true", help="preselect the SDK simulator")
    p.add_argument("--native", action="store_true", help="own window instead of the browser (pywebview)")
    p.add_argument("--log", type=Path, default=None, help="log file")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s %(message)s",
        filename=args.log,
    )
    if args.log:
        # system log of all function blocks (commands, responses, errors) and of the transport
        logging.getLogger("srci").setLevel(logging.DEBUG)
    from nicegui import app, ui

    from srci_teach.ui.pendant import Pendant, Workspace

    robot = RobotService(plc_log=args.log is not None)
    ws = Workspace(
        robot=robot,
        programs_dir=args.programs.resolve(),
        program=Program(t("prog.default")),
        target=Target(host=args.robot, port=args.robot_port, length=args.length, simulator=args.simulator),
    )

    @ui.page("/")
    def index() -> None:
        Pendant(ws).build()

    app.on_shutdown(robot.disconnect)
    secret_file = Path.home() / ".srci_teach_secret"
    try:
        secret = secret_file.read_text().strip()
    except OSError:
        secret = secrets.token_hex(16)
        with contextlib.suppress(OSError):
            secret_file.write_text(secret)
    ui.run(
        host=args.host,
        port=args.port,
        title="SRCI Teach",
        favicon="🦾",
        storage_secret=secret,
        reload=False,
        show=False,
        native=args.native,
        reconnect_timeout=2.0,
    )


if __name__ in {"__main__", "__mp_main__"}:
    main()
