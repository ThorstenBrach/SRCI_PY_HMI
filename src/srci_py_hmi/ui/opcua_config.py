"""Connection over OPC UA: fields of the connection page and the node browser (configurator).

The robot controller offers the SRCI telegrams on two variables of its OPC UA server; the
configurator connects to the server, lists its variables and takes the two telegram nodes
(PLC->RC written by the HMI, RC->PLC read) - see ``srci.transport.OpcUaTransport``.
"""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING, Any

from nicegui import app, run, ui

from srci_py_hmi.robot import Target

if TYPE_CHECKING:
    from srci_py_hmi.ui.pendant import Pendant


def save_settings(target: Target) -> None:
    """OPC UA settings for the next start (without the password)."""
    app.storage.general["opcua"] = {**target.opcua_settings(), "transport": target.transport}


def build_fields(p: Pendant, target: Target) -> None:
    """Endpoint, login, telegram nodes and length (inside the connection card)."""
    ui.input(p.tr("opcua.endpoint"), placeholder="opc.tcp://192.168.2.10:4840").bind_value(
        target, "opcua_endpoint"
    ).props("filled").classes("w-full").mark("opcua-endpoint")
    with ui.row().classes("w-full gap-3 no-wrap"):
        ui.input(p.tr("opcua.user")).bind_value(target, "opcua_user").props("filled").classes("flex-1").mark(
            "opcua-user"
        )
        ui.input(p.tr("opcua.password"), password=True, password_toggle_button=True).bind_value(
            target, "opcua_password"
        ).props("filled").classes("flex-1").mark("opcua-password")
    ui.input(p.tr("opcua.out"), placeholder="ns=2;s=SRCI.PlcToRob").bind_value(target, "opcua_out").props(
        "filled"
    ).classes("w-full tp-mono-in").mark("opcua-out")
    ui.input(p.tr("opcua.in"), placeholder="ns=2;s=SRCI.RobToPlc").bind_value(target, "opcua_in").props(
        "filled"
    ).classes("w-full tp-mono-in").mark("opcua-in")
    with ui.row().classes("w-full gap-3 items-center no-wrap"):
        ui.number(p.tr("conn.length"), min=32, max=1024, precision=0).bind_value(
            target, "length", forward=lambda v: int(v or 256)
        ).props("filled").classes("flex-1")
        ui.button(p.tr("opcua.browse"), icon="travel_explore", on_click=lambda: browse_dialog(p, target)).props(
            "outline no-caps"
        ).mark("opcua-browse")
    ui.label(p.tr("opcua.hint")).classes("tp-muted")


async def browse_dialog(p: Pendant, target: Target) -> None:
    """Connect to the server, list its variables and take the telegram nodes."""
    from srci.transport.opcua import OpcUaNodeInfo, browse

    endpoint = target.opcua_endpoint.strip()
    try:
        found: list[OpcUaNodeInfo] | None = await run.io_bound(
            browse,
            endpoint,
            username=target.opcua_user.strip() or None,
            password=target.opcua_password or None,
        )
    except Exception as exc:  # TransportConnectError, missing asyncua
        ui.notify(f"{p.tr('opcua.browse_failed')}: {exc}", type="negative", position="top", multi_line=True)
        return
    if found is None:  # app shutting down
        return
    nodes = found
    only = {"value": True}
    with p.dialog() as dialog, ui.card().classes("w-[min(920px,96vw)] max-w-none"):
        ui.label(p.tr("opcua.browse_title", endpoint=endpoint)).classes("text-[17px] font-semibold")
        with ui.row().classes("w-full items-center gap-3"):
            ui.switch(p.tr("opcua.only_candidates"), value=True, on_change=lambda e: show(bool(e.value))).mark(
                "opcua-only"
            )
            ui.label(p.tr("opcua.count", n=len(nodes))).classes("tp-muted")
        listing = ui.column().classes("w-full gap-1 max-h-[60vh] overflow-auto")

        def pick(info: OpcUaNodeInfo, direction: str) -> None:
            setattr(target, "opcua_out" if direction == "out" else "opcua_in", info.node_id)
            if info.length > 0 and info.length != target.length:
                target.length = info.length
                ui.notify(p.tr("opcua.length_taken", n=info.length), type="info", position="top")
            show(only["value"])

        def show(candidates_only: bool) -> None:
            only["value"] = candidates_only
            listing.clear()
            shown = [n for n in nodes if n.telegram_candidate or not candidates_only]
            with listing:
                if not shown:
                    ui.label(p.tr("opcua.none")).classes("tp-empty w-full")
                for info in shown:
                    _row(p, target, info, pick)

        show(True)
        with ui.row().classes("w-full justify-end gap-2"):
            ui.button(p.tr("common.ok"), on_click=lambda: dialog.submit(None)).props(
                "unelevated no-caps color=primary"
            ).mark("opcua-done")
    await dialog


def _row(p: Pendant, target: Target, info: Any, pick: Any) -> None:
    size = f"[{info.length}]" if info.length >= 0 else ""
    with ui.element("div").classes("tp-item w-full").mark(f"opcua-node-{info.node_id}"):
        with ui.column().classes("flex-1 gap-0 min-w-0"):
            ui.label(info.path).classes("font-medium truncate")
            access = p.tr("opcua.writable") if info.writable else p.tr("opcua.readonly")
            ui.label(f"{info.node_id} · {info.data_type}{size} · {access}").classes("tp-muted tp-mono truncate")
        for direction, used, key in (("out", info.node_id == target.opcua_out, "opcua.as_out"),
                                     ("in", info.node_id == target.opcua_in, "opcua.as_in")):  # fmt: skip
            button = ui.button(p.tr(key), icon="check" if used else None, on_click=partial(pick, info, direction))
            button.mark(f"opcua-{direction}:{info.node_id}")
            button.props(f"{'unelevated color=primary' if used else 'outline'} no-caps dense")
            if direction == "out" and not info.writable:
                button.disable()
