"""The page in a simulated browser (``nicegui.testing.user_simulation``) against the SDK simulator.

Connect, switch the robot on, teach a point and append it as a step - the way a user does it.
Skipped without the SDK library (see tests/test_robot_sim.py).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from pathlib import Path

import pytest

pytest.importorskip("nicegui")
sdk = pytest.importorskip("srci.sim.sdk")
try:
    sdk.SdkSimulator().close()
except sdk.SdkNotAvailableError as exc:  # pragma: no cover - depends on the machine
    pytest.skip(f"SRCI SDK simulator not available: {exc}", allow_module_level=True)

from nicegui import background_tasks, ui  # noqa: E402
from nicegui.testing import User, user_simulation  # noqa: E402

from srci_py_hmi.model import Program  # noqa: E402
from srci_py_hmi.robot import Phase, RobotService, Target  # noqa: E402
from srci_py_hmi.ui.pendant import Pendant, Workspace  # noqa: E402


async def wait_for(condition: Callable[[], bool], timeout: float = 10.0) -> None:
    end = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > end:
            raise AssertionError("condition not reached")
        await asyncio.sleep(0.05)


def press(button: ui.button) -> None:
    """pointerdown on a jog key, as the browser sends it when the key is pressed."""
    for listener in button._event_listeners.values():
        if listener.type == "pointerdown":
            result = listener.handler(None)
            if asyncio.iscoroutine(result):
                background_tasks.create(result)


async def scenario(ws: Workspace) -> None:
    async with user_simulation(lambda: Pendant(ws).build()) as user:
        await run_user(user, ws)


async def run_user(user: User, ws: Workspace) -> None:
    await user.open("/")
    await user.should_see("Roboter verbinden")
    user.find(kind=ui.button, content="Verbinden").click()
    await wait_for(lambda: ws.robot.snapshot().phase is Phase.READY)
    await user.should_see("SRCI_PY SimRobot")
    user.find(kind=ui.switch).click()  # robot on
    await wait_for(lambda: ws.robot.snapshot().enabled)
    user.find(kind=ui.button, content="Bewegen").click()
    user.find(kind=ui.button, content="Punkt teachen").click()
    await wait_for(lambda: len(ws.program.points) == 1)
    assert ws.program.points[0].name == "P1"
    assert ws.dirty
    user.find(kind=ui.button, content="Programm").click()
    await user.should_see(marker="add-step-P1")  # the list is redrawn by the UI timer
    user.find(marker="add-step-P1").click()
    await wait_for(lambda: len(ws.program.steps) == 1)
    await user.should_see(marker="step-0")  # the list is redrawn by the UI timer
    # step editor: LIN, blended (corner distance 10 mm), velocity 50 %
    user.find(marker="step-0").click()
    await user.should_see(marker="step-apply")
    user.find(marker="motion-toggle").elements.pop().set_value("linear")
    user.find(marker="blend-toggle").elements.pop().set_value(True)
    user.find(marker="step-apply").click()
    await wait_for(lambda: ws.program.steps[0].motion.value == "linear")
    step = ws.program.steps[0]
    assert step.blending_mode == "CORNER_DISTANCE" and step.blending == 10.0
    await user.should_see("LIN ⤳")
    # tool 1 on the robot
    user.find(kind=ui.button, content="Werkzeuge").click()
    await wait_for(lambda: len(ws.tools) > 1, 20.0)  # read in the background after connecting
    await user.should_see(marker="edit-tool-1")
    user.find(marker="edit-tool-1").click()
    await user.should_see(marker="coord-write")
    numbers = [n for n in user.find(kind=ui.number).elements if n.props.get("label") == "Z"]
    max(numbers, key=lambda n: n.id).set_value(150.0)  # the one in the dialog (created last)
    user.find(marker="coord-write").click()
    await wait_for(lambda: len(ws.tools) > 1 and ws.tools[1].values[2] == 150.0)
    # measure tool 1: the dialog has its own jog keys - the robot moves without closing it
    user.find(marker="cal-tool-1").click()
    await user.should_see(marker="cal-take-tip1")
    keys = sorted((b for b in user.find(kind=ui.button).elements if "tp-key-btn" in b.classes), key=lambda b: b.id)
    assert len(keys) == 24  # 12 on the jog page, 12 in the dialog (created later)
    before = ws.robot.snapshot().joints[0]
    press(keys[12 + 1])  # J1 + in the dialog
    for _ in range(10):  # held for 1 s: the heartbeat of the browser
        ws.robot.alive()
        await asyncio.sleep(0.1)
    ws.robot.release()
    # tool and frame are chosen in the dialog as well (active coordinate system of the robot service)
    user.find(marker="pad-tool").elements.pop().set_value(1)
    user.find(marker="pad-frame").elements.pop().set_value(1)
    await wait_for(lambda: (ws.robot.tool, ws.robot.frame) == (1, 1))
    await wait_for(lambda: ws.robot.snapshot().joints[0] > before + 0.1)
    user.find(kind=ui.button, content="Abbrechen").click()
    # an RC without CalculateTool (profile Core, e.g. JAKA MiniCobo): the HMI calculates itself
    reported = ws.robot.supported() or frozenset()
    ws.robot.supported = lambda: reported - {"CalculateTool", "CalculateFrame"}  # type: ignore[method-assign]
    await asyncio.sleep(0.5)  # the tool list is redrawn without the functions
    user.find(marker="cal-tool-1").click()
    await user.should_see("die HMI berechnet das Ergebnis selbst")
    await user.should_see(marker="pad-tool")
    user.find(kind=ui.button, content="Abbrechen").click()
    # an RC that can neither jog nor guide by hand: the dialog shows no jog keys
    ws.robot.supported = lambda: reported - {"CalculateTool", "CalculateFrame", "GroupJog", "FreeDrive"}  # type: ignore[method-assign]
    await asyncio.sleep(0.5)
    user.find(marker="cal-tool-1").click()
    await user.should_see(marker="cal-take-tip1")
    await asyncio.sleep(0.3)  # the timer of the page hides the pad
    await user.should_not_see(marker="pad-tool")
    # reload (as the language switch does) with T1 / F1 active: the selects must offer them
    await user.open("/")
    await user.should_see("Koordinatensystem")


def test_connect_teach_and_append_step(tmp_path: Path) -> None:
    ws = Workspace(robot=RobotService(), programs_dir=tmp_path, program=Program("Test"),
                   target=Target(simulator=True))  # fmt: skip
    try:
        asyncio.run(scenario(ws))
    finally:
        ws.robot.disconnect()
