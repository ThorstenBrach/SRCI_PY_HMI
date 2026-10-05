"""Dialog to edit one step: motions (target point, motion type, blending, dynamics), relative
motions, waiting, outputs, inputs, subprograms and stop points."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nicegui import ui

from srci_py_hmi.model import (
    BLENDING_MODES,
    BLENDING_UNITS,
    CARTESIAN,
    DEFAULT,
    JOINTS,
    Motion,
    Step,
    StepKind,
)
from srci_py_hmi.robot import step_function
from srci_py_hmi.ui import coords

if TYPE_CHECKING:
    from srci_py_hmi.ui.pendant import Pendant

DYNAMICS = ("velocity", "acceleration", "deceleration", "jerk")
DYN_KEYS = {
    "velocity": "step.vel",
    "acceleration": "step.acc",
    "deceleration": "step.dec",
    "jerk": "step.jerk",
}
# icon of each step kind in the list and in the "add step" menu
KIND_ICONS = {
    StepKind.MOVE: "place",
    StepKind.RELATIVE: "open_in_full",
    StepKind.WAIT: "hourglass_empty",
    StepKind.OUTPUT: "output",
    StepKind.WAIT_INPUT: "input",
    StepKind.SUBPROGRAM: "account_tree",
    StepKind.HALT: "front_hand",
}


def motion_label(p: Pendant, step: Step) -> str:
    """``LIN``, ``PTP``, ``Joint``, ``CIRC`` - with ``⤳`` when blended."""
    return p.tr(f"step.{step.motion.value}") + (" ⤳" if step.blended else "")


def blend_label(p: Pendant, step: Step) -> str:
    if step.exact_stop:
        return p.tr("step.absolute")
    unit0, unit1 = BLENDING_UNITS[step.blending_mode]
    text = f"{step.blending:g} {unit0}" if unit0 else ""
    if unit1:
        text += f" / {step.blending_post:g} {unit1}"
    return text


def signal_label(p: Pendant, kind: str, signal: int) -> str:
    """``DO 3`` or ``DO 3 · Gripper closed`` (local label)."""
    name = p.ws.labels.get(kind, {}).get(str(signal), "")
    return f"{kind.upper()} {signal}" + (f" · {name}" if name else "")


def step_title(p: Pendant, step: Step) -> str:
    """Main text of a step in the list."""
    if step.kind is StepKind.MOVE:
        return step.point if step.motion is not Motion.CIRC else f"{step.via} → {step.point}"
    if step.kind is StepKind.RELATIVE:
        names = JOINTS if step.motion is Motion.JOINT else CARTESIAN
        moved = [f"{n} {v:+g}" for n, v in zip(names, step.offset, strict=True) if v]
        return p.tr("kind.relative") + ("  " + "  ".join(moved) if moved else "")
    if step.kind is StepKind.WAIT:
        return p.tr("kind.wait_s", s=f"{step.duration:g}")
    if step.kind is StepKind.OUTPUT:
        return f"{signal_label(p, 'do', step.signal)} := {int(step.value)}"
    if step.kind is StepKind.WAIT_INPUT:
        return p.tr("kind.wait_for", s=f"{signal_label(p, 'di', step.signal)} = {int(step.value)}")
    if step.kind is StepKind.SUBPROGRAM:
        return p.tr("kind.subprogram_n", n=step.job)
    return p.tr("kind.halt")


def _mark(p: Pendant, result: bool | None) -> str:
    """Suffix of a blending mode in the select: accepted / refused by the robot in this connection."""
    if result is None:
        return ""
    return "  ✓" if result else "  – " + p.tr("blend.rejected")


def default_blending(p: Pendant) -> str:
    """Blending mode for a step that is switched to blended: the last one the robot accepted in this
    connection, else one it did not refuse (JAKA MiniCobo: only MAX_CORNER_DEVIATION)."""
    results = p.robot.blending_results
    accepted = [m for m, ok in results.items() if ok]
    if accepted:
        return accepted[-1]
    for mode in ("CORNER_DISTANCE", "MAX_CORNER_DEVIATION", *BLENDING_MODES[1:]):
        if results.get(mode) is not False:
            return mode
    return "CORNER_DISTANCE"


def new_step(p: Pendant, kind: StepKind) -> Step:
    """A new step of ``kind`` with sensible defaults."""
    points = [pt.name for pt in p.ws.program.points]
    if kind is StepKind.MOVE:
        return Step(points[-1] if points else "", Motion.JOINT)
    if kind is StepKind.RELATIVE:
        return Step("", Motion.LINEAR, kind=kind, offset=[0.0, 0.0, 50.0, 0.0, 0.0, 0.0], reference="tool",
                    tool=p.robot.tool, frame=p.robot.frame)  # fmt: skip
    if kind is StepKind.WAIT:
        return Step("", kind=kind, duration=1.0)
    return Step("", kind=kind)


async def edit_step(p: Pendant, index: int | None, step: Step | None = None) -> Step | None:
    """Opens the editor for step ``index`` (or a new ``step``); returns the new step (not yet
    stored) or None."""
    if step is None:
        assert index is not None
        step = p.ws.program.steps[index]
    kind = step.kind
    points = [pt.name for pt in p.ws.program.points]
    v: dict[str, Any] = {
        "point": step.point if step.point in points else (points[-1] if points else None),
        "via": step.via if step.via in points else (points[0] if points else None),
        "motion": step.motion.value,
        "blended": step.blended,
        "mode": step.blending_mode if step.blended else default_blending(p),
        "p0": step.blending or 10.0,
        "p1": step.blending_post,
        "reference": step.reference,
        "tool": step.tool,
        "frame": step.frame,
        "duration": step.duration,
        "signal": step.signal,
        "value": step.value,
        "timeout": step.timeout,
        "job": step.job,
        "data": ", ".join(str(b) for b in step.data),
        "note": step.note,
        "enabled": step.enabled,
    }
    offset_inputs: list[ui.number] = []
    dyn = {name: getattr(step, name) for name in DYNAMICS}
    title = p.tr("step.title", n=index + 1) if index is not None else p.tr("step.new")
    motions = (Motion.LINEAR, Motion.PTP, Motion.JOINT) + ((Motion.CIRC,) if kind is StepKind.MOVE else ())

    with ui.dialog() as dialog, ui.card().classes("w-full max-w-[640px] gap-4"):
        with ui.row().classes("w-full items-center justify-between no-wrap"):
            with ui.row().classes("items-center gap-3 no-wrap"):
                ui.icon(KIND_ICONS[kind]).classes("text-[26px] text-[var(--blue)]")
                with ui.column().classes("gap-0"):
                    ui.label(title).classes("text-[22px] font-bold")
                    ui.label(p.tr(f"kind.{kind.value}")).classes("tp-muted")
            ui.switch(p.tr("step.enabled"), value=v["enabled"]).bind_value(v, "enabled").mark("step-enabled")

        if kind in (StepKind.MOVE, StepKind.RELATIVE):
            ui.label(p.tr("step.motion")).classes("tp-card-title")
            ui.toggle({m.value: p.tr(f"step.{m.value}") for m in motions}, value=v["motion"]).bind_value(
                v, "motion"
            ).props("no-caps unelevated").classes("tp-seg self-start").mark("motion-toggle")
            prefix = "step.rel_" if kind is StepKind.RELATIVE else "step."
            ui.label().bind_text_from(v, "motion", lambda m: p.tr(f"{prefix}{m}_long")).classes("tp-muted -mt-2")

            def unsupported(m: str) -> str:
                f = step_function(Step("", Motion(m), kind=kind, via="x"))
                return "" if f is None or p.snap.can(f) else p.tr("caps.not_supported", f=f)

            ui.label().bind_text_from(v, "motion", unsupported).classes("text-[var(--red)] font-medium -mt-2")

        if kind is StepKind.MOVE:
            with ui.row().classes("w-full gap-3 no-wrap"):
                ui.select(points, value=v["point"], label=p.tr("step.point")).bind_value(v, "point").props(
                    "filled"
                ).classes("flex-1").mark("step-point")
                ui.select(points, value=v["via"], label=p.tr("step.via")).bind_value(v, "via").props(
                    "filled"
                ).classes("flex-1").bind_visibility_from(v, "motion", lambda m: m == "circ")
            ui.label(p.tr("step.circ_hint")).classes("tp-muted -mt-2").bind_visibility_from(
                v, "motion", lambda m: m == "circ"
            )

        if kind is StepKind.RELATIVE:
            with ui.row().classes("w-full gap-3 no-wrap items-center"):
                ui.toggle({"tool": p.tr("jog.tool"), "frame": p.tr("coord.frame")}, value=v["reference"]).bind_value(
                    v, "reference"
                ).props("no-caps unelevated").classes("tp-seg").bind_visibility_from(
                    v, "motion", lambda m: m != "joint"
                )
                ui.select(coords.options(p, coords.TOOL), value=v["tool"], label=p.tr("coord.tool")).bind_value(
                    v, "tool"
                ).props("filled dense").classes("flex-1")
                ui.select(coords.options(p, coords.FRAME), value=v["frame"], label=p.tr("coord.frame")).bind_value(
                    v, "frame"
                ).props("filled dense").classes("flex-1").bind_visibility_from(v, "motion", lambda m: m != "joint")
            with ui.element("div").classes("grid grid-cols-3 gap-3 w-full"):
                for i in range(6):
                    offset_inputs.append(
                        ui.number(value=step.offset[i], format="%.2f").props("filled dense").classes("tp-mono-in")
                    )

            def offset_labels() -> None:
                joint = v["motion"] == "joint"
                for i, field in enumerate(offset_inputs):
                    name = (JOINTS if joint else CARTESIAN)[i]
                    unit = "°" if joint or i >= 3 else "mm"
                    p.put(field, "props", f'label="Δ {name}" suffix="{unit}"')

            offset_labels()
            ui.timer(0.3, offset_labels)

        if kind in (StepKind.MOVE, StepKind.RELATIVE):
            ui.label(p.tr("step.blend")).classes("tp-card-title")
            ui.toggle({False: p.tr("step.absolute"), True: p.tr("step.blended")}, value=v["blended"]).bind_value(
                v, "blended"
            ).props("no-caps unelevated").classes("tp-seg self-start").mark("blend-toggle")
            with ui.column().classes("w-full gap-3").bind_visibility_from(v, "blended"):
                results = p.robot.blending_results
                ui.select(
                    {m: p.tr(f"blend.{m}") + _mark(p, results.get(m))
                     for m in BLENDING_MODES if m != "EXACT_STOP"}, value=v["mode"],
                    label=p.tr("step.blend_mode"),
                ).bind_value(v, "mode").props("filled").classes("w-full")  # fmt: skip
                with ui.row().classes("w-full gap-3 no-wrap"):
                    before = ui.number(p.tr("step.blend_before"), value=v["p0"], min=0, max=1000).bind_value(
                        v, "p0"
                    )
                    before.props("filled").classes("flex-1 tp-mono-in")
                    after = ui.number(p.tr("step.blend_after"), value=v["p1"], min=0, max=1000).bind_value(
                        v, "p1"
                    )
                    after.props("filled").classes("flex-1 tp-mono-in")

            def units() -> None:
                u0, u1 = BLENDING_UNITS[str(v["mode"])]
                before.props(f'suffix="{u0 or ""}"')
                after.props(f'suffix="{u1 or ""}"')
                after.set_visibility(u1 is not None)

            units()
            ui.timer(0.2, units)
            dynamics_rows(p, dyn)

        if kind is StepKind.WAIT:
            ui.number(p.tr("step.duration"), value=v["duration"], min=0, max=3600, step=0.5, suffix="s").bind_value(
                v, "duration"
            ).props("filled").classes("w-48 tp-mono-in")
            ui.label(p.tr("step.wait_hint")).classes("tp-muted")

        if kind in (StepKind.OUTPUT, StepKind.WAIT_INPUT):
            io = "do" if kind is StepKind.OUTPUT else "di"
            with ui.row().classes("w-full gap-3 items-center no-wrap"):
                ui.number(p.tr("io.signal"), value=v["signal"], min=0, max=2047, precision=0).bind_value(
                    v, "signal", forward=lambda x: int(x or 0)
                ).props("filled").classes("w-36 tp-mono-in").mark("step-signal")
                ui.toggle({True: p.tr("io.on"), False: p.tr("io.off")}, value=v["value"]).bind_value(
                    v, "value"
                ).props("no-caps unelevated").classes("tp-seg")
            ui.label().bind_text_from(v, "signal", lambda s: signal_label(p, io, int(s or 0))).classes(
                "tp-muted -mt-2"
            )
            if kind is StepKind.WAIT_INPUT:
                ui.number(p.tr("step.timeout"), value=v["timeout"], min=0, max=3600, suffix="s").bind_value(
                    v, "timeout"
                ).props("filled").classes("w-48 tp-mono-in")
                ui.label(p.tr("step.timeout_hint")).classes("tp-muted -mt-2")
            else:
                ui.label(p.tr("step.output_hint")).classes("tp-muted")

        if kind is StepKind.SUBPROGRAM:
            ui.number(p.tr("step.job"), value=v["job"], min=0, max=65535, precision=0).bind_value(
                v, "job", forward=lambda x: int(x or 0)
            ).props("filled").classes("w-48 tp-mono-in")
            ui.input(p.tr("step.data"), value=v["data"]).bind_value(v, "data").props("filled").classes(
                "w-full tp-mono-in"
            )
            ui.label(p.tr("step.subprogram_hint")).classes("tp-muted -mt-2")

        if kind is StepKind.HALT:
            ui.label(p.tr("step.halt_hint")).classes("tp-banner w-full")

        ui.input(p.tr("step.note"), value=v["note"]).bind_value(v, "note").props("filled dense").classes("w-full")

        with ui.row().classes("w-full justify-end gap-2"):
            ui.button(p.tr("common.cancel"), on_click=lambda: dialog.submit(None)).props("flat no-caps")
            ui.button(p.tr("step.apply"), on_click=lambda: dialog.submit(True)).props(
                "unelevated no-caps color=primary"
            ).mark("step-apply")
    if not await dialog:
        return None
    blended = bool(v["blended"]) and kind in (StepKind.MOVE, StepKind.RELATIVE)
    motion = Motion(str(v["motion"]))
    if kind is StepKind.MOVE and not v["point"]:
        raise ValueError(p.tr("step.need_point"))
    if kind is StepKind.MOVE and motion is Motion.CIRC and v["via"] == v["point"]:
        raise ValueError(p.tr("step.need_via"))
    data = [int(x, 0) for x in str(v["data"]).replace(";", ",").replace(" ", ",").split(",") if x.strip()]
    return Step(
        point=str(v["point"] or "") if kind is StepKind.MOVE else "",
        motion=motion,
        blending_mode=str(v["mode"]) if blended else "EXACT_STOP",
        blending=float(v["p0"] or 0.0) if blended else 0.0,
        blending_post=float(v["p1"] or 0.0) if blended and BLENDING_UNITS[str(v["mode"])][1] else 0.0,
        **dyn,
        kind=kind,
        via=str(v["via"] or "") if kind is StepKind.MOVE and motion is Motion.CIRC else "",
        offset=[float(f.value or 0.0) for f in offset_inputs] if kind is StepKind.RELATIVE else [0.0] * 6,
        reference=str(v["reference"]),
        tool=int(v["tool"] or 0),
        frame=int(v["frame"] or 0),
        duration=float(v["duration"] or 0.0),
        signal=int(v["signal"] or 0),
        value=bool(v["value"]),
        timeout=float(v["timeout"] or 0.0),
        job=int(v["job"] or 0),
        data=data,
        enabled=bool(v["enabled"]),
        note=str(v["note"] or "").strip(),
    )


def dynamics_rows(p: Pendant, dyn: dict[str, float]) -> None:
    """Sliders for velocity, acceleration, deceleration and jerk, each in % or "default of the RC"."""
    with ui.row().classes("w-full items-baseline justify-between"):
        ui.label(p.tr("step.dynamics")).classes("tp-card-title")
        ui.label(p.tr("step.dynamics_hint")).classes("tp-muted")
    with ui.column().classes("w-full gap-0"):
        for name in DYNAMICS:
            state: dict[str, Any] = {
                "default": bool(dyn[name] == DEFAULT),
                "value": 100.0 if dyn[name] == DEFAULT else dyn[name],
            }
            with ui.element("div").classes("tp-row"):
                ui.label(p.tr(DYN_KEYS[name])).classes("w-36 font-medium")
                slider = ui.slider(min=1, max=100, step=1, value=state["value"]).classes("flex-1")
                value = ui.label().classes("tp-mono w-14 text-right")
                default = ui.checkbox(p.tr("step.default"), value=state["default"])

                def sync(_: object = None, n: str = name, s: ui.slider = slider, lab: ui.label = value,
                         d: ui.checkbox = default) -> None:  # fmt: skip
                    dyn[n] = DEFAULT if d.value else float(s.value)
                    s.set_enabled(not d.value)
                    lab.set_text("RC" if d.value else f"{s.value:.0f} %")

                slider.on_value_change(sync)
                default.on_value_change(sync)
                sync()


async def path_settings(p: Pendant) -> bool:
    """Set blending and dynamics of all motion steps at once. Returns True if steps changed."""
    motions = [s for s in p.ws.program.steps if s.is_motion]
    if not motions:
        ui.notify(p.tr("path.no_motions"), type="warning", position="top")
        return False
    v: dict[str, Any] = {"blend": "keep", "mode": default_blending(p), "p0": 10.0, "dyn": False}
    dyn = {name: getattr(motions[0], name) for name in DYNAMICS}
    with ui.dialog() as dialog, ui.card().classes("w-full max-w-[600px] gap-4"):
        ui.label(p.tr("path.title")).classes("text-[22px] font-bold")
        ui.label(p.tr("path.lead", n=len(motions))).classes("tp-muted -mt-3")
        ui.label(p.tr("step.blend")).classes("tp-card-title")
        ui.toggle({"keep": p.tr("path.keep"), "exact": p.tr("step.absolute"), "blend": p.tr("step.blended")},
                  value="keep").bind_value(v, "blend").props("no-caps unelevated").classes("tp-seg self-start")  # fmt: skip
        with ui.row().classes("w-full gap-3 no-wrap").bind_visibility_from(v, "blend", lambda b: b == "blend"):
            ui.select({m: p.tr(f"blend.{m}") for m in BLENDING_MODES if m != "EXACT_STOP"}, value=v["mode"],
                      label=p.tr("step.blend_mode")).bind_value(v, "mode").props("filled").classes("flex-1")  # fmt: skip
            ui.number(p.tr("step.blend_before"), value=10.0, min=0, max=1000).bind_value(v, "p0").props(
                "filled"
            ).classes("w-40 tp-mono-in")
        ui.switch(p.tr("path.set_dynamics"), value=False).bind_value(v, "dyn")
        with ui.column().classes("w-full").bind_visibility_from(v, "dyn"):
            dynamics_rows(p, dyn)
        with ui.row().classes("w-full justify-end gap-2"):
            ui.button(p.tr("common.cancel"), on_click=lambda: dialog.submit(False)).props("flat no-caps")
            ui.button(p.tr("path.apply_all"), on_click=lambda: dialog.submit(True)).props(
                "unelevated no-caps color=primary"
            ).mark("path-apply")
    if not await dialog:
        return False
    for s in motions:
        if v["blend"] == "exact":
            s.blending_mode, s.blending, s.blending_post = "EXACT_STOP", 0.0, 0.0
        elif v["blend"] == "blend":
            s.blending_mode, s.blending = str(v["mode"]), float(v["p0"] or 0.0)
            s.blending_post = s.blending if BLENDING_UNITS[s.blending_mode][1] else 0.0
        if v["dyn"]:
            for name in DYNAMICS:
                setattr(s, name, dyn[name])
    return True
