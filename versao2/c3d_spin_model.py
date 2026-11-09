# -*- coding: utf-8 -*-
"""Spin model for the Movie tab (pure Python, no Qt): which spins exist, how
far they turn at each moment, and how a keyframe's turn is described.

A spin belongs to a keyframe and acts on the transition to the NEXT one
(``kf.spin = {"mode", "axis", "dir", "force3d"}``).  ``mode`` is a plain
string so projects saved by earlier versions keep working.  The user picks
an ANGLE (45/90/180/360) and a TYPE:

    vai e volta   offset = angle * sin(pi * e)      goes to the angle and returns
    só ida        offset = angle * e                turns the angle and stays
                  (360° is a loop: it lands on the same pose)

Older modes still play: "720° — duas voltas" and "Balanço ±45°".
The movie always lands exactly on the next keyframe: see c3d_camera_math.
"""

from __future__ import annotations

import importlib.util
import math
import re
import sys
from pathlib import Path

import numpy as np


def _sibling(name):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(f"{name}.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


cam = _sibling("c3d_camera_math")

ANGLES = (45, 90, 180, 360)

SPIN_MODES = {"Nenhum": (None, 0)}
for _a in ANGLES:
    SPIN_MODES[f"{_a}° — vai e volta"] = ("swing", _a)
    SPIN_MODES["360° — volta completa" if _a == 360 else f"{_a}° — e fica"] = (
        ("turn", 1) if _a == 360 else ("stay", _a))
SPIN_MODES["720° — duas voltas"] = ("turn", 2)      # older projects
SPIN_MODES["Balanço ±45°"] = ("rock", 45)           # older projects

AXES = {"Vertical (Y)": 1, "Horizontal (X)": 0, "Profundidade (Z)": 2}
DIRECTIONS = {"Anti-horário ↺": 1.0, "Horário ↻": -1.0}


def default_spin() -> dict:
    return {"mode": "Nenhum", "axis": "Vertical (Y)", "dir": "Anti-horário ↺", "force3d": True}


def get_spin(kf) -> dict:
    spin = getattr(kf, "spin", None)
    return {**default_spin(), **spin} if spin else default_spin()


def mode_for(angle: int, back: bool) -> str:
    """Mode name for the user's choice (angle in ANGLES, vai e volta or só ida)."""
    if back:
        return f"{angle}° — vai e volta"
    return "360° — volta completa" if angle == 360 else f"{angle}° — e fica"


def parse_mode(mode: str):
    """(angle, back) for a mode the new controls can show, else None."""
    kind, amount = SPIN_MODES.get(mode, (None, 0))
    if kind == "swing":
        return amount, True
    if kind == "stay":
        return amount, False
    if kind == "turn" and amount == 1:
        return 360, False
    return None


def spin_offset(spin: dict, e: float) -> float:
    """Angle offset in degrees at eased progress e in [0, 1]."""
    kind, amount = SPIN_MODES.get(spin["mode"], (None, 0))
    sign = DIRECTIONS.get(spin["dir"], 1.0)
    if kind == "turn":
        deg = amount * 360.0 * e
    elif kind == "swing":
        deg = amount * math.sin(math.pi * e)
    elif kind == "rock":
        deg = amount * math.sin(2.0 * math.pi * e)
    elif kind == "stay":
        deg = amount * e
    else:
        return 0.0
    return sign * deg


def final_offset(spin: dict) -> float:
    """Spin angle left over at the end of the transition (the angle for 'só ida')."""
    kind, amount = SPIN_MODES.get(spin["mode"], (None, 0))
    return DIRECTIONS.get(spin["dir"], 1.0) * amount if kind == "stay" else 0.0


def spin_badge(spin: dict) -> str:
    kind, amount = SPIN_MODES.get(spin["mode"], (None, 0))
    if kind is None:
        return ""
    axis = spin["axis"].split("(")[-1].rstrip(")")
    arrow = "↺" if DIRECTIONS.get(spin["dir"], 1.0) > 0 else "↻"
    text = {"turn": f"{amount * 360}°", "swing": f"{amount}° ⇄", "rock": "±45°",
            "stay": f"{amount}°→"}[kind]
    return f"  🌀{text} {axis}{arrow}"


def peak_degrees(spin: dict) -> float:
    """Total degrees the camera travels during the transition."""
    kind, amount = SPIN_MODES.get(spin["mode"], (None, 0))
    return {"turn": amount * 360.0, "swing": 2.0 * amount, "rock": 4.0 * amount,
            "stay": float(amount)}.get(kind, 0.0)


def accumulated_angle(kfs, i: int, flips=None) -> str:
    """How far keyframe i is turned from the first keyframe, per screen axis.

    Uses the real rotation between the two poses (so a hand-rotated
    (180, -0, 180) reads as Y 180°, not X 180 + Z 180).  Turns declared by
    'só ida' are tallied along the chain: a pose that went 180° twice is the
    same pose as KF 1, and a ±180° rotation has no sign of its own, so the
    declared turn supplies it."""
    if i <= 0 or i >= len(kfs):
        return ""
    flips = cam.DEFAULT_FLIPS if flips is None else flips
    geo = cam.relative_rotvec_deg(kfs[0].camera["angles"], kfs[i].camera["angles"], flips)
    cum = {0: 0.0, 1: 0.0, 2: 0.0}
    for j in range(i):
        sp = get_spin(kfs[j])
        cum[AXES.get(sp["axis"], 1)] += final_offset(sp)
    parts, full_turns = [], False
    for ax, name in ((0, "X"), (1, "Y"), (2, "Z")):
        d, c = float(geo[ax]), cum[ax]
        if abs(c) > 0.5 and abs(((c - d + 180.0) % 360.0) - 180.0) < 0.5:
            d = c                                  # same rotation mod 360: show the declared one
            full_turns = full_turns or abs(c) >= 359.5
        if abs(d) >= 0.5:
            parts.append(f"{name} {d:+.0f}°")
    if not parts:
        return ""
    same_pose = float(np.linalg.norm(geo)) < 0.5 and full_turns
    return "∠ " + ", ".join(parts) + (" = pose do KF 1" if same_pose else "")


__all__ = ["cam", "ANGLES", "SPIN_MODES", "AXES", "DIRECTIONS", "default_spin", "get_spin",
           "mode_for", "parse_mode", "spin_offset", "final_offset", "spin_badge",
           "peak_degrees", "accumulated_angle"]
