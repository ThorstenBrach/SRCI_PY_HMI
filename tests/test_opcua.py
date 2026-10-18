"""Connection over OPC UA: target settings, robot service and the configurator of the connection page.

The robot controller is ``srci.sim.opcua.OpcUaRcSimulator`` (asyncua server on localhost); with the
SDK library it answers with the SDK simulator, else with a fixed telegram (browse / pick only).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from srci_py_hmi.robot import OPCUA, SIMULATOR, TCP, Phase, RobotService, Target


def test_target_kind_and_settings() -> None:
    """kind switches simulator / transport; the OPC UA settings are kept without the password."""
    t = Target()
    assert (t.kind, t.describe()) == (TCP, "192.168.2.10:5000")
    t.kind = OPCUA
    assert (t.simulator, t.transport, t.describe()) == (False, OPCUA, "opc.tcp://192.168.2.10:4840")
    t.kind = SIMULATOR
    assert (t.simulator, t.transport, t.describe()) == (True, OPCUA, "SDK simulator")
    t.kind = TCP
    assert (t.simulator, t.transport) == (False, TCP)
    t.opcua_out, t.opcua_in, t.opcua_user, t.opcua_password = "ns=2;s=o", "ns=2;s=i", "robot", "secret"
    stored = t.opcua_settings()
    assert "secret" not in stored.values()
    other = Target()
    other.restore_opcua({**stored, "transport": OPCUA})
    assert (other.opcua_out, other.opcua_in, other.opcua_user, other.transport) == ("ns=2;s=o", "ns=2;s=i", "robot", OPCUA)
    other.restore_opcua(None)  # nothing stored yet
    other.restore_opcua({"out": 5, "transport": "x"})  # damaged storage is ignored
    assert (other.opcua_out, other.transport) == ("ns=2;s=o", OPCUA)


def test_opcua_without_nodes_fails() -> None:
    """Connect without telegram nodes: error, phase FAILED."""
    robot = RobotService()
    with pytest.raises(ValueError, match="NodeId"):
        robot.connect(Target(transport=OPCUA))
    assert robot.snapshot().phase is Phase.FAILED
    robot.disconnect()


# ---------------------------------------------------------------------- with a local OPC UA server

SIZE = 256


def _sdk() -> object | None:
    try:
        from srci_py_hmi.robot import sdk_simulator_class

        sim = sdk_simulator_class()()
    except Exception:
        return None
    sim.set_move_cycles(100)
    return sim


@pytest.fixture
def rc() -> Iterator[object]:
    pytest.importorskip("asyncua")
    from srci.sim.opcua import OpcUaRcSimulator

    sim = _sdk()
    handler: Callable[[bytes], bytes] = (
        (lambda telegram: sim.exchange(telegram, SIZE)) if sim is not None else (lambda telegram: bytes(SIZE))  # type: ignore[attr-defined]
    )
    server = OpcUaRcSimulator(handler, SIZE, SIZE).start()
    server.sdk = sim  # type: ignore[attr-defined]
    try:
        yield server
    finally:
        server.stop()
        if sim is not None:
            sim.close()  # type: ignore[attr-defined]


def test_connect_over_opcua(rc: object) -> None:
    """RobotService over OPC UA against the SDK simulator: initialized, robot data, power on."""
    if rc.sdk is None:  # type: ignore[attr-defined]
        pytest.skip("SRCI SDK simulator not available")
    robot = RobotService()
    target = Target(transport=OPCUA, opcua_endpoint=rc.endpoint, opcua_out=rc.out_node, opcua_in=rc.in_node,  # type: ignore[attr-defined]
                    length=SIZE)  # fmt: skip
    try:
        robot.connect(target)
        s = robot.snapshot()
        assert s.phase is Phase.READY
        assert s.target == rc.endpoint  # type: ignore[attr-defined]
        robot.set_enabled(True)
        deadline = time.monotonic() + 5
        while not robot.snapshot().enabled:
            assert time.monotonic() < deadline
            time.sleep(0.05)
    finally:
        robot.disconnect()


def test_configurator_browses_and_takes_the_nodes(rc: object, tmp_path: Path) -> None:
    """Connection page: OPC UA, browse the server, take both telegram nodes (and the length)."""
    pytest.importorskip("nicegui")
    from nicegui import ui
    from nicegui.testing import User, user_simulation

    from srci_py_hmi.model import Program
    from srci_py_hmi.ui.pendant import Pendant, Workspace

    target = Target(opcua_endpoint=rc.endpoint, length=64)  # type: ignore[attr-defined]
    ws = Workspace(robot=RobotService(), programs_dir=tmp_path, program=Program("Test"), target=target)

    async def wait_for(condition: Callable[[], bool], timeout: float = 10.0) -> None:
        end = time.monotonic() + timeout
        while not condition():
            if time.monotonic() > end:
                raise AssertionError("condition not reached")
            await asyncio.sleep(0.05)

    async def run_user(user: User) -> None:
        await user.open("/")
        await user.should_see("Roboter verbinden")
        user.find(marker="conn-kind").elements.pop().set_value(OPCUA)
        assert target.kind == OPCUA
        await user.should_see(marker="opcua-browse")
        user.find(marker="opcua-browse").click()
        out_button = f"opcua-out:{rc.out_node}"  # type: ignore[attr-defined]
        await user.should_see(marker=out_button, retries=100)
        user.find(marker=out_button).click()
        await wait_for(lambda: target.opcua_out == rc.out_node)  # type: ignore[attr-defined]
        assert target.length == SIZE  # taken from the node
        user.find(marker=f"opcua-in:{rc.in_node}").click()  # type: ignore[attr-defined]
        await wait_for(lambda: target.opcua_in == rc.in_node)  # type: ignore[attr-defined]
        user.find(marker="opcua-done").click()
        if rc.sdk is not None:  # type: ignore[attr-defined]
            user.find(kind=ui.button, content="Verbinden").click()
            await wait_for(lambda: ws.robot.snapshot().phase is Phase.READY, 20.0)

    async def scenario() -> None:
        async with user_simulation(lambda: Pendant(ws).build()) as user:
            await run_user(user)

    try:
        asyncio.run(scenario())
    finally:
        ws.robot.disconnect()
