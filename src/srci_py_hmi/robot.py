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
* runs programs (:mod:`srci_py_hmi.model`) step by step or continuously,
* pauses and continues motions (GroupInterrupt / GroupContinue, ReturnToPrimary after jogging
  away from the path), switches the external operation mode and hand guiding (FreeDrive),
* reads and writes the data of the RC: I/O and registers, loads, dynamics, software limits,
  DH parameters, system variables, and lets the RC calculate tools, frames, kinematics and
  shifted positions.

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
    MC_CalculateForwardKinematicFB,
    MC_CalculateFrameFB,
    MC_CalculateInverseKinematicFB,
    MC_CalculateToolFB,
    MC_CallSubprogramFB,
    MC_ChangeSpeedOverrideFB,
    MC_EnableRobotFB,
    MC_FreeDriveFB,
    MC_GroupContinueFB,
    MC_GroupInterruptFB,
    MC_GroupJogFB,
    MC_GroupResetFB,
    MC_GroupStopFB,
    MC_MoveAxesAbsoluteFB,
    MC_MoveAxesRelativeFB,
    MC_MoveCircularAbsoluteFB,
    MC_MoveDirectAbsoluteFB,
    MC_MoveDirectRelativeFB,
    MC_MoveLinearAbsoluteFB,
    MC_MoveLinearRelativeFB,
    MC_ReadActualPositionCyclicFB,
    MC_ReadActualPositionFB,
    MC_ReadDHParameterFB,
    MC_ReadDigitalInputsFB,
    MC_ReadDigitalOutputsFB,
    MC_ReadFrameDataFB,
    MC_ReadIntegersFB,
    MC_ReadLoadDataFB,
    MC_ReadRealsFB,
    MC_ReadRobotDefaultDynamicsFB,
    MC_ReadRobotReferenceDynamicsFB,
    MC_ReadRobotSWLimitsFB,
    MC_ReadSystemVariableFB,
    MC_ReadToolDataFB,
    MC_ReturnToPrimaryFB,
    MC_SetOperationModeFB,
    MC_ShiftPositionFB,
    MC_WriteDigitalOutputsFB,
    MC_WriteFrameDataFB,
    MC_WriteIntegersFB,
    MC_WriteLoadDataFB,
    MC_WriteRealsFB,
    MC_WriteRobotDefaultDynamicsFB,
    MC_WriteRobotReferenceDynamicsFB,
    MC_WriteRobotSWLimitsFB,
    MC_WriteSystemVariableFB,
    MC_WriteToolDataFB,
)
from srci.logging_bridge import PythonLogger
from srci.transport import TcpTransport
from srci.transport.base import Transport
from srci.types import (
    ArmConfigElbow,
    ArmConfigShoulder,
    ArmConfigWrist,
    BlendingMode,
    CircMode,
    DataType,
    FrameCalculationMode,
    JogMode,
    MessageLevel,
    OperationMode,
    RaSequenceState,
    ReferenceElement,
    ReferenceType,
    ReturnMode,
    Severity,
    ToolCalculationMode,
    TransformMode,
    TurnMode,
)

from srci_py_hmi import sysvars
from srci_py_hmi.model import CARTESIAN, JOINTS, Motion, Point, Program, Step, StepKind

log = logging.getLogger("srci_py_hmi.robot")

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
MOTION_FUNCTIONS = {"joint": "MoveAxesAbsolute", "ptp": "MoveDirectAbsolute", "linear": "MoveLinearAbsolute",
                    "circ": "MoveCircularAbsolute"}  # fmt: skip
RELATIVE_FUNCTIONS = {"joint": "MoveAxesRelative", "ptp": "MoveDirectRelative", "linear": "MoveLinearRelative"}
STEP_FUNCTIONS = {StepKind.OUTPUT: "WriteDigitalOutputs", StepKind.WAIT_INPUT: "ReadDigitalInputs",
                  StepKind.SUBPROGRAM: "CallSubprogram"}  # fmt: skip
# external operation modes the PLC can switch (MC_SetOperationMode, manual 4.1.1)
EXTERNAL_MODES = (OperationMode.AUTO_EXT, OperationMode.T1_EXT, OperationMode.T2_EXT)
IO_BYTES = 5  # bytes per Read/WriteDigitalInputs/Outputs (40 signals)
REGISTERS = 7  # values per Read/WriteIntegers/Reals

BLENDING_NOT_SUPPORTED = 0x8E05  # error of the RC: BlendingMode not supported

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
    FREE_DRIVE = "free_drive"  # hand guiding (FreeDrive)


@dataclass
class Target:
    """Where to connect to."""

    host: str = "192.168.2.10"
    port: int = 5000
    length: int = 256  # telegram length per direction = size of the PROFINET module
    simulator: bool = False  # SRCI SDK simulator behind a local gateway (needs SRCI_SDK_SIM_LIB)
    # LifeSign timeout [ms]: 50 is the spec default; the JAKA MiniCobo needs >= 300 (no LifeSign for
    # ~200 ms while it switches the drives off after a rejected command)
    lifesign_ms: int = 500


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
    interrupted: bool = False  # motions paused (GroupInterrupt) - continue with GroupContinue
    secondary: bool = False  # secondary sequence active (jogged away from the interrupted path)
    in_primary_pos: bool = True  # robot is on the interrupted path again
    highest_load: int = 0
    working_hours: tuple[int, int] = (0, 0)  # RC, robot arm [h]

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


@dataclass
class LoadInfo:
    """A load (payload) of the RC: center of gravity, mass and moments of inertia."""

    no: int
    values: list[float]  # X, Y, Z [mm], Rx, Ry, Rz [deg] of the center of gravity
    mass: float = 0.0  # kg
    inertia: list[float] = field(default_factory=lambda: [0.0] * 3)  # Ix, Iy, Iz [kg m²]


@dataclass
class Dynamics:
    """Default dynamics [% of the reference] and reference dynamics (absolute) of the RC."""

    default: list[float]  # velocity, acceleration, deceleration, jerk [%]
    reference: list[float]  # velocity [mm/s], acceleration, deceleration [mm/s²], jerk [mm/s³]


@dataclass
class ToolResult:
    """Result of CalculateTool."""

    values: list[float]
    max_error: float
    mean_error: float


class RobotService:
    """The connection to one robot (thread safe)."""

    def __init__(self, *, plc_log: bool = False) -> None:
        self.plc_log = plc_log  # system log of the function blocks -> logger srci.plc (log file)
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
        self._free: MC_FreeDriveFB | None = None
        self._io_lock = threading.Lock()  # one parallel read / write (I/O, registers) at a time
        self._jog_alive = 0.0  # last heartbeat of the held key (jog, move, program)
        self._hold = False  # a motion runs that needs the heartbeat (hold-to-run)
        self._stop_event = threading.Event()  # set by stop(): a running program ends
        self._program_step = -1
        self._watchdog: threading.Thread | None = None
        self._closing = threading.Event()
        self.override = 20.0
        # blending modes the RC accepted (True) or refused with 16#8E05 (False) - per connection, the
        # RC reports them nowhere else
        self.blending_results: dict[str, bool] = {}
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
        s.interrupted = status.RaSequenceState == RaSequenceState.INTERRUPTED or bool(status.PrimarySequencePaused)
        s.secondary = bool(status.SecondarySequenceActive)
        s.in_primary_pos = bool(status.InPrimaryPos)
        cfg = ag.State.ConfigurationData
        s.highest_load = _highest(client, "Load")
        s.working_hours = (int(cfg.RCWorkingHours), int(cfg.RAWorkingHours))
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

    def can(self, function: str) -> bool:
        """The RC reports ``function`` (True as long as the functions are not known)."""
        known = self.supported()
        return known is None or function in known

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
            self.blending_results = {}
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
            self._watchdog = threading.Thread(target=self._watch, name="srci-hmi-watchdog", daemon=True)
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
        cfg = client.program.ParCfg
        cfg.Com.LifeSignTimeOut = target.lifesign_ms
        cfg.Rob.Parameter.MessageLevel = MessageLevel.WARNING
        if self.plc_log:
            client.program.external_logger = PythonLogger()
            client.program.log_level = Severity.DEBUG
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
        self._enable = self._cyclic = self._jog = self._free = None
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
            if self._free is not None and silent:
                log.warning("hand guiding stopped: no heartbeat for %.1f s", JOG_WATCHDOG)
                with contextlib.suppress(Exception):
                    self._free_off()
            if self._hold and silent:
                log.warning("motion stopped: key released or no heartbeat for %.1f s", JOG_WATCHDOG)
                self._hold = False
                with contextlib.suppress(Exception):
                    self.stop()
            # ReadActualPosition runs on the RC in parallel to motions and jogging: the display
            # follows the robot also while a program runs
            # (but not during other commands like EnableRobot: some RCs do not like parallel commands
            # while they switch the drives on)
            if self._cyclic is None and time.monotonic() - last_poll > 0.25:
                if self._activity in (Activity.MOVING, Activity.RUNNING, Activity.JOGGING):
                    self._poll_position()
                elif self._busy.acquire(blocking=False):
                    try:
                        self._poll_position()
                    finally:
                        self._busy.release()
                last_poll = time.monotonic()

    # ------------------------------------------------------------------ commands

    def program_paused(self) -> bool:
        """A program (or a move to a point) runs, but its motion is interrupted (GroupInterrupt)."""
        client = self._client
        if client is None or self._activity not in (Activity.RUNNING, Activity.MOVING):
            return False
        status = client.program.axes_group.State.StatusRobotArm
        return status.RaSequenceState == RaSequenceState.INTERRUPTED or bool(status.PrimarySequencePaused)

    @contextlib.contextmanager
    def _command(
        self, what: str, activity: Activity | None = None, wait: float = 5.0, *, while_paused: bool = False
    ) -> Iterator[SrciClient]:
        """Exclusive use of the client for a command sequence; waits up to ``wait`` s for a running
        one (e.g. reading the tool table after connecting). ``while_paused``: also while a program
        is interrupted (it holds the lock and only waits for its motion) - jog, hand guiding and
        ReturnToPrimary in the secondary sequence."""
        if not self._busy.acquire(timeout=wait):
            if while_paused and self.program_paused():
                client = self.client
                try:
                    yield client
                except BaseException as exc:
                    self._set(error=f"{what}: {_text(exc)}")
                    raise
                return
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
                    # a pending error of the RC (e.g. "sequence timeout" of the last connection)
                    # refuses EnableRobot with 16#8C04 "robot disabled due to an error": acknowledge first
                    if self.supported() is None or "GroupReset" in (self.supported() or ()):
                        client.execute(MC_GroupResetFB(), timeout=10.0)
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
        with self._command("GroupJog", wait=0.5, while_paused=True) as client:
            if self._enable is None:
                raise SrciError("GroupJog: switch the robot on first")
            self._jog_off()
            paused = self._activity is not Activity.IDLE  # program interrupted: it stays "running"
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
            self._set(activity=None if paused else Activity.JOGGING, error="")
            self._jog = jog
            try:
                client.enable(jog, timeout=3.0)
            except BaseException as exc:
                self._jog = None
                with contextlib.suppress(Exception):
                    client.disable(jog, timeout=2.0)
                self._set(activity=None if paused else Activity.IDLE, error=f"GroupJog: {_text(exc)}")
                raise

    def jog_alive(self) -> None:
        """Heartbeat of a held key - jog, move to point, program with ``hold`` (call every
        100..200 ms while the key is held)."""
        self._jog_alive = time.monotonic()

    alive = jog_alive

    def release(self) -> None:
        """A held key was released: jog and hand guiding off, a hold-to-run motion stops."""
        self._jog_off()
        self._free_off()
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
            fb = _absolute_block(Step(point.name, motion, velocity), point)
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
        # all functions the steps to run need - before the first motion starts
        self.require(*sorted({f for s in steps[start:end] if (f := step_function(s))}))
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
                        if not step.is_motion:
                            if pending:
                                break  # I/O, wait, subprogram: after the motions before it
                            self._program_step = index
                            if on_step is not None:
                                on_step(index)
                            self._run_action(client, step)
                            index += 1
                            continue
                        fb = _motion_block(step, program)
                        client.start(fb)
                        pending.append((index, fb))
                        index += 1
                    if self._stop_event.is_set():
                        raise SrciError("stopped")
                    if not pending:
                        continue
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

        # an interrupted motion (GroupInterrupt) may wait for ever: the timeout counts only while
        # the robot is not paused
        status = client.program.axes_group.State.StatusRobotArm
        deadline = time.monotonic() + timeout
        while True:
            try:
                client.run_until(finished, min(1.0, max(0.05, deadline - time.monotonic())),
                                 f"{type(fb).__name__} Done")  # fmt: skip
                break
            except WaitTimeoutError:
                if status.RaSequenceState == RaSequenceState.INTERRUPTED or status.PrimarySequencePaused:
                    deadline = max(deadline, time.monotonic() + timeout)
                elif time.monotonic() >= deadline:
                    raise
        if self._stop_event.is_set() and not fb.Done:
            with contextlib.suppress(Exception):
                client.wait_done(fb, timeout=5.0, check=False)
            raise SrciError("stopped")
        blending = getattr(fb.ParCmd, "BlendingMode", None)
        mode = BlendingMode(blending).name if blending is not None else "EXACT_STOP"
        try:
            client.wait_done(fb, timeout=5.0)
        except CommandError as exc:
            if exc.error_id == BLENDING_NOT_SUPPORTED:
                self.blending_results[mode] = False
            raise
        if mode != "EXACT_STOP":
            self.blending_results[mode] = True

    def _run_action(self, client: SrciClient, step: Step) -> None:
        """A program step that is no motion (the motions before it are done)."""
        if step.kind is StepKind.WAIT:
            # waited here, not with WaitTime: works on every RC and STOPP ends it at once
            if self._stop_event.wait(step.duration):
                raise SrciError("stopped")
        elif step.kind is StepKind.OUTPUT:
            client.execute(_output_block(step.signal, step.value), timeout=5.0)
        elif step.kind is StepKind.WAIT_INPUT:
            byte, bit = divmod(step.signal, 8)
            end = time.monotonic() + step.timeout if step.timeout > 0 else None
            while True:
                fb = MC_ReadDigitalInputsFB()
                fb.ParCmd.Index = _io_index(byte)
                values = client.execute(fb, timeout=5.0).OutCmd.Values
                if bool(values[0] >> bit & 1) == step.value:
                    return
                if end is not None and time.monotonic() > end:
                    raise SrciError(f"DI {step.signal}: not {int(step.value)} within {step.timeout:g} s")
                if self._stop_event.wait(0.1):
                    raise SrciError("stopped")
        elif step.kind is StepKind.SUBPROGRAM:
            fb = _subprogram_block(step.job, step.data)
            client.start(fb)
            self._wait_motion(client, fb, 3600.0)

    # ------------------------------------------------------------------ pause, mode, hand guiding

    def interrupt(self) -> None:
        """Pause the motions (GroupInterrupt): a running program waits; jogging away from the path
        is possible (secondary sequence). Does not wait for a running command."""
        self.require("GroupInterrupt")
        self._direct("GroupInterrupt", MC_GroupInterruptFB())

    def resume(self) -> None:
        """Continue interrupted motions (GroupContinue)."""
        self.require("GroupContinue")
        self._direct("GroupContinue", MC_GroupContinueFB())

    def _direct(self, what: str, fb: Any, timeout: float = 5.0) -> Any:
        """A command beside the one holding the lock (like GroupStop)."""
        client = self.client
        try:
            return client.execute(fb, timeout=timeout)
        except (SrciError, WaitTimeoutError) as exc:
            self._set(error=f"{what}: {_text(exc)}")
            raise

    def return_to_primary(self, mode: ReturnMode = ReturnMode.INTERRUPT_POSITION, velocity: float = 20.0,
                          *, hold: bool = True) -> None:  # fmt: skip
        """Move back to the interrupted path (ReturnToPrimary) after jogging away from it; then
        GroupContinue goes on. ``hold``: only while :meth:`alive` is called."""
        self.require("ReturnToPrimary")
        with self._command("ReturnToPrimary", wait=0.5, while_paused=True) as client:
            self._require_enabled()
            fb = MC_ReturnToPrimaryFB()
            fb.ParCmd.ReturnMode = mode
            fb.ParCmd.VelocityRate = velocity
            fb.ParCmd.ToolNo, fb.ParCmd.FrameNo = self.tool, self.frame
            self._start_hold(hold)
            try:
                client.enable(fb, timeout=5.0)
                client.run_until(lambda: bool(fb.Done or fb.Error or fb.CommandAborted
                                              or (not self._hold and hold)), 120.0, "ReturnToPrimary Done")  # fmt: skip
                if fb.Error:
                    error = int(fb.ErrorID)
                    raise CommandError(fb, f"ReturnToPrimary: error 16#{error:04X}", error)
            finally:
                self._hold = False
                with contextlib.suppress(Exception):
                    client.disable(fb, timeout=3.0)

    def set_operation_mode(self, mode: OperationMode) -> None:
        """Switch the external operation mode of the RC (SetOperationMode): Automatic External, T1
        External or T2 External. The key switch of the RC must be on "External"."""
        if mode not in EXTERNAL_MODES:
            raise ValueError(f"{mode.name}: only the external modes can be switched by the PLC")
        self.require("SetOperationMode")
        with self._command("SetOperationMode") as client:
            fb = MC_SetOperationModeFB()
            fb.ParCmd.OperationMode = mode
            client.execute(fb, timeout=10.0)

    def free_drive_press(self) -> None:
        """Hand guiding (FreeDrive) while the key is held (hold-to-run like jogging)."""
        self.require("FreeDrive")
        self._jog_alive = time.monotonic()
        with self._command("FreeDrive", wait=0.5, while_paused=True) as client:
            self._require_enabled()
            self._jog_off()
            self._free_off()
            paused = self._activity is not Activity.IDLE
            fb = MC_FreeDriveFB()
            self._free = fb
            self._set(activity=None if paused else Activity.FREE_DRIVE, error="")
            try:
                client.enable(fb, timeout=5.0)
            except BaseException as exc:
                self._free = None
                with contextlib.suppress(Exception):
                    client.disable(fb, timeout=2.0)
                self._set(activity=None if paused else Activity.IDLE, error=f"FreeDrive: {_text(exc)}")
                raise

    def _free_off(self) -> None:
        fb, self._free = self._free, None
        if fb is None:
            return
        try:
            if self._client is not None:
                # some RCs keep Busy for a while after the hand guiding: disable() removes the block anyway
                with contextlib.suppress(WaitTimeoutError):
                    self._client.disable(fb, timeout=2.0)
        finally:
            if self._activity == Activity.FREE_DRIVE:
                self._set(activity=Activity.IDLE)

    # ------------------------------------------------------------------ I/O and registers

    @contextlib.contextmanager
    def _parallel(self, what: str) -> Iterator[SrciClient]:
        """A parallel command (I/O, registers): also while a program runs, not beside a command
        sequence like EnableRobot."""
        if self._phase != Phase.READY:
            raise SrciError(f"{what}: not connected")
        locked = False
        if self._activity is Activity.IDLE:
            if not self._busy.acquire(timeout=2.0):
                raise SrciError(f"{what}: another command is running")
            locked = True
        try:
            with self._io_lock:
                yield self.client
        except BaseException as exc:
            self._set(error=f"{what}: {_text(exc)}")
            raise
        finally:
            if locked:
                self._busy.release()

    def read_io(self, first_byte: int, outputs: bool = False) -> list[int]:
        """:data:`IO_BYTES` bytes of the digital inputs (or outputs) from ``first_byte``."""
        name = "ReadDigitalOutputs" if outputs else "ReadDigitalInputs"
        self.require(name)
        with self._parallel(name) as client:
            fb = MC_ReadDigitalOutputsFB() if outputs else MC_ReadDigitalInputsFB()
            fb.ParCmd.Index = _io_index(first_byte)
            return [int(v) for v in client.execute(fb, timeout=5.0).OutCmd.Values]

    def write_output(self, signal: int, value: bool) -> None:
        """Digital output ``signal`` (byte * 8 + bit) := ``value`` (WriteDigitalOutputs, only this bit)."""
        self.require("WriteDigitalOutputs")
        with self._parallel("WriteDigitalOutputs") as client:
            client.execute(_output_block(signal, value), timeout=5.0)

    def read_registers(self, real: bool, first: int) -> list[float]:
        """:data:`REGISTERS` integer (or real) registers of the RC from index ``first``."""
        name = "ReadReals" if real else "ReadIntegers"
        self.require(name)
        with self._parallel(name) as client:
            fb = MC_ReadRealsFB() if real else MC_ReadIntegersFB()
            fb.ParCmd.Index = _register_index(first)
            return [float(v) for v in client.execute(fb, timeout=5.0).OutCmd.Values]

    def write_registers(self, real: bool, first: int, values: list[float]) -> None:
        """Write :data:`REGISTERS` registers from index ``first`` (the block is always written whole:
        Write Integers / Reals has no mask)."""
        if len(values) != REGISTERS:
            raise ValueError(f"{REGISTERS} values expected")
        name = "WriteReals" if real else "WriteIntegers"
        self.require(name)
        with self._parallel(name) as client:
            fb = MC_WriteRealsFB() if real else MC_WriteIntegersFB()
            fb.ParCmd.Index = _register_index(first)
            fb.ParCmd.Values = [float(v) for v in values] if real else [round(v) for v in values]
            client.execute(fb, timeout=5.0)

    # ------------------------------------------------------------------ loads, dynamics, limits

    def read_loads(self) -> list[LoadInfo]:
        """All loads of the RC (index 0 .. HighestLoadIndex, ReadLoadData)."""
        self.require("ReadLoadData")
        with self._command("ReadLoadData") as client:
            highest = _highest(client, "Load")
            loads = []
            for no in range(highest + 1):
                fb = MC_ReadLoadDataFB()
                fb.ParCmd.LoadNo = no
                d = client.execute(fb, timeout=5.0).OutCmd.LoadData
                loads.append(LoadInfo(no, [getattr(d, n) for n in CARTESIAN], d.Mass, [d.Ix, d.Iy, d.Iz]))
            return loads

    def write_load(self, load: LoadInfo) -> None:
        """Write a load to the RC (WriteLoadData; load 0 is "no load" and cannot be changed)."""
        if load.no < 1:
            raise ValueError("load 0 cannot be changed")
        if load.mass < 0:
            raise ValueError("negative mass")
        self.require("WriteLoadData")
        with self._command("WriteLoadData") as client:
            fb = MC_WriteLoadDataFB()
            fb.ParCmd.LoadNo = load.no
            d = fb.ParCmd.LoadData
            for name, value in zip(CARTESIAN, load.values, strict=True):
                setattr(d, name, float(value))
            d.Mass = float(load.mass)
            d.Ix, d.Iy, d.Iz = (float(v) for v in load.inertia)
            client.execute(fb, timeout=5.0)

    def read_dynamics(self) -> Dynamics:
        """Default and reference dynamics of the RC (ReadRobotDefault/ReferenceDynamics)."""
        self.require("ReadRobotDefaultDynamics", "ReadRobotReferenceDynamics")
        with self._command("ReadRobotDynamics") as client:
            d = client.execute(MC_ReadRobotDefaultDynamicsFB(), timeout=5.0).OutCmd.DynamicValues
            r = client.execute(MC_ReadRobotReferenceDynamicsFB(), timeout=5.0).OutCmd.DynamicValues
            return Dynamics([d.VelocityRate, d.AccelerationRate, d.DecelerationRate, d.JerkRate],
                            [r.VelocityReference, r.AccelerationReference, r.DecelerationReference,
                             r.JerkReference])  # fmt: skip

    def write_default_dynamics(self, rates: list[float]) -> None:
        """Default dynamics [% of the reference] used by motions with "default" (-1)."""
        if len(rates) != 4 or any(not 0.0 < v <= 100.0 for v in rates):
            raise ValueError("four values 0 < v <= 100 %")
        self.require("WriteRobotDefaultDynamics")
        with self._command("WriteRobotDefaultDynamics") as client:
            fb = MC_WriteRobotDefaultDynamicsFB()
            d = fb.ParCmd.DynamicValues
            d.VelocityRate, d.AccelerationRate, d.DecelerationRate, d.JerkRate = (float(v) for v in rates)
            client.execute(fb, timeout=5.0)

    def write_reference_dynamics(self, values: list[float]) -> None:
        """Reference dynamics (100 %) of the RC: velocity, acceleration, deceleration, jerk."""
        if len(values) != 4 or any(v <= 0.0 for v in values):
            raise ValueError("four values > 0")
        self.require("WriteRobotReferenceDynamics")
        with self._command("WriteRobotReferenceDynamics") as client:
            fb = MC_WriteRobotReferenceDynamicsFB()
            d = fb.ParCmd.DynamicValues
            (d.VelocityReference, d.AccelerationReference, d.DecelerationReference,
             d.JerkReference) = (float(v) for v in values)  # fmt: skip
            client.execute(fb, timeout=5.0)

    def read_sw_limits(self) -> list[tuple[float, float]]:
        """Software limits J1..J6 (lower, upper) [deg] (ReadRobotSWLimits)."""
        self.require("ReadRobotSWLimits")
        with self._command("ReadRobotSWLimits") as client:
            lim = client.execute(MC_ReadRobotSWLimitsFB(), timeout=5.0).OutCmd.LimitValues
            return [(getattr(lim, f"{j}LowerLimit"), getattr(lim, f"{j}UpperLimit")) for j in JOINTS]

    def write_sw_limits(self, limits: list[tuple[float, float]], factory: bool = False) -> bool:
        """Write the software limits J1..J6 (or reset them to the factory defaults); returns True
        if the RC asks for a restart."""
        if not factory and (len(limits) != 6 or any(lo >= hi for lo, hi in limits)):
            raise ValueError("six limits with lower < upper")
        self.require("WriteRobotSWLimits")
        with self._command("WriteRobotSWLimits") as client:
            fb = MC_WriteRobotSWLimitsFB()
            lim = fb.ParCmd.LimitValues
            if self.can("ReadRobotSWLimits"):  # the external axes keep the values of the RC
                old = client.execute(MC_ReadRobotSWLimitsFB(), timeout=5.0).OutCmd.LimitValues
                for f in dataclasses.fields(old):
                    setattr(lim, f.name, copy.deepcopy(getattr(old, f.name)))
            for j, (lo, hi) in zip(JOINTS, limits, strict=False):
                setattr(lim, f"{j}LowerLimit", float(lo))
                setattr(lim, f"{j}UpperLimit", float(hi))
            fb.ParCmd.ResetToFactoryDefaults = factory
            return bool(client.execute(fb, timeout=10.0).OutCmd.RestartRequested)

    def read_dh(self, modified: bool = False) -> dict[str, list[float]]:
        """DH parameters of the robot (ReadDHParameter): alpha, a, d, theta, direction, zero
        position per joint."""
        self.require("ReadDHParameter")
        with self._command("ReadDHParameter") as client:
            fb = MC_ReadDHParameterFB()
            fb.ParCmd.ModifiedConvention = modified
            dh = client.execute(fb, timeout=5.0).OutCmd.DHParameter
            return {"alpha": list(dh.Alpha[:6]), "a": list(dh.A[:6]), "d": list(dh.D[:6]),
                    "theta": list(dh.Theta[:6]),
                    "direction": [1.0 if v else -1.0 for v in dh.PositiveJointDirection[:6]],
                    "zero": list(dh.JointZeroPosition[:6])}  # fmt: skip

    def read_system_variable(self, param: int, subs: list[int], rc_param: bool = False) -> list[sysvars.Value]:
        """Read (sub-)parameters of a system variable (ReadSystemVariable, up to 8 per command)."""
        self.require("ReadSystemVariable")
        values: list[sysvars.Value] = []
        with self._command("ReadSystemVariable") as client:
            for chunk in _chunks(subs, 8):
                fb = MC_ReadSystemVariableFB()
                fb.ParCmd.RCParameter = rc_param
                for i, sub in enumerate(chunk):
                    fb.ParCmd.ParameterID[i], fb.ParCmd.SubParameterID[i] = param, sub
                out = client.execute(fb, timeout=5.0).OutCmd
                for i, sub in enumerate(chunk):
                    raw = bytes(int(b) & 0xFF for b in getattr(out, f"Data_{i}"))
                    values.append(sysvars.Value(sub, int(out.DataType[i]), raw))
            return values

    def write_system_variable(self, param: int, values: list[sysvars.Value], rc_param: bool = False) -> bool:
        """Write (sub-)parameters of a system variable; returns True if the RC asks for a restart."""
        self.require("WriteSystemVariable")
        restart = False
        with self._command("WriteSystemVariable") as client:
            for chunk in _chunks(values, 8):
                fb = MC_WriteSystemVariableFB()
                fb.ParCmd.RCParameter = rc_param
                for i, v in enumerate(chunk):
                    fb.ParCmd.ParameterID[i], fb.ParCmd.SubParameterID[i] = param, v.sub
                    fb.ParCmd.DataType[i] = DataType(v.data_type)
                    setattr(fb.ParCmd, f"Data_{i}", list(v.raw.ljust(4, b"\0")[:4]))
                restart |= bool(client.execute(fb, timeout=10.0).OutCmd.RestartRequested)
        return restart

    # ------------------------------------------------------------------ calculations of the RC

    def forward_kinematics(self, joints: list[float], tool: int, frame: int) -> list[float]:
        """Cartesian position of ``joints`` (CalculateForwardKinematic)."""
        self.require("CalculateForwardKinematic")
        with self._command("CalculateForwardKinematic") as client:
            fb = MC_CalculateForwardKinematicFB()
            fb.ParCmd.ToolNo, fb.ParCmd.FrameNo = tool, frame
            _set_joints(fb.ParCmd.JointPosition, joints)
            return _cart(client.execute(fb, timeout=5.0).OutCmd.CartesianPosition)

    def inverse_kinematics(self, cartesian: list[float], tool: int, frame: int) -> list[float]:
        """Joint position of a Cartesian position (CalculateInverseKinematic)."""
        self.require("CalculateInverseKinematic")
        with self._command("CalculateInverseKinematic") as client:
            fb = MC_CalculateInverseKinematicFB()
            fb.ParCmd.ToolNo, fb.ParCmd.FrameNo = tool, frame
            _set_cart(fb.ParCmd.CartesianPosition, cartesian)
            j = client.execute(fb, timeout=5.0).OutCmd.JointPosition
            return [getattr(j, n) for n in JOINTS]

    def calculate_tool(self, mode: ToolCalculationMode, positions: list[list[float]], tool: int,
                       frame: int = 0, external: bool = False) -> ToolResult:  # fmt: skip
        """TCP from taught flange positions (CalculateTool, manual 6.9.5)."""
        if not 1 <= len(positions) <= 6:
            raise ValueError("1..6 positions")
        self.require("CalculateTool")
        with self._command("CalculateTool") as client:
            fb = MC_CalculateToolFB()
            par = fb.ParCmd
            par.Mode, par.ToolNo, par.FrameNo, par.ExternalTCP = mode, tool, frame, external
            for target, values in zip(par.PositionsArray, positions, strict=False):
                _set_cart(target, values)
            out = client.execute(fb, timeout=10.0).OutCmd
            return ToolResult([getattr(out.ToolData, n) for n in CARTESIAN], out.TCPMaxError, out.TCPMeanError)

    def calculate_frame(self, mode: FrameCalculationMode, frame: int, reference: int,
                        positions: dict[str, list[float]]) -> list[float]:  # fmt: skip
        """Frame from taught positions (CalculateFrame, manual 6.9.4): ``positions`` with the keys
        ``Origin``, ``Position_X``, ``Position_XY``, ``OriginShift`` (as the method needs)."""
        self.require("CalculateFrame")
        with self._command("CalculateFrame") as client:
            fb = MC_CalculateFrameFB()
            par = fb.ParCmd
            par.Mode, par.FrameNo, par.ReferenceFrame = mode, frame, reference
            for key, values in positions.items():
                _set_cart(getattr(par, key), values)
            return _cart(client.execute(fb, timeout=10.0).OutCmd.Position)

    def shift_position(self, mode: TransformMode, position: list[float], frame: int, parameter: list[float],
                       element: ReferenceElement = ReferenceElement.NOT_USED, angle: float = 0.0,
                       target_frame: int | None = None) -> list[float]:  # fmt: skip
        """Mirror, rotate or shift a position (ShiftPosition, manual 6.9.6). ``parameter``: point,
        line or plane (X..Rz) of the transformation in ``frame``."""
        self.require("ShiftPosition")
        with self._command("ShiftPosition") as client:
            fb = MC_ShiftPositionFB()
            par = fb.ParCmd
            par.Mode, par.FrameNo = mode, frame
            par.TargetFrameNo = frame if target_frame is None else target_frame
            _set_cart(par.Position, position)
            t = par.TransformationParameter_1
            t.ReferenceFrame = frame
            for name, value in zip(CARTESIAN, parameter, strict=True):
                setattr(t, name, float(value))
            par.TransformationParameter_2, par.RotationAngle = element, float(angle)
            return _cart(client.execute(fb, timeout=5.0).OutCmd.TransformedPosition)

    def call_subprogram(self, job: int, data: list[int]) -> list[int]:
        """Run a subprogram of the RC (CallSubprogram) and return its data."""
        self.require("CallSubprogram")
        self._stop_event.clear()
        with self._command("CallSubprogram", Activity.RUNNING) as client:
            fb = _subprogram_block(job, data)
            client.start(fb)
            self._wait_motion(client, fb, 3600.0)
            return [int(b) for b in fb.OutCmd.ReturnData]


def step_function(step: Step) -> str | None:
    """The function of the RC a program step needs (None: waiting needs none)."""
    if step.kind is StepKind.MOVE:
        return MOTION_FUNCTIONS[step.motion.value]
    if step.kind is StepKind.RELATIVE:
        return RELATIVE_FUNCTIONS[step.motion.value]
    return STEP_FUNCTIONS.get(step.kind)


def _motion_block(step: Step, program: Program) -> Any:
    """The function block of a motion step of ``program``."""
    if step.kind is StepKind.RELATIVE:
        return _relative_block(step)
    via = program.point(step.via) if step.motion is Motion.CIRC else None
    return _absolute_block(step, program.point(step.point), via)


def _free_config(fb: Any) -> None:
    # the JAKA MiniCobo accepts TurnMode only FREE, ConfigMode SAME or FREE (SRCI_PY examples/jaka_minicobo)
    fb.ParCmd.TurnMode = TurnMode.FREE
    cm = fb.ParCmd.ConfigMode
    cm.Shoulder, cm.Elbow, cm.Wrist = ArmConfigShoulder.FREE, ArmConfigElbow.FREE, ArmConfigWrist.FREE


def _absolute_block(step: Step, point: Point, via: Point | None = None) -> Any:
    """The function block of a step to a point: JOINT -> MoveAxesAbsolute, PTP ->
    MoveDirectAbsolute, LINEAR -> MoveLinearAbsolute, CIRC -> MoveCircularAbsolute through
    ``via``, with the dynamics and blending of the step."""
    fb: Any
    if step.motion is Motion.CIRC:
        if via is None:
            raise ValueError("a circular motion needs a via point")
        fb = MC_MoveCircularAbsoluteFB()
        fb.ParCmd.CircMode = CircMode.BORDER  # arc through the via point (AuxPoint) to the end point
        _set_cart(fb.ParCmd.AuxPoint, via.cartesian)
        _set_cart(fb.ParCmd.EndPoint, point.cartesian)
        fb.ParCmd.ToolNo, fb.ParCmd.FrameNo = point.tool, point.frame
        _free_config(fb)
    elif step.motion in (Motion.LINEAR, Motion.PTP):
        fb = MC_MoveLinearAbsoluteFB() if step.motion == Motion.LINEAR else MC_MoveDirectAbsoluteFB()
        _set_cart(fb.ParCmd.Position, point.cartesian)
        fb.ParCmd.ToolNo, fb.ParCmd.FrameNo = point.tool, point.frame
        _free_config(fb)
    else:
        fb = MC_MoveAxesAbsoluteFB()
        _set_joints(fb.ParCmd.JointPosition, point.joints)
    _dynamics(fb, step)
    return fb


def _relative_block(step: Step) -> Any:
    """MoveLinearRelative / MoveDirectRelative (offset in the tool or the frame) or
    MoveAxesRelative (joint offsets)."""
    fb: Any
    if step.motion is Motion.JOINT:
        fb = MC_MoveAxesRelativeFB()
        _set_joints(fb.ParCmd.JointDistance, step.offset)
        fb.ParCmd.ToolNo = step.tool
    else:
        fb = MC_MoveLinearRelativeFB() if step.motion is Motion.LINEAR else MC_MoveDirectRelativeFB()
        _set_cart(fb.ParCmd.Distance, step.offset)
        fb.ParCmd.ReferenceType = ReferenceType.TOOL if step.reference == "tool" else ReferenceType.FRAME
        fb.ParCmd.ToolNo, fb.ParCmd.FrameNo = step.tool, step.frame
        _free_config(fb)
    _dynamics(fb, step)
    return fb


def _dynamics(fb: Any, step: Step) -> None:
    par = fb.ParCmd
    par.VelocityRate, par.AccelerationRate = step.velocity, step.acceleration
    par.DecelerationRate, par.JerkRate = step.deceleration, step.jerk
    par.BlendingMode = BlendingMode[step.blending_mode]
    par.BlendingParameter[0] = step.blending if step.blended else 0.0
    par.BlendingParameter[1] = step.blending_post if step.blended else 0.0


def _set_cart(target: Any, values: list[float]) -> None:
    for name, value in zip(CARTESIAN, values, strict=True):
        setattr(target, name, float(value))


def _set_joints(target: Any, values: list[float]) -> None:
    for name, value in zip(JOINTS, values, strict=True):
        setattr(target, name, float(value))


def _cart(position: Any) -> list[float]:
    return [float(getattr(position, n)) for n in CARTESIAN]


def _io_index(first_byte: int) -> list[int]:
    """:data:`IO_BYTES` different byte addresses from ``first_byte`` (the RC refuses repeated ones)."""
    if not 0 <= first_byte <= 255:
        raise ValueError(f"byte {first_byte} outside 0..255")
    # near the end of the address range the other entries go below (Values[0] stays first_byte)
    first = min(first_byte, 256 - IO_BYTES)
    return [first_byte, *(b for b in range(first, first + IO_BYTES) if b != first_byte)]


def _register_index(first: int) -> list[int]:
    if not 0 <= first <= 255 - REGISTERS + 1:
        raise ValueError(f"register {first} outside 0..{256 - REGISTERS}")
    return [first + i for i in range(REGISTERS)]


def _output_block(signal: int, value: bool) -> Any:
    """WriteDigitalOutputs of one bit (mask: the other outputs keep their value)."""
    byte, bit = divmod(int(signal), 8)
    fb = MC_WriteDigitalOutputsFB()
    fb.ParCmd.Index = _io_index(byte)
    fb.ParCmd.OutputBitmask = [1 << bit, 0, 0, 0, 0]
    fb.ParCmd.Values = [(1 << bit) if value else 0, 0, 0, 0, 0]
    return fb


def _subprogram_block(job: int, data: list[int]) -> Any:
    fb = MC_CallSubprogramFB()
    fb.ParCmd.JobID = int(job)
    for i, b in enumerate(data[:190]):
        fb.ParCmd.Data[i] = int(b)
    return fb


def _chunks(items: list[Any], n: int) -> Iterator[list[Any]]:
    for i in range(0, len(items), n):
        yield items[i : i + n]



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
