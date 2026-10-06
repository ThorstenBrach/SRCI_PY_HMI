"""Points, steps and JSON of :mod:`srci_py_hmi.model` (no robot)."""

from __future__ import annotations

from pathlib import Path

import pytest

from srci_py_hmi.model import Motion, Program, Step, StepKind

J = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
C = [100.0, 200.0, 300.0, 180.0, 0.0, 90.0]


def test_points_get_increasing_names() -> None:
    p = Program()
    assert [p.add_point(J, C).name for _ in range(3)] == ["P1", "P2", "P3"]
    p.rename_point("P2", "Home")
    assert p.add_point(J, C).name == "P4"


def test_duplicate_and_invalid_points_are_refused() -> None:
    p = Program()
    p.add_point(J, C, name="Home")
    with pytest.raises(ValueError):
        p.add_point(J, C, name="Home")
    with pytest.raises(ValueError):
        p.add_point(J[:5], C)
    with pytest.raises(ValueError):
        p.rename_point("Home", "  ")


def test_rename_follows_steps_and_delete_removes_them() -> None:
    p = Program()
    p.add_point(J, C)
    p.add_point(J, C)
    p.add_step("P1")
    p.add_step("P2", Motion.LINEAR)
    p.add_step("P1")
    p.rename_point("P1", "Pick")
    assert [s.point for s in p.steps] == ["Pick", "P2", "Pick"]
    assert p.delete_point("Pick") == 2
    assert [s.point for s in p.steps] == ["P2"]


def test_steps_check_point_and_velocity() -> None:
    p = Program()
    p.add_point(J, C)
    with pytest.raises(KeyError):
        p.add_step("P9")
    with pytest.raises(ValueError):
        p.add_step("P1", velocity=0)
    with pytest.raises(ValueError):
        p.add_step("P1", velocity=101)
    assert p.add_step("P1", blending=-5).exact_stop


def test_move_step_stays_in_range() -> None:
    p = Program()
    p.add_point(J, C, name="A")
    p.add_point(J, C, name="B")
    p.add_step("A")
    p.add_step("B")
    assert p.move_step(1, -1) == 0
    assert [s.point for s in p.steps] == ["B", "A"]
    assert p.move_step(0, -1) == 0
    assert p.move_step(1, +1) == 1


def test_json_round_trip(tmp_path: Path) -> None:
    p = Program("Palette")
    p.add_point(J, C, tool=1, frame=2)
    p.points[0].note = "über dem Teil"
    p.add_step("P1", Motion.LINEAR, 35.0, 5.0)
    path = tmp_path / "sub" / "palette.json"
    p.save(path)
    q = Program.load(path)
    assert q.to_dict() == p.to_dict()
    assert q.steps[0].motion is Motion.LINEAR
    assert not q.steps[0].exact_stop


def test_newer_format_is_refused() -> None:
    with pytest.raises(ValueError):
        Program.from_dict({"format": 99})


def test_step_dynamics_and_blending() -> None:
    p = Program()
    p.add_point(J, C)
    s = p.add_step("P1", Motion.PTP, 50.0, 5.0, blending_mode="CORNER_DISTANCE_2R", blending_post=3.0,
                   acceleration=40.0)  # fmt: skip
    assert s.blended and s.blending == 5.0 and s.blending_post == 3.0
    assert (s.deceleration, s.jerk) == (-1.0, -1.0)  # default of the RC
    assert p.add_step("P1", velocity=-1.0).velocity == -1.0
    with pytest.raises(ValueError):
        p.add_step("P1", acceleration=0.0)
    with pytest.raises(ValueError):
        p.add_step("P1", blending_mode="SPIRAL")
    q = Program.from_json(p.to_json())
    assert q.to_dict() == p.to_dict()


def test_format_1_programs_are_read() -> None:
    old = {"format": 1, "name": "alt", "points": [{"name": "A", "joints": J, "cartesian": C}],
           "steps": [{"point": "A", "motion": "linear", "velocity": 30.0, "blending": 20.0},
                     {"point": "A", "motion": "joint", "velocity": 30.0, "blending": 0.0}]}  # fmt: skip
    p = Program.from_dict(old)
    assert p.steps[0].blending_mode == "CORNER_DISTANCE" and p.steps[0].blending == 20.0
    assert p.steps[1].exact_stop


def test_steps_of_all_kinds_round_trip() -> None:
    p = Program()
    p.add_point(J, C, name="A")
    p.add_point(J, C, name="B")
    p.insert_step(Step("B", Motion.CIRC, via="A", note="arc"))
    p.insert_step(Step("", Motion.LINEAR, kind=StepKind.RELATIVE, offset=[0, 0, 50, 0, 0, 0], reference="frame",
                       tool=1, frame=2))  # fmt: skip
    p.insert_step(Step("", kind=StepKind.WAIT, duration=1.5))
    p.insert_step(Step("", kind=StepKind.OUTPUT, signal=12, value=False))
    p.insert_step(Step("", kind=StepKind.WAIT_INPUT, signal=3, timeout=2.0, enabled=False))
    p.insert_step(Step("", kind=StepKind.SUBPROGRAM, job=7, data=[1, 2, 255]))
    p.insert_step(Step("", kind=StepKind.HALT))
    q = Program.from_json(p.to_json())
    assert q.to_dict() == p.to_dict()
    assert [s.kind for s in q.steps] == [s.kind for s in p.steps]
    assert "kind" not in p.to_dict()["steps"][0]  # a motion to a point looks like format 2
    assert p.to_dict()["steps"][2] == {"kind": "wait", "duration": 1.5}
    assert not q.steps[4].enabled and q.steps[0].note == "arc"


def test_circ_needs_via_point_and_follows_it() -> None:
    p = Program()
    p.add_point(J, C, name="A")
    p.add_point(J, C, name="B")
    with pytest.raises(ValueError):
        Step("B", Motion.CIRC)
    with pytest.raises(KeyError):
        p.insert_step(Step("B", Motion.CIRC, via="X"))
    p.insert_step(Step("B", Motion.CIRC, via="A"))
    p.rename_point("A", "Via")
    assert p.steps[0].via == "Via"
    assert p.delete_point("Via") == 1


def test_invalid_step_values_are_refused() -> None:
    with pytest.raises(ValueError):
        Step("", Motion.CIRC, kind=StepKind.RELATIVE)
    with pytest.raises(ValueError):
        Step("", kind=StepKind.OUTPUT, signal=5000)
    with pytest.raises(ValueError):
        Step("", kind=StepKind.SUBPROGRAM, data=[300])
    with pytest.raises(ValueError):
        Step("", kind=StepKind.RELATIVE, offset=[1.0, 2.0])


def test_skipped_steps_and_previous_motion() -> None:
    p = Program()
    p.add_point(J, C, name="A")
    p.add_step("A")
    p.insert_step(Step("", kind=StepKind.WAIT, duration=1))
    p.add_step("A")
    p.add_step("A")
    p.steps[2].enabled = False
    assert p.next_enabled(2) == 3
    assert p.previous_motion(3) == 0  # step 2 is skipped, step 1 is no motion
    assert p.previous_motion(0) == 0
