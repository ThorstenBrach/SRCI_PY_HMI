"""The teach pendant page (one instance per browser tab, one robot for all tabs)."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from nicegui import app, background_tasks, run, ui
from srci.types import JogMode

from srci_teach.i18n import LANGUAGES, t
from srci_teach.model import CARTESIAN, JOINTS, Motion, Program
from srci_teach.robot import (
    CORE_FUNCTIONS,
    MOTION_FUNCTIONS,
    Activity,
    CoordData,
    Phase,
    RobotService,
    Snapshot,
    Target,
)
from srci_teach.ui import coords
from srci_teach.ui.step_editor import blend_label, edit_step, motion_label
from srci_teach.ui.theme import COLORS, CSS, HOLD_JS

log = logging.getLogger("srci_teach.ui")

# value range of the position bars (joints [deg], X/Y/Z [mm], Rx/Ry/Rz [deg])
JOINT_RANGE = 360.0
CART_RANGES = (1000.0, 1000.0, 1000.0, 180.0, 180.0, 180.0)
INCREMENTS = {"0": 0.0, "0.1": 0.1, "1": 1.0, "10": 10.0}
JOG_MODES = {"axes": JogMode.JOG_AXES, "base": JogMode.JOG_FRAME, "tool": JogMode.JOG_TOOL}


@dataclass
class Workspace:
    """State shared by all tabs: the robot, the open program and where it is stored."""

    robot: RobotService
    programs_dir: Path
    target: Target = field(default_factory=Target)
    program: Program = field(default_factory=Program)
    path: Path | None = None
    dirty: bool = False
    revision: int = 0  # changed program -> every tab redraws its lists
    tools: list[CoordData] = field(default_factory=list)  # last read tables of the RC
    frames: list[CoordData] = field(default_factory=list)
    coord_revision: int = 0  # changed tools / frames / active coordinate system
    labels: dict[str, dict[str, str]] = field(default_factory=dict)  # local names of tools / frames
    loading_coords: bool = False
    coords_tried: bool = False  # tools / frames read after the current connection

    def __post_init__(self) -> None:
        self.labels = coords.load_labels(self.labels_path)

    @property
    def labels_path(self) -> Path:
        return self.programs_dir / "labels.json"

    def save_labels(self) -> None:
        import json

        self.programs_dir.mkdir(parents=True, exist_ok=True)
        self.labels_path.write_text(json.dumps(self.labels, indent=2, ensure_ascii=False), encoding="utf-8")

    def changed(self) -> None:
        self.dirty = True
        self.revision += 1

    def files(self) -> list[Path]:
        if not self.programs_dir.is_dir():
            return []
        return sorted(self.programs_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)


def _fmt(v: float) -> str:
    return f"{v:,.2f}".replace(",", " ")


class Pendant:
    """UI of one browser tab."""

    def __init__(self, ws: Workspace) -> None:
        self.ws = ws
        self.robot = ws.robot
        storage = app.storage.user
        self.lang: str = storage.get("lang", "de")
        self.page: str = storage.get("page", "connection")
        self.jog_mode: str = storage.get("jog_mode", "axes")
        self.jog_speed: float = float(storage.get("jog_speed", 10.0))
        self.increment: str = storage.get("increment", "0")
        self.auto_run = False
        self.from_step = 0
        self.held = False
        self.seen_revision = -1
        self.snap = Snapshot()
        self.nav_buttons: dict[str, ui.button] = {}
        self.axis_values: list[ui.label] = []
        self.axis_bars: list[ui.element] = []
        self.axis_names: list[ui.label] = []
        self.jog_keys: list[ui.button] = []
        self._sent: dict[tuple[int, str], str] = {}
        self.seen_coords: tuple[object, ...] = ()
        self.seen_blending: tuple[tuple[str, bool], ...] = ()
        self.coord_pages = {kind: coords.CoordPage(self, kind) for kind in (coords.TOOL, coords.FRAME)}

    def put(self, element: ui.element, kind: str, value: str) -> None:
        """Set classes / style / props only if they changed (the timer runs every 150 ms and
        every call would otherwise send an update to the browser)."""
        key = (id(element), kind)
        if self._sent.get(key) == value:
            return
        self._sent[key] = value
        if kind == "style":
            element.style(replace=value)
        elif kind == "classes":
            element.classes(replace=value)
        else:
            element.props(value)

    def tr(self, key: str, **values: object) -> str:
        return t(key, self.lang, **values)

    # ------------------------------------------------------------------ actions

    async def act(self, fn: Callable[..., Any], *args: Any, done: str = "", quiet_stop: bool = False,
                  **kwargs: Any) -> Any:  # fmt: skip
        """Run a blocking robot call in a worker thread; errors as a notification."""
        try:
            result = await run.io_bound(fn, *args, **kwargs)
        except Exception as exc:
            text = str(exc) or type(exc).__name__
            log.warning("%s: %s", getattr(fn, "__name__", fn), text)
            if quiet_stop and "stopped" in text:
                ui.notify(text.capitalize(), type="warning", position="top", timeout=1500)
            else:
                ui.notify(text, type="negative", position="top", multi_line=True)
            return None
        if done:
            ui.notify(done, type="positive", position="top", timeout=1500)
        return result

    async def connect(self) -> None:
        if self.snap.phase in (Phase.READY, Phase.LOST):
            await self.act(self.robot.disconnect)
        else:
            await self.act(self.robot.connect, self.ws.target)

    async def set_power(self, on: bool) -> None:
        if on != self.snap.enabled:
            await self.act(self.robot.set_enabled, on)

    async def stop(self) -> None:
        self.held = False
        await self.act(self.robot.stop)

    # hold-to-run: pointerdown on a key starts, "hold_release" (browser) ends the motion
    async def jog_press(self, axis: int, direction: int) -> None:
        if not self.snap.enabled:
            ui.notify(self.tr("jog.need_enable"), type="warning", position="top")
            return
        self.held = True
        await self.act(
            self.robot.jog_press,
            JOG_MODES[self.jog_mode],
            axis,
            direction,
            self.jog_speed,
            INCREMENTS[self.increment],
        )
        if not self.held:  # released while the jog was being started
            await run.io_bound(self.robot.release)

    async def hold_release(self) -> None:
        if self.held:
            self.held = False
            await run.io_bound(self.robot.release)

    async def move_to(self, name: str, motion: Motion) -> None:
        self.held = True
        point = self.ws.program.point(name)
        await self.act(self.robot.move_to, point, motion, 20.0, hold=not self.auto_run, quiet_stop=True)
        self.held = False

    async def run_program(self, single_step: bool) -> None:
        steps = self.ws.program.steps
        if not steps:
            return
        start = min(self.from_step, len(steps) - 1)
        self.held = True

        def on_step(i: int) -> None:
            self.from_step = i

        nxt = await self.act(
            self.robot.run_program,
            self.ws.program,
            start,
            single_step=single_step,
            hold=not self.auto_run,
            on_step=on_step,
            quiet_stop=True,
        )
        self.held = False
        if nxt is not None:
            if nxt >= len(steps):
                self.from_step = 0
                if not single_step:
                    ui.notify(self.tr("prog.finished"), type="positive", position="top")
            else:
                self.from_step = nxt
        self.draw_steps.refresh()

    async def teach(self) -> None:
        position = await self.act(self.robot.current_position)
        if position is None:
            return
        joints, cartesian = position
        point = self.ws.program.add_point(joints, cartesian, tool=self.robot.tool, frame=self.robot.frame)
        self.ws.changed()
        ui.notify(self.tr("teach.done", name=point.name), type="positive", position="top", timeout=1500)

    async def teach_again(self, name: str) -> None:
        position = await self.act(self.robot.current_position)
        if position is None:
            return
        self.ws.program.update_point(name, *position, tool=self.robot.tool, frame=self.robot.frame)
        self.ws.changed()
        ui.notify(self.tr("teach.again_done", name=name), type="positive", position="top")

    def remember(self, key: str, value: Any) -> None:
        app.storage.user[key] = value

    # ------------------------------------------------------------------ page

    def build(self) -> None:
        ui.colors(**COLORS)
        # layer "overrides" of NiceGUI: comes before "quasar_importants", so the !important rules of
        # the theme win against Quasar's color classes (bg-primary, text-primary are !important)
        ui.add_css("@layer overrides {\n" + CSS + "\n}")
        ui.add_head_html(HOLD_JS)
        ui.add_head_html('<meta name="theme-color" content="#F2F2F7">')
        dark = ui.dark_mode()
        dark.bind_value(app.storage.user, "dark")
        ui.on("hold_alive", lambda: self.robot.alive())
        ui.on("hold_release", self.hold_release)

        self.build_header(dark)
        with (
            ui.left_drawer(value=True, bordered=False)
            .classes("tp-drawer")
            .props("width=232 breakpoint=900") as drawer
        ):
            self.drawer = drawer
            with ui.column().classes("w-full gap-1 p-3"):
                for key, icon in (("connection", "link"), ("jog", "open_with"),
                                  ("program", "format_list_numbered"), ("tools", "construction"),
                                  ("frames", "grid_4x4"), ("messages", "notifications_none")):  # fmt: skip
                    btn = ui.button(self.tr(f"nav.{key}"), icon=icon, on_click=lambda k=key: self.show(k))
                    btn.props("flat no-caps align=left").classes("tp-nav w-full")
                    self.nav_buttons[key] = btn
                ui.space()
        with ui.tab_panels(value=self.page, animated=False).classes("w-full bg-transparent") as panels:
            self.panels = panels
            with ui.tab_panel("connection").classes("p-0"):
                self.build_connection()
            with ui.tab_panel("jog").classes("p-0"):
                self.build_jog()
            with ui.tab_panel("program").classes("p-0"):
                self.build_program()
            with ui.tab_panel("tools").classes("p-0"):
                self.coord_pages[coords.TOOL].build()
            with ui.tab_panel("frames").classes("p-0"):
                self.coord_pages[coords.FRAME].build()
            with ui.tab_panel("messages").classes("p-0"):
                self.build_messages()
        self.show(self.page)
        ui.timer(0.15, self.refresh)
        ui.timer(0.5, self.auto_load_coords)

    def show(self, page: str) -> None:
        self.page = page
        self.panels.set_value(page)
        self.remember("page", page)
        for key, btn in self.nav_buttons.items():
            btn.classes(add="active") if key == page else btn.classes(remove="active")

    def build_header(self, dark: Any) -> None:
        with ui.header().classes("tp-header items-center px-4 py-2 gap-3"):
            ui.button(icon="menu", on_click=lambda: self.drawer.toggle()).props("flat round dense").classes(
                "lt-md text-[var(--text)]"
            )
            with ui.row().classes("items-center gap-3 no-wrap"):
                ui.icon("precision_manufacturing", size="26px").classes("text-[var(--blue)]")
                with ui.column().classes("gap-0"):
                    ui.label(self.tr("app.title")).classes("tp-title")
                    self.header_sub = ui.label("").classes("tp-sub")
            ui.space()
            with ui.element("div").classes("tp-pill") as pill:
                self.pill = pill
                ui.element("div").classes("tp-dot")
                self.pill_text = ui.label("")
            with ui.button(icon="translate").props("flat round").classes("text-[var(--text-2)]"), ui.menu():
                for code, name in LANGUAGES.items():
                    ui.menu_item(name, on_click=lambda c=code: self.set_language(c))
            ui.button(icon="contrast", on_click=lambda: dark.set_value(not dark.value)).props(
                "flat round"
            ).classes("text-[var(--text-2)]").tooltip(self.tr("theme.toggle"))
            ui.button(self.tr("stop"), icon="pan_tool", on_click=self.stop).classes("tp-stop").props(
                "unelevated no-caps"
            ).tooltip(self.tr("stop.hint"))

    def set_language(self, code: str) -> None:
        self.remember("lang", code)
        ui.navigate.reload()

    def page_title(self, title: str, lead: str = "") -> None:
        with ui.column().classes("gap-0"):
            ui.label(title).classes("tp-h1")
            if lead:
                ui.label(lead).classes("tp-lead")

    def card(self, title: str = "") -> ui.column:
        col = ui.column().classes("tp-card gap-0")
        if title:
            with col:
                ui.label(title).classes("tp-card-title")
        return col

    def info_row(self, key: str) -> ui.label:
        with ui.element("div").classes("tp-row"):
            ui.label(key).classes("tp-key")
            return ui.label("–").classes("tp-val")

    # ------------------------------------------------------------------ connection

    def build_connection(self) -> None:
        target = self.ws.target
        with ui.column().classes("tp-page"):
            self.page_title(self.tr("conn.title"), self.tr("conn.subtitle"))
            with ui.element("div").classes("grid w-full gap-5 md:grid-cols-2"):
                with self.card():
                    ui.toggle(
                        {False: self.tr("conn.robot"), True: self.tr("conn.simulator")},
                        value=target.simulator,
                    ).bind_value(target, "simulator").props("no-caps unelevated").classes(
                        "tp-seg self-start mb-4"
                    )
                    with (
                        ui.column()
                        .classes("w-full gap-3")
                        .bind_visibility_from(target, "simulator", lambda v: not v)
                    ):
                        ui.input(self.tr("conn.host")).bind_value(target, "host").props("filled").classes(
                            "w-full"
                        )
                        with ui.row().classes("w-full gap-3 no-wrap"):
                            ui.number(self.tr("conn.port"), min=1, max=65535, precision=0).bind_value(
                                target, "port", forward=lambda v: int(v or 5000)
                            ).props("filled").classes("flex-1")
                            ui.number(self.tr("conn.length"), min=32, max=1024, precision=0).bind_value(
                                target, "length", forward=lambda v: int(v or 256)
                            ).props("filled").classes("flex-1")
                    ui.label(self.tr("conn.sim_hint")).classes("tp-muted").bind_visibility_from(
                        target, "simulator"
                    )
                    # LifeSign timeout: quick choice + free value, remembered for the next start
                    ui.label(self.tr("conn.lifesign")).classes("tp-card-title mt-4")
                    with ui.row().classes("w-full items-center gap-3 no-wrap"):
                        presets = ui.toggle({100: "100", 250: "250", 500: "500", 1000: "1000"}, value=None)
                        presets.props("no-caps unelevated").classes("tp-seg").mark("lifesign-presets")
                        lifesign = (
                            ui.number(
                                value=target.lifesign_ms, min=20, max=5000, step=50, precision=0, suffix="ms"
                            )
                            .props("filled dense")
                            .classes("w-32 tp-mono-in")
                            .mark("lifesign")
                        )

                        def set_lifesign(value: Any) -> None:
                            ms = int(value or 0)
                            if 20 <= ms <= 5000:
                                target.lifesign_ms = ms
                                app.storage.general["lifesign_ms"] = ms
                                lifesign.set_value(ms)
                                presets.set_value(ms if ms in (100, 250, 500, 1000) else None)

                        presets.on_value_change(lambda e: set_lifesign(e.value) if e.value else None)
                        lifesign.on("blur", lambda: set_lifesign(lifesign.value))
                        lifesign.on("keydown.enter", lambda: set_lifesign(lifesign.value))
                        presets.set_value(
                            target.lifesign_ms if target.lifesign_ms in (100, 250, 500, 1000) else None
                        )
                    ui.label(self.tr("conn.lifesign_hint")).classes("tp-muted mt-1")
                    with ui.row().classes("w-full items-center mt-5 gap-3"):
                        self.connect_btn = (
                            ui.button(self.tr("conn.connect"), on_click=self.connect)
                            .props("unelevated no-caps color=primary")
                            .classes("px-6")
                        )
                        self.connect_spinner = ui.spinner(size="22px").classes("text-[var(--blue)]")
                    self.conn_error = ui.label("").classes("tp-banner err mt-4 w-full")

                with ui.column().classes("gap-5 w-full"):
                    with self.card(self.tr("power.title")):
                        with ui.element("div").classes("tp-row"):
                            ui.label(self.tr("power.enable")).classes("text-[17px] font-medium")
                            self.power = ui.switch(on_change=lambda e: self.set_power(bool(e.value))).props(
                                "color=positive"
                            )
                        with ui.element("div").classes("tp-row py-2"):
                            with ui.column().classes("gap-0 flex-1"):
                                ui.label(self.tr("override")).classes("text-[17px] font-medium")
                                ui.label(self.tr("override.hint")).classes("tp-muted")
                            self.override_label = ui.label(f"{self.robot.override:.0f} %").classes(
                                "tp-val tp-mono text-[17px]"
                            )
                        self.override = (
                            ui.slider(min=1, max=100, step=1, value=self.robot.override)
                            .props("color=primary")
                            .classes("mt-1")
                        )
                        self.override.on("change", lambda e: self.act(self.robot.set_override, float(e.args)))
                        self.override.on_value_change(
                            lambda e: self.override_label.set_text(f"{e.value:.0f} %")
                        )
                        with ui.row().classes("w-full mt-3"):
                            ui.button(
                                self.tr("power.reset"),
                                icon="restart_alt",
                                on_click=lambda: self.act(self.robot.reset),
                            ).props("flat no-caps").classes("tp-btn-soft").tooltip(
                                self.tr("power.reset_hint")
                            )
                    with self.card(self.tr("caps.title")):
                        self.draw_caps()
                    with self.card(self.tr("robot.title")):
                        self.info = {k: self.info_row(self.tr(f"robot.{k}"))
                                     for k in ("manufacturer", "model", "firmware", "srci", "mode")}  # fmt: skip

    @ui.refreshable_method
    def draw_caps(self) -> None:
        supported = self.snap.supported
        if supported is None:
            ui.label(self.tr("caps.unknown")).classes("tp-muted")
            return
        core = [f for f in CORE_FUNCTIONS if f in supported]
        ui.label(self.tr("caps.summary", n=len(core), total=len(CORE_FUNCTIONS))).classes("font-medium mb-2")
        with ui.element("div").classes("flex flex-wrap gap-1"):
            for f in CORE_FUNCTIONS:
                ok = f in supported
                with ui.element("div").classes("tp-cap" + ("" if ok else " missing")):
                    ui.icon("check" if ok else "close").classes("text-[14px]")
                    ui.label(f)
        extra = sorted(supported - set(CORE_FUNCTIONS))
        if not extra:
            ui.label(self.tr("caps.none_more")).classes("tp-muted mt-3")
            return
        with ui.expansion(self.tr("caps.more", n=len(extra))).classes("w-full mt-2 tp-muted").props("dense"):
            ui.label(", ".join(extra)).classes("tp-muted text-[13px]")

    # ------------------------------------------------------------------ jog

    def build_jog(self) -> None:
        with ui.column().classes("tp-page"):
            with ui.row().classes("w-full items-end justify-between"):
                self.page_title(self.tr("jog.title"), self.tr("jog.hold"))
                mode = ui.toggle(
                    {"axes": self.tr("jog.axes"), "base": self.tr("jog.base"), "tool": self.tr("jog.tool")},
                    value=self.jog_mode,
                    on_change=lambda e: self.set_jog_mode(e.value),
                )
                mode.props("no-caps unelevated").classes("tp-seg")
            self.jog_banner = ui.row().classes("tp-banner w-full items-center justify-between")
            with self.jog_banner:
                self.jog_banner_text = ui.label(self.tr("jog.need_enable"))
                self.jog_banner_btn = (
                    ui.button(self.tr("power.enable"), on_click=lambda: self.set_power(True))
                    .props("unelevated no-caps color=primary dense")
                    .classes("px-4")
                )
            with ui.element("div").classes("grid w-full gap-5 items-start lg:grid-cols-[1.5fr_1fr]"):
                with self.card():
                    for i in range(6):
                        with ui.element("div").classes("tp-axis"):
                            self.axis_names.append(ui.label("").classes("tp-axis-name"))
                            with ui.column().classes("gap-1"):
                                self.axis_values.append(
                                    ui.label("–").classes("tp-axis-val tp-mono text-left")
                                )
                                with ui.element("div").classes("tp-bar w-full"):
                                    self.axis_bars.append(ui.element("div"))
                            for direction, icon in ((-1, "remove"), (1, "add")):
                                key = ui.button(icon=icon).props("unelevated").classes("tp-key-btn")
                                key.on("pointerdown", lambda _, a=i, d=direction: self.jog_press(a, d))
                                self.jog_keys.append(key)
                    self.update_axis_names()
                with ui.column().classes("gap-5 w-full"):
                    with self.card(self.tr("jog.speed")):
                        with ui.row().classes("w-full items-center no-wrap gap-4"):
                            ui.slider(
                                min=1,
                                max=100,
                                step=1,
                                value=self.jog_speed,
                                on_change=lambda e: self.set_jog_speed(e.value),
                            ).classes("flex-1")
                            self.jog_speed_label = ui.label(f"{self.jog_speed:.0f} %").classes(
                                "tp-val tp-mono w-14"
                            )
                        ui.label(self.tr("jog.step")).classes("tp-card-title mt-4")
                        inc = ui.toggle(
                            {"0": self.tr("jog.continuous"), "0.1": "0.1", "1": "1", "10": "10"},
                            value=self.increment,
                            on_change=lambda e: self.set_increment(e.value),
                        )
                        inc.props("no-caps unelevated").classes("tp-seg")
                        self.increment_unit = ui.label("").classes("tp-muted mt-1")
                    with self.card(self.tr("coord.system")):
                        with ui.row().classes("w-full gap-3 no-wrap"):
                            self.tool_select = (
                                ui.select(
                                    {0: "T0"},
                                    value=self.robot.tool,
                                    label=self.tr("coord.tool"),
                                    on_change=lambda e: self.select_coords(tool=e.value),
                                )
                                .props("filled dense options-dense")
                                .classes("flex-1")
                            )
                            self.frame_select = (
                                ui.select(
                                    {0: "F0"},
                                    value=self.robot.frame,
                                    label=self.tr("coord.frame"),
                                    on_change=lambda e: self.select_coords(frame=e.value),
                                )
                                .props("filled dense options-dense")
                                .classes("flex-1")
                            )
                        ui.label(self.tr("coord.system_hint")).classes("tp-muted mt-2")
                    with self.card(self.tr("pos.title")):
                        self.other_title = ui.label("").classes("tp-muted")
                        self.other_values = ui.label("").classes(
                            "tp-mono text-[15px] leading-7 whitespace-pre"
                        )
                    ui.button(self.tr("teach.point"), icon="add_location_alt", on_click=self.teach).props(
                        "unelevated no-caps color=primary size=lg"
                    ).classes("w-full h-16 text-[17px]")
            self.update_increment_unit()

    async def select_coords(self, tool: int | None = None, frame: int | None = None) -> None:
        tool = self.robot.tool if tool is None else int(tool)
        frame = self.robot.frame if frame is None else int(frame)
        if (tool, frame) != (self.robot.tool, self.robot.frame):
            await self.act(self.robot.set_coordinate_system, tool, frame)
            self.ws.coord_revision += 1

    def set_jog_mode(self, mode: str) -> None:
        self.jog_mode = mode
        self.remember("jog_mode", mode)
        self.update_axis_names()
        self.update_increment_unit()

    def set_jog_speed(self, v: float) -> None:
        self.jog_speed = float(v)
        self.remember("jog_speed", self.jog_speed)
        self.jog_speed_label.set_text(f"{self.jog_speed:.0f} %")

    def set_increment(self, v: str) -> None:
        self.increment = v
        self.remember("increment", v)
        self.update_increment_unit()

    def update_increment_unit(self) -> None:
        if self.increment == "0":
            text = ""
        elif self.jog_mode == "axes":
            text = f"{self.increment} °"
        else:
            text = f"{self.increment} mm / {self.increment} °"
        self.increment_unit.set_text(text)

    def update_axis_names(self) -> None:
        names = JOINTS if self.jog_mode == "axes" else CARTESIAN
        for label, name in zip(self.axis_names, names, strict=True):
            label.set_text(name)

    # ------------------------------------------------------------------ program

    def build_program(self) -> None:
        with ui.column().classes("tp-page"):
            with ui.row().classes("w-full items-center justify-between gap-3"):
                with ui.column().classes("gap-0"):
                    name = (
                        ui.input(placeholder=self.tr("prog.name"), value=self.ws.program.name)
                        .props("borderless dense")
                        .classes("tp-h1 min-w-[260px]")
                    )
                    name.on("change", lambda: self.rename_program(name.value))
                    self.name_input = name
                    self.dirty_label = ui.label(self.tr("prog.unsaved")).classes("tp-muted")
                with ui.row().classes("gap-2"):
                    ui.button(self.tr("prog.new"), icon="note_add", on_click=self.new_program).props(
                        "flat no-caps"
                    ).classes("tp-btn-soft")
                    ui.button(self.tr("prog.open"), icon="folder_open", on_click=self.open_dialog).props(
                        "flat no-caps"
                    ).classes("tp-btn-soft")
                    ui.button(self.tr("prog.save"), icon="save", on_click=self.save).props(
                        "unelevated no-caps color=primary"
                    )
            with ui.element("div").classes("grid w-full gap-5 items-start lg:grid-cols-2"):
                with self.card(self.tr("prog.points")):
                    self.draw_points()
                with self.card(self.tr("prog.steps")):
                    self.draw_steps()
                    with ui.column().classes("w-full gap-3 mt-4 pt-4 border-t border-[var(--line)]"):
                        with ui.row().classes("w-full items-center gap-3 no-wrap"):
                            self.start_btn = (
                                ui.button(self.tr("prog.run"), icon="play_arrow")
                                .props("unelevated no-caps color=positive size=lg")
                                .classes("tp-hold flex-1 h-14")
                            )
                            self.start_btn.on("pointerdown", lambda: self.run_if_hold(False))
                            self.start_btn.on("click", lambda: self.run_if_auto(False))
                            self.step_btn = (
                                ui.button(self.tr("prog.step"), icon="skip_next")
                                .props("flat no-caps size=lg")
                                .classes("tp-btn-soft tp-hold h-14")
                            )
                            self.step_btn.on("pointerdown", lambda: self.run_if_hold(True))
                            self.step_btn.on("click", lambda: self.run_if_auto(True))
                        self.run_hint = ui.label(self.tr("prog.hold_hint")).classes("tp-muted")
                        with ui.row().classes("items-center gap-2"):
                            ui.switch(
                                self.tr("prog.auto"),
                                value=self.auto_run,
                                on_change=lambda e: self.set_auto(bool(e.value)),
                            )
                            ui.icon("info_outline").classes("text-[var(--text-3)]").tooltip(
                                self.tr("prog.auto_hint")
                            )

    def rename_program(self, name: str) -> None:
        name = (name or "").strip()
        if name and name != self.ws.program.name:
            self.ws.program.name = name
            self.ws.changed()

    def set_auto(self, auto: bool) -> None:
        self.auto_run = auto
        for btn in (self.start_btn, self.step_btn):
            btn.classes(remove="tp-hold") if auto else btn.classes(add="tp-hold")
        self.run_hint.set_text(self.tr("prog.auto_hint") if auto else self.tr("prog.hold_hint"))

    async def run_if_hold(self, single_step: bool) -> None:
        if not self.auto_run:
            await self.run_program(single_step)

    async def run_if_auto(self, single_step: bool) -> None:
        if self.auto_run:
            await self.run_program(single_step)

    @ui.refreshable_method
    def draw_points(self) -> None:
        program = self.ws.program
        if not program.points:
            ui.label(self.tr("prog.no_points")).classes("tp-empty w-full")
            return
        for point in program.points:
            with ui.element("div").classes("tp-item"):
                ui.icon("place").classes("text-[var(--blue)] text-[22px]")
                with ui.column().classes("gap-0 flex-1 min-w-0"):
                    ui.label(point.name).classes("font-semibold")
                    ui.label("  ".join(f"{v:.1f}" for v in point.joints)).classes("tp-muted tp-mono truncate")
                move = (
                    ui.button(self.tr("point.move"))
                    .props("flat no-caps dense")
                    .classes("tp-btn-soft tp-hold px-3")
                )
                move.on("pointerdown", lambda _, n=point.name: self.move_to(n, Motion.JOINT))
                ui.button(icon="playlist_add", on_click=lambda n=point.name: self.add_step(n)).props(
                    "flat round dense"
                ).classes("text-[var(--blue)]").tooltip(self.tr("point.add_step")).mark(
                    f"add-step-{point.name}"
                )
                with ui.button(icon="more_horiz").props("flat round dense").classes("text-[var(--text-2)]"):
                    with ui.menu():
                        ui.menu_item(
                            self.tr("teach.again"), on_click=lambda n=point.name: self.teach_again(n)
                        )
                        ui.menu_item(
                            self.tr("point.rename"), on_click=lambda n=point.name: self.rename_dialog(n)
                        )
                        ui.menu_item(
                            self.tr("point.delete"), on_click=lambda n=point.name: self.delete_point(n)
                        )

    @ui.refreshable_method
    def draw_steps(self) -> None:
        program = self.ws.program
        if not program.steps:
            ui.label(self.tr("prog.no_steps")).classes("tp-empty w-full")
            return
        running = self.snap.activity is Activity.RUNNING
        for i, step in enumerate(program.steps):
            current = i == (self.snap.program_step if running else self.from_step)
            with ui.element("div").classes("tp-item" + (" current" if current else "")):
                badge = ui.label(str(i + 1)).classes("tp-badge cursor-pointer")
                badge.on("click", lambda _, n=i: self.set_from_step(n))
                with (
                    ui.row()
                    .classes("flex-1 min-w-0 items-center gap-2 no-wrap cursor-pointer")
                    .on("click", lambda _, n=i: self.edit_step(n))
                    .mark(f"step-{i}")
                ):
                    ui.label(step.point).classes("font-semibold min-w-0 truncate")
                    ui.space()
                    kind = {Motion.LINEAR: "lin", Motion.PTP: "ptp", Motion.JOINT: "joint"}[step.motion]
                    chip = ui.label(motion_label(self, step)).classes(f"tp-chip {kind}")
                    if not self.snap.can(MOTION_FUNCTIONS[step.motion.value]):
                        chip.classes("unsupported").tooltip(
                            self.tr("caps.not_supported", f=MOTION_FUNCTIONS[step.motion.value])
                        )
                    refused = step.blended and self.robot.blending_results.get(step.blending_mode) is False
                    blend = ui.label(blend_label(self, step)).classes(
                        "tp-chip" + (" blend" if step.blended else "") + (" unsupported" if refused else "")
                    )
                    if refused:
                        blend.tooltip(self.tr("blend.rejected"))
                    vel = self.tr("step.default") if step.velocity < 0 else f"{step.velocity:.0f} %"
                    ui.label(vel).classes("tp-mono tp-muted w-16 text-right")
                with ui.button(icon="more_vert").props("flat round dense").classes("text-[var(--text-2)]"):
                    with ui.menu():
                        ui.menu_item(self.tr("coord.edit"), on_click=lambda n=i: self.edit_step(n))
                        ui.menu_item(self.tr("step.duplicate"), on_click=lambda n=i: self.duplicate_step(n))
                        ui.menu_item(self.tr("step.up"), on_click=lambda n=i: self.move_step(n, -1))
                        ui.menu_item(self.tr("step.down"), on_click=lambda n=i: self.move_step(n, 1))
                        ui.menu_item(self.tr("common.delete"), on_click=lambda n=i: self.delete_step(n))

    def set_from_step(self, i: int) -> None:
        self.from_step = i
        self.draw_steps.refresh()

    def add_step(self, name: str) -> None:
        self.ws.program.add_step(name)
        self.ws.changed()

    async def edit_step(self, i: int) -> None:
        try:
            new = await edit_step(self, i)
        except ValueError as exc:
            ui.notify(str(exc), type="negative", position="top")
            return
        if new is not None and i < len(self.ws.program.steps):
            self.ws.program.steps[i] = new
            self.ws.changed()

    def duplicate_step(self, i: int) -> None:
        import copy

        self.ws.program.steps.insert(i + 1, copy.deepcopy(self.ws.program.steps[i]))
        self.ws.changed()

    def move_step(self, i: int, offset: int) -> None:
        self.ws.program.move_step(i, offset)
        self.ws.changed()

    def delete_step(self, i: int) -> None:
        self.ws.program.delete_step(i)
        self.from_step = min(self.from_step, max(0, len(self.ws.program.steps) - 1))
        self.ws.changed()

    async def rename_dialog(self, name: str) -> None:
        with ui.dialog() as dialog, ui.card().classes("min-w-[320px]"):
            ui.label(self.tr("point.rename")).classes("text-[17px] font-semibold")
            field_ = ui.input(self.tr("common.name"), value=name).props("filled autofocus").classes("w-full")
            with ui.row().classes("w-full justify-end gap-2"):
                ui.button(self.tr("common.cancel"), on_click=lambda: dialog.submit(None)).props(
                    "flat no-caps"
                )
                ui.button(self.tr("common.ok"), on_click=lambda: dialog.submit(field_.value)).props(
                    "unelevated no-caps color=primary"
                )
            field_.on("keydown.enter", lambda: dialog.submit(field_.value))
        new = await dialog
        if new and new != name:
            try:
                self.ws.program.rename_point(name, str(new))
            except ValueError as exc:
                ui.notify(str(exc), type="negative", position="top")
                return
            self.ws.changed()

    async def delete_point(self, name: str) -> None:
        steps = sum(1 for s in self.ws.program.steps if s.point == name)
        if not await self.confirm(self.tr("point.delete_confirm", name=name, steps=steps), danger=True):
            return
        self.ws.program.delete_point(name)
        self.from_step = 0
        self.ws.changed()

    async def confirm(self, text: str, danger: bool = False) -> bool:
        with ui.dialog() as dialog, ui.card().classes("min-w-[320px]"):
            ui.label(text).classes("text-[17px] font-medium")
            with ui.row().classes("w-full justify-end gap-2"):
                ui.button(self.tr("common.cancel"), on_click=lambda: dialog.submit(False)).props(
                    "flat no-caps"
                )
                ui.button(self.tr("common.ok"), on_click=lambda: dialog.submit(True)).props(
                    f"unelevated no-caps color={'negative' if danger else 'primary'}"
                )
        return bool(await dialog)

    async def new_program(self) -> None:
        if self.ws.dirty and not await self.confirm(self.tr("prog.new_confirm")):
            return
        self.ws.program = Program(self.tr("prog.default"))
        self.ws.path, self.ws.dirty = None, False
        self.ws.revision += 1
        self.from_step = 0

    def save(self) -> None:
        ws = self.ws
        stem = "".join(c if c.isalnum() or c in "-_ " else "_" for c in ws.program.name).strip() or "program"
        ws.path = ws.path if ws.path and ws.path.stem == stem else ws.programs_dir / f"{stem}.json"
        try:
            ws.program.save(ws.path)
        except OSError as exc:
            ui.notify(str(exc), type="negative", position="top")
            return
        ws.dirty = False
        ui.notify(self.tr("prog.saved", path=ws.path.name), type="positive", position="top", timeout=1500)

    async def open_dialog(self) -> None:
        files = self.ws.files()
        with ui.dialog() as dialog, ui.card().classes("min-w-[360px]"):
            ui.label(self.tr("prog.open")).classes("text-[17px] font-semibold")
            if not files:
                ui.label("–").classes("tp-empty w-full")
            for path in files:
                with ui.element("div").classes("tp-item cursor-pointer") as item:
                    ui.icon("description").classes("text-[var(--blue)]")
                    ui.label(path.stem).classes("flex-1")
                item.on("click", lambda _, p=path: dialog.submit(p))
            with ui.row().classes("w-full justify-end"):
                ui.button(self.tr("common.cancel"), on_click=lambda: dialog.submit(None)).props(
                    "flat no-caps"
                )
        path = await dialog
        if path is None:
            return
        if self.ws.dirty and not await self.confirm(self.tr("prog.new_confirm")):
            return
        try:
            self.ws.program = Program.load(path)
        except (OSError, ValueError, KeyError) as exc:
            ui.notify(f"{path.name}: {exc}", type="negative", position="top")
            return
        self.ws.path, self.ws.dirty = path, False
        self.ws.revision += 1
        self.from_step = 0

    def auto_load_coords(self) -> None:
        """Read tools and frames once the RC has reported its functions (after connecting) - as a
        background task, so the timer does not wait for it."""
        s = self.snap
        if s.phase is not Phase.READY:
            self.ws.coords_tried = False  # next connection: read again
        elif s.supported is not None and not self.ws.coords_tried:
            self.ws.coords_tried = True  # once per connection, also if reading fails

            async def load() -> None:
                with self.panels:  # UI context of this tab for the notifications
                    await self.load_coords()

            background_tasks.create(load(), name="read tools and frames")

    async def load_coords(self) -> None:
        """Tools and frames of the RC after connecting (once for all tabs)."""
        if self.ws.loading_coords:
            return
        self.ws.loading_coords = True
        try:
            for page in self.coord_pages.values():
                if page.can_read:
                    await page.read()
        finally:
            self.ws.loading_coords = False

    # ------------------------------------------------------------------ messages

    def build_messages(self) -> None:
        with ui.column().classes("tp-page"):
            self.page_title(self.tr("msg.title"))
            self.last_error = ui.label("").classes("tp-banner err w-full")
            with self.card():
                self.draw_messages()

    @ui.refreshable_method
    def draw_messages(self) -> None:
        messages = self.snap.messages
        if not messages:
            ui.label(self.tr("msg.none")).classes("tp-empty w-full")
            return
        colors = {"ERROR": "var(--red)", "FATAL_ERROR": "var(--red)", "WARNING": "var(--orange)"}
        for m in messages:
            with ui.element("div").classes("tp-item"):
                ui.icon(
                    "error_outline"
                    if "ERROR" in m.severity
                    else "warning_amber"
                    if m.severity == "WARNING"
                    else "info_outline"
                ).style(f"color: {colors.get(m.severity, 'var(--blue)')}; font-size: 22px")
                with ui.column().classes("gap-0 flex-1 min-w-0"):
                    ui.label(m.text or "–").classes("font-medium")
                    ui.label(f"{m.severity} · 16#{m.code:04X}").classes("tp-muted tp-mono")

    # ------------------------------------------------------------------ cyclic update

    def refresh(self) -> None:
        old = self.snap
        s = self.snap = self.robot.snapshot()
        ready = s.phase is Phase.READY
        # header
        if s.phase is not Phase.READY:
            text, kind = (
                self.tr(f"phase.{s.phase.value}"),
                "err" if s.phase in (Phase.LOST, Phase.FAILED) else "",
            )
            if s.phase is Phase.CONNECTING:
                kind = "busy"
        elif s.error_pending:
            text, kind = self.tr("state.error"), "err"
        elif s.activity is not Activity.IDLE:
            text, kind = self.tr(f"activity.{s.activity.value}"), "busy"
        else:
            text, kind = (
                f"{self.tr('phase.ready')} · {self.tr('state.on' if s.enabled else 'state.off')}",
                ("ok" if s.enabled else "warn"),
            )
        self.pill_text.set_text(text)
        self.put(self.pill, "classes", f"tp-pill {kind}")
        self.header_sub.set_text(
            " · ".join(x for x in (s.manufacturer, s.target) if x)
            if s.phase is not Phase.DISCONNECTED
            else self.tr("phase.disconnected")
        )
        # connection page
        connected = s.phase in (Phase.READY, Phase.LOST)
        self.connect_btn.set_text(self.tr("conn.disconnect" if connected else "conn.connect"))
        self.put(self.connect_btn, "props", f"color={'negative' if connected else 'primary'}")
        self.connect_btn.set_enabled(s.phase is not Phase.CONNECTING)
        self.connect_spinner.set_visibility(s.phase is Phase.CONNECTING)
        self.conn_error.set_text(s.error)
        self.conn_error.set_visibility(bool(s.error) and s.phase in (Phase.FAILED, Phase.LOST))
        self.power.set_enabled(ready and s.can("EnableRobot"))
        if s.supported != old.supported:
            self.draw_caps.refresh()
        if self.power.value != s.enabled:
            self.power.set_value(s.enabled)  # set_power() ignores it (no change)
        self.override.set_enabled(ready and s.can("ChangeSpeedOverride"))
        for key, value in (("manufacturer", s.manufacturer), ("model", s.robot), ("firmware", s.firmware),
                           ("srci", s.srci_version), ("mode", s.operation_mode if ready else "")):  # fmt: skip
            self.info[key].set_text(value or "–")
        # jog page
        jog_supported = s.can("GroupJog")
        self.jog_banner.set_visibility(ready and (not s.enabled or not jog_supported))
        self.jog_banner_text.set_text(self.tr("jog.need_enable" if jog_supported else "jog.unsupported"))
        self.jog_banner_btn.set_visibility(jog_supported)
        can_jog = ready and s.enabled and jog_supported and s.activity in (Activity.IDLE, Activity.JOGGING)
        for jog_key in self.jog_keys:
            self.put(jog_key, "classes", "tp-key-btn" if can_jog else "tp-key-btn disabled")
        axes = self.jog_mode == "axes"
        values = s.joints if axes else s.cartesian
        for i, (label, bar) in enumerate(zip(self.axis_values, self.axis_bars, strict=True)):
            v = values[i]
            label.set_text(_fmt(v) if s.position_valid else "–")
            span = JOINT_RANGE if axes else CART_RANGES[i] * 2
            w = min(50.0, abs(v) / span * 100.0)
            self.put(bar, "style", f"left: {50.0 - w if v < 0 else 50.0:.1f}%; width: {w:.1f}%")
        other = s.cartesian if axes else s.joints
        names = CARTESIAN if axes else JOINTS
        self.other_title.set_text(self.tr("pos.tcp" if axes else "pos.joints"))
        self.other_values.set_text(
            "\n".join(f"{n:<3}{_fmt(v):>12}" for n, v in zip(names, other, strict=True))
            if s.position_valid
            else self.tr("pos.invalid")
        )
        # program page
        if self.seen_revision != self.ws.revision:
            self.seen_revision = self.ws.revision
            self.name_input.set_value(self.ws.program.name)
            self.draw_points.refresh()
            self.draw_steps.refresh()
        elif (s.activity is Activity.RUNNING and s.program_step != old.program_step) or (
            old.activity is Activity.RUNNING and s.activity is not Activity.RUNNING
        ):
            self.draw_steps.refresh()
        results = tuple(sorted(self.robot.blending_results.items()))
        if results != self.seen_blending:
            self.seen_blending = results
            self.draw_steps.refresh()
        self.dirty_label.set_visibility(self.ws.dirty)
        busy = s.activity in (Activity.RUNNING, Activity.MOVING)
        for btn in (self.start_btn, self.step_btn):
            # stays enabled while it is held: disabling it would end the pointer capture -> release
            btn.set_enabled(ready and s.enabled and bool(self.ws.program.steps) and (not busy or self.held))
        # tools and frames
        coord_key = (self.ws.coord_revision, s.tool, s.frame, s.highest_tool, s.highest_frame, s.supported)
        if coord_key != self.seen_coords:
            self.seen_coords = coord_key
            for page in self.coord_pages.values():
                page.draw.refresh()
            self.tool_select.set_options(coords.options(self, coords.TOOL), value=s.tool)
            self.frame_select.set_options(coords.options(self, coords.FRAME), value=s.frame)
        for page in self.coord_pages.values():
            page.read_btn.set_enabled(ready and s.activity is Activity.IDLE and page.can_read)
        # messages
        if [m.code for m in s.messages] != [m.code for m in old.messages] or len(s.messages) != len(
            old.messages
        ):
            self.draw_messages.refresh()
        self.last_error.set_text(f"{self.tr('msg.last_error')}: {s.error}")
        self.last_error.set_visibility(bool(s.error))
