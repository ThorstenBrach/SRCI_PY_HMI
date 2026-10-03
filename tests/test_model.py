"""Points, steps and JSON of :mod:`srci_teach.model` (no robot)."""

from __future__ import annotations

from pathlib import Path

import pytest

from srci_teach.model import Motion, Program

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
