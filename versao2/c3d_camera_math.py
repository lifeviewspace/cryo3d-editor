# -*- coding: utf-8 -*-
"""Camera orientation maths for the Movie tab (numpy + scipy, no Qt, no GL).

napari stores the 3-D camera as three Euler angles, but that triple is NOT
unique: after you rotate the view with the mouse, napari reports the same
pose as e.g. (180, -0, 180) where my buttons wrote (0, 180, 0).  Blending
the three numbers one by one between two keyframes therefore tumbles the
volume along a wandering axis (measured: the rotation axis ends up to 74°
off the clean one) and a spin added to ``angles[1]`` turns the opposite
way for the two spellings of the same pose.

Here every keyframe pose is converted to a rotation with the SAME formula
napari uses (napari/_vispy/camera.py: scipy 'yzx', y-axis and 90° vispy
quirks, plus the orientation flips), blended along the shortest geodesic
(slerp), and spun by LEFT-multiplying a rotation about a screen axis.  Left
multiplication keeps napari's ``up_direction`` fixed for every pose (checked
in test_c3d_movie_spin.py), i.e. a true turntable even with a tilted view.
"""

from __future__ import annotations

import warnings

import numpy as np
from scipy.spatial.transform import Rotation as R

# napari 0.7, default orientation (towards, down, right): vispy flips axis 3
DEFAULT_FLIPS = np.array([1, 1, -1])

# index in napari's angles -> rotation axis on screen (same indices as AXES)
_SCREEN_AXES = {0: (1.0, 0.0, 0.0), 1: (0.0, 1.0, 0.0), 2: (0.0, 0.0, 1.0)}


def flips_from_viewer(viewer) -> np.ndarray:
    try:
        return np.where(np.asarray(viewer.camera._vispy_flipped_axes(ndisplay=3)), -1, 1)
    except Exception:
        return DEFAULT_FLIPS


def rot_from_angles(angles, flips=DEFAULT_FLIPS) -> R:
    """napari camera.angles -> rotation (same mapping as napari's setter)."""
    a = np.asarray(angles, dtype=float) * flips
    a = a * (1, -1, 1) + (0, 0, 90)
    return R.from_euler("yzx", a, degrees=True)


def angles_from_rot(rot: R, flips=DEFAULT_FLIPS) -> np.ndarray:
    """Rotation -> camera.angles (same mapping as napari's getter)."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")        # scipy gimbal-lock note: same pose either way
        e = rot.as_euler("yzx", degrees=True)
    e = (e - (0, 0, 90)) * (1, -1, 1)
    return np.asarray(e * flips, dtype=float)


def turn(axis: int, degrees: float) -> R:
    """Rotation by ``degrees`` about the screen axis (0 horizontal, 1 vertical, 2 depth).

    Axis 1 with +degrees equals the old ``angles[1] += degrees`` spin when
    the view is centred, so existing movies keep their direction."""
    return R.from_rotvec(np.radians(degrees) * np.asarray(_SCREEN_AXES[axis]))


def camera_angles_at(a1, a2, e: float, flips=DEFAULT_FLIPS, axis: int = 1,
                     offset: float = 0.0, final: float = 0.0) -> np.ndarray:
    """Camera angles at eased progress ``e`` between keyframe poses a1 and a2.

    base   = geodesic blend from a1 to a2 (to a2 turned back by ``final``)
    result = turn(axis, offset) * base

    ``offset`` is the spin angle at ``e`` and ``final`` its value at e = 1
    (180 for "180° e fica", 0 for loops such as 360° / vai e volta).  With
    ``final`` compensated, the movie always lands exactly on a2.
    """
    r1, r2 = rot_from_angles(a1, flips), rot_from_angles(a2, flips)
    if abs(final) % 360.0 > 1e-9:
        r2 = turn(axis, -final) * r2
    rel = (r1.inv() * r2).as_rotvec()
    if np.linalg.norm(rel) > np.pi - 1e-3:
        # Exactly 180° apart both ways round reach the same pose, and numerical
        # noise would pick one at random.  Pick the anticlockwise one (+ about the
        # first significant screen axis in the order vertical, horizontal, depth),
        # which is where the old per-angle blend went for typed (0, 180, 0).
        left = (r2 * r1.inv()).as_rotvec()
        for k in (1, 0, 2):
            if abs(left[k]) > 1e-6:
                if left[k] < 0:
                    rel = -rel
                break
    out = r1 * R.from_rotvec(e * rel)
    if offset:
        out = turn(axis, offset) * out
    return angles_from_rot(out, flips)


def relative_rotvec_deg(a_from, a_to, flips=DEFAULT_FLIPS) -> np.ndarray:
    """Rotation taking pose a_from to a_to, as screen-axis components in degrees."""
    r = rot_from_angles(a_to, flips) * rot_from_angles(a_from, flips).inv()
    return np.degrees(r.as_rotvec())


def pose_distance_deg(a, b, flips=DEFAULT_FLIPS) -> float:
    return float(np.degrees((rot_from_angles(a, flips).inv() * rot_from_angles(b, flips)).magnitude()))
