"""Wizards to measure a tool (CalculateTool) and a frame (CalculateFrame) with the RC: choose the
method, move the robot to the positions it asks for, take them over one by one, let the RC
calculate and write the result."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from nicegui import ui
from srci.types import FrameCalculationMode, ToolCalculationMode

from srci_py_hmi import geometry
from srci_py_hmi.model import CARTESIAN
from srci_py_hmi.robot import CoordData, ToolResult
from srci_py_hmi.ui import coords
from srci_py_hmi.ui.jog_pad import JogPad

if TYPE_CHECKING:
    from srci_py_hmi.ui.pendant import Pendant


@dataclass(frozen=True)
class Method:
    key: str  # text key "cal.<key>"
    mode: Any  # ToolCalculationMode / FrameCalculationMode
    positions: tuple[str, ...]  # text keys of the positions to take over ("cal.pos.<name>")
    sketch: str  # "tip", "orient", "frame"
    local: bool = False  # also calculated by the HMI (RC without CalculateTool / CalculateFrame)


TOOL_METHODS = (
    Method("tool4", ToolCalculationMode.FOUR_POINT_METHOD, ("tip1", "tip2", "tip3", "tip4"), "tip", True),
    Method("tool3", ToolCalculationMode.THREE_POINT_METHOD, ("tip1", "tip2", "tip3"), "tip", True),
    Method("tool5", ToolCalculationMode.FIVE_POINT_METHOD, ("tip1", "tip2", "tip3", "xdir", "zdir"), "tip"),
    Method("tool6", ToolCalculationMode.SIX_POINT_METHOD, ("tip1", "tip2", "tip3", "tip4", "xdir", "zdir"), "tip"),
    Method("tool2z", ToolCalculationMode.TWO_POINT_Z_METHOD, ("tip1", "tip2"), "tip"),
    Method("abc_world", ToolCalculationMode.ABC_WORLD_METHOD, ("aligned",), "orient", True),
    Method("abc2", ToolCalculationMode.ABC_TWO_POINT_METHOD, ("origin", "xaxis", "xyplane"), "orient"),
)
# CalculateFrame: the positions go to these inputs
FRAME_INPUTS = {"origin": "Origin", "xaxis": "Position_X", "xyplane": "Position_XY", "shift": "OriginShift"}
FRAME_METHODS = (
    Method("frame3", FrameCalculationMode.THREE_POINT_METHOD, ("origin", "xaxis", "xyplane"), "frame", True),
    Method("frame4", FrameCalculationMode.FOUR_POINT_METHOD, ("origin", "xaxis", "xyplane", "shift"), "frame", True),
    Method("frame1", FrameCalculationMode.ONE_POINT_METHOD, ("origin",), "frame", True),
)

# small sketches in the colors of the theme (currentColor / --blue)
SKETCHES = {
    "tip": """<svg viewBox="0 0 220 120" width="220" height="120" fill="none" stroke="currentColor" stroke-width="2"
  stroke-linecap="round" stroke-linejoin="round">
  <path d="M110 112 L104 70 L116 70 Z" fill="var(--card-2)"/>
  <g opacity=".35"><rect x="30" y="14" width="34" height="14" rx="3"/><path d="M47 28 L80 58 L107 68"/></g>
  <g opacity=".6"><rect x="156" y="14" width="34" height="14" rx="3"/><path d="M173 28 L140 58 L113 68"/></g>
  <rect x="93" y="6" width="34" height="14" rx="3"/><path d="M110 20 L110 62"/>
  <circle cx="110" cy="68" r="4" fill="var(--blue)" stroke="var(--blue)"/>
</svg>""",
    "orient": """<svg viewBox="0 0 220 120" width="220" height="120" fill="none" stroke="currentColor" stroke-width="2"
  stroke-linecap="round">
  <rect x="70" y="10" width="40" height="16" rx="3"/><path d="M90 26 L90 64"/>
  <path d="M90 64 L150 64" stroke="var(--blue)"/><path d="M144 59 L150 64 L144 69" stroke="var(--blue)"/>
  <path d="M90 64 L90 108" stroke="var(--red)"/><path d="M85 102 L90 108 L95 102" stroke="var(--red)"/>
  <text x="156" y="68" fill="currentColor" stroke="none" font-size="12">X</text>
  <text x="96" y="112" fill="currentColor" stroke="none" font-size="12">Z</text>
</svg>""",
    "frame": """<svg viewBox="0 0 220 120" width="220" height="120" fill="none" stroke="currentColor" stroke-width="2"
  stroke-linecap="round">
  <path d="M20 100 L180 100 L200 70 L60 70 Z" fill="var(--card-2)" stroke-width="1.5"/>
  <path d="M60 92 L150 92" stroke="var(--blue)"/><path d="M144 87 L150 92 L144 97" stroke="var(--blue)"/>
  <path d="M60 92 L90 74" stroke="var(--green)"/>
  <path d="M60 92 L60 30" stroke="var(--red)"/><path d="M55 36 L60 30 L65 36" stroke="var(--red)"/>
  <circle cx="60" cy="92" r="4" fill="currentColor"/><circle cx="150" cy="92" r="4" fill="var(--blue)" stroke="none"/>
  <circle cx="112" cy="76" r="4" fill="var(--green)" stroke="none"/>
  <text x="66" y="112" fill="currentColor" stroke="none" font-size="11">P0</text>
  <text x="144" y="112" fill="currentColor" stroke="none" font-size="11">X</text>
  <text x="118" y="72" fill="currentColor" stroke="none" font-size="11">XY</text>
</svg>""",
}


def calculate_local(p: Pendant, m: Method, tool: bool, no: int, taken: dict[str, list[float]]) -> Any:
    """The result of method ``m`` calculated by the HMI (the RC has no CalculateTool / CalculateFrame)."""
    if tool:
        old = next((t for t in p.ws.tools if t.no == no), CoordData(no, [0.0] * 6))
        if m.key == "abc_world":  # orientation only: the TCP stays
            return ToolResult([*old.values[:3], *geometry.orientation_abc_world(taken["aligned"])], 0.0, 0.0)
        tcp = geometry.tcp_from_tip([taken[n] for n in m.positions])
        # the RC returns the orientation 0, 0, 0 for these methods - the HMI keeps the one of the tool
        return ToolResult([*tcp.tcp, *old.values[3:]], tcp.max_error, tcp.mean_error)
    pos = [taken[n] for n in m.positions]
    if m.key == "frame3":
        return geometry.frame_three_points(*pos)
    if m.key == "frame4":
        return geometry.frame_four_points(*pos)
    return geometry.frame_one_point(pos[0])


async def calibrate(p: Pendant, kind: str, no: int) -> None:
    """Wizard for tool / frame ``no`` (``kind``: coords.TOOL or coords.FRAME)."""
    tool = kind == coords.TOOL
    function = "CalculateTool" if tool else "CalculateFrame"
    on_rc = p.snap.can(function)  # else the HMI calculates (geometry.py) - only the unambiguous methods
    methods = tuple(m for m in (TOOL_METHODS if tool else FRAME_METHODS) if on_rc or m.local)
    state: dict[str, Any] = {"method": methods[0].key, "reference": 0, "result": None}
    taken: dict[str, list[float]] = {}
    manual = [100.0, 0.0, 0.0, 0.0]  # 2-point + Z: tool length Z and orientation Rx, Ry, Rz
    by_key = {m.key: m for m in methods}

    def method() -> Method:
        return by_key[str(state["method"])]

    async def take(name: str) -> None:
        # tool: position of the flange (T0) in the world (F0); frame: TCP of the active tool in the reference
        t, f = (0, 0) if tool else (p.robot.tool, int(state["reference"] or 0))
        values = await p.act(p.robot.read_position, t, f)
        if values is not None:
            taken[name] = values
            state["result"] = None
            draw.refresh()

    async def calculate() -> None:
        m = method()
        if not on_rc:
            try:
                result: Any = calculate_local(p, m, tool, no, taken)
            except ValueError as exc:
                ui.notify(str(exc), type="negative", position="top", multi_line=True)
                return
        elif tool:
            positions = [taken[n] for n in m.positions]
            if m.mode == ToolCalculationMode.TWO_POINT_Z_METHOD:
                positions.append([0.0, 0.0, manual[0], *manual[1:]])
            result = await p.act(p.robot.calculate_tool, m.mode, positions, no)
        else:
            result = await p.act(p.robot.calculate_frame, m.mode, no, int(state["reference"] or 0),
                                 {FRAME_INPUTS[n]: taken[n] for n in m.positions})  # fmt: skip
        if result is not None:
            state["result"] = result
            draw.refresh()

    @ui.refreshable
    def draw() -> None:
        m = method()
        with ui.row().classes("w-full items-center gap-4 no-wrap"):
            ui.html(SKETCHES[m.sketch]).classes("text-[var(--text-2)] shrink-0")
            ui.label(p.tr(f"cal.{m.key}_hint")).classes("tp-muted")
        for i, name in enumerate(m.positions):
            values = taken.get(name)
            with ui.element("div").classes("tp-item" + (" current" if values is None and all(
                    n in taken for n in m.positions[:i]) else "")):  # fmt: skip
                ui.label(str(i + 1)).classes("tp-badge")
                with ui.column().classes("gap-0 flex-1 min-w-0"):
                    ui.label(p.tr(f"cal.pos.{name}")).classes("font-semibold")
                    ui.label("   ".join(f"{n} {v:.1f}" for n, v in zip(CARTESIAN, values, strict=True))
                             if values else p.tr("cal.not_taken")).classes("tp-muted tp-mono truncate")  # fmt: skip
                if values is not None:
                    ui.icon("check_circle").classes("text-[var(--green)] text-[22px]")
                ui.button(p.tr("cal.take"), icon="my_location", on_click=lambda n=name: take(n)).props(
                    "flat no-caps dense"
                ).classes("tp-btn-soft px-3").mark(f"cal-take-{name}")
        if tool and m.mode == ToolCalculationMode.TWO_POINT_Z_METHOD:
            with ui.row().classes("w-full gap-2 no-wrap"):
                for i, label in enumerate(("Z", "Rx", "Ry", "Rz")):
                    ui.number(label, value=manual[i], suffix="mm" if i == 0 else "°",
                              on_change=lambda e, k=i: manual.__setitem__(k, float(e.value or 0))).props(
                        "filled dense").classes("flex-1 tp-mono-in")  # fmt: skip
        result = state["result"]
        if result is not None:
            values = result.values if isinstance(result, ToolResult) else result
            with ui.column().classes("w-full gap-1 tp-card-2 mt-1"):
                ui.label(p.tr("cal.result")).classes("tp-card-title")
                ui.label("   ".join(f"{n} {v:.2f}" for n, v in zip(CARTESIAN, values, strict=True))).classes(
                    "tp-mono text-[15px]"
                )
                if isinstance(result, ToolResult):
                    ui.label(p.tr("cal.errors", max=f"{result.max_error:.2f}", mean=f"{result.mean_error:.2f}")).classes(
                        "tp-muted"
                    )
        complete = all(n in taken for n in m.positions)
        with ui.row().classes("w-full justify-end gap-2 mt-1"):
            ui.button(p.tr("common.cancel"), on_click=lambda: dialog.submit(None)).props("flat no-caps")
            ui.button(p.tr("cal.calculate"), icon="calculate", on_click=calculate).props(
                "flat no-caps"
            ).classes("tp-btn-soft").set_enabled(complete)
            ui.button(p.tr("cal.write", name=coords.label(p, kind, no)), on_click=lambda: dialog.submit(state["result"])).props(
                "unelevated no-caps color=primary"
            ).mark("cal-write").set_enabled(result is not None)

    def restart() -> None:
        taken.clear()
        state["result"] = None
        draw.refresh()

    with p.dialog() as dialog, ui.card().classes(
        "w-full max-w-[1180px] gap-3"
    ):
        ui.label(p.tr("cal.title", name=coords.label(p, kind, no))).classes("text-[22px] font-bold")
        if not on_rc:
            ui.label(p.tr("cal.local", f=function)).classes("tp-banner w-full")
        # left: the positions of the method, right: jog the robot to them without leaving the dialog
        with ui.element("div").classes("tp-cal-grid grid w-full gap-5 items-start lg:grid-cols-[1fr_400px]"):
            with ui.column().classes("w-full gap-3"):
                with ui.row().classes("w-full gap-3 no-wrap"):
                    ui.select({m.key: p.tr(f"cal.{m.key}") for m in methods}, value=state["method"],
                              label=p.tr("cal.method"), on_change=lambda: restart()).bind_value(
                        state, "method").props("filled").classes("flex-1").mark("cal-method")  # fmt: skip
                    if not tool:
                        ui.select({k: v for k, v in coords.options(p, coords.FRAME).items() if k != no}, value=0,
                                  label=p.tr("coord.reference"),
                                  on_change=lambda: restart()).bind_value(state, "reference").props(
                            "filled").classes("w-48")  # fmt: skip
                ui.label(p.tr("cal.tool_hint" if tool else "cal.frame_hint")).classes("tp-muted -mt-1")
                draw()
            with ui.column().classes("w-full gap-1 tp-card-2") as jog_box:
                pad = JogPad(p, compact=True).build()
            pad.container = jog_box  # hidden without GroupJog and FreeDrive
            pad.update(p.snap)
    try:
        result = await dialog
    finally:
        pad.close()
    if result is None:
        return
    if tool:
        old = next((t for t in p.ws.tools if t.no == no), CoordData(no, [0.0] * 6))
        data = CoordData(no, list(result.values), old.load_no, old.external_tcp)
        writer: Callable[[CoordData], None] = p.robot.write_tool
        reader: Callable[[], list[CoordData]] = p.robot.read_tools
    else:
        data = CoordData(no, list(result), reference=int(state["reference"] or 0))
        writer, reader = p.robot.write_frame, p.robot.read_frames

    def write() -> bool:
        writer(data)
        return True

    if await p.act(write, done=p.tr("coord.saved", name=coords.label(p, kind, no))):
        table = await p.act(reader)
        if table is not None:
            if tool:
                p.ws.tools = table
            else:
                p.ws.frames = table
            p.ws.coord_revision += 1
