"""Dialog to edit one step: target point, motion type, blending and dynamics."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nicegui import ui

from srci_teach.model import BLENDING_MODES, BLENDING_UNITS, DEFAULT, Motion, Step
from srci_teach.robot import MOTION_FUNCTIONS

if TYPE_CHECKING:
    from srci_teach.ui.pendant import Pendant

DYNAMICS = ("velocity", "acceleration", "deceleration", "jerk")
DYN_KEYS = {
    "velocity": "step.vel",
    "acceleration": "step.acc",
    "deceleration": "step.dec",
    "jerk": "step.jerk",
}


def motion_label(p: Pendant, step: Step) -> str:
    """``LIN``, ``PTP``, ``Joint`` - with ``⤳`` when blended."""
    return p.tr(f"step.{step.motion.value}") + (" ⤳" if step.blended else "")


def blend_label(p: Pendant, step: Step) -> str:
    if step.exact_stop:
        return p.tr("step.absolute")
    unit0, unit1 = BLENDING_UNITS[step.blending_mode]
    text = f"{step.blending:g} {unit0}" if unit0 else ""
    if unit1:
        text += f" / {step.blending_post:g} {unit1}"
    return text


async def edit_step(p: Pendant, index: int) -> Step | None:
    """Opens the editor for step ``index``; returns the new step (not yet stored) or None."""
    step = p.ws.program.steps[index]
    v: dict[str, Any] = {
        "point": step.point,
        "motion": step.motion.value,
        "blended": step.blended,
        "mode": step.blending_mode if step.blended else "CORNER_DISTANCE",
        "p0": step.blending or 10.0,
        "p1": step.blending_post,
    }
    dyn = {name: getattr(step, name) for name in DYNAMICS}
    with ui.dialog() as dialog, ui.card().classes("w-full max-w-[600px] gap-4"):
        with ui.row().classes("w-full items-center justify-between"):
            ui.label(p.tr("step.title", n=index + 1)).classes("text-[22px] font-bold")
            ui.select(
                [pt.name for pt in p.ws.program.points], value=v["point"], label=p.tr("step.point")
            ).bind_value(v, "point").props("filled dense").classes("min-w-[160px]")

        # motion type
        ui.label(p.tr("step.motion")).classes("tp-card-title")
        ui.toggle(
            {m.value: p.tr(f"step.{m.value}") for m in (Motion.LINEAR, Motion.PTP, Motion.JOINT)},
            value=v["motion"],
        ).bind_value(v, "motion").props("no-caps unelevated").classes("tp-seg self-start").mark(
            "motion-toggle"
        )
        ui.label().bind_text_from(v, "motion", lambda m: p.tr(f"step.{m}_long")).classes("tp-muted -mt-2")
        ui.label().bind_text_from(
            v,
            "motion",
            lambda m: (
                "" if p.snap.can(MOTION_FUNCTIONS[m]) else p.tr("caps.not_supported", f=MOTION_FUNCTIONS[m])
            ),
        ).classes("text-[var(--red)] font-medium -mt-2")

        # blending
        ui.label(p.tr("step.blend")).classes("tp-card-title")
        ui.toggle({False: p.tr("step.absolute"), True: p.tr("step.blended")}, value=v["blended"]).bind_value(
            v, "blended"
        ).props("no-caps unelevated").classes("tp-seg self-start").mark("blend-toggle")
        with ui.column().classes("w-full gap-3").bind_visibility_from(v, "blended"):
            ui.select(
                {m: p.tr(f"blend.{m}") for m in BLENDING_MODES if m != "EXACT_STOP"}, value=v["mode"],
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

        # dynamics
        with ui.row().classes("w-full items-baseline justify-between"):
            ui.label(p.tr("step.dynamics")).classes("tp-card-title")
            ui.label(p.tr("step.dynamics_hint")).classes("tp-muted")
        with ui.column().classes("w-full gap-0"):
            for name in DYNAMICS:
                state = {
                    "default": dyn[name] == DEFAULT,
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

        with ui.row().classes("w-full justify-end gap-2"):
            ui.button(p.tr("common.cancel"), on_click=lambda: dialog.submit(None)).props("flat no-caps")
            ui.button(p.tr("step.apply"), on_click=lambda: dialog.submit(True)).props(
                "unelevated no-caps color=primary"
            ).mark("step-apply")
    if not await dialog:
        return None
    blended = bool(v["blended"])
    return Step(
        point=str(v["point"]),
        motion=Motion(str(v["motion"])),
        blending_mode=str(v["mode"]) if blended else "EXACT_STOP",
        blending=float(v["p0"] or 0.0) if blended else 0.0,
        blending_post=float(v["p1"] or 0.0) if blended and BLENDING_UNITS[str(v["mode"])][1] else 0.0,
        **dyn,
    )
