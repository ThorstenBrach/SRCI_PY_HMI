"""Texts of the UI in German and English (``t("key")``)."""

from __future__ import annotations

from contextvars import ContextVar

LANGUAGES = {"de": "Deutsch", "en": "English"}
DEFAULT = "de"

_language: ContextVar[str] = ContextVar("language", default=DEFAULT)

TEXTS: dict[str, dict[str, str]] = {
    # app / navigation
    "app.title": {"de": "SRCI Teach", "en": "SRCI Teach"},
    "nav.connection": {"de": "Verbindung", "en": "Connection"},
    "nav.jog": {"de": "Bewegen", "en": "Jog"},
    "nav.program": {"de": "Programm", "en": "Program"},
    "nav.messages": {"de": "Meldungen", "en": "Messages"},
    "stop": {"de": "STOPP", "en": "STOP"},
    "stop.hint": {
        "de": "Stoppt Tippen, Programm und Bewegung (GroupStop). Ersetzt nicht den Not-Halt.",
        "en": "Stops jogging, program and motion (GroupStop). No replacement for the emergency stop.",
    },
    "theme.toggle": {"de": "Hell / Dunkel", "en": "Light / dark"},
    "language": {"de": "Sprache", "en": "Language"},
    # phases / activity
    "phase.disconnected": {"de": "Nicht verbunden", "en": "Not connected"},
    "phase.connecting": {"de": "Verbinde …", "en": "Connecting …"},
    "phase.ready": {"de": "Bereit", "en": "Ready"},
    "phase.lost": {"de": "Verbindung verloren", "en": "Connection lost"},
    "phase.failed": {"de": "Verbindung fehlgeschlagen", "en": "Connection failed"},
    "activity.jogging": {"de": "Tippen", "en": "Jogging"},
    "activity.moving": {"de": "Fährt", "en": "Moving"},
    "activity.running": {"de": "Programm läuft", "en": "Program running"},
    "state.off": {"de": "Aus", "en": "Off"},
    "state.on": {"de": "Ein", "en": "On"},
    "state.error": {"de": "Störung", "en": "Fault"},
    # connection page
    "conn.title": {"de": "Roboter verbinden", "en": "Connect robot"},
    "conn.subtitle": {
        "de": "Über das SPS-Gateway (TCP) oder gegen den SDK-Simulator.",
        "en": "Through the PLC gateway (TCP) or against the SDK simulator.",
    },
    "conn.robot": {"de": "Roboter", "en": "Robot"},
    "conn.simulator": {"de": "Simulator", "en": "Simulator"},
    "conn.host": {"de": "IP-Adresse des Gateways", "en": "Gateway IP address"},
    "conn.port": {"de": "Port", "en": "Port"},
    "conn.length": {"de": "Telegrammlänge [Byte]", "en": "Telegram length [bytes]"},
    "conn.lifesign": {"de": "LifeSign-Timeout [ms]", "en": "LifeSign timeout [ms]"},
    "conn.connect": {"de": "Verbinden", "en": "Connect"},
    "conn.disconnect": {"de": "Trennen", "en": "Disconnect"},
    "conn.sim_hint": {
        "de": "Benötigt die lokal gebaute SDK-Bibliothek (SRCI_SDK_SIM_LIB).",
        "en": "Needs the locally built SDK library (SRCI_SDK_SIM_LIB).",
    },
    "robot.title": {"de": "Roboter", "en": "Robot"},
    "robot.manufacturer": {"de": "Hersteller", "en": "Manufacturer"},
    "robot.model": {"de": "Roboter", "en": "Robot"},
    "robot.firmware": {"de": "Firmware", "en": "Firmware"},
    "robot.srci": {"de": "SRCI-Version", "en": "SRCI version"},
    "robot.mode": {"de": "Betriebsart", "en": "Operation mode"},
    "power.title": {"de": "Antriebe", "en": "Drives"},
    "power.enable": {"de": "Roboter einschalten", "en": "Switch robot on"},
    "power.reset": {"de": "Quittieren", "en": "Reset"},
    "power.reset_hint": {
        "de": "Fehler der Robotersteuerung quittieren (GroupReset)",
        "en": "Acknowledge errors of the robot controller (GroupReset)",
    },
    "override": {"de": "Geschwindigkeit", "en": "Speed"},
    "override.hint": {"de": "Override für alle Bewegungen", "en": "Override for all motions"},
    # jog page
    "jog.title": {"de": "Bewegen", "en": "Jog"},
    "jog.axes": {"de": "Achsen", "en": "Joints"},
    "jog.base": {"de": "Basis", "en": "Base"},
    "jog.tool": {"de": "Werkzeug", "en": "Tool"},
    "jog.speed": {"de": "Tippgeschwindigkeit", "en": "Jog speed"},
    "jog.step": {"de": "Schrittweite", "en": "Increment"},
    "jog.continuous": {"de": "Stufenlos", "en": "Continuous"},
    "jog.hold": {"de": "Taste gedrückt halten – loslassen stoppt.", "en": "Hold the key – release stops."},
    "jog.need_enable": {"de": "Zum Tippen den Roboter einschalten.", "en": "Switch the robot on to jog."},
    "pos.title": {"de": "Aktuelle Position", "en": "Actual position"},
    "pos.joints": {"de": "Achsen [°]", "en": "Joints [°]"},
    "pos.tcp": {"de": "TCP [mm, °]", "en": "TCP [mm, °]"},
    "pos.invalid": {"de": "Keine Position", "en": "No position"},
    "teach.point": {"de": "Punkt teachen", "en": "Teach point"},
    "teach.done": {"de": "{name} geteacht", "en": "{name} taught"},
    "teach.again": {"de": "Neu teachen", "en": "Teach again"},
    "teach.again_done": {
        "de": "{name} mit aktueller Position überschrieben",
        "en": "{name} overwritten with the actual position",
    },
    # program page
    "prog.title": {"de": "Programm", "en": "Program"},
    "prog.points": {"de": "Punkte", "en": "Points"},
    "prog.steps": {"de": "Ablauf", "en": "Sequence"},
    "prog.no_points": {
        "de": "Noch keine Punkte. Roboter verfahren und „Punkt teachen“ tippen.",
        "en": "No points yet. Jog the robot and tap “Teach point”.",
    },
    "prog.no_steps": {
        "de": "Noch keine Schritte. Bei einem Punkt auf „+“ tippen.",
        "en": "No steps yet. Tap “+” on a point.",
    },
    "prog.default": {"de": "Neues Programm", "en": "New program"},
    "prog.name": {"de": "Programmname", "en": "Program name"},
    "prog.save": {"de": "Sichern", "en": "Save"},
    "prog.saved": {"de": "Gesichert: {path}", "en": "Saved: {path}"},
    "prog.open": {"de": "Öffnen", "en": "Open"},
    "prog.new": {"de": "Neu", "en": "New"},
    "prog.new_confirm": {"de": "Ungesicherte Änderungen verwerfen?", "en": "Discard unsaved changes?"},
    "prog.unsaved": {"de": "nicht gesichert", "en": "not saved"},
    "prog.run": {"de": "Start", "en": "Start"},
    "prog.step": {"de": "Einzelschritt", "en": "Single step"},
    "prog.from": {"de": "ab Schritt", "en": "from step"},
    "prog.finished": {"de": "Programm beendet", "en": "Program finished"},
    "prog.hold_hint": {
        "de": "Halten zum Fahren: loslassen stoppt den Roboter.",
        "en": "Hold to run: releasing stops the robot.",
    },
    "prog.auto": {"de": "Ohne Halten fahren", "en": "Run without holding"},
    "prog.auto_hint": {
        "de": "Nur mit freiem Arbeitsraum und Not-Halt in Reichweite.",
        "en": "Only with a clear working area and the emergency stop within reach.",
    },
    "point.move": {"de": "Anfahren", "en": "Move to"},
    "point.add_step": {"de": "Als Schritt anfügen", "en": "Append as step"},
    "point.rename": {"de": "Umbenennen", "en": "Rename"},
    "point.delete": {"de": "Löschen", "en": "Delete"},
    "point.delete_confirm": {
        "de": "{name} und {steps} Schritt(e) löschen?",
        "en": "Delete {name} and {steps} step(s)?",
    },
    "step.linear": {"de": "LIN", "en": "LIN"},
    "step.joint": {"de": "Joint", "en": "Joint"},
    "common.cancel": {"de": "Abbrechen", "en": "Cancel"},
    "common.ok": {"de": "OK", "en": "OK"},
    "common.name": {"de": "Name", "en": "Name"},
    "common.delete": {"de": "Löschen", "en": "Delete"},
    # tools and frames
    "nav.tools": {"de": "Werkzeuge", "en": "Tools"},
    "nav.frames": {"de": "Koordinatensysteme", "en": "Frames"},
    "tools.title": {"de": "Werkzeuge", "en": "Tools"},
    "tools.lead": {
        "de": "TCP-Daten auf der Robotersteuerung (ReadToolData / WriteToolData).",
        "en": "TCP data on the robot controller (ReadToolData / WriteToolData).",
    },
    "frames.title": {"de": "Koordinatensysteme", "en": "Frames"},
    "frames.lead": {
        "de": "Benutzerkoordinatensysteme auf der Robotersteuerung (ReadFrameData / WriteFrameData).",
        "en": "User frames on the robot controller (ReadFrameData / WriteFrameData).",
    },
    "coord.read": {"de": "Vom Roboter lesen", "en": "Read from robot"},
    "coord.edit": {"de": "Bearbeiten", "en": "Edit"},
    "coord.use": {"de": "Verwenden", "en": "Use"},
    "coord.active": {"de": "aktiv", "en": "active"},
    "coord.none": {
        "de": "Noch nicht gelesen. Verbinden und „Vom Roboter lesen“ tippen.",
        "en": "Not read yet. Connect and tap “Read from robot”.",
    },
    "coord.saved": {"de": "{name} auf den Roboter geschrieben", "en": "{name} written to the robot"},
    "coord.flange": {"de": "Flansch", "en": "Flange"},
    "coord.base": {"de": "Basis", "en": "Base"},
    "coord.fixed": {"de": "fest, nicht änderbar", "en": "fixed, cannot be changed"},
    "coord.name": {"de": "Bezeichnung (nur lokal)", "en": "Label (local only)"},
    "coord.load": {"de": "Last-Nr.", "en": "Load no."},
    "coord.external": {"de": "Externer TCP (stehendes Werkzeug)", "en": "External TCP (stationary tool)"},
    "coord.reference": {"de": "Bezugssystem", "en": "Reference frame"},
    "coord.from_tcp": {"de": "Aktuelle TCP-Position übernehmen", "en": "Take the actual TCP position"},
    "coord.from_tcp_hint": {
        "de": "Position des aktiven Werkzeugs im Bezugssystem",
        "en": "Position of the active tool in the reference frame",
    },
    "coord.write": {"de": "Auf Roboter schreiben", "en": "Write to robot"},
    "coord.tool": {"de": "Werkzeug", "en": "Tool"},
    "coord.frame": {"de": "Koordinatensystem", "en": "Frame"},
    "coord.system": {"de": "Koordinatensystem", "en": "Coordinate system"},
    "coord.system_hint": {
        "de": "Gilt für die Anzeige, das kartesische Tippen und das Teachen.",
        "en": "Used for the display, Cartesian jogging and teaching.",
    },
    # step editor
    "step.title": {"de": "Schritt {n}", "en": "Step {n}"},
    "step.point": {"de": "Zielpunkt", "en": "Target point"},
    "step.motion": {"de": "Bewegungsart", "en": "Motion type"},
    "step.ptp": {"de": "PTP", "en": "PTP"},
    "step.joint_long": {
        "de": "Joint – Achswinkel anfahren (MoveAxesAbsolute)",
        "en": "Joint – move to the joint angles (MoveAxesAbsolute)",
    },
    "step.ptp_long": {
        "de": "PTP – kartesisches Ziel, achsinterpoliert (MoveDirectAbsolute)",
        "en": "PTP – Cartesian target, joint interpolated (MoveDirectAbsolute)",
    },
    "step.linear_long": {
        "de": "LIN – gerade Bahn des TCP (MoveLinearAbsolute)",
        "en": "LIN – straight path of the TCP (MoveLinearAbsolute)",
    },
    "step.blend": {"de": "Überschleifen", "en": "Blending"},
    "step.absolute": {"de": "Genauhalt", "en": "Exact stop"},
    "step.blended": {"de": "Überschleifen", "en": "Blended"},
    "step.blend_mode": {"de": "Art", "en": "Mode"},
    "step.blend_before": {"de": "Vor dem Punkt", "en": "Before the point"},
    "step.blend_after": {"de": "Nach dem Punkt (Post)", "en": "After the point (post)"},
    "step.dynamics": {"de": "Dynamik", "en": "Dynamics"},
    "step.dynamics_hint": {
        "de": "in % der Referenzdynamik der Robotersteuerung",
        "en": "in % of the reference dynamics of the robot controller",
    },
    "step.vel": {"de": "Geschwindigkeit", "en": "Velocity"},
    "step.acc": {"de": "Beschleunigung", "en": "Acceleration"},
    "step.dec": {"de": "Verzögerung", "en": "Deceleration"},
    "step.jerk": {"de": "Ruck", "en": "Jerk"},
    "step.default": {"de": "Standard", "en": "Default"},
    "step.apply": {"de": "Übernehmen", "en": "Apply"},
    "step.duplicate": {"de": "Duplizieren", "en": "Duplicate"},
    "step.up": {"de": "Nach oben", "en": "Move up"},
    "step.down": {"de": "Nach unten", "en": "Move down"},
    "step.edit_hint": {"de": "Schritt antippen zum Bearbeiten", "en": "Tap a step to edit it"},
    "blend.EXACT_STOP": {"de": "Genauhalt", "en": "Exact stop"},
    "blend.CORNER_DISTANCE": {"de": "Eckabstand", "en": "Corner distance"},
    "blend.CORNER_DISTANCE_1R": {"de": "Eckabstand, ein Radius", "en": "Corner distance, one radius"},
    "blend.CORNER_DISTANCE_2R": {
        "de": "Eckabstand, zwei Radien (vor/nach)",
        "en": "Corner distance, two radii",
    },
    "blend.MAX_CORNER_DEVIATION": {"de": "Max. Eckabweichung", "en": "Max. corner deviation"},
    "blend.DEFINED_VELOCITY": {"de": "Geschwindigkeit an der Ecke", "en": "Velocity at the corner"},
    "blend.RAMP_OVERLAP": {"de": "Rampenüberlappung", "en": "Ramp overlap"},
    # messages page
    "msg.title": {"de": "Meldungen", "en": "Messages"},
    "msg.none": {"de": "Keine Meldungen der Robotersteuerung.", "en": "No messages of the robot controller."},
    "msg.last_error": {"de": "Letzter Fehler", "en": "Last error"},
    # errors
    "err.not_connected": {"de": "Nicht verbunden", "en": "Not connected"},
    "err.need_enable": {"de": "Erst den Roboter einschalten", "en": "Switch the robot on first"},
}


def set_language(language: str) -> None:
    _language.set(language if language in LANGUAGES else DEFAULT)


def language() -> str:
    return _language.get()


def t(key: str, lang: str | None = None, **values: object) -> str:
    """Text for ``key`` in the current (or given) language; unknown keys return the key."""
    entry = TEXTS.get(key)
    if entry is None:
        return key
    text = entry.get(lang or _language.get()) or entry[DEFAULT]
    return text.format(**values) if values else text
