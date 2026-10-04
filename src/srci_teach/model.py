"""Taught points and programs (pure data, no robot, no UI).

A program is a list of points (taught positions) and a list of steps (motions to points). A
point stores both the joint and the Cartesian position (in the tool and frame it was taught
with), so a step can move to it with

* ``JOINT``: MoveAxesAbsolute to the joint angles (exact, independent of tool and configuration),
* ``PTP``: MoveDirectAbsolute to the Cartesian position (joint interpolated, fastest path),
* ``LINEAR``: MoveLinearAbsolute to the Cartesian position (straight path of the TCP).

Every step has its own dynamics (velocity, acceleration, deceleration, jerk in % of the
reference dynamics of the RC, -1 = default of the RC) and blending (BlendingMode of the spec,
parameter before / after the point). Programs are stored as JSON.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

FORMAT_VERSION = 2
DEFAULT = -1.0  # dynamics value "not set": the RC uses its default dynamics
# BlendingMode of the spec (table 6-9) - names of srci.types.BlendingMode
BLENDING_MODES = ("EXACT_STOP", "CORNER_DISTANCE", "CORNER_DISTANCE_1R", "CORNER_DISTANCE_2R",
                  "MAX_CORNER_DEVIATION", "DEFINED_VELOCITY", "RAMP_OVERLAP")  # fmt: skip
# unit of BlendingParameter[0] / [1] per mode (None: not used)
BLENDING_UNITS: dict[str, tuple[str | None, str | None]] = {
    "EXACT_STOP": (None, None),
    "CORNER_DISTANCE": ("mm", None),
    "CORNER_DISTANCE_1R": ("mm", None),
    "CORNER_DISTANCE_2R": ("mm", "mm"),
    "MAX_CORNER_DEVIATION": ("mm", None),
    "DEFINED_VELOCITY": ("%", None),
    "RAMP_OVERLAP": ("%", None),
}
JOINTS = ("J1", "J2", "J3", "J4", "J5", "J6")
CARTESIAN = ("X", "Y", "Z", "Rx", "Ry", "Rz")


class Motion(StrEnum):
    JOINT = "joint"  # MoveAxesAbsolute to the joint position of the point
    PTP = "ptp"  # MoveDirectAbsolute to the Cartesian position (joint interpolated)
    LINEAR = "linear"  # MoveLinearAbsolute to the Cartesian position of the point


@dataclass
class Point:
    name: str
    joints: list[float]  # J1..J6 [deg]
    cartesian: list[float]  # X, Y, Z [mm], Rx, Ry, Rz [deg] in tool/frame below
    tool: int = 0
    frame: int = 0
    note: str = ""


@dataclass
class Step:
    point: str  # name of the point
    motion: Motion = Motion.JOINT
    velocity: float = 20.0  # % of the reference velocity of the RC (-1 = default of the RC)
    blending: float = 0.0  # BlendingParameter[0], e.g. corner distance before the point [mm]
    blending_mode: str = "EXACT_STOP"  # name of the BlendingMode
    blending_post: float = 0.0  # BlendingParameter[1], e.g. CORNER_DISTANCE_2R after the point [mm]
    acceleration: float = DEFAULT  # % of the reference acceleration (-1 = default of the RC)
    deceleration: float = DEFAULT  # %
    jerk: float = DEFAULT  # %

    def __post_init__(self) -> None:
        self.motion = Motion(self.motion)
        if self.blending_mode not in BLENDING_MODES:
            raise ValueError(f"unknown BlendingMode {self.blending_mode!r}")
        self.velocity = _rate(self.velocity, "velocity")
        for name in ("acceleration", "deceleration", "jerk"):
            setattr(self, name, _rate(getattr(self, name), name))
        self.blending, self.blending_post = (
            max(0.0, float(self.blending)),
            max(0.0, float(self.blending_post)),
        )

    @property
    def exact_stop(self) -> bool:
        return self.blending_mode == "EXACT_STOP"

    @property
    def blended(self) -> bool:
        return not self.exact_stop


@dataclass
class Program:
    name: str = "Program"
    points: list[Point] = field(default_factory=list)
    steps: list[Step] = field(default_factory=list)

    # ------------------------------------------------------------------ points

    def point(self, name: str) -> Point:
        for p in self.points:
            if p.name == name:
                return p
        raise KeyError(name)

    def next_point_name(self, prefix: str = "P") -> str:
        """``P1``, ``P2`` ... the first number above all used numbers with this prefix."""
        used = [
            int(m.group(1)) for p in self.points if (m := re.fullmatch(rf"{re.escape(prefix)}(\d+)", p.name))
        ]
        return f"{prefix}{max(used, default=0) + 1}"

    def add_point(self, joints: list[float], cartesian: list[float], *, name: str | None = None,
                  tool: int = 0, frame: int = 0) -> Point:  # fmt: skip
        name = name or self.next_point_name()
        if any(p.name == name for p in self.points):
            raise ValueError(f"point {name!r} exists already")
        _check_len(joints, 6, "joints")
        _check_len(cartesian, 6, "cartesian")
        point = Point(name, [float(v) for v in joints], [float(v) for v in cartesian], tool, frame)
        self.points.append(point)
        return point

    def update_point(self, name: str, joints: list[float], cartesian: list[float],
                     *, tool: int = 0, frame: int = 0) -> Point:  # fmt: skip
        """Teach the point again (new position, same name and steps)."""
        _check_len(joints, 6, "joints")
        _check_len(cartesian, 6, "cartesian")
        p = self.point(name)
        p.joints, p.cartesian = [float(v) for v in joints], [float(v) for v in cartesian]
        p.tool, p.frame = tool, frame
        return p

    def rename_point(self, old: str, new: str) -> None:
        new = new.strip()
        if not new:
            raise ValueError("empty name")
        if new != old and any(p.name == new for p in self.points):
            raise ValueError(f"point {new!r} exists already")
        self.point(old).name = new
        for s in self.steps:
            if s.point == old:
                s.point = new

    def delete_point(self, name: str) -> int:
        """Delete the point and the steps that move to it; returns the number of deleted steps."""
        self.points.remove(self.point(name))
        before = len(self.steps)
        self.steps = [s for s in self.steps if s.point != name]
        return before - len(self.steps)

    # ------------------------------------------------------------------ steps

    def add_step(self, point: str, motion: Motion = Motion.JOINT, velocity: float = 20.0,
                 blending: float = 0.0, index: int | None = None, **dynamics: Any) -> Step:  # fmt: skip
        """Append (or insert at ``index``) a motion to ``point``. ``blending`` > 0 without a
        ``blending_mode`` means CORNER_DISTANCE (format 1); further fields of :class:`Step` as
        keyword arguments (``blending_mode``, ``blending_post``, ``acceleration`` ...)."""
        self.point(point)  # KeyError if unknown
        if blending > 0.0 and "blending_mode" not in dynamics:
            dynamics["blending_mode"] = "CORNER_DISTANCE"
        step = Step(point, Motion(motion), velocity, blending, **dynamics)
        self.steps.insert(len(self.steps) if index is None else index, step)
        return step

    def move_step(self, index: int, offset: int) -> int:
        """Move a step up (-1) or down (+1); returns the new index."""
        new = min(max(index + offset, 0), len(self.steps) - 1)
        self.steps.insert(new, self.steps.pop(index))
        return new

    def delete_step(self, index: int) -> None:
        del self.steps[index]

    # ------------------------------------------------------------------ JSON

    def to_dict(self) -> dict[str, Any]:
        return {"format": FORMAT_VERSION, "name": self.name,
                "points": [asdict(p) for p in self.points],
                "steps": [{**asdict(s), "motion": s.motion.value} for s in self.steps]}  # fmt: skip

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Program:
        if data.get("format", FORMAT_VERSION) > FORMAT_VERSION:
            raise ValueError(f"program format {data['format']} is newer than this version ({FORMAT_VERSION})")
        program = cls(str(data.get("name", "Program")))
        for p in data.get("points", []):
            program.add_point(p["joints"], p["cartesian"], name=str(p["name"]),
                              tool=int(p.get("tool", 0)), frame=int(p.get("frame", 0)))  # fmt: skip
            program.points[-1].note = str(p.get("note", ""))
        extra = ("blending_mode", "blending_post", "acceleration", "deceleration", "jerk")
        for s in data.get("steps", []):
            program.add_step(str(s["point"]), Motion(s.get("motion", Motion.JOINT)),
                             float(s.get("velocity", 20.0)), float(s.get("blending", 0.0)),
                             **{k: s[k] for k in extra if k in s})  # fmt: skip
        return program

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)

    @classmethod
    def from_json(cls, text: str) -> Program:
        return cls.from_dict(json.loads(text))

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(self.to_json(), encoding="utf-8")
        tmp.replace(path)  # never a half written program

    @classmethod
    def load(cls, path: Path) -> Program:
        return cls.from_json(path.read_text(encoding="utf-8"))


def _check_len(values: list[float], n: int, what: str) -> None:
    if len(values) != n:
        raise ValueError(f"{what}: {n} values expected, got {len(values)}")


def _rate(v: float, what: str) -> float:
    """% of the reference dynamics: 0 < v <= 100, or -1 (default of the RC)."""
    v = float(v)
    if v == DEFAULT:
        return v
    if not 0.0 < v <= 100.0:
        raise ValueError(f"{what} {v} % outside 0 < v <= 100 (or -1 = default of the RC)")
    return v
