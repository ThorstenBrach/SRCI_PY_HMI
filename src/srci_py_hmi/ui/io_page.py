"""Page "I/O": digital inputs and outputs of the RC (Read/WriteDigitalInputs/Outputs) as a grid of
signals that is read live, outputs switched by a tap, and the integer / real registers
(Read/WriteIntegers, Read/WriteReals)."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from nicegui import background_tasks, run, ui

from srci_py_hmi.robot import IO_BYTES, REGISTERS, Phase

if TYPE_CHECKING:
    from srci_py_hmi.ui.pendant import Pendant

GROUPS = {b: f"{b * 8} – {(b + IO_BYTES) * 8 - 1}" for b in range(0, 256 - IO_BYTES + 1, IO_BYTES)}
REGISTER_GROUPS = {i: f"{i} – {i + REGISTERS - 1}" for i in range(0, 256 - REGISTERS + 1, REGISTERS)}


class IoPage:
    def __init__(self, p: Pendant) -> None:
        self.p = p
        self.first = {"di": 0, "do": 0}  # first byte of the shown group
        self.values: dict[str, list[int] | None] = {"di": None, "do": None}
        self.leds: dict[str, list[ui.element]] = {"di": [], "do": []}
        self.numbers: dict[str, list[ui.label]] = {"di": [], "do": []}
        self.live = True
        self.reading = False
        self.last_read = 0.0
        self.reg = {"real": False, "first": 0}
        self.reg_inputs: list[ui.number] = []

    def name(self, kind: str, signal: int) -> str:
        return self.p.ws.labels.get(kind, {}).get(str(signal), "")

    def build(self) -> None:
        p = self.p
        with ui.column().classes("tp-page"):
            with ui.row().classes("w-full items-end justify-between gap-3"):
                p.page_title(p.tr("io.title"), p.tr("io.lead"))
                with ui.row().classes("items-center gap-3"):
                    ui.switch(p.tr("io.live"), value=self.live, on_change=lambda e: setattr(self, "live", e.value))
                    ui.button(p.tr("io.read"), icon="sync", on_click=self.read_now).props("flat no-caps").classes(
                        "tp-btn-soft"
                    )
            self.banner = ui.label("").classes("tp-banner w-full")
            with ui.element("div").classes("grid w-full gap-5 items-start lg:grid-cols-2"):
                for kind in ("di", "do"):
                    with p.card():
                        with ui.row().classes("w-full items-center justify-between no-wrap mb-2"):
                            with ui.column().classes("gap-0"):
                                ui.label(p.tr(f"io.{kind}")).classes("text-[17px] font-semibold")
                                ui.label(p.tr(f"io.{kind}_hint")).classes("tp-muted")
                            with ui.row().classes("items-center gap-1 no-wrap"):
                                ui.select(GROUPS, value=0, on_change=lambda e, k=kind: self.set_group(k, e.value)).props(
                                    "filled dense options-dense"
                                ).classes("w-36 tp-mono-in")
                                ui.button(icon="edit_note", on_click=lambda k=kind: self.edit_labels(k)).props(
                                    "flat round dense"
                                ).classes("text-[var(--blue)]").tooltip(p.tr("io.labels"))
                        self.grid(kind)
            with p.card(p.tr("reg.title")):
                with ui.row().classes("w-full items-center gap-3"):
                    ui.toggle({False: p.tr("reg.int"), True: p.tr("reg.real")}, value=False,
                              on_change=lambda e: self.set_reg(real=bool(e.value))).props(
                        "no-caps unelevated").classes("tp-seg")  # fmt: skip
                    ui.select(REGISTER_GROUPS, value=0, label=p.tr("reg.index"),
                              on_change=lambda e: self.set_reg(first=int(e.value))).props(
                        "filled dense options-dense").classes("w-36 tp-mono-in")  # fmt: skip
                    ui.space()
                    self.reg_read = ui.button(p.tr("io.read"), icon="download", on_click=self.read_registers).props(
                        "flat no-caps"
                    ).classes("tp-btn-soft")
                    self.reg_write = ui.button(p.tr("reg.write"), icon="upload", on_click=self.write_registers).props(
                        "unelevated no-caps color=primary"
                    ).mark("reg-write")
                with ui.element("div").classes("grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-3 w-full mt-3"):
                    for i in range(REGISTERS):
                        self.reg_inputs.append(
                            ui.number(str(i), value=0).props("filled dense").classes("tp-mono-in").mark(f"reg-{i}")
                        )
                ui.label(p.tr("reg.hint")).classes("tp-muted mt-2")

    def grid(self, kind: str) -> None:
        with ui.column().classes("w-full gap-2"):
            for byte in range(IO_BYTES):
                with ui.element("div").classes("tp-io-row"):
                    self.numbers[kind].append(ui.label("").classes("tp-muted tp-mono w-10"))
                    for bit in range(8):
                        led = ui.element("div").classes(f"tp-led {kind}")
                        with led:
                            ui.label(str(bit)).classes("tp-led-bit")
                        if kind == "do":
                            led.on("click", lambda _, b=byte, i=bit: self.toggle(b, i))
                        self.leds[kind].append(led)
        self.update_names(kind)

    def update_names(self, kind: str) -> None:
        first = self.first[kind]
        for byte, label in enumerate(self.numbers[kind]):
            label.set_text(f"{(first + byte) * 8}")
        for i, led in enumerate(self.leds[kind]):
            signal = first * 8 + i
            name = self.name(kind, signal)
            led.props(f'title="{kind.upper()} {signal}{(" · " + name) if name else ""}"')
            led.classes(add="named") if name else led.classes(remove="named")

    def set_group(self, kind: str, first: int) -> None:
        self.first[kind] = int(first)
        self.values[kind] = None
        self.update_names(kind)
        self.draw()
        self.read_now()

    # ------------------------------------------------------------------ reading

    def can(self, kind: str) -> bool:
        return self.p.snap.can("ReadDigitalInputs" if kind == "di" else "ReadDigitalOutputs")

    def tick(self) -> None:
        """Called by the timer of the pendant while the page is shown."""
        s = self.p.snap
        ready = s.phase is Phase.READY
        missing = [f for f in ("ReadDigitalInputs", "ReadDigitalOutputs", "WriteDigitalOutputs") if not s.can(f)]
        text = (self.p.tr("io.need_connection") if not ready
                else self.p.tr("caps.not_supported", f=", ".join(missing)) if missing else "")  # fmt: skip
        self.banner.set_text(text)
        self.banner.set_visibility(bool(text))
        for btn in (self.reg_read, self.reg_write):
            btn.set_enabled(ready)
        if ready and self.live and time.monotonic() - self.last_read > 0.5:
            self.read_now()

    def read_now(self) -> None:
        if self.reading or self.p.snap.phase is not Phase.READY:
            return
        self.reading = True
        self.last_read = time.monotonic()

        async def read() -> None:
            try:
                for kind in ("di", "do"):
                    if self.can(kind):
                        try:
                            self.values[kind] = await run.io_bound(self.p.robot.read_io, self.first[kind], kind == "do")
                        except Exception:  # shown in the banner of the messages, not every 0.5 s
                            self.values[kind] = None
                self.draw()
            finally:
                self.reading = False
                self.last_read = time.monotonic()

        background_tasks.create(read(), name="read I/O")

    def draw(self) -> None:
        for kind in ("di", "do"):
            values = self.values[kind]
            for i, led in enumerate(self.leds[kind]):
                byte, bit = divmod(i, 8)
                state = "unknown" if values is None else ("on" if values[byte] >> bit & 1 else "off")
                self.p.put(led, "classes", f"tp-led {kind} {state}" + (" named" if self.name(kind, self.first[kind] * 8 + i) else ""))

    async def toggle(self, byte: int, bit: int) -> None:
        values = self.values["do"]
        if values is None:
            return
        signal = (self.first["do"] + byte) * 8 + bit
        new = not bool(values[byte] >> bit & 1)
        def write() -> bool:
            self.p.robot.write_output(signal, new)
            return True

        if not await self.p.act(write):
            return
        values[byte] ^= 1 << bit  # shown at once, confirmed by the next read
        self.draw()
        self.read_now()

    async def edit_labels(self, kind: str) -> None:
        p = self.p
        first = self.first[kind] * 8
        inputs: dict[int, ui.input] = {}
        with ui.dialog() as dialog, ui.card().classes("w-full max-w-[640px] gap-3"):
            ui.label(p.tr("io.labels_title", kind=kind.upper(), a=first, b=first + IO_BYTES * 8 - 1)).classes(
                "text-[20px] font-semibold"
            )
            with ui.scroll_area().classes("w-full h-[420px]"), ui.element("div").classes("grid grid-cols-2 gap-2 w-full"):
                for signal in range(first, first + IO_BYTES * 8):
                    inputs[signal] = ui.input(f"{kind.upper()} {signal}", value=self.name(kind, signal)).props(
                        "filled dense"
                    )
            with ui.row().classes("w-full justify-end gap-2"):
                ui.button(p.tr("common.cancel"), on_click=lambda: dialog.submit(False)).props("flat no-caps")
                ui.button(p.tr("common.save"), on_click=lambda: dialog.submit(True)).props(
                    "unelevated no-caps color=primary"
                )
        if not await dialog:
            return
        labels = p.ws.labels.setdefault(kind, {})
        for signal, field in inputs.items():
            text = str(field.value or "").strip()
            if text:
                labels[str(signal)] = text
            else:
                labels.pop(str(signal), None)
        p.ws.save_labels()
        self.update_names(kind)
        self.draw()

    # ------------------------------------------------------------------ registers

    def set_reg(self, real: bool | None = None, first: int | None = None) -> None:
        if real is not None:
            self.reg["real"] = real
        if first is not None:
            self.reg["first"] = first
        for i, field in enumerate(self.reg_inputs):
            field.props(f'label="{self.reg["first"] + i}"')
            field.set_value(0)
            field.props(f'step={0.1 if self.reg["real"] else 1}')

    async def read_registers(self) -> None:
        values: Any = await self.p.act(self.p.robot.read_registers, bool(self.reg["real"]), int(self.reg["first"]))
        if values is not None:
            for field, value in zip(self.reg_inputs, values, strict=True):
                field.set_value(round(value, 4) if self.reg["real"] else int(value))

    async def write_registers(self) -> None:
        values = [float(f.value or 0.0) for f in self.reg_inputs]
        if self.reg["real"] is False and any(v != int(v) for v in values):
            ui.notify(self.p.tr("reg.integers_only"), type="warning", position="top")
            return
        def write() -> bool:
            self.p.robot.write_registers(bool(self.reg["real"]), int(self.reg["first"]), values)
            return True

        await self.p.act(write, done=self.p.tr("reg.written"))
