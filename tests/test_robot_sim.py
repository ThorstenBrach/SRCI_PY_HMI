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

from srci_py_hmi.model import Motion, Program
from srci_py_hmi.robot import Activity, Phase, RobotService, Target

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
    from srci_py_hmi.robot import CoordData

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
    for motion in (Motion.LINEAR, Motion.PTP, Motion.JOINT):
        # the harness supports CORNER_DISTANCE and RAMP_OVERLAP (SDK default: none)
        p.add_step("B", motion, 50.0, 5.0, blending_mode="CORNER_DISTANCE", acceleration=50.0)
        p.add_step("A", motion, 50.0, 50.0, blending_mode="RAMP_OVERLAP")
        p.add_step("B", motion, -1.0)
    assert robot.run_program(p, hold=False) == 9
    assert joints(robot)[0] == 20.0


def test_functions_the_rc_does_not_report_are_refused(robot: RobotService) -> None:
    """RCSupportedFunctions: a motion type / jog the RC does not report is not sent at all."""
    from srci_py_hmi.robot import NotSupportedError

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


def _background(fn: object, *args: object, **kwargs: object) -> tuple[threading.Thread, list[object]]:
    """Run ``fn`` in a thread; the list gets its result or exception."""
    out: list[object] = []

    def run() -> None:
        try:
            out.append(fn(*args, **kwargs))  # type: ignore[operator]
        except BaseException as exc:
            out.append(exc)

    worker = threading.Thread(target=run)
    worker.start()
    return worker, out


def test_program_with_all_step_kinds(robot: RobotService) -> None:
    from srci_py_hmi.model import Step, StepKind

    robot.set_enabled(True)
    p = Program()
    p.add_point([0.0] * 6, [0.0] * 6, name="A")
    p.add_point([20.0, 0, 0, 0, 0, 0], [20.0, 0, 0, 0, 0, 0], name="B")
    p.add_step("B")
    p.insert_step(Step("B", Motion.CIRC, via="A"))
    p.insert_step(Step("", Motion.JOINT, kind=StepKind.RELATIVE, offset=[5.0, 0, 0, 0, 0, 0]))
    p.insert_step(Step("", Motion.LINEAR, kind=StepKind.RELATIVE, offset=[0, 0, 10.0, 0, 0, 0]))
    p.insert_step(Step("", kind=StepKind.WAIT, duration=0.3))
    p.insert_step(Step("", kind=StepKind.OUTPUT, signal=9, value=True))
    p.insert_step(Step("", kind=StepKind.WAIT_INPUT, signal=2, value=False, timeout=2.0))  # inputs of the sim: 0
    p.insert_step(Step("", kind=StepKind.SUBPROGRAM, job=1))
    p.insert_step(Step("", kind=StepKind.WAIT, duration=60.0, enabled=False))  # skipped
    p.add_step("A")
    seen: list[int] = []
    started = time.monotonic()
    assert robot.run_program(p, hold=False, on_step=seen.append) == len(p.steps)
    assert time.monotonic() - started < 30.0
    assert 8 not in seen and seen[-1] == 9


def test_wait_for_input_times_out_and_stop_ends_a_wait(robot: RobotService) -> None:
    from srci_py_hmi.model import Step, StepKind

    robot.set_enabled(True)
    p = Program()
    p.insert_step(Step("", kind=StepKind.WAIT_INPUT, signal=2, value=True, timeout=0.5))
    with pytest.raises(Exception, match="DI 2"):
        robot.run_program(p, hold=False)
    q = Program()
    q.insert_step(Step("", kind=StepKind.WAIT, duration=30.0))
    worker, out = _background(robot.run_program, q, hold=False)
    time.sleep(0.5)
    robot.stop()
    worker.join(5.0)
    assert not worker.is_alive() and "stopped" in str(out[0])


def test_stop_point_waits_for_continue(robot: RobotService) -> None:
    from srci_py_hmi.model import Step, StepKind

    robot.set_enabled(True)
    p = Program()
    p.add_point([10.0, 0, 0, 0, 0, 0], [0.0] * 6)
    p.insert_step(Step("", kind=StepKind.HALT))
    p.add_step("P1")
    worker, out = _background(robot.run_program, p, hold=False)
    time.sleep(0.8)
    assert robot.snapshot().halted and worker.is_alive()
    robot.resume()
    worker.join(10.0)
    assert out == [2] and not robot.snapshot().halted
    assert joints(robot)[0] == 10.0


def test_interrupt_and_continue_a_program(robot: RobotService) -> None:
    robot.set_enabled(True)
    p = Program()
    p.add_point([40.0, 0, 0, 0, 0, 0], [0.0] * 6)
    p.add_step("P1", velocity=5.0)
    worker, out = _background(robot.run_program, p, hold=False)
    time.sleep(0.4)
    robot.interrupt()
    time.sleep(0.5)
    assert robot.snapshot().interrupted and worker.is_alive()
    robot.resume()
    worker.join(30.0)
    assert out == [1]


def test_io_and_registers(robot: RobotService) -> None:
    assert len(robot.read_io(0)) == 5 and len(robot.read_io(10, outputs=True)) == 5
    robot.write_output(9, True)
    robot.write_registers(False, 0, [1, 2, 3, 4, 5, 6, 7])
    robot.write_registers(True, 7, [0.5] * 7)
    assert len(robot.read_registers(False, 0)) == 7
    with pytest.raises(ValueError):
        robot.write_registers(False, 0, [1, 2])
    with pytest.raises(ValueError):
        robot.read_io(300)


def test_loads_dynamics_limits_and_dh(robot: RobotService) -> None:
    from srci_py_hmi.robot import LoadInfo

    loads = robot.read_loads()
    assert loads and loads[0].no == 1
    robot.write_load(LoadInfo(1, [0.0, 0.0, 50.0, 0.0, 0.0, 0.0], 2.5, [0.01, 0.01, 0.02]))
    with pytest.raises(ValueError):
        robot.write_load(LoadInfo(0, [0.0] * 6, 1.0))
    d = robot.read_dynamics()
    assert len(d.default) == 4 and d.reference[0] > 0
    robot.write_default_dynamics([50.0, 50.0, 50.0, 50.0])
    robot.write_reference_dynamics(d.reference)
    limits = robot.read_sw_limits()
    assert len(limits) == 6 and all(lo < hi for lo, hi in limits)
    assert robot.write_sw_limits(limits) in (True, False)
    with pytest.raises(ValueError):
        robot.write_sw_limits([(10.0, -10.0)] * 6)
    assert set(robot.read_dh()) == {"alpha", "a", "d", "theta", "direction", "zero"}


def test_system_variables_and_calculations(robot: RobotService) -> None:
    from srci.types import FrameCalculationMode, ToolCalculationMode, TransformMode

    from srci_py_hmi import sysvars

    values = robot.read_system_variable(15, list(range(1, 13)))  # 12 sub-parameters: two commands
    assert [v.sub for v in values] == list(range(1, 13))
    robot.write_system_variable(32, [sysvars.Value.encode(1, sysvars.UINT, 500)])
    assert len(robot.forward_kinematics([0.0, 30.0, 60.0, 0.0, 90.0, 0.0], 0, 0)) == 6
    assert len(robot.inverse_kinematics([300.0, 0.0, 300.0, 180.0, 0.0, 0.0], 0, 0)) == 6
    tips = [[100.0, 0, 0, 0, 0, 0], [0, 100.0, 0, 0, 0, 0], [-100.0, 0, 0, 0, 0, 0]]
    assert len(robot.calculate_tool(ToolCalculationMode.THREE_POINT_METHOD, tips, 1).values) == 6
    frame = robot.calculate_frame(FrameCalculationMode.THREE_POINT_METHOD, 1, 0,
                                  {"Origin": tips[0], "Position_X": tips[1], "Position_XY": tips[2]})  # fmt: skip
    assert len(frame) == 6
    assert len(robot.shift_position(TransformMode.SHIFT_BY_VECTOR, [0.0] * 6, 0, [10.0, 0, 0, 0, 0, 0])) == 6


def test_operation_mode_and_hand_guiding(robot: RobotService) -> None:
    from srci.types import OperationMode

    robot.set_operation_mode(OperationMode.T1_EXT)
    with pytest.raises(ValueError):
        robot.set_operation_mode(OperationMode.T1_LOCAL)
    robot.set_enabled(True)
    robot.free_drive_press()
    assert robot.snapshot().activity is Activity.FREE_DRIVE
    time.sleep(3.5)  # no heartbeat: the watchdog ends the hand guiding (the sim needs ~2 s to disable)
    assert robot.snapshot().activity is Activity.IDLE
