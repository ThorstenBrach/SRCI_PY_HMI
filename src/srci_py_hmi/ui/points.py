"""Dialogs for taught points: edit the values (with the kinematics of the RC) and shift / mirror /
rotate a point (ShiftPosition)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nicegui import ui
from srci.types import ReferenceElement, TransformMode

from srci_py_hmi.model import CARTESIAN, JOINTS, Point
from srci_py_hmi.ui import coords

if TYPE_CHECKING:
    from srci_py_hmi.ui.pendant import Pendant

# ShiftPosition modes (manual 6.9.6) and what their parameter means
SHIFT_MODES = {
    "SHIFT_BY_VECTOR": TransformMode.SHIFT_BY_VECTOR,
    "MIRROR_AT_POINT": TransformMode.MIRROR_AT_POINT,
    "MIRROR_AT_STRAIGHT_LINE": TransformMode.MIRROR_AT_STRAIGHT_LINE,
    "MIRROR_AT_PLANE": TransformMode.MIRROR_AT_PLANE,
    "ROTATE_AROUND_STRAIGHT_LINE": TransformMode.ROTATE_AROUND_STRAIGHT_LINE,
}
LINES = {"X_AXIS": ReferenceElement.X_AXIS, "Y_AXIS": ReferenceElement.Y_AXIS, "Z_AXIS": ReferenceElement.Z_AXIS}
PLANES = {"XY_PLANE": ReferenceElement.XY_PLANE, "XZ_PLANE": ReferenceElement.XZ_PLANE,
          "YZ_PLANE": ReferenceElement.YZ_PLANE}  # fmt: skip


def _numbers(values: list[float], names: tuple[str, ...], joint: bool) -> list[ui.number]:
    fields = []
    with ui.element("div").classes("grid grid-cols-3 gap-3 w-full"):
        for i, (n, v) in enumerate(zip(names, values, strict=True)):
            unit = "°" if joint or i >= 3 else "mm"
            fields.append(ui.number(n, value=round(v, 3), format="%.3f", suffix=unit).props("filled dense")
                          .classes("tp-mono-in"))  # fmt: skip
    return fields


async def edit_point(p: Pendant, name: str) -> None:
    """Edit name, Cartesian position, joints, tool and frame of a point."""
    point = p.ws.program.point(name)
    v: dict[str, Any] = {"name": point.name, "tool": point.tool, "frame": point.frame, "note": point.note}
    with p.dialog() as dialog, ui.card().classes("w-full max-w-[620px] gap-3"):
        with ui.row().classes("w-full items-center gap-3 no-wrap"):
            ui.icon("place").classes("text-[26px] text-[var(--blue)]")
            ui.input(p.tr("common.name"), value=v["name"]).bind_value(v, "name").props("filled dense").classes(
                "flex-1 text-[18px]"
            )
        ui.label(p.tr("pos.tcp")).classes("tp-card-title mt-1")
        cart = _numbers(point.cartesian, CARTESIAN, False)
        with ui.row().classes("w-full gap-3 no-wrap"):
            ui.select(coords.options(p, coords.TOOL, v["tool"]), value=v["tool"], label=p.tr("coord.tool")).bind_value(
                v, "tool"
            ).props("filled dense").classes("flex-1")
            ui.select(coords.options(p, coords.FRAME, v["frame"]), value=v["frame"], label=p.tr("coord.frame")).bind_value(
                v, "frame"
            ).props("filled dense").classes("flex-1")
        ui.label(p.tr("point.coord_warning")).classes("tp-muted")
        ui.label(p.tr("pos.joints")).classes("tp-card-title mt-1")
        joints = _numbers(point.joints, JOINTS, True)

        async def from_joints() -> None:
            values = await p.act(p.robot.forward_kinematics, [float(f.value or 0) for f in joints],
                                 int(v["tool"]), int(v["frame"]))  # fmt: skip
            if values is not None:
                for f, x in zip(cart, values, strict=True):
                    f.set_value(round(x, 3))

        async def from_cart() -> None:
            values = await p.act(p.robot.inverse_kinematics, [float(f.value or 0) for f in cart],
                                 int(v["tool"]), int(v["frame"]))  # fmt: skip
            if values is not None:
                for f, x in zip(joints, values, strict=True):
                    f.set_value(round(x, 3))

        async def take_actual() -> None:
            # the actual position in the tool / frame chosen above (the robot reads it in its own)
            position = await p.act(p.robot.current_position)
            if position is None:
                return
            for f, x in zip(joints, position[0], strict=True):
                f.set_value(round(x, 3))
            if (int(v["tool"]), int(v["frame"])) == (p.robot.tool, p.robot.frame):
                values = position[1]
            else:
                values = await p.act(p.robot.read_position, int(v["tool"]), int(v["frame"]))
                if values is None:
                    return
            for f, x in zip(cart, values, strict=True):
                f.set_value(round(x, 3))

        with ui.row().classes("w-full gap-2"):
            ui.button(p.tr("target.take"), icon="my_location", on_click=take_actual).props(
                "flat no-caps"
            ).classes("tp-btn-soft").mark("point-take")
            ui.button(p.tr("point.calc_joints"), icon="calculate", on_click=from_cart).props(
                "flat no-caps"
            ).classes("tp-btn-soft").set_enabled(p.snap.can("CalculateInverseKinematic"))
            ui.button(p.tr("point.calc_cart"), icon="calculate", on_click=from_joints).props(
                "flat no-caps"
            ).classes("tp-btn-soft").set_enabled(p.snap.can("CalculateForwardKinematic"))
        pad = coords.jog_expansion(p)
        ui.input(p.tr("step.note"), value=v["note"]).bind_value(v, "note").props("filled dense").classes("w-full")
        with ui.row().classes("w-full justify-end gap-2"):
            ui.button(p.tr("common.cancel"), on_click=lambda: dialog.submit(False)).props("flat no-caps")
            ui.button(p.tr("common.save"), on_click=lambda: dialog.submit(True)).props(
                "unelevated no-caps color=primary"
            ).mark("point-save")
    try:
        confirmed = await dialog
    finally:
        pad.close()
    if not confirmed:
        return
    try:
        if v["name"] != point.name:
            p.ws.program.rename_point(point.name, str(v["name"]))
    except ValueError as exc:
        ui.notify(str(exc), type="negative", position="top")
        return
    point.cartesian = [float(f.value or 0.0) for f in cart]
    point.joints = [float(f.value or 0.0) for f in joints]
    point.tool, point.frame, point.note = int(v["tool"]), int(v["frame"]), str(v["note"] or "")
    p.ws.changed()


async def shift_point(p: Pendant, name: str) -> None:
    """Shift, mirror or rotate a point with the RC (ShiftPosition); the result is a new point (its
    joints from the inverse kinematics) or replaces the point."""
    point = p.ws.program.point(name)
    v: dict[str, Any] = {"mode": "SHIFT_BY_VECTOR", "line": "Z_AXIS", "plane": "XY_PLANE", "angle": 90.0,
                         "new": True}  # fmt: skip
    with p.dialog() as dialog, ui.card().classes("w-full max-w-[620px] gap-3"):
        ui.label(p.tr("shift.title", name=name)).classes("text-[22px] font-bold")
        ui.select({k: p.tr(f"shift.{k}") for k in SHIFT_MODES}, value=v["mode"], label=p.tr("shift.mode")).bind_value(
            v, "mode"
        ).props("filled").classes("w-full").mark("shift-mode")
        ui.label().bind_text_from(v, "mode", lambda m: p.tr(f"shift.{m}_hint")).classes("tp-muted -mt-1")
        params = _numbers([0.0] * 6, CARTESIAN, False)
        with ui.row().classes("w-full gap-3 no-wrap"):
            ui.select({k: p.tr(f"shift.{k}") for k in LINES}, value=v["line"], label=p.tr("shift.line")).bind_value(
                v, "line"
            ).props("filled dense").classes("flex-1").bind_visibility_from(
                v, "mode", lambda m: m in ("MIRROR_AT_STRAIGHT_LINE", "ROTATE_AROUND_STRAIGHT_LINE")
            )
            ui.select({k: p.tr(f"shift.{k}") for k in PLANES}, value=v["plane"], label=p.tr("shift.plane")).bind_value(
                v, "plane"
            ).props("filled dense").classes("flex-1").bind_visibility_from(v, "mode", lambda m: m == "MIRROR_AT_PLANE")
            ui.number(p.tr("shift.angle"), value=v["angle"], suffix="°").bind_value(v, "angle").props(
                "filled dense"
            ).classes("w-36 tp-mono-in").bind_visibility_from(v, "mode", lambda m: m == "ROTATE_AROUND_STRAIGHT_LINE")
        ui.toggle({True: p.tr("shift.as_new"), False: p.tr("shift.replace")}, value=True).bind_value(
            v, "new"
        ).props("no-caps unelevated").classes("tp-seg self-start")
        with ui.row().classes("w-full justify-end gap-2"):
            ui.button(p.tr("common.cancel"), on_click=lambda: dialog.submit(False)).props("flat no-caps")
            ui.button(p.tr("shift.apply"), on_click=lambda: dialog.submit(True)).props(
                "unelevated no-caps color=primary"
            ).mark("shift-apply")
    if not await dialog:
        return
    mode = str(v["mode"])
    element = (LINES[v["line"]] if mode in ("MIRROR_AT_STRAIGHT_LINE", "ROTATE_AROUND_STRAIGHT_LINE")
               else PLANES[v["plane"]] if mode == "MIRROR_AT_PLANE" else ReferenceElement.NOT_USED)  # fmt: skip
    cart = await p.act(p.robot.shift_position, SHIFT_MODES[mode], point.cartesian, point.frame,
                       [float(f.value or 0.0) for f in params], element, float(v["angle"] or 0.0))  # fmt: skip
    if cart is None:
        return
    joints = point.joints
    if p.snap.can("CalculateInverseKinematic"):
        result = await p.act(p.robot.inverse_kinematics, cart, point.tool, point.frame)
        if result is None:
            return
        joints = result
    else:
        ui.notify(p.tr("shift.no_ik"), type="warning", position="top", multi_line=True)
    if v["new"]:
        new = p.ws.program.add_point(joints, cart, name=_free_name(p, f"{name}'"), tool=point.tool,
                                     frame=point.frame)  # fmt: skip
        ui.notify(p.tr("shift.created", name=new.name), type="positive", position="top")
    else:
        point.cartesian, point.joints = cart, joints
    p.ws.changed()


def _free_name(p: Pendant, base: str) -> str:
    names = {pt.name for pt in p.ws.program.points}
    name, n = base, 2
    while name in names:
        name, n = f"{base}{n}", n + 1
    return name


def home_point(joints: list[float], cartesian: list[float], tool: int, frame: int) -> Point:
    return Point("Home", list(joints), list(cartesian), tool, frame)
