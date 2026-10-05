"""Page "System": data of the robot controller - dynamics, software limits, DH parameters, system
variables (standardized parameter list) and a kinematics calculator."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nicegui import ui

from srci_py_hmi import sysvars
from srci_py_hmi.model import CARTESIAN, JOINTS
from srci_py_hmi.robot import Dynamics, Phase
from srci_py_hmi.ui import coords

if TYPE_CHECKING:
    from srci_py_hmi.ui.pendant import Pendant

DYN_NAMES = ("step.vel", "step.acc", "step.dec", "step.jerk")
REF_UNITS = ("mm/s", "mm/s²", "mm/s²", "mm/s³")


class SystemPage:
    def __init__(self, p: Pendant) -> None:
        self.p = p
        self.dynamics: Dynamics | None = None
        self.limits: list[tuple[float, float]] | None = None
        self.dh: dict[str, list[float]] | None = None
        self.var: dict[str, Any] = {"id": 7, "rc": False, "custom_id": 1, "custom_sub": 1, "custom_type": sysvars.REAL}
        self.var_values: list[sysvars.Value] = []
        self.limit_bars: list[tuple[ui.element, ui.label]] = []
        self.buttons: list[tuple[ui.button, str]] = []

    def button(self, text: str, icon: str, handler: Any, function: str, primary: bool = False) -> ui.button:
        b = ui.button(text, icon=icon, on_click=handler).props(
            "unelevated no-caps color=primary" if primary else "flat no-caps"
        )
        if not primary:
            b.classes("tp-btn-soft")
        self.buttons.append((b, function))
        return b

    def build(self) -> None:
        p = self.p
        with ui.column().classes("tp-page"):
            p.page_title(p.tr("sys.title"), p.tr("sys.lead"))
            with ui.element("div").classes("grid w-full gap-5 items-start lg:grid-cols-2"):
                with ui.column().classes("gap-5 w-full"):
                    with p.card(p.tr("dyn.title")):
                        self.draw_dynamics()
                        with ui.row().classes("w-full gap-2 mt-3"):
                            self.button(p.tr("coord.read"), "sync", self.read_dynamics, "ReadRobotDefaultDynamics")
                            ui.space()
                            self.button(p.tr("coord.write"), "upload", self.write_dynamics,
                                        "WriteRobotDefaultDynamics", primary=True).mark("dyn-write")  # fmt: skip
                    with p.card(p.tr("kin.title")):
                        self.build_kinematics()
                    with p.card(p.tr("dh.title")):
                        self.draw_dh()
                        with ui.row().classes("w-full mt-3"):
                            self.button(p.tr("coord.read"), "sync", self.read_dh, "ReadDHParameter")
                with ui.column().classes("gap-5 w-full"):
                    with p.card(p.tr("lim.title")):
                        ui.label(p.tr("lim.lead")).classes("tp-muted mb-2")
                        self.draw_limits()
                        with ui.row().classes("w-full gap-2 mt-3"):
                            self.button(p.tr("coord.read"), "sync", self.read_limits, "ReadRobotSWLimits")
                            ui.space()
                            self.button(p.tr("lim.factory"), "restart_alt", self.factory_limits, "WriteRobotSWLimits")
                            self.button(p.tr("lim.edit"), "edit", self.edit_limits, "WriteRobotSWLimits",
                                        primary=True).mark("lim-edit")  # fmt: skip
                    with p.card(p.tr("var.title")):
                        self.build_variables()

    def tick(self) -> None:
        s = self.p.snap
        ready = s.phase is Phase.READY
        for b, function in self.buttons:
            b.set_enabled(ready and s.can(function))
        limits = self.limits
        if limits is None:
            return
        for i, (marker, value) in enumerate(self.limit_bars):
            lo, hi = limits[i]
            j = s.joints[i]
            pos = 0.0 if hi <= lo else min(100.0, max(0.0, (j - lo) / (hi - lo) * 100.0))
            near = hi > lo and min(j - lo, hi - j) < 0.05 * (hi - lo)
            self.p.put(marker, "style", f"left: calc({pos:.1f}% - 2px)")
            self.p.put(marker, "classes", "tp-limit-marker" + (" near" if near else ""))
            value.set_text(f"{j:.1f}°" if s.position_valid else "–")

    # ------------------------------------------------------------------ dynamics

    @ui.refreshable_method
    def draw_dynamics(self) -> None:
        p = self.p
        d = self.dynamics
        if d is None:
            ui.label(p.tr("sys.not_read")).classes("tp-empty w-full")
            return
        with ui.element("div").classes("grid grid-cols-[1fr_auto_auto] gap-x-6 w-full"):
            ui.label("").classes("tp-card-title")
            ui.label(p.tr("dyn.default")).classes("tp-card-title text-right")
            ui.label(p.tr("dyn.reference")).classes("tp-card-title text-right")
            self.dyn_inputs: list[ui.number] = []
            self.ref_inputs: list[ui.number] = []
            for i, key in enumerate(DYN_NAMES):
                ui.label(p.tr(key)).classes("font-medium self-center")
                self.dyn_inputs.append(ui.number(value=round(d.default[i], 2), min=1, max=100, suffix="%")
                                       .props("filled dense").classes("w-28 tp-mono-in"))  # fmt: skip
                self.ref_inputs.append(ui.number(value=round(d.reference[i], 2), min=0, suffix=REF_UNITS[i])
                                       .props("filled dense").classes("w-40 tp-mono-in"))  # fmt: skip
        ui.label(p.tr("dyn.hint")).classes("tp-muted mt-2")

    async def read_dynamics(self) -> None:
        d = await self.p.act(self.p.robot.read_dynamics)
        if d is not None:
            self.dynamics = d
            self.draw_dynamics.refresh()

    async def write_dynamics(self) -> None:
        if self.dynamics is None:
            await self.read_dynamics()
            return
        default = [float(f.value or 0) for f in self.dyn_inputs]
        reference = [float(f.value or 0) for f in self.ref_inputs]
        robot = self.p.robot

        def write() -> bool:
            assert self.dynamics is not None
            if default != self.dynamics.default:
                robot.write_default_dynamics(default)
            if reference != self.dynamics.reference:
                robot.write_reference_dynamics(reference)
            return True

        if await self.p.act(write, done=self.p.tr("sys.written")):
            await self.read_dynamics()

    # ------------------------------------------------------------------ software limits

    @ui.refreshable_method
    def draw_limits(self) -> None:
        p = self.p
        self.limit_bars = []
        if self.limits is None:
            ui.label(p.tr("sys.not_read")).classes("tp-empty w-full")
            return
        for name, (lo, hi) in zip(JOINTS, self.limits, strict=True):
            with ui.element("div").classes("tp-limit-row"):
                ui.label(name).classes("font-semibold")
                ui.label(f"{lo:.1f}°").classes("tp-mono tp-muted text-right")
                with ui.element("div").classes("tp-limit"):
                    marker = ui.element("div").classes("tp-limit-marker")
                ui.label(f"{hi:.1f}°").classes("tp-mono tp-muted")
                value = ui.label("–").classes("tp-mono text-right font-medium")
                self.limit_bars.append((marker, value))

    async def read_limits(self) -> None:
        limits = await self.p.act(self.p.robot.read_sw_limits)
        if limits is not None:
            self.limits = limits
            self.draw_limits.refresh()

    async def edit_limits(self) -> None:
        p = self.p
        if self.limits is None:
            await self.read_limits()
            if self.limits is None:
                return
        fields: list[tuple[ui.number, ui.number]] = []
        with ui.dialog() as dialog, ui.card().classes("w-full max-w-[520px] gap-3"):
            ui.label(p.tr("lim.title")).classes("text-[20px] font-semibold")
            ui.label(p.tr("lim.warning")).classes("tp-banner w-full")
            for name, (lo, hi) in zip(JOINTS, self.limits, strict=True):
                with ui.row().classes("w-full items-center gap-3 no-wrap"):
                    ui.label(name).classes("w-10 font-semibold")
                    fields.append((
                        ui.number(p.tr("lim.lower"), value=lo, suffix="°").props("filled dense").classes("flex-1 tp-mono-in"),
                        ui.number(p.tr("lim.upper"), value=hi, suffix="°").props("filled dense").classes("flex-1 tp-mono-in"),
                    ))  # fmt: skip
            with ui.row().classes("w-full justify-end gap-2"):
                ui.button(p.tr("common.cancel"), on_click=lambda: dialog.submit(False)).props("flat no-caps")
                ui.button(p.tr("coord.write"), on_click=lambda: dialog.submit(True)).props(
                    "unelevated no-caps color=negative"
                ).mark("lim-write")
        if not await dialog:
            return
        limits = [(float(a.value or 0), float(b.value or 0)) for a, b in fields]
        restart = await p.act(p.robot.write_sw_limits, limits)
        if restart is not None:
            ui.notify(p.tr("sys.restart") if restart else p.tr("sys.written"),
                      type="warning" if restart else "positive", position="top")  # fmt: skip
            await self.read_limits()

    async def factory_limits(self) -> None:
        if not await self.p.confirm(self.p.tr("lim.factory_confirm"), danger=True):
            return
        restart = await self.p.act(self.p.robot.write_sw_limits, [], True)
        if restart is not None:
            ui.notify(self.p.tr("sys.restart") if restart else self.p.tr("sys.written"), position="top")
            await self.read_limits()

    # ------------------------------------------------------------------ DH parameters

    @ui.refreshable_method
    def draw_dh(self) -> None:
        p = self.p
        if self.dh is None:
            ui.label(p.tr("sys.not_read")).classes("tp-empty w-full")
            return
        cols = (("alpha", "α [°]"), ("a", "a [mm]"), ("d", "d [mm]"), ("theta", "θ [°]"), ("zero", p.tr("dh.zero")),
                ("direction", p.tr("dh.direction")))  # fmt: skip
        with ui.element("div").classes("grid grid-cols-7 gap-x-3 gap-y-1 w-full tp-mono text-[14px]"):
            ui.label("")
            for _, title in cols:
                ui.label(title).classes("tp-card-title text-right")
            for i, name in enumerate(JOINTS):
                ui.label(name).classes("font-semibold")
                for key, _ in cols:
                    value = self.dh[key][i]
                    text = ("+" if value > 0 else "−") if key == "direction" else f"{value:.2f}"
                    ui.label(text).classes("text-right")

    async def read_dh(self) -> None:
        dh = await self.p.act(self.p.robot.read_dh)
        if dh is not None:
            self.dh = dh
            self.draw_dh.refresh()

    # ------------------------------------------------------------------ system variables

    def build_variables(self) -> None:
        p = self.p
        options = {par.id: f"{par.id} · {par.name(p.lang)}" for par in sysvars.PARAMETERS}
        with ui.row().classes("w-full items-center gap-3 no-wrap"):
            ui.select(options, value=self.var["id"], label=p.tr("var.parameter"), with_input=True).bind_value(
                self.var, "id"
            ).props("filled dense options-dense").classes("flex-1").bind_visibility_from(self.var, "rc", lambda v: not v)
            ui.switch(p.tr("var.rc"), value=False).bind_value(self.var, "rc").tooltip(p.tr("var.rc_hint"))
        with ui.row().classes("w-full items-center gap-3 no-wrap").bind_visibility_from(self.var, "rc"):
            ui.number("ID", value=1, min=0, max=65535, precision=0).bind_value(self.var, "custom_id").props(
                "filled dense"
            ).classes("w-28 tp-mono-in")
            ui.number(p.tr("var.sub"), value=1, min=0, max=255, precision=0).bind_value(self.var, "custom_sub").props(
                "filled dense"
            ).classes("w-28 tp-mono-in")
            ui.select(sysvars.TYPE_NAMES, value=sysvars.REAL, label=p.tr("var.type")).bind_value(
                self.var, "custom_type"
            ).props("filled dense").classes("w-36")
        with ui.row().classes("w-full gap-2 mt-2"):
            self.button(p.tr("coord.read"), "download", self.read_variable, "ReadSystemVariable").mark("var-read")
            ui.space()
            self.button(p.tr("var.edit"), "edit", self.edit_variable, "WriteSystemVariable")
        self.draw_variable()

    def parameter(self) -> sysvars.Parameter:
        if self.var["rc"]:
            sub = int(self.var["custom_sub"] or 0)
            return sysvars.Parameter(int(self.var["custom_id"] or 0), "RC", "RC", (str(sub),),
                                     int(self.var["custom_type"]), writable=True)  # fmt: skip
        return sysvars.BY_ID[int(self.var["id"])]

    def subs(self, par: sysvars.Parameter) -> list[int]:
        if self.var["rc"]:
            return [int(self.var["custom_sub"] or 0)]
        return list(range(1, len(par.subs) + 1))

    @ui.refreshable_method
    def draw_variable(self) -> None:
        p = self.p
        if not self.var_values:
            ui.label(p.tr("var.none")).classes("tp-empty w-full")
            return
        par = self.parameter()
        if par.text:
            with ui.element("div").classes("tp-row"):
                ui.label(par.name(p.lang)).classes("tp-key")
                ui.label(sysvars.text_of(self.var_values) or "–").classes("tp-val tp-mono")
            return
        for value in self.var_values:
            name = par.subs[value.sub - 1] if 0 < value.sub <= len(par.subs) else str(value.sub)
            with ui.element("div").classes("tp-row"):
                ui.label(name).classes("tp-key")
                type_name = sysvars.TYPE_NAMES.get(value.data_type, str(value.data_type))
                ui.label(f"{value.decode()} {par.unit}".strip()).classes("tp-val tp-mono").tooltip(
                    f"{type_name} · {value.raw.hex(' ')}"
                )

    async def read_variable(self) -> None:
        par = self.parameter()
        values = await self.p.act(self.p.robot.read_system_variable, par.id, self.subs(par), bool(self.var["rc"]))
        if values is not None:
            self.var_values = values
            self.draw_variable.refresh()

    async def edit_variable(self) -> None:
        p = self.p
        par = self.parameter()
        if not par.writable:
            ui.notify(p.tr("var.read_only"), type="warning", position="top")
            return
        if not self.var_values:
            await self.read_variable()
        current = {v.sub: v.decode() for v in self.var_values}
        fields: dict[int, ui.input] = {}
        with ui.dialog() as dialog, ui.card().classes("w-full max-w-[520px] gap-3"):
            ui.label(f"{par.id} · {par.name(p.lang)}").classes("text-[20px] font-semibold")
            if par.text:
                text = ui.input(p.tr("common.name"), value=sysvars.text_of(self.var_values)).props("filled")
            else:
                for sub in self.subs(par):
                    label = par.subs[sub - 1] if 0 < sub <= len(par.subs) else str(sub)
                    fields[sub] = ui.input(f"{label} {par.unit}".strip(), value=str(current.get(sub, ""))).props(
                        "filled dense"
                    ).classes("tp-mono-in")
            with ui.row().classes("w-full justify-end gap-2"):
                ui.button(p.tr("common.cancel"), on_click=lambda: dialog.submit(False)).props("flat no-caps")
                ui.button(p.tr("coord.write"), on_click=lambda: dialog.submit(True)).props(
                    "unelevated no-caps color=primary"
                )
        if not await dialog:
            return
        try:
            if par.text:
                raw = str(text.value or "").encode("latin-1")[: 4 * len(par.subs)].ljust(4 * len(par.subs), b"\0")
                values = [sysvars.Value(i + 1, sysvars.CHARS, raw[4 * i : 4 * i + 4]) for i in range(len(par.subs))]
            else:
                values = [sysvars.Value.encode(sub, par.data_type, f.value) for sub, f in fields.items()]
        except (ValueError, UnicodeEncodeError) as exc:
            ui.notify(str(exc), type="negative", position="top")
            return
        restart = await p.act(p.robot.write_system_variable, par.id, values, bool(self.var["rc"]))
        if restart is not None:
            ui.notify(p.tr("sys.restart") if restart else p.tr("sys.written"), position="top")
            await self.read_variable()

    # ------------------------------------------------------------------ kinematics

    def build_kinematics(self) -> None:
        p = self.p
        ui.label(p.tr("kin.lead")).classes("tp-muted mb-2")
        kin: dict[str, Any] = {"tool": p.robot.tool, "frame": p.robot.frame}
        with ui.row().classes("w-full gap-3 no-wrap"):
            ui.select(coords.options(p, coords.TOOL), value=kin["tool"], label=p.tr("coord.tool")).bind_value(
                kin, "tool"
            ).props("filled dense").classes("flex-1")
            ui.select(coords.options(p, coords.FRAME), value=kin["frame"], label=p.tr("coord.frame")).bind_value(
                kin, "frame"
            ).props("filled dense").classes("flex-1")
        ui.label(p.tr("pos.joints")).classes("tp-card-title mt-2")
        with ui.element("div").classes("grid grid-cols-3 gap-2 w-full"):
            joints = [ui.number(n, value=0.0, format="%.3f", suffix="°").props("filled dense").classes("tp-mono-in")
                      for n in JOINTS]  # fmt: skip
        ui.label(p.tr("pos.tcp")).classes("tp-card-title mt-2")
        with ui.element("div").classes("grid grid-cols-3 gap-2 w-full"):
            cart = [ui.number(n, value=0.0, format="%.3f", suffix="mm" if i < 3 else "°").props("filled dense")
                    .classes("tp-mono-in") for i, n in enumerate(CARTESIAN)]  # fmt: skip

        def take() -> None:
            s = p.snap
            for f, v in zip(joints, s.joints, strict=True):
                f.set_value(round(v, 3))
            for f, v in zip(cart, s.cartesian, strict=True):
                f.set_value(round(v, 3))
            kin["tool"], kin["frame"] = s.tool, s.frame

        async def forward() -> None:
            values = await p.act(p.robot.forward_kinematics, [float(f.value or 0) for f in joints],
                                 int(kin["tool"]), int(kin["frame"]))  # fmt: skip
            if values is not None:
                for f, v in zip(cart, values, strict=True):
                    f.set_value(round(v, 3))

        async def inverse() -> None:
            values = await p.act(p.robot.inverse_kinematics, [float(f.value or 0) for f in cart],
                                 int(kin["tool"]), int(kin["frame"]))  # fmt: skip
            if values is not None:
                for f, v in zip(joints, values, strict=True):
                    f.set_value(round(v, 3))

        with ui.row().classes("w-full gap-2 mt-3"):
            ui.button(p.tr("kin.take"), icon="my_location", on_click=take).props("flat no-caps").classes("tp-btn-soft")
            self.button(p.tr("kin.forward"), "south", forward, "CalculateForwardKinematic").mark("kin-forward")
            self.button(p.tr("kin.inverse"), "north", inverse, "CalculateInverseKinematic")
