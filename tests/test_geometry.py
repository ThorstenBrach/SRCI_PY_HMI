"""Measuring tools and frames in the HMI (:mod:`srci_py_hmi.geometry`), with synthetic positions."""

from __future__ import annotations

import math
import random

import pytest

from srci_py_hmi import geometry as g


def close(a: list[float], b: list[float], tol: float = 1e-6) -> bool:
    return all(abs(x - y) < tol for x, y in zip(a, b, strict=True))


def flange_for(tcp: list[float], point: list[float], rx: float, ry: float, rz: float) -> list[float]:
    """Flange position with orientation rx, ry, rz whose TCP lies on ``point``."""
    r = g.rotation(rx, ry, rz)
    p = g.sub(point, g.apply(r, tcp))
    return [*p, rx, ry, rz]


def test_rotation_follows_the_spec_and_euler_inverts_it() -> None:
    # Rz 90: X -> Y (extrinsic x-y-z, R = Rz Ry Rx)
    assert close(g.apply(g.rotation(0, 0, 90), [1, 0, 0]), [0, 1, 0])
    # Rx 90 first, then Rz 90: Y -> Z (Rx) -> Z (Rz)
    assert close(g.apply(g.rotation(90, 0, 90), [0, 1, 0]), [0, 0, 1])
    for angles in ([10.0, 20.0, 30.0], [180.0, 0.0, 0.0], [-45.0, 60.0, 170.0], [0.0, 89.0, 5.0]):
        again = g.rotation(*g.euler(g.rotation(*angles)))
        assert close([v for row in again for v in row], [v for row in g.rotation(*angles) for v in row])


def test_tcp_from_four_positions() -> None:
    tcp, point = [12.0, -5.0, 150.0], [400.0, 100.0, 50.0]
    flanges = [flange_for(tcp, point, *a) for a in ([180, 0, 0], [150, 20, 10], [200, -25, 40], [170, 10, -60])]
    result = g.tcp_from_tip(flanges)
    assert close(result.tcp, tcp, 1e-6) and close(result.point, point, 1e-6)
    assert result.max_error < 1e-6


def test_tcp_with_measuring_errors_reports_them() -> None:
    rnd = random.Random(1)
    tcp, point = [0.0, 0.0, 200.0], [300.0, 0.0, 0.0]
    flanges = []
    for a in ([180, 0, 0], [150, 25, 0], [210, -20, 30], [175, 15, -45]):
        f = flange_for(tcp, point, *a)
        flanges.append([v + rnd.uniform(-0.3, 0.3) if i < 3 else v for i, v in enumerate(f)])
    result = g.tcp_from_tip(flanges)
    assert close(result.tcp, tcp, 2.0)
    assert 0.0 < result.mean_error <= result.max_error < 1.0


def test_tcp_needs_different_orientations() -> None:
    same = [flange_for([0, 0, 100], [0, 0, 0], 180, 0, 0)] * 3
    with pytest.raises(ValueError):
        g.tcp_from_tip(same)
    with pytest.raises(ValueError):
        g.tcp_from_tip(same[:2])


def test_abc_world_orientation() -> None:
    # flange pointing down (Rx 180): the tool axes as the method asks -> relative orientation
    rel = g.orientation_abc_world([0, 0, 500, 180, 0, 0])
    r_tool = g.matmul(g.rotation(180, 0, 0), g.rotation(*rel))
    assert close(g.apply(r_tool, [1, 0, 0]), [0, 0, -1])
    assert close(g.apply(r_tool, [0, 1, 0]), [0, 1, 0])
    assert close(g.apply(r_tool, [0, 0, 1]), [1, 0, 0])


def test_frames() -> None:
    o, x, xy = [100.0, 200.0, 0.0, 0, 0, 0], [300.0, 200.0, 0.0, 0, 0, 0], [150.0, 400.0, 0.0, 0, 0, 0]
    assert close(g.frame_three_points(o, x, xy), [100.0, 200.0, 0.0, 0.0, 0.0, 0.0])
    # rotated by 90 deg around Z: X axis along +Y of the reference
    f = g.frame_three_points(o, [100.0, 300.0, 0.0], [0.0, 250.0, 0.0])
    assert close(f, [100.0, 200.0, 0.0, 0.0, 0.0, 90.0])
    # tilted plane: points on a slope, the frame's Z is the plane normal
    f = g.frame_three_points([0, 0, 0], [100, 0, 0], [0, 100, 100])
    assert math.isclose(f[3], 45.0) and close(f[:3], [0, 0, 0])
    assert close(g.frame_four_points(o, x, xy, [1.0, 2.0, 3.0]), [1.0, 2.0, 3.0, 0.0, 0.0, 0.0])
    assert g.frame_one_point([1, 2, 3, 4, 5, 6]) == [1, 2, 3, 4, 5, 6]
    with pytest.raises(ValueError):
        g.frame_three_points(o, o, xy)
