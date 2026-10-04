"""Robot service: one SRCI connection, used by all browser tabs of the teach pendant.

The UI never talks to :class:`srci.api.SrciClient` directly. This service

* opens the connection (PLC gateway over TCP, or the SRCI SDK simulator for a dry run),
* runs commands one after the other (``_busy`` lock) - except :meth:`stop`, which always
  goes through at once,
* keeps the actual position up to date (``ReadActualPositionCyclic``, fallback: polling with
  ``ReadActualPosition``),
* jogs with hold-to-run: a jog key moves only while the browser keeps sending
  :meth:`jog_alive`; without it for :data:`JOG_WATCHDOG` s the jog stops (closed tab, lost
  network, crashed browser),
* runs programs (:mod:`srci_teach.model`) step by step or continuously.

All methods block (they wait for the robot) - call them from a worker thread
(``nicegui.run.io_bound``). :meth:`snapshot` is cheap and can be called from the UI timer.

SRCI is no safety interface: the emergency stop of the robot stays the only safe stop.
"""

from __future__ import annotations

import contextlib
import copy
import dataclasses
import logging
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from srci.api import CommandError, SrciClient, WaitTimeoutError
from srci.errors import SrciError
from srci.fb import (
    MC_ChangeSpeedOverrideFB,
    MC_EnableRobotFB,
    MC_GroupJogFB,
    MC_GroupResetFB,
    MC_GroupStopFB,
    MC_MoveAxesAbsoluteFB,
    MC_MoveDirectAbsoluteFB,
    MC_MoveLinearAbsoluteFB,
    MC_ReadActualPositionCyclicFB,
    MC_ReadActualPositionFB,
    MC_ReadFrameDataFB,
    MC_ReadToolDataFB,
    MC_WriteFrameDataFB,
    MC_WriteToolDataFB,
)
from srci.transport import TcpTransport
from srci.transport.base import Transport
from srci.types import (
    ArmConfigElbow,
    ArmConfigShoulder,
    ArmConfigWrist,
    BlendingMode,
    JogMode,
    MessageLevel,
    RaSequenceState,
    TurnMode,
)

from srci_teach.model import CARTESIAN, JOINTS, Motion, Point, Program, Step

log = logging.getLogger("srci_teach.robot")

# functions of the profile "Core" (spec chapter 6) - shown on the connection page
CORE_FUNCTIONS = (
    "ReadRobotData", "EnableRobot", "GroupReset", "ReadActualPosition", "ReadActualPositionCyclic",
    "ExchangeConfiguration", "SetSequence", "ChangeSpeedOverride", "ReadMessages",
    "ReadRobotReferenceDynamics", "WriteFrameData", "WriteToolData", "WriteLoadData",
    "WriteRobotReferenceDynamics", "WriteRobotDefaultDynamics", "ReadRobotDefaultDynamics",
    "ReadFrameData", "ReadToolData", "ReadLoadData", "ReadRobotSWLimits", "GroupJog",
    "MoveLinearAbsolute", "MoveDirectAbsolute", "MoveAxesAbsolute", "GroupStop", "GroupContinue",
    "GroupInterrupt", "ReturnToPrimary",
)  # fmt: skip
MOTION_FUNCTIONS = {"joint": "MoveAxesAbsolute", "ptp": "MoveDirectAbsolute", "linear": "MoveLinearAbsolute"}

JOG_WATCHDOG = 0.5  # s without jog_alive() -> the jog stops
JOG_AXES = ("X_J1", "Y_J2", "Z_J3", "Rx_J4", "Ry_J5", "Rz_J6")


class NotSupportedError(SrciError):
    """The robot controller does not report the function in RCSupportedFunctions."""

    def __init__(self, functions: str) -> None:
        self.functions = functions
        super().__init__(f"{functions}: not supported by the robot (RCSupportedFunctions)")


class Phase(StrEnum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    READY = "ready"  # initialized, commands enabled
    LOST = "lost"  # was ready, the RobotTask is no longer initialized
    FAILED = "failed"  # connection or initialization failed


class Activity(StrEnum):
    IDLE = "idle"
    JOGGING = "jogging"
    MOVING = "moving"  # single motion (move to point)
    RUNNING = "running"  # program


@dataclass
class Target:
    """Where to connect to."""

    host: str = "192.168.2.10"
    port: int = 5000
    length: int = 256  # telegram length per direction = size of the PROFINET module
    simulator: bool = False  # SRCI SDK simulator behind a local gateway (needs SRCI_SDK_SIM_LIB)
    lifesign_ms: int = 100


@dataclass
class Message:
    severity: str
    code: int
    text: str


@dataclass
class Snapshot:
    """Everything the UI shows, read in one go."""

    phase: Phase = Phase.DISCONNECTED
    activity: Activity = Activity.IDLE
    target: str = ""
    error: str = ""  # last error of a command of this service
    enabled: bool = False
    moving: bool = False
    error_pending: bool = False
    operation_mode: str = ""
    override: float = 0.0
    joints: list[float] = field(default_factory=lambda: [0.0] * 6)
    cartesian: list[float] = field(default_factory=lambda: [0.0] * 6)
    position_valid: bool = False
    manufacturer: str = ""
    robot: str = ""
    firmware: str = ""
    srci_version: str = ""
    messages: list[Message] = field(default_factory=list)
    program_step: int = -1  # index of the running / last started step
    simulator: bool = False
    tool: int = 0  # Cartesian position (and jogging) in this tool ...
    frame: int = 0  # ... and this frame
    highest_tool: int = 0  # highest tool / frame index of the RC (ExchangeConfiguration)
    highest_frame: int = 0
    # functions the RC reports in RCSupportedFunctions (ReadRobotData); None = not known yet
    supported: frozenset[str] | None = None

    def can(self, function: str) -> bool:
        """The RC supports ``function`` (True as long as it is not known)."""
        return self.supported is None or function in self.supported


@dataclass
class CoordData:
    """A tool (TCP relative to the flange) or a frame (relative to its reference frame)."""

    no: int
    values: list[float]  # X, Y, Z [mm], Rx, Ry, Rz [deg]
    load_no: int = 0  # tool: load of the tool
    external_tcp: bool = False  # tool: stationary tool (TCP outside the robot)
    reference: int = 0  # frame: reference frame


class RobotService:
    """The connection to one robot (thread safe)."""

    def __init__(self) -> None:
        self._client: SrciClient | None = None
        self._transport: Transport | None = None
        self._stack = contextlib.ExitStack()
        self._target = Target()
        self._phase = Phase.DISCONNECTED
        self._activity = Activity.IDLE
        self._error = ""
        self._busy = threading.RLock()  # one command sequence at a time (not stop)
        self._state = threading.Lock()  # phase / activity / error
        self._poll_lock = threading.Lock()  # one ReadActualPosition at a time
        self._enable: MC_EnableRobotFB | None = None
        self._cyclic: MC_ReadActualPositionCyclicFB | None = None
        self._polled: Any = None  # OutCmd of the last ReadActualPosition (fallback)
        self._jog: MC_GroupJogFB | None = None
        self._jog_alive = 0.0  # last heartbeat of the held key (jog, move, program)
        self._hold = False  # a motion runs that needs the heartbeat (hold-to-run)
        self._stop_event = threading.Event()  # set by stop(): a running program ends
        self._program_step = -1
        self._watchdog: threading.Thread | None = None
        self._closing = threading.Event()
        self.override = 20.0
        self.tool = 0  # tool / frame of the displayed Cartesian position, of jogging and teaching
        self.frame = 0
        self.listeners: list[Callable[[], None]] = []  # called after a change of phase / activity

    # ------------------------------------------------------------------ state

    def _set(self, *, phase: Phase | None = None, activity: Activity | None = None,
             error: str | None = None) -> None:  # fmt: skip
        with self._state:
            if phase is not None:
                self._phase = phase
            if activity is not None:
                self._activity = activity
            if error is not None:
                self._error = error
        for listener in list(self.listeners):
            with contextlib.suppress(Exception):
                listener()

    @property
    def connected(self) -> bool:
        return self._client is not None and self._phase == Phase.READY

    @property
    def client(self) -> SrciClient:
        if self._client is None:
            raise SrciError("not connected")
        return self._client

    def snapshot(self) -> Snapshot:
        s = Snapshot(phase=self._phase, activity=self._activity, error=self._error,
                     program_step=self._program_step, simulator=self._target.simulator,
                     tool=self.tool, frame=self.frame)  # fmt: skip
        t = self._target
        s.target = "SDK simulator" if t.simulator else f"{t.host}:{t.port}"
        client = self._client
        if client is None:
            return s
        program = client.program
        if self._phase == Phase.READY and not program.initialized:
            self._set(phase=Phase.LOST, error="RobotTask no longer initialized (LifeSign / connection)")
            s.phase = Phase.LOST
        ag = program.axes_group
        status = ag.State.StatusRobotArm
        enable = self._enable  # EnableRobot of this service (the status bit of the RC may lag)
        s.enabled = enable is not None and bool(enable.Enabled)
        s.moving = bool(status.IsMoving)
        s.error_pending = bool(status.ErrorPending)
        s.operation_mode = status.OperationMode.name
        s.override = self.override
        data = ag.State.RobotData
        s.manufacturer = data.RCManufacturer.strip()
        s.robot = data.RobotID.strip() or data.RCOrderID.strip()
        s.firmware = data.RCFirmwareVersion.strip()
        v = ag.Cyclic.RobToPlc.SRCIVersion
        s.srci_version = f"{v.MajorVersion}.{v.MinorVersion}" if v.MajorVersion else ""
        joints, cartesian, valid = self._position()
        s.joints, s.cartesian, s.position_valid = joints, cartesian, valid
        s.highest_tool, s.highest_frame = _highest(client, "Tool"), _highest(client, "Frame")
        s.supported = self.supported()
        s.messages = [Message(m.Severity.name, int(m.MessageCode), m.MessageText)
                      for m in program.message_log if m.MessageCode][:50]  # fmt: skip
        return s

    def supported(self) -> frozenset[str] | None:
        """Functions in RCSupportedFunctions (ReadRobotData of the RobotTask); None before the
        RC has reported them."""
        client = self._client
        if client is None or not client.program.initialized:
            return None
        funcs = client.program.axes_group.State.RobotData.RCSupportedFunctions
        names = frozenset(f.name for f in dataclasses.fields(funcs) if getattr(funcs, f.name) is True)
        return names or None

    def require(self, *functions: str) -> None:
        """Raises :class:`NotSupportedError` if the RC does not report one of ``functions``."""
        known = self.supported()
        missing = [f for f in functions if known is not None and f not in known]
        if missing:
            raise NotSupportedError(", ".join(missing))

    def _position(self) -> tuple[list[float], list[float], bool]:
        cyc = self._cyclic
        if cyc is not None and not cyc.Error and cyc.OutCmd.ReadingJointPosition:
            j, c = cyc.OutCmd.JointPosition, cyc.OutCmd.CartesianPosition
            return [getattr(j, n) for n in JOINTS], [getattr(c, n) for n in CARTESIAN], True
        out = self._polled
        if out is not None:
            j, c = out.ActualJointPosition, out.ActualCartesianPosition
            return [getattr(j, n) for n in JOINTS], [getattr(c, n) for n in CARTESIAN], True
        return [0.0] * 6, [0.0] * 6, False

    # ------------------------------------------------------------------ connection

    def connect(self, target: Target) -> None:
        """Open the connection and wait until the RobotTask is initialized (raises on failure)."""
        with self._busy:
            self.disconnect()
            self._target = target
            self._closing.clear()
            self._set(phase=Phase.CONNECTING, activity=Activity.IDLE, error="")
            try:
                self._open(target)
                client = self.client
                client.wait_initialized(timeout=15.0)
                self._start_position(client)
            except BaseException as exc:
                self._set(phase=Phase.FAILED, error=_text(exc))
                self._close()
                raise
            self._set(phase=Phase.READY)
            self._watchdog = threading.Thread(target=self._watch, name="srci-teach-watchdog", daemon=True)
            self._watchdog.start()

    def _open(self, target: Target) -> None:
        n = target.length
        if target.simulator:
            from srci.sim.gateway import PlcGatewaySimulator
            from srci.sim.sdk import SdkSimulator

            sim = self._stack.enter_context(SdkSimulator())
            sim.set_move_cycles(100)  # simulated motions take about 1 s
            gateway = self._stack.enter_context(
                PlcGatewaySimulator(lambda telegram: sim.exchange(telegram, n), n, n)
            )
            transport: Transport = TcpTransport("127.0.0.1", gateway.port, n, n, response_timeout=0.5)
        else:
            # the PLC answers within a few PLC cycles; a late answer closes the connection
            transport = TcpTransport(target.host, target.port, n, n, response_timeout=0.1)
        self._transport = self._stack.enter_context(transport)
        client = SrciClient(transport)
        cfg = client.program.config
        cfg.Com.LifeSignTimeOut = target.lifesign_ms
        cfg.Rob.Parameter.MessageLevel = MessageLevel.WARNING
        self._client = client

    def _start_position(self, client: SrciClient) -> None:
        cyc = MC_ReadActualPositionCyclicFB()
        cyc.ParCmd.ReadJointPosition = True
        cyc.ParCmd.ReadCartesianPosition = True
        cyc.ParCmd.ToolNo, cyc.ParCmd.FrameNo = self.tool, self.frame
        try:
            client.enable(cyc, timeout=3.0)
            self._cyclic = cyc
        except (CommandError, WaitTimeoutError) as exc:
            log.info("ReadActualPositionCyclic not available (%s) - polling ReadActualPosition", exc)
            with contextlib.suppress(Exception):
                client.remove(cyc)
            self._cyclic = None
            self._poll_position()

    def _poll_position(self) -> None:
        client = self._client
        if client is None or self._phase not in (Phase.READY, Phase.CONNECTING):
            return
        fb = MC_ReadActualPositionFB()
        fb.ParCmd.ToolNo, fb.ParCmd.FrameNo = self.tool, self.frame
        with self._poll_lock, contextlib.suppress(CommandError, WaitTimeoutError, SrciError):
            self._polled = client.execute(fb, timeout=2.0).OutCmd

    def disconnect(self) -> None:
        """Robot off (if possible) and close the connection."""
        self._closing.set()
        self._stop_event.set()
        with self._busy:
            if self._client is not None and self._phase == Phase.READY:
                with contextlib.suppress(Exception):
                    self._jog_off()
                if self._enable is not None:
                    with contextlib.suppress(Exception):
                        self._client.disable(self._enable, timeout=3.0)
            self._close()
            self._set(phase=Phase.DISCONNECTED, activity=Activity.IDLE)

    def _close(self) -> None:
        if self._client is not None:
            with contextlib.suppress(Exception):
                self._client.close()
        with contextlib.suppress(Exception):
            self._stack.close()
        self._stack = contextlib.ExitStack()
        self._client = self._transport = None
        self._enable = self._cyclic = self._jog = None
        self._polled = None

    def _watch(self) -> None:
        """Jog watchdog and position polling (fallback without ReadActualPositionCyclic)."""
        last_poll = 0.0
        while not self._closing.wait(0.05):
            jog = self._jog
            silent = time.monotonic() - self._jog_alive > JOG_WATCHDOG
            if jog is not None and silent:
                log.warning("jog stopped: no heartbeat for %.1f s", JOG_WATCHDOG)
                with contextlib.suppress(Exception):
                    self.jog_release()
            if self._hold and silent:
                log.warning("motion stopped: key released or no heartbeat for %.1f s", JOG_WATCHDOG)
                self._hold = False
                with contextlib.suppress(Exception):
                    self.stop()
            # ReadActualPosition runs on the RC in parallel to motions and jogging: the display
            # follows the robot also while a program runs
            if self._cyclic is None and time.monotonic() - last_poll > 0.25:
                self._poll_position()
                last_poll = time.monotonic()

    # ------------------------------------------------------------------ commands

    @contextlib.contextmanager
    def _command(
        self, what: str, activity: Activity | None = None, wait: float = 5.0
    ) -> Iterator[SrciClient]:
        """Exclusive use of the client for a command sequence; waits up to ``wait`` s for a running
        one (e.g. reading the tool table after connecting)."""
        if not self._busy.acquire(timeout=wait):
            raise SrciError(f"{what}: another command is running")
        try:
            client = self.client
            if self._phase != Phase.READY:
                raise SrciError(f"{what}: not connected")
            if activity is not None:
                self._set(activity=activity, error="")
            try:
                yield client
            except BaseException as exc:
                self._set(error=f"{what}: {_text(exc)}")
                raise
            finally:
                if activity is not None:
                    self._set(activity=Activity.IDLE)
        finally:
            self._busy.release()

    def reset(self) -> None:
        """GroupReset: acknowledge errors of the robot."""
        self.require("GroupReset")
        with self._command("GroupReset") as client:
            client.execute(MC_GroupResetFB(), timeout=10.0)
            self._set(error="")

    def set_enabled(self, on: bool) -> None:
        """Switch the robot on (EnableRobot) or off."""
        self.require("EnableRobot")
        with self._command("EnableRobot") as client:
            if on:
                if self._enable is None:
                    enable = MC_EnableRobotFB()
                    try:
                        client.enable(enable, timeout=15.0)
                    except BaseException:
                        with contextlib.suppress(Exception):
                            client.disable(enable, timeout=3.0)
                        raise
                    self._enable = enable
                    self._apply_override(client)
            elif self._enable is not None:
                enable, self._enable = self._enable, None
                client.disable(enable, timeout=10.0)

    def set_override(self, percent: float) -> None:
        """Speed override of all motions [%]."""
        if not 0.0 < percent <= 100.0:
            raise ValueError(f"override {percent} outside 0 < x <= 100")
        self.override = float(percent)
        if self.connected:
            self.require("ChangeSpeedOverride")
            with self._command("ChangeSpeedOverride") as client:
                self._apply_override(client)

    def _apply_override(self, client: SrciClient) -> None:
        fb = MC_ChangeSpeedOverrideFB()
        fb.ParCmd.Override = self.override
        client.execute(fb, timeout=5.0)

    def stop(self) -> None:
        """Stop everything at once: jog off, end a running program, GroupStop. Does not wait for
        a running command (no ``_busy``)."""
        self._stop_event.set()
        client = self._client
        if client is None:
            return
        with contextlib.suppress(Exception):
            self._jog_off()
        try:
            client.execute(MC_GroupStopFB(), timeout=5.0, check=False)
        except (SrciError, WaitTimeoutError) as exc:
            self._set(error=f"GroupStop: {_text(exc)}")
            raise

    # ------------------------------------------------------------------ tools and frames

    def set_coordinate_system(self, tool: int, frame: int) -> None:
        """Tool and frame of the displayed Cartesian position, of Cartesian jogging and of
        taught points."""
        self.tool, self.frame = int(tool), int(frame)
        cyc, client = self._cyclic, self._client
        if cyc is not None and client is not None:
            par = copy.deepcopy(cyc.ParCmd)
            par.ToolNo, par.FrameNo = self.tool, self.frame
            client.set(cyc, ParCmd=par)
        self._polled = None  # the last polled position was in the old tool/frame
        if self.connected:
            self._poll_position()

    def read_position(self, tool: int, frame: int) -> list[float]:
        """Cartesian position of ``tool`` in ``frame`` (ReadActualPosition), e.g. to take the TCP
        as the origin of a new frame."""
        self.require("ReadActualPosition")
        with self._command("ReadActualPosition") as client:
            fb = MC_ReadActualPositionFB()
            fb.ParCmd.ToolNo, fb.ParCmd.FrameNo = tool, frame
            c = client.execute(fb, timeout=5.0).OutCmd.ActualCartesianPosition
            return [getattr(c, n) for n in CARTESIAN]

    def read_tools(self) -> list[CoordData]:
        """All tools of the RC (index 0 .. HighestToolIndex, ReadToolData)."""
        self.require("ReadToolData")
        with self._command("ReadToolData") as client:
            highest = _highest(client, "Tool")
            tools = []
            for no in range(highest + 1):
                fb = MC_ReadToolDataFB()
                fb.ParCmd.ToolNo = no
                d = client.execute(fb, timeout=5.0).OutCmd.ToolData
                tools.append(
                    CoordData(no, [getattr(d, n) for n in CARTESIAN], int(d.LoadNo), bool(d.ExternalTCP))
                )
            return tools

    def write_tool(self, tool: CoordData) -> None:
        """Write a tool to the RC (WriteToolData; tool 0 is the flange and cannot be changed)."""
        if tool.no < 1:
            raise ValueError("tool 0 is the flange of the robot")
        self.require("WriteToolData")
        with self._command("WriteToolData") as client:
            fb = MC_WriteToolDataFB()
            fb.ParCmd.ToolNo = tool.no
            d = fb.ParCmd.ToolData
            for name, value in zip(CARTESIAN, tool.values, strict=True):
                setattr(d, name, float(value))
            d.LoadNo, d.ExternalTCP = tool.load_no, tool.external_tcp
            client.execute(fb, timeout=5.0)

    def read_frames(self) -> list[CoordData]:
        """All frames of the RC (index 0 .. HighestFrameIndex, ReadFrameData)."""
        self.require("ReadFrameData")
        with self._command("ReadFrameData") as client:
            highest = _highest(client, "Frame")
            frames = []
            for no in range(highest + 1):
                fb = MC_ReadFrameDataFB()
                fb.ParCmd.FrameNo = no
                d = client.execute(fb, timeout=5.0).OutCmd.FrameData
                frames.append(
                    CoordData(no, [getattr(d, n) for n in CARTESIAN], reference=int(d.ReferenceFrame))
                )
            return frames

    def write_frame(self, frame: CoordData) -> None:
        """Write a frame to the RC (WriteFrameData; frame 0 is the world/base frame)."""
        if frame.no < 1:
            raise ValueError("frame 0 is the base frame of the robot")
        if frame.reference == frame.no:
            raise ValueError("a frame cannot refer to itself")
        self.require("WriteFrameData")
        with self._command("WriteFrameData") as client:
            fb = MC_WriteFrameDataFB()
            fb.ParCmd.FrameNo = frame.no
            d = fb.ParCmd.FrameData
            for name, value in zip(CARTESIAN, frame.values, strict=True):
                setattr(d, name, float(value))
            d.ReferenceFrame = frame.reference
            client.execute(fb, timeout=5.0)

    # ------------------------------------------------------------------ jog

    def jog_press(self, mode: JogMode, axis: int, direction: int, speed: float,
                  increment: float = 0.0, tool: int | None = None, frame: int | None = None) -> None:  # fmt: skip
        """Start jogging ``axis`` (0..5: X/J1 .. Rz/J6) in ``direction`` (+1 / -1) with ``speed`` %
        of the jog velocity. ``increment`` > 0: move only this distance [mm or deg] (step jog).
        Cartesian jogging (JOG_FRAME / JOG_TOOL) uses ``tool`` / ``frame`` (default: the
        coordinate system of :meth:`set_coordinate_system`). The motion continues only while
        :meth:`jog_alive` is called (hold-to-run)."""
        tool = self.tool if tool is None else tool
        frame = self.frame if frame is None else frame
        if axis not in range(6) or direction not in (1, -1):
            raise ValueError("axis 0..5, direction +1/-1")
        self.require("GroupJog")
        self._jog_alive = time.monotonic()
        with self._command("GroupJog", wait=0.5) as client:
            if self._enable is None:
                raise SrciError("GroupJog: switch the robot on first")
            self._jog_off()
            # GroupJog needs the RA sequence IDLE or INTERRUPTED (16#8F13): after the previous jog the
            # RC ends the jog sequence for a few cycles
            status = client.program.axes_group.State.StatusRobotArm
            with contextlib.suppress(WaitTimeoutError):
                client.run_until(
                    lambda: status.RaSequenceState in (RaSequenceState.IDLE, RaSequenceState.INTERRUPTED),
                    1.0,
                    "RA sequence idle",
                )
            jog = MC_GroupJogFB()
            par = jog.ParCmd
            par.Mode, par.Override, par.ToolNo, par.FrameNo = (
                mode,
                min(100, max(1, round(speed))),
                tool,
                frame,
            )
            if increment > 0.0:
                if mode == JogMode.JOG_AXES or axis >= 3:
                    par.IncrementalRotation = float(increment)
                else:
                    par.IncrementalTranslation = float(increment)
            setattr(par.Control, f"{JOG_AXES[axis]}_{'Pos' if direction > 0 else 'Neg'}", True)
            self._set(activity=Activity.JOGGING, error="")
            self._jog = jog
            try:
                client.enable(jog, timeout=3.0)
            except BaseException as exc:
                self._jog = None
                with contextlib.suppress(Exception):
                    client.disable(jog, timeout=2.0)
                self._set(activity=Activity.IDLE, error=f"GroupJog: {_text(exc)}")
                raise

    def jog_alive(self) -> None:
        """Heartbeat of a held key - jog, move to point, program with ``hold`` (call every
        100..200 ms while the key is held)."""
        self._jog_alive = time.monotonic()

    alive = jog_alive

    def release(self) -> None:
        """A held key was released: jog off, a hold-to-run motion stops."""
        self._jog_off()
        if self._hold:
            self._hold = False
            self.stop()

    def jog_release(self) -> None:
        """Jog key released."""
        self._jog_off()

    def _jog_off(self) -> None:
        jog, self._jog = self._jog, None
        if jog is None:
            return
        try:
            if self._client is not None:
                self._client.disable(jog, timeout=3.0)
        finally:
            if self._activity == Activity.JOGGING:
                self._set(activity=Activity.IDLE)

    # ------------------------------------------------------------------ teach

    def current_position(self) -> tuple[list[float], list[float]]:
        """The actual joint and Cartesian position (fresh, for teaching; Cartesian in the tool and
        frame of :meth:`set_coordinate_system`)."""
        if self._cyclic is None:
            if not self.connected:
                raise SrciError("not connected")
            self._poll_position()
        joints, cartesian, valid = self._position()
        if not valid:
            raise SrciError("no actual position available")
        return joints, cartesian

    def move_to(self, point: Point, motion: Motion = Motion.JOINT, velocity: float = 20.0,
                *, hold: bool = True) -> None:  # fmt: skip
        """Move to a taught point (exact stop) and wait until it is reached. ``hold``: the
        motion continues only while :meth:`alive` is called (hold-to-run)."""
        self.require(MOTION_FUNCTIONS[Motion(motion).value])
        self._stop_event.clear()
        with self._command(f"Move to {point.name}", Activity.MOVING) as client:
            self._require_enabled()
            fb = _motion_block(Step(point.name, motion, velocity), point)
            self._start_hold(hold)
            try:
                client.start(fb)
                self._wait_motion(client, fb, 120.0)
            finally:
                self._hold = False

    def run_program(self, program: Program, start: int = 0, *, single_step: bool = False,
                    hold: bool = True, on_step: Callable[[int], None] | None = None) -> int:  # fmt: skip
        """Run the steps of ``program`` from index ``start``. Motions are sent ahead (up to two
        in the queue of the RC), so steps with blending are blended. ``single_step``: only one
        step. Returns the index of the next step (``len(steps)`` at the end)."""
        steps = program.steps
        if not 0 <= start < len(steps):
            raise ValueError(f"step {start} does not exist")
        end = start + 1 if single_step else len(steps)
        # all motion types of the steps to run - before the first motion starts
        self.require(*sorted({MOTION_FUNCTIONS[s.motion.value] for s in steps[start:end]}))
        self._stop_event.clear()
        with self._command(f"Program {program.name}", Activity.RUNNING) as client:
            self._require_enabled()
            pending: list[tuple[int, Any]] = []
            index = start
            self._start_hold(hold)
            try:
                while index < end or pending:
                    # keep up to two motions on the RC: the next one is known while one moves
                    while index < end and len(pending) < 2 and not self._stop_event.is_set():
                        step = steps[index]
                        fb = _motion_block(step, program.point(step.point))
                        client.start(fb)
                        pending.append((index, fb))
                        index += 1
                    if self._stop_event.is_set():
                        raise SrciError("stopped")
                    i, fb = pending[0]
                    self._program_step = i
                    if on_step is not None:
                        on_step(i)
                    self._wait_motion(client, fb, 300.0)
                    pending.pop(0)
            except BaseException:
                for _, fb in pending:
                    with contextlib.suppress(Exception):
                        client.remove(fb)
                raise
            finally:
                self._hold = False
            return index

    def _start_hold(self, hold: bool) -> None:
        self._jog_alive = time.monotonic()
        self._hold = hold

    def _require_enabled(self) -> None:
        if self._enable is None:
            raise SrciError("switch the robot on first")

    def _wait_motion(self, client: SrciClient, fb: Any, timeout: float) -> None:
        def finished() -> bool:
            return bool(fb.Done or fb.Error or fb.CommandAborted or self._stop_event.is_set())

        client.run_until(finished, timeout, f"{type(fb).__name__} Done")
        if self._stop_event.is_set() and not fb.Done:
            with contextlib.suppress(Exception):
                client.wait_done(fb, timeout=5.0, check=False)
            raise SrciError("stopped")
        client.wait_done(fb, timeout=5.0)


def _motion_block(step: Step, point: Point) -> Any:
    """The function block of a step: JOINT -> MoveAxesAbsolute, PTP -> MoveDirectAbsolute,
    LINEAR -> MoveLinearAbsolute, with the dynamics and blending of the step."""
    fb: Any
    if step.motion in (Motion.LINEAR, Motion.PTP):
        fb = MC_MoveLinearAbsoluteFB() if step.motion == Motion.LINEAR else MC_MoveDirectAbsoluteFB()
        pos = fb.ParCmd.Position
        for name, value in zip(CARTESIAN, point.cartesian, strict=True):
            setattr(pos, name, value)
        fb.ParCmd.ToolNo, fb.ParCmd.FrameNo = point.tool, point.frame
        # the JAKA MiniCobo accepts only TurnMode FREE / ConfigMode FREE (SRCI_PY examples/jaka_minicobo)
        fb.ParCmd.TurnMode = TurnMode.FREE
        cm = fb.ParCmd.ConfigMode
        cm.Shoulder, cm.Elbow, cm.Wrist = ArmConfigShoulder.FREE, ArmConfigElbow.FREE, ArmConfigWrist.FREE
    else:
        fb = MC_MoveAxesAbsoluteFB()
        jp = fb.ParCmd.JointPosition
        for name, value in zip(JOINTS, point.joints, strict=True):
            setattr(jp, name, value)
    par = fb.ParCmd
    par.VelocityRate, par.AccelerationRate = step.velocity, step.acceleration
    par.DecelerationRate, par.JerkRate = step.deceleration, step.jerk
    par.BlendingMode = BlendingMode[step.blending_mode]
    par.BlendingParameter[0] = step.blending if step.blended else 0.0
    par.BlendingParameter[1] = step.blending_post if step.blended else 0.0
    return fb


def _highest(client: SrciClient, kind: str) -> int:
    """Highest usable tool / frame index: the one of the RC, limited by the size of the tables of
    the library (``UnifiedToolIndex``, ``srci.configure(TOOL_MAX=...)``)."""
    state = client.program.axes_group.State
    return min(
        int(getattr(state.ConfigurationData, f"Highest{kind}Index")),
        int(getattr(state, f"Unified{kind}Index")),
    )


def _text(exc: BaseException) -> str:
    text = str(exc) or type(exc).__name__
    return text.replace("\n", " ")[:300]
