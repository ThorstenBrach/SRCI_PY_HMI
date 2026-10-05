"""Measuring tools and frames in the HMI - for robot controllers without CalculateTool /
CalculateFrame (profile Extended), e.g. the JAKA MiniCobo (profile Core only).

Positions are X, Y, Z [mm], Rx, Ry, Rz [deg] as in SRCI: extrinsic x-y-z rotations (= intrinsic
z-y'-x''), R = Rz(Rz) * Ry(Ry) * Rx(Rx) (SIMATIC Robot Library manual 4.2, ISO 9787).
Pure Python (3x3 matrices), no further dependency.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

Matrix = list[list[float]]
Vector = list[float]


def rotation(rx: float, ry: float, rz: float) -> Matrix:
    """Rotation matrix of Rx, Ry, Rz [deg]."""
    a, b, c = (math.radians(v) for v in (rx, ry, rz))
    ca, sa, cb, sb, cc, sc = math.cos(a), math.sin(a), math.cos(b), math.sin(b), math.cos(c), math.sin(c)
    return [
        [cc * cb, cc * sb * sa - sc * ca, cc * sb * ca + sc * sa],
        [sc * cb, sc * sb * sa + cc * ca, sc * sb * ca - cc * sa],
        [-sb, cb * sa, cb * ca],
    ]


def euler(r: Matrix) -> Vector:
    """Rx, Ry, Rz [deg] of a rotation matrix (inverse of :func:`rotation`)."""
    sb = -r[2][0]
    if abs(sb) < 1.0 - 1e-9:
        ry = math.asin(sb)
        rx = math.atan2(r[2][1], r[2][2])
        rz = math.atan2(r[1][0], r[0][0])
    else:  # gimbal lock: Rx and Rz turn around the same axis, Rx = 0
        ry = math.copysign(math.pi / 2, sb)
        rx = 0.0
        rz = math.atan2(-r[0][1], r[1][1])
    return [math.degrees(v) for v in (rx, ry, rz)]


def matmul(a: Matrix, b: Matrix) -> Matrix:
    return [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]


def transpose(a: Matrix) -> Matrix:
    return [[a[j][i] for j in range(3)] for i in range(3)]


def apply(a: Matrix, v: Vector) -> Vector:
    return [sum(a[i][k] * v[k] for k in range(3)) for i in range(3)]


def sub(a: Vector, b: Vector) -> Vector:
    return [x - y for x, y in zip(a, b, strict=True)]


def cross(a: Vector, b: Vector) -> Vector:
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]


def norm(a: Vector) -> float:
    return math.sqrt(sum(x * x for x in a))


def unit(a: Vector, what: str = "vector") -> Vector:
    n = norm(a)
    if n < 1e-6:
        raise ValueError(f"{what}: the positions are too close to each other")
    return [x / n for x in a]


def pose(position: Vector) -> tuple[Vector, Matrix]:
    """Translation and rotation of X, Y, Z, Rx, Ry, Rz."""
    return list(position[:3]), rotation(*position[3:6])


def compose(t: Vector, r: Matrix) -> Vector:
    """X, Y, Z, Rx, Ry, Rz of a translation and a rotation."""
    return [*t, *euler(r)]


def _solve(a: list[list[float]], b: list[float]) -> list[float]:
    """Linear system (Gauss with pivoting)."""
    n = len(b)
    m = [[*row, b[i]] for i, row in enumerate(a)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(m[r][col]))
        if abs(m[pivot][col]) < 1e-9:
            raise ValueError("the positions do not determine the TCP: choose more different orientations")
        m[col], m[pivot] = m[pivot], m[col]
        for r in range(n):
            if r != col:
                f = m[r][col] / m[col][col]
                m[r] = [x - f * y for x, y in zip(m[r], m[col], strict=True)]
    return [m[i][n] / m[i][i] for i in range(n)]


@dataclass
class TcpResult:
    tcp: Vector  # X, Y, Z of the TCP relative to the flange [mm]
    point: Vector  # the fixed point in the world [mm]
    max_error: float  # distance of the single positions from the result [mm]
    mean_error: float


def tcp_from_tip(flanges: list[Vector]) -> TcpResult:
    """TCP from flange positions (in the world) with the tool tip on one fixed point:
    R_i * t + p_i = c for all i, least squares for t (TCP) and c (fixed point)."""
    if len(flanges) < 3:
        raise ValueError("at least 3 positions")
    # normal equations of A x = b with A = [R_i, -I], b = -p_i
    ata = [[0.0] * 6 for _ in range(6)]
    atb = [0.0] * 6
    for f in flanges:
        p, r = pose(f)
        for row in range(3):
            a_row = [*r[row], *(-1.0 if k == row else 0.0 for k in range(3))]
            for i in range(6):
                atb[i] += a_row[i] * -p[row]
                for j in range(6):
                    ata[i][j] += a_row[i] * a_row[j]
    x = _solve(ata, atb)
    t, c = x[:3], x[3:]
    errors = []
    for f in flanges:
        p, r = pose(f)
        errors.append(norm(sub([a + b for a, b in zip(apply(r, t), p, strict=True)], c)))
    return TcpResult(t, c, max(errors), sum(errors) / len(errors))


def orientation_abc_world(flange: Vector) -> Vector:
    """Tool orientation (ABC world, manual 6.9.5.8): the tool is aligned with +X along -Z, +Y
    along +Y and +Z along +X of the world. Returns Rx, Ry, Rz of the tool relative to the flange."""
    _, r_flange = pose(flange)
    # columns: the tool axes in the world
    target = [[0.0, 0.0, 1.0], [0.0, 1.0, 0.0], [-1.0, 0.0, 0.0]]
    return euler(matmul(transpose(r_flange), target))


def frame_from_points(origin: Vector, x_axis: Vector, xy_plane: Vector) -> tuple[Vector, Matrix]:
    """Frame through 3 points: origin, a point on +X, a point in the XY plane (positive Y side)."""
    x = unit(sub(x_axis[:3], origin[:3]), "X axis")
    z = unit(cross(x, sub(xy_plane[:3], origin[:3])), "XY plane")
    y = cross(z, x)
    return list(origin[:3]), [[x[i], y[i], z[i]] for i in range(3)]


def frame_three_points(origin: Vector, x_axis: Vector, xy_plane: Vector) -> Vector:
    """CalculateFrame, 3-point method (manual 6.9.4.3)."""
    return compose(*frame_from_points(origin, x_axis, xy_plane))


def frame_four_points(origin: Vector, x_axis: Vector, xy_plane: Vector, shift: Vector) -> Vector:
    """CalculateFrame, 4-point method (6.9.4.4): the orientation of the auxiliary frame through the
    first three points, the origin at the fourth position."""
    _, r = frame_from_points(origin, x_axis, xy_plane)
    return compose(list(shift[:3]), r)


def frame_one_point(origin: Vector) -> Vector:
    """CalculateFrame, 1-point method (6.9.4.5): origin and orientation of one position."""
    return [float(v) for v in origin[:6]]
