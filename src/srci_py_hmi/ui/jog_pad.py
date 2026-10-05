"""The jog keys (hold-to-run) as a component: on the jog page and - compact, with mode, speed and
increment - inside dialogs that need the robot moved, e.g. the measuring of tools and frames.

All pads share the settings of the pendant (mode, speed, increment) and are updated by its
timer (:meth:`Pendant.refresh` calls :meth:`JogPad.update`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nicegui import ui

from srci_py_hmi.model import CARTESIAN, JOINTS
from srci_py_hmi.robot import Activity, Phase, Snapshot
from srci_py_hmi.ui import coords

if TYPE_CHECKING:
    from srci_py_hmi.ui.pendant import Pendant

# value range of the position bars (joints [deg], X/Y/Z [mm], Rx/Ry/Rz [deg])
JOINT_RANGE = 360.0
CART_RANGES = (1000.0, 1000.0, 1000.0, 180.0, 180.0, 180.0)


def _fmt(v: float) -> str:
    return f"{v:,.2f}".replace(",", " ")


class JogPad:
    """Six axes with value, bar and -/+ keys; ``compact``: smaller and with its own settings."""

    def __init__(self, p: Pendant, *, compact: bool = False) -> None:
        self.p = p
        self.compact = compact
        self.names: list[ui.label] = []
        self.values: list[ui.label] = []
        self.bars: list[ui.element] = []
        self.keys: list[ui.button] = []
        self.mode_toggle: ui.toggle | None = None
        self.speed_slider: ui.slider | None = None
        self.increment_toggle: ui.toggle | None = None
        self.banner: ui.label | None = None
        self.free_btn: ui.button | None = None
        self.tool_select: ui.select | None = None
        self.frame_select: ui.select | None = None
        self.seen_coords: tuple[object, ...] = ()
        # hidden when the RC can neither jog nor guide by hand (set by the dialog: card / expansion)
        self.container: ui.element | None = None

    def build(self) -> JogPad:
        p = self.p
        if self.compact:
            with ui.row().classes("w-full items-center justify-between no-wrap gap-2"):
                ui.label(p.tr("jog.title")).classes("tp-card-title mb-0")
                self.mode_toggle = ui.toggle(
                    {"axes": p.tr("jog.axes"), "base": p.tr("jog.base"), "tool": p.tr("jog.tool")},
                    value=p.jog_mode, on_change=lambda e: p.set_jog_mode(e.value),
                ).props("no-caps unelevated dense").classes("tp-seg")  # fmt: skip
            # active tool and frame: Cartesian jogging, the displayed TCP and the positions taken over
            with ui.row().classes("w-full gap-2 no-wrap"):
                self.tool_select = (
                    ui.select(coords.options(p, coords.TOOL), value=p.robot.tool, label=p.tr("coord.tool"),
                              on_change=lambda e: p.select_coords(tool=e.value))
                    .props("filled dense options-dense").classes("flex-1").mark("pad-tool")
                )  # fmt: skip
                self.frame_select = (
                    ui.select(coords.options(p, coords.FRAME), value=p.robot.frame, label=p.tr("coord.frame"),
                              on_change=lambda e: p.select_coords(frame=e.value))
                    .props("filled dense options-dense").classes("flex-1").mark("pad-frame")
                )  # fmt: skip
            self.banner = ui.label("").classes("tp-banner w-full text-[13px] py-2")
        with ui.column().classes("w-full gap-0" + (" tp-pad-compact" if self.compact else "")):
            for i in range(6):
                with ui.element("div").classes("tp-axis"):
                    self.names.append(ui.label("").classes("tp-axis-name"))
                    with ui.column().classes("gap-1"):
                        self.values.append(ui.label("–").classes("tp-axis-val tp-mono text-left"))
                        with ui.element("div").classes("tp-bar w-full"):
                            self.bars.append(ui.element("div"))
                    for direction, icon in ((-1, "remove"), (1, "add")):
                        key = ui.button(icon=icon).props("unelevated").classes("tp-key-btn")
                        key.on("pointerdown", lambda _, a=i, d=direction: p.jog_press(a, d))
                        self.keys.append(key)
        if self.compact:
            with ui.row().classes("w-full items-center no-wrap gap-3 mt-2"):
                ui.icon("speed").classes("text-[var(--text-2)]")
                self.speed_slider = ui.slider(min=1, max=100, step=1, value=p.jog_speed,
                                              on_change=lambda e: p.set_jog_speed(e.value)).classes("flex-1")  # fmt: skip
                ui.label().bind_text_from(p, "jog_speed", lambda v: f"{v:.0f} %").classes("tp-mono w-12 text-right")
            with ui.row().classes("w-full items-center justify-between no-wrap gap-2 mt-1"):
                self.increment_toggle = ui.toggle(
                    {"0": p.tr("jog.continuous"), "0.1": "0.1", "1": "1", "10": "10"},
                    value=p.increment, on_change=lambda e: p.set_increment(e.value),
                ).props("no-caps unelevated dense").classes("tp-seg")  # fmt: skip
                if p.snap.can("FreeDrive"):
                    self.free_btn = (
                        ui.button(p.tr("free.button"), icon="back_hand")
                        .props("flat no-caps dense")
                        .classes("tp-btn-soft tp-hold px-3")
                        .tooltip(p.tr("free.hint"))
                    )
                    self.free_btn.on("pointerdown", p.free_drive)
        self.sync()
        p.jog_pads.append(self)
        return self

    def close(self) -> None:
        """The dialog of the pad is closed: no more updates."""
        if self in self.p.jog_pads:
            self.p.jog_pads.remove(self)

    def sync(self) -> None:
        """Mode, speed and increment of the pendant (changed on another pad)."""
        p = self.p
        names = JOINTS if p.jog_mode == "axes" else CARTESIAN
        for label, name in zip(self.names, names, strict=True):
            label.set_text(name)
        pairs: tuple[tuple[Any, Any], ...] = ((self.mode_toggle, p.jog_mode), (self.speed_slider, p.jog_speed),
                                              (self.increment_toggle, p.increment))  # fmt: skip
        for control, value in pairs:
            if control is not None and control.value != value:
                control.set_value(value)

    def update(self, s: Snapshot) -> None:
        p = self.p
        if self.container is not None:
            movable = s.can("GroupJog") or s.can("FreeDrive")
            self.container.set_visibility(movable)
            if not movable:
                return
        if self.tool_select is not None and self.frame_select is not None:
            coord_key = (p.ws.coord_revision, s.tool, s.frame, s.highest_tool, s.highest_frame)
            if coord_key != self.seen_coords:  # other choice on the jog page, tables read or written
                self.seen_coords = coord_key
                self.tool_select.set_options(coords.options(p, coords.TOOL), value=s.tool)
                self.frame_select.set_options(coords.options(p, coords.FRAME), value=s.frame)
        ready = s.phase is Phase.READY
        jog_supported = s.can("GroupJog")
        # also while a program is interrupted: jogging away from the path (secondary sequence)
        idle = s.activity in (Activity.IDLE, Activity.JOGGING) or (
            s.interrupted and s.activity in (Activity.RUNNING, Activity.MOVING)
        )
        can_jog = ready and s.enabled and jog_supported and idle
        for key in self.keys:
            p.put(key, "classes", "tp-key-btn" if can_jog else "tp-key-btn disabled")
        if self.banner is not None:
            text = ("" if can_jog else p.tr("jog.unsupported") if not jog_supported
                    else p.tr("jog.need_enable") if not s.enabled else "")  # fmt: skip
            self.banner.set_text(text)
            self.banner.set_visibility(ready and bool(text))
        if self.free_btn is not None:
            self.free_btn.set_enabled(ready and s.enabled)
        axes = p.jog_mode == "axes"
        values = s.joints if axes else s.cartesian
        for i, (label, bar) in enumerate(zip(self.values, self.bars, strict=True)):
            v = values[i]
            label.set_text(_fmt(v) if s.position_valid else "–")
            span = JOINT_RANGE if axes else CART_RANGES[i] * 2
            w = min(50.0, abs(v) / span * 100.0)
            p.put(bar, "style", f"left: {50.0 - w if v < 0 else 50.0:.1f}%; width: {w:.1f}%")
