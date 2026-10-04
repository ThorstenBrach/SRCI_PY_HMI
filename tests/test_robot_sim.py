"""The robot service against the SRCI SDK simulator (skipped without the SDK library).

The SDK is licensed and not part of this repository: build it in ``SRCI SDK/srci_py_harness``
and set ``SRCI_SDK_SIM_LIB`` (see SRCI_PY).
"""

from __future__ import annotations

import contextlib
import threading
import time
from collections.abc import Iterator

import pytest
from srci.types import JogMode

from srci_teach.model import Motion, Program
from srci_teach.robot import Activity, Phase, RobotService, Target

sdk = pytest.importorskip("srci.sim.sdk")
try:
    sdk.SdkSimulator().close()
except sdk.SdkNotAvailableError as exc:  # pragma: no cover - depends on the machine
    pytest.skip(f"SRCI SDK simulator not available: {exc}", allow_module_level=True)


@pytest.fixture
def robot() -> Iterator[RobotService]:
    r = RobotService()
    r.connect(Target(simulator=True))
    r.reset()
    yield r
    r.disconnect()


def joints(r: RobotService) -> list[float]:
    time.sleep(0.6)  # position is polled every 0.25 s
    return [round(v, 1) for v in r.snapshot().joints]


def test_connect_shows_robot_data(robot: RobotService) -> None:
    s = robot.snapshot()
    assert s.phase is Phase.READY
    assert s.srci_version.startswith("1.")
    assert s.manufacturer
    assert s.position_valid
    assert not s.enabled


def test_motion_needs_enable(robot: RobotService) -> None:
    p = Program()
    p.add_point([0.0] * 6, [0.0] * 6)
    with pytest.raises(Exception, match="switch the robot on"):
        robot.move_to(p.points[0], hold=False)
    assert robot.snapshot().error


def test_move_to_point_and_teach(robot: RobotService) -> None:
    robot.set_enabled(True)
    assert robot.snapshot().enabled
    p = Program()
    p.add_point([10.0, 20.0, 30.0, 0.0, 45.0, 0.0], [0.0] * 6)
    robot.move_to(p.points[0], hold=False)
    assert joints(robot) == [10.0, 20.0, 30.0, 0.0, 45.0, 0.0]
    j, _ = robot.current_position()
    assert round(j[4], 1) == 45.0
    robot.set_enabled(False)
    assert not robot.snapshot().enabled


def test_program_runs_all_steps_in_order(robot: RobotService) -> None:
    robot.set_enabled(True)
    p = Program()
    p.add_point([0.0] * 6, [0.0] * 6, name="A")
    p.add_point([20.0, 0, 0, 0, 0, 0], [0.0] * 6, name="B")
    for name in "BABA":
        p.add_step(name, Motion.JOINT, 50.0, 10.0 if name == "B" else 0.0)
    seen: list[int] = []
    assert robot.run_program(p, hold=False, on_step=seen.append) == 4
    assert seen == [0, 1, 2, 3]
    assert robot.run_program(p, 2, single_step=True, hold=False) == 3
    assert joints(robot)[0] == 20.0


def test_hold_to_run_stops_without_heartbeat(robot: RobotService) -> None:
    robot.set_enabled(True)
    p = Program()
    p.add_point([90.0, 0, 0, 0, 0, 0], [0.0] * 6)
    started = time.monotonic()
    with pytest.raises(Exception, match="stopped"):
        robot.move_to(p.points[0], hold=True)  # nobody calls alive()
    assert time.monotonic() - started < 3.0
    assert robot.snapshot().activity is Activity.IDLE


def test_stop_ends_a_running_program(robot: RobotService) -> None:
    robot.set_enabled(True)
    p = Program()
    p.add_point([0.0] * 6, [0.0] * 6, name="A")
    p.add_point([30.0, 0, 0, 0, 0, 0], [0.0] * 6, name="B")
    for name in "BABABA":
        p.add_step(name)
    errors: list[BaseException] = []

    def run() -> None:
        try:
            robot.run_program(p, hold=False)
        except BaseException as exc:
            errors.append(exc)

    worker = threading.Thread(target=run)
    worker.start()
    time.sleep(1.5)
    robot.stop()
    worker.join(10.0)
    assert not worker.is_alive()
    assert errors and "stopped" in str(errors[0])
    assert robot.snapshot().program_step < 5


def test_jog_moves_while_held_and_watchdog_stops(robot: RobotService) -> None:
    robot.set_enabled(True)
    before = joints(robot)[0]
    robot.jog_press(JogMode.JOG_AXES, 0, +1, 50.0)
    for _ in range(8):
        robot.alive()
        time.sleep(0.1)
    robot.release()
    after = joints(robot)[0]
    assert after > before
    robot.jog_press(JogMode.JOG_AXES, 0, +1, 50.0)
    time.sleep(1.2)  # no heartbeat
    assert robot.snapshot().activity is Activity.IDLE
    stopped = joints(robot)[0]
    assert joints(robot)[0] == stopped


def test_motion_after_stop_reset_and_jog(robot: RobotService) -> None:
    """After GroupStop + GroupReset and after a jog the next motion runs (SRCI_PY F76, harness)."""
    robot.set_enabled(True)
    p = Program()
    p.add_point([0.0] * 6, [0.0] * 6, name="A")
    p.add_point([40.0, 0, 0, 0, 0, 0], [0.0] * 6, name="B")
    worker = threading.Thread(target=lambda: _quiet(robot.move_to, p.point("B"), hold=False))
    worker.start()
    time.sleep(0.4)
    robot.stop()
    worker.join(10.0)
    robot.reset()
    robot.move_to(p.point("A"), hold=False)
    robot.jog_press(JogMode.JOG_AXES, 1, +1, 50.0)
    for _ in range(5):
        robot.alive()
        time.sleep(0.1)
    robot.release()
    robot.move_to(p.point("B"), hold=False)
    assert joints(robot)[:2] == [40.0, 0.0]


def _quiet(fn: object, *args: object, **kwargs: object) -> None:
    with contextlib.suppress(Exception):
        fn(*args, **kwargs)  # type: ignore[operator]


def test_tools_and_frames(robot: RobotService) -> None:
    from srci_teach.robot import CoordData

    s = robot.snapshot()
    assert s.highest_tool >= 1 and s.highest_frame >= 1
    robot.write_tool(CoordData(1, [0.0, 0.0, 150.0, 0.0, 0.0, 0.0], load_no=1))
    robot.write_frame(CoordData(1, [500.0, 0.0, 0.0, 0.0, 0.0, 90.0]))
    assert robot.read_tools()[1].values[2] == 150.0
    assert robot.read_frames()[1].values == [500.0, 0.0, 0.0, 0.0, 0.0, 90.0]
    with pytest.raises(ValueError):
        robot.write_tool(CoordData(0, [0.0] * 6))
    robot.set_coordinate_system(1, 1)
    assert (robot.snapshot().tool, robot.snapshot().frame) == (1, 1)


def test_all_motion_types_with_dynamics(robot: RobotService) -> None:
    robot.set_enabled(True)
    p = Program()
    p.add_point([0.0] * 6, [0.0] * 6, name="A")
    p.add_point([20.0, 0, 0, 0, 0, 0], [20.0, 0, 0, 0, 0, 0], name="B")
    for motion in Motion:
        # the harness supports CORNER_DISTANCE and RAMP_OVERLAP (SDK default: none)
        p.add_step("B", motion, 50.0, 5.0, blending_mode="CORNER_DISTANCE", acceleration=50.0)
        p.add_step("A", motion, 50.0, 50.0, blending_mode="RAMP_OVERLAP")
        p.add_step("B", motion, -1.0)
    assert robot.run_program(p, hold=False) == 9
    assert joints(robot)[0] == 20.0


def test_functions_the_rc_does_not_report_are_refused(robot: RobotService) -> None:
    """RCSupportedFunctions: a motion type / jog the RC does not report is not sent at all."""
    from srci_teach.robot import NotSupportedError

    s = robot.snapshot()
    assert s.supported is not None and s.can("MoveDirectAbsolute")
    robot.set_enabled(True)
    reported = s.supported - {"MoveDirectAbsolute", "GroupJog"}
    robot.supported = lambda: reported  # type: ignore[method-assign]  # an RC without them
    assert not robot.snapshot().can("MoveDirectAbsolute")
    p = Program()
    p.add_point([10.0, 0, 0, 0, 0, 0], [10.0, 0, 0, 0, 0, 0])
    p.add_step("P1", Motion.JOINT)
    p.add_step("P1", Motion.PTP)
    with pytest.raises(NotSupportedError, match="MoveDirectAbsolute"):
        robot.run_program(p, hold=False)
    assert joints(robot)[0] == 0.0  # not even the first (supported) step was started
    with pytest.raises(NotSupportedError, match="GroupJog"):
        robot.jog_press(JogMode.JOG_AXES, 0, 1, 10.0)
    assert robot.run_program(p, 0, single_step=True, hold=False) == 1


def test_enable_acknowledges_a_pending_error(robot: RobotService) -> None:
    """EnableRobot is refused while the RC has an error (16#8C04) - set_enabled resets first."""
    from srci.fb import MC_GroupResetFB

    calls: list[str] = []
    original = robot.client.execute

    def spy(block, *args, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(type(block).__name__)
        return original(block, *args, **kwargs)

    robot.client.execute = spy  # type: ignore[method-assign]
    robot.set_enabled(True)
    assert calls[0] == MC_GroupResetFB.__name__
    assert robot.snapshot().enabled


def test_blending_modes_accepted_and_refused_are_remembered(robot: RobotService) -> None:
    """The RC reports its blending modes nowhere: the service records 16#8E05 and accepted modes."""
    robot.set_enabled(True)
    p = Program()
    p.add_point([0.0] * 6, [0.0] * 6, name="A")
    p.add_point([10.0, 0, 0, 0, 0, 0], [10.0, 0, 0, 0, 0, 0], name="B")
    p.add_step("B", Motion.LINEAR, 50.0, 5.0, blending_mode="MAX_CORNER_DEVIATION")
    p.add_step("A", Motion.LINEAR)
    robot.run_program(p, hold=False)
    assert robot.blending_results == {"MAX_CORNER_DEVIATION": True}
    q = Program()
    q.points = p.points
    q.add_step("B", Motion.JOINT, 50.0, 5.0, blending_mode="CORNER_DISTANCE_2R", blending_post=5.0)
    q.add_step("A", Motion.JOINT)
    with pytest.raises(Exception, match="8E05"):
        robot.run_program(q, hold=False)
    assert robot.blending_results["CORNER_DISTANCE_2R"] is False
    assert Target().lifesign_ms == 500  # JAKA: no LifeSign for ~200 ms after a rejected command
