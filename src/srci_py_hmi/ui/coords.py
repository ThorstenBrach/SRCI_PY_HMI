"""Pages "Tools" and "Frames": the tables of the robot controller (Read/Write Tool/FrameData).

The data live on the RC; the UI keeps the last read copy in the :class:`Workspace` and local
labels ("Gripper", "Pallet") in ``labels.json`` next to the programs.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from nicegui import ui

from srci_py_hmi.model import CARTESIAN
from srci_py_hmi.robot import CoordData

if TYPE_CHECKING:
    from srci_py_hmi.ui.pendant import Pendant

TOOL, FRAME = "tool", "frame"


def label(p: Pendant, kind: str, no: int) -> str:
    """``T1 Gripper`` / ``F0 Base``."""
    prefix = "T" if kind == TOOL else "F"
    name = p.ws.labels.get(kind, {}).get(str(no), "")
    if no == 0 and not name:
        name = p.tr("coord.flange" if kind == TOOL else "coord.base")
    return f"{prefix}{no} {name}".strip()


def options(p: Pendant, kind: str) -> dict[int, str]:
    """Select options 0..highest (names from the read table and the local labels)."""
    highest = p.snap.highest_tool if kind == TOOL else p.snap.highest_frame
    table = p.ws.tools if kind == TOOL else p.ws.frames
    count = max(highest + 1, len(table), 1)
    return {no: label(p, kind, no) for no in range(count)}


def _values(data: CoordData) -> str:
    return "   ".join(f"{n} {v:.1f}" for n, v in zip(CARTESIAN, data.values, strict=True))


class CoordPage:
    """One page (tools or frames)."""

    def __init__(self, p: Pendant, kind: str) -> None:
        self.p = p
        self.kind = kind

    @property
    def function(self) -> str:
        return "ToolData" if self.kind == TOOL else "FrameData"

    @property
    def can_read(self) -> bool:
        return self.p.snap.can(f"Read{self.function}")

    @property
    def can_write(self) -> bool:
        return self.p.snap.can(f"Write{self.function}")

    @property
    def table(self) -> list[CoordData]:
        return self.p.ws.tools if self.kind == TOOL else self.p.ws.frames

    def build(self) -> None:
        p = self.p
        with ui.column().classes("tp-page"):
            with ui.row().classes("w-full items-end justify-between gap-3"):
                p.page_title(p.tr(f"{self.kind}s.title"), p.tr(f"{self.kind}s.lead"))
                self.read_btn = (
                    ui.button(p.tr("coord.read"), icon="sync", on_click=self.read)
                    .props("flat no-caps")
                    .classes("tp-btn-soft")
                )
            with p.card():
                self.draw()

    async def read(self) -> None:
        reader = self.p.robot.read_tools if self.kind == TOOL else self.p.robot.read_frames
        table = await self.p.act(reader)
        if table is None:
            return
        if self.kind == TOOL:
            self.p.ws.tools = table
        else:
            self.p.ws.frames = table
        self.p.ws.coord_revision += 1

    @ui.refreshable_method
    def draw(self) -> None:
        p = self.p
        missing = [
            f"{rw}{self.function}"
            for rw, ok in (("Read", self.can_read), ("Write", self.can_write))
            if not ok
        ]
        if missing:
            ui.label(p.tr("caps.not_supported", f=", ".join(missing))).classes("tp-banner w-full mb-2")
        if not self.table:
            ui.label(p.tr("coord.none")).classes("tp-empty w-full")
            return
        active = p.snap.tool if self.kind == TOOL else p.snap.frame
        for data in self.table:
            with ui.element("div").classes("tp-item" + (" current" if data.no == active else "")):
                ui.label(f"{'T' if self.kind == TOOL else 'F'}{data.no}").classes("tp-badge")
                with ui.column().classes("gap-0 flex-1 min-w-0"):
                    with ui.row().classes("items-center gap-2"):
                        ui.label(label(p, self.kind, data.no).split(" ", 1)[-1] or "–").classes(
                            "font-semibold"
                        )
                        if data.no == active:
                            ui.label(p.tr("coord.active")).classes("tp-chip ptp")
                    extra = (
                        f"   {p.tr('coord.load')} {data.load_no}" + ("   ext." if data.external_tcp else "")
                        if self.kind == TOOL
                        else f"   ↳ F{data.reference}"
                    )
                    ui.label(_values(data) + (extra if data.no else "")).classes("tp-muted tp-mono truncate")
                if data.no != active:
                    ui.button(p.tr("coord.use"), on_click=lambda n=data.no: self.use(n)).props(
                        "flat no-caps dense"
                    ).classes("tp-btn-soft px-3")
                if data.no == 0 or not self.can_write:
                    ui.icon("lock").classes("text-[var(--text-3)]").tooltip(p.tr("coord.fixed"))
                else:
                    ui.button(icon="edit", on_click=lambda d=data: self.edit(d)).props(
                        "flat round dense"
                    ).classes("text-[var(--blue)]").tooltip(p.tr("coord.edit")).mark(
                        f"edit-{self.kind}-{data.no}"
                    )

    async def use(self, no: int) -> None:
        robot = self.p.robot
        tool, frame = (no, robot.tool) if self.kind == TOOL else (robot.tool, no)
        await self.p.act(robot.set_coordinate_system, tool, frame)
        self.p.ws.coord_revision += 1

    async def edit(self, data: CoordData) -> None:
        p = self.p
        d = copy.deepcopy(data)
        name = p.ws.labels.get(self.kind, {}).get(str(d.no), "")
        title = label(p, self.kind, d.no)
        with ui.dialog() as dialog, ui.card().classes("min-w-[340px] max-w-[560px] w-full gap-3"):
            ui.label(title).classes("text-[20px] font-semibold")
            name_in = ui.input(p.tr("coord.name"), value=name).props("filled").classes("w-full")
            inputs = []
            with ui.element("div").classes("grid grid-cols-3 gap-3 w-full"):
                for n, v in zip(CARTESIAN, d.values, strict=True):
                    unit = "mm" if n in ("X", "Y", "Z") else "°"
                    inputs.append(
                        ui.number(n, value=round(v, 3), format="%.3f", suffix=unit)
                        .props("filled")
                        .classes("tp-mono-in")
                    )
            if self.kind == TOOL:
                load = ui.number(p.tr("coord.load"), value=d.load_no, min=0, max=255, precision=0).props(
                    "filled"
                )
                ext = ui.switch(p.tr("coord.external"), value=d.external_tcp)
            else:
                ref = (
                    ui.select(
                        {k: v for k, v in options(p, FRAME).items() if k != d.no},
                        value=d.reference,
                        label=p.tr("coord.reference"),
                    )
                    .props("filled")
                    .classes("w-full")
                )

                async def take_tcp() -> None:
                    values = await p.act(p.robot.read_position, p.robot.tool, int(ref.value or 0))
                    if values is not None:
                        for field, value in zip(inputs, values, strict=True):
                            field.set_value(round(value, 3))

                ui.button(p.tr("coord.from_tcp"), icon="my_location", on_click=take_tcp).props(
                    "flat no-caps"
                ).classes("tp-btn-soft self-start").tooltip(p.tr("coord.from_tcp_hint"))
            with ui.row().classes("w-full justify-end gap-2 mt-2"):
                ui.button(p.tr("common.cancel"), on_click=lambda: dialog.submit(False)).props("flat no-caps")
                ui.button(p.tr("coord.write"), on_click=lambda: dialog.submit(True)).props(
                    "unelevated no-caps color=primary"
                ).mark("coord-write")
        if not await dialog:
            return
        d.values = [float(i.value or 0.0) for i in inputs]
        if self.kind == TOOL:
            d.load_no, d.external_tcp = int(load.value or 0), bool(ext.value)
            writer: Callable[[CoordData], None] = p.robot.write_tool
            reader: Callable[[], list[CoordData]] = p.robot.read_tools
        else:
            d.reference = int(ref.value or 0)
            writer, reader = p.robot.write_frame, p.robot.read_frames
        self.save_label(d.no, str(name_in.value or "").strip())

        def write() -> bool:
            writer(d)
            return True

        if not await p.act(write, done=p.tr("coord.saved", name=label(p, self.kind, d.no))):
            return
        table = await p.act(reader)
        if table is not None:
            if self.kind == TOOL:
                p.ws.tools = table
            else:
                p.ws.frames = table
        p.ws.coord_revision += 1

    def save_label(self, no: int, name: str) -> None:
        labels = self.p.ws.labels.setdefault(self.kind, {})
        if name:
            labels[str(no)] = name
        else:
            labels.pop(str(no), None)
        self.p.ws.save_labels()


def load_labels(path: Any) -> dict[str, dict[str, str]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {k: {str(n): str(v) for n, v in d.items()} for k, d in data.items() if isinstance(d, dict)}
