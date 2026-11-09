# -*- coding: utf-8 -*-
"""Spin between keyframes for the Movie tab of Cryo3DEditor v2.0 (the tab UI).

The spin model (angles, vai e volta / só ida, offsets) is in c3d_spin_model.py
and the camera maths (poses blended as rotations, spins as real turns about a
screen axis) in c3d_camera_math.py.  This module adds the controls, the
keyframe list badges, the label highlight captured in keyframes, the
smooth show/hide of layers and the diagnostic logs of the movie.
"""

from __future__ import annotations

import importlib.util
import sys
from contextlib import nullcontext as _null
from pathlib import Path

import numpy as np
from qtpy.QtWidgets import QCheckBox, QComboBox, QHBoxLayout, QVBoxLayout


def _sibling(name):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(f"{name}.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_model = _sibling("c3d_spin_model")
globals().update({k: getattr(_model, k) for k in _model.__all__})   # cam, SPIN_MODES, get_spin, ...


def build_tab_class(editor):
    """Subclass the editor's AnimationTab (loaded by path in v2.0)."""

    class SpinAnimationTab(editor.AnimationTab):
        """AnimationTab + per-transition spin (see module docstring)."""

        # ── UI ───────────────────────────────────────────────────────
        def _build_keyframe_tab(self):
            w = super()._build_keyframe_tab()
            if not hasattr(self, "keyframe_layout"):      # imageio missing
                return w
            w.layout().insertWidget(2, self._build_spin_group())
            return w

        def _build_spin_group(self):
            g = editor._group("2½ ▸ 🌀 GIRO ENTRE KEYFRAMES")
            lay = QVBoxLayout()
            self.lbl_spin_title = editor._lbl("Clique num keyframe da lista acima", bold=True,
                                              color=editor.ACCENT)
            lay.addWidget(self.lbl_spin_title)
            lay.addWidget(editor._info(
                "Escolha o giro e clique em Aplicar: vale para a passagem do keyframe "
                "selecionado até o próximo."))

            self.combo_angle = QComboBox()
            self.combo_angle.addItems([f"{a}°" for a in ANGLES])
            self.combo_angle.setCurrentText("90°")
            self.combo_angle.setToolTip("Quantos graus a câmera gira.")
            self.combo_axis = QComboBox()
            self.combo_axis.addItems(list(AXES))
            self.combo_dir = QComboBox()
            self.combo_dir.addItems(list(DIRECTIONS))
            for c in (self.combo_angle, self.combo_axis, self.combo_dir):
                c.setStyleSheet(editor.INPUT_STYLE)
            row = QHBoxLayout()
            row.addWidget(editor._lbl("Ângulo:"))
            row.addWidget(self.combo_angle)
            row.addWidget(editor._lbl("Eixo:"))
            row.addWidget(self.combo_axis)
            lay.addLayout(row)
            row = QHBoxLayout()
            row.addWidget(editor._lbl("Sentido:"))
            row.addWidget(self.combo_dir)
            lay.addLayout(row)

            self.chk_back = QCheckBox("↔  Vai e volta  (gira até o ângulo e retorna à pose)")
            self.chk_back.setChecked(True)
            self.chk_back.setStyleSheet(f"color:{editor.TEXT_MAIN};")
            self.chk_back.setToolTip(
                "Ligado: a câmera gira até o ângulo e volta para a pose do keyframe.\n"
                "Desligado (só ida): gira o ângulo e fica virado. Em 45°, 90° e 180° isso "
                "insere logo depois um keyframe já virado; 360° dá uma volta completa e "
                "chega na mesma pose.")
            lay.addWidget(self.chk_back)
            self.chk_spin_3d = QCheckBox("Girar em 3D (keyframes 2D viram 3D durante o giro)")
            self.chk_spin_3d.setChecked(True)
            self.chk_spin_3d.setStyleSheet(f"color:{editor.TEXT_MAIN};")
            lay.addWidget(self.chk_spin_3d)

            def chip(text, tip, fn, variant):
                b = editor._btn(text, variant)
                b.setToolTip(tip)
                b.clicked.connect(fn)
                return b

            self.btn_apply = chip(
                "✔  Aplicar giro nesta passagem",
                "Aplica o giro escolhido do keyframe selecionado até o próximo. No último "
                "keyframe, cria o próximo (mesma pose) para você.", self._apply_spin, "run")
            self.btn_none = chip("✕  Sem giro", "Remove o giro desta passagem.",
                                 lambda: self._quick_mode("Nenhum"), "secondary")
            self.btn_insert = chip(
                "➕  Inserir giro parado nesta pose",
                "Insere logo depois um keyframe na mesma pose e aplica o giro entre os dois: "
                "a câmera gira sem sair do lugar (toca-discos) e o filme continua.",
                self._insert_here, "blue")
            row = QHBoxLayout()
            row.addWidget(self.btn_apply)
            row.addWidget(self.btn_none)
            lay.addLayout(row)
            lay.addWidget(self.btn_insert)

            self.lbl_spin_hint = editor._info("")
            lay.addWidget(self.lbl_spin_hint)
            g.setLayout(lay)
            self._set_spin_controls_enabled(False)
            return g

        def _set_spin_controls_enabled(self, on):
            """``on``: the selected keyframe has a transition (not the last one)."""
            has_kf = 0 <= self.selected_index < len(self.keyframes)
            for c in (self.combo_angle, self.chk_back, self.combo_axis, self.combo_dir,
                      self.chk_spin_3d, self.btn_apply, self.btn_insert):
                c.setEnabled(has_kf)
            self.btn_none.setEnabled(on)

        def _flips(self):
            return cam.flips_from_viewer(self.state.viewer)

        def _has_transition(self, i):
            return 0 <= i < len(self.keyframes) - 1

        def _load_spin_controls(self):
            """Show the selected keyframe's spin in the controls; a keyframe
            without a spin leaves them as the user last chose."""
            i = self.selected_index
            self._set_spin_controls_enabled(self._has_transition(i))
            if self._has_transition(i):
                spin = get_spin(self.keyframes[i])
                if spin["mode"] != "Nenhum":
                    self.combo_axis.setCurrentText(spin["axis"])
                    self.combo_dir.setCurrentText(spin["dir"])
                    self.chk_spin_3d.setChecked(spin["force3d"])
                    parsed = parse_mode(spin["mode"])
                    if parsed:
                        self.combo_angle.setCurrentText(f"{parsed[0]}°")
                        self.chk_back.setChecked(parsed[1])
            self._update_spin_hint()

        def _update_spin_hint(self):
            i = self.selected_index
            n = len(self.keyframes)
            name = lambda k: self.keyframes[k].name or f"KF {k + 1}"
            if not (0 <= i < n):
                title = "Clique num keyframe da lista acima"
                text = ""
            elif not self._has_transition(i):
                title = f"{name(i)} (último)"
                text = ("Último keyframe: Aplicar cria o próximo keyframe para você "
                        "(mesma pose, ou já virado no 'só ida').")
            else:
                title = f"{name(i)}  →  {name(i + 1)}"
                kf = self.keyframes[i]
                spin = get_spin(kf)
                peak = peak_degrees(spin)
                secs = kf.duration / max(1, self.spin_fps.value())
                if peak == 0:
                    text = f"Sem giro nesta passagem ({kf.duration} quadros, {secs:.1f} s)."
                else:
                    per = peak / max(1, kf.duration)
                    fast = "  ⚠ rápido — aumente Duration" if per > 8 else ""
                    text = (f"{peak:.0f}° em {kf.duration} quadros "
                            f"≈ {per:.1f}°/quadro, {secs:.1f} s{fast}")
            if 0 <= i < n and self._has_transition(i):
                sp = get_spin(self.keyframes[i])
                if sp["mode"] != "Nenhum" and parse_mode(sp["mode"]) is None:
                    text = (text + "\n" if text else "") + f"Giro de versão anterior: {sp['mode']}."
                if final_offset(sp):
                    flips = self._flips()
                    want = cam.angles_from_rot(
                        cam.turn(AXES.get(sp["axis"], 1), final_offset(sp)) *
                        cam.rot_from_angles(self.keyframes[i].camera["angles"], flips), flips)
                    off = cam.pose_distance_deg(want, self.keyframes[i + 1].camera["angles"], flips)
                    if off > 5.0:
                        text = (text + "\n" if text else "") + (
                            f"⚠ o próximo keyframe não está virado {abs(final_offset(sp)):.0f}° "
                            f"(diferença {off:.0f}°): o giro limpo só acontece se ele estiver. "
                            "Aplique de novo com 'só ida', que cria esse keyframe.")
            if 0 <= i < n:
                ang = accumulated_angle(self.keyframes, i, self._flips())
                if ang:
                    text = (text + "\n" if text else "") + \
                        f"Ângulo acumulado deste keyframe vs KF 1: {ang[2:]}"
            self.lbl_spin_title.setText(title)
            self.lbl_spin_hint.setText(text)

        def _refresh_badges(self):
            for i in range(self.keyframe_layout.count() - 1):
                w = self.keyframe_layout.itemAt(i).widget()
                if isinstance(w, editor.KeyframeWidget) and i < len(self.keyframes):
                    kf = self.keyframes[i]
                    mode = "3D" if kf.dims.get("ndisplay", 3) == 3 else "2D"
                    pt = kf.dims.get("point", [0, 0, 0])
                    sl = int(pt[0]) if len(pt) > 0 else 0
                    badge = spin_badge(get_spin(kf)) if self._has_transition(i) else ""
                    focus = "".join(f"\n🎯 {n}: {lbl}" for n, lbl in
                                    getattr(kf, "label_focus", {}).items())
                    ang = accumulated_angle(self.keyframes, i, self._flips())
                    ang = f"\n{ang}" if ang else ""
                    w.info_label.setText(f"{mode} | Z={sl} | {kf.duration}f{badge}{ang}{focus}")

        # ── one-click actions ────────────────────────────────────────
        def _twin_after(self, i, suffix):
            """Insert a copy of keyframe i right after it. The copy inherits
            i's old transition (spin) so whatever came next is unchanged."""
            src = self.keyframes[i]
            twin = src.copy()
            twin.name = f"{src.name or f'KF {i + 1}'} {suffix}"
            twin.spin = get_spin(src) if self._has_transition(i) else default_spin()
            twin.label_focus = dict(getattr(src, "label_focus", {}))
            self.keyframes.insert(i + 1, twin)
            return src, twin

        def _spin_choice(self):
            """(angle, vai e volta?, mode name) from the controls."""
            angle = int(self.combo_angle.currentText().rstrip("°"))
            back = self.chk_back.isChecked()
            return angle, back, mode_for(angle, back)

        def _spin_dict(self, mode):
            return {"mode": mode, "axis": self.combo_axis.currentText(),
                    "dir": self.combo_dir.currentText(), "force3d": self.chk_spin_3d.isChecked()}

        def _apply_spin(self):
            angle, back, mode = self._spin_choice()
            if SPIN_MODES[mode][0] == "stay":          # só ida < 360°: needs a turned keyframe
                return self._quick_stay(angle)
            return self._quick_mode(mode)

        def _quick_mode(self, mode):
            i = self.selected_index
            if not (0 <= i < len(self.keyframes)):
                return editor.show_warning("Clique num keyframe da lista primeiro.")
            if not self._has_transition(i):
                if mode == "Nenhum":
                    return
                self._twin_after(i, "↺")
            src = self.keyframes[i]
            src.spin = self._spin_dict(mode)
            if mode != "Nenhum":
                src.duration = max(src.duration, 90 if "360" in mode else 60)
            self._refresh_keyframe_list()
            self._select_quietly(i)
            self.status_label.setText(f"{mode} aplicado em {src.name or f'KF {i + 1}'}")

        def _quick_stay(self, angle):
            """'Só ida': insert, right after the selected keyframe, the same pose turned
            ``angle``° about the screen axis (a real rotation, so it also works for a pose
            that came from a mouse rotation).  The segment turns the way you chose, as a
            clean turntable, and lands exactly on that keyframe."""
            i = self.selected_index
            if not (0 <= i < len(self.keyframes)):
                return editor.show_warning("Clique num keyframe da lista primeiro.")
            src, twin = self._twin_after(i, f"↻{angle}°")
            ax = AXES.get(self.combo_axis.currentText(), 1)
            sign = DIRECTIONS.get(self.combo_dir.currentText(), 1.0)
            flips = self._flips()
            r1 = cam.rot_from_angles(src.camera["angles"], flips)
            twin.camera["angles"] = cam.angles_from_rot(cam.turn(ax, angle * sign) * r1, flips)
            if self.chk_spin_3d.isChecked():
                twin.dims["ndisplay"] = 3
            src.spin = self._spin_dict(mode_for(angle, False))
            src.duration = max(src.duration, 60)
            self._refresh_keyframe_list()
            self._select_quietly(i)
            self.status_label.setText(f"Criado '{twin.name}': gira {angle}° e fica do outro lado")

        def _select_quietly(self, i):
            """Highlight row i and load its controls without moving the camera."""
            self.selected_index = i
            for k in range(self.keyframe_layout.count() - 1):
                w = self.keyframe_layout.itemAt(k).widget()
                if isinstance(w, editor.KeyframeWidget):
                    w.set_selected(k == i)
            self._load_spin_controls()

        def _insert_here(self):
            """Spin in place: a copy of the selected keyframe goes right after it and the
            chosen spin runs between the two."""
            i = self.selected_index
            if not (0 <= i < len(self.keyframes)):
                return editor.show_warning("Clique num keyframe da lista primeiro.")
            angle, back, mode = self._spin_choice()
            if SPIN_MODES[mode][0] == "stay":
                return self._quick_stay(angle)
            src, _twin = self._twin_after(i, "↺")
            src.spin = self._spin_dict(mode)
            src.duration = max(src.duration, 90 if "360" in mode else 60)
            self._refresh_keyframe_list()
            self._select_quietly(i)
            self.status_label.setText(f"{mode} inserido depois de {src.name or f'KF {i + 1}'}")

        # ── keep spin + badges in sync with the base tab ─────────────
        def _refresh_keyframe_list(self):
            super()._refresh_keyframe_list()
            if hasattr(self, "combo_angle"):
                self._refresh_badges()
                self._load_spin_controls()

        def _on_keyframe_clicked(self, index):
            super()._on_keyframe_clicked(index)
            self._load_spin_controls()

        def _update_selected(self):
            i = self.selected_index
            spin = getattr(self.keyframes[i], "spin", None) if 0 <= i < len(self.keyframes) else None
            super()._update_selected()
            if spin is not None and 0 <= i < len(self.keyframes):
                self.keyframes[i].spin = spin
                self._refresh_badges()

        def _update_duration(self, value):
            super()._update_duration(value)
            if hasattr(self, "combo_angle"):
                self._refresh_badges()
                self._update_spin_hint()

        # ── highlighted label ("show selected") is part of the keyframe ──
        def _layer_label_colors(self, layer):
            """{label: rgba} as the layer shows it now, for every label present."""
            colors = dict(self.state.label_colors.get(layer.name, {}))
            if colors:
                return colors
            cdict = getattr(layer.colormap, "color_dict", None) or {}
            colors = {int(k): tuple(float(c) for c in v) for k, v in cdict.items()
                      if k is not None and int(k) != 0}
            if colors:
                return colors
            data = np.asarray(layer.data)
            if data.dtype.kind == "u" and data.dtype.itemsize <= 2:
                present = np.flatnonzero(np.bincount(data.ravel()))
            else:
                present = np.unique(data)
            present = [int(v) for v in present if v != 0]
            rgba = layer.colormap.map(np.array(present, dtype=data.dtype)) if present else []
            return {v: tuple(float(c) for c in rgba[k]) for k, v in enumerate(present)}

        def _focus_labels_into(self, kf):
            """For each Labels layer in 'show selected' mode, store in the
            keyframe its colours with every label except the selected one
            transparent — that is what the canvas shows, and it survives
            replay (napari's selection mode itself is not recorded)."""
            kf.label_focus = {}
            for layer in self.state.get_labels():
                if not getattr(layer, "show_selected_label", False):
                    continue
                sel = int(layer.selected_label)
                colors = self._layer_label_colors(layer)
                kf.label_colors[layer.name] = {
                    lbl: (c[0], c[1], c[2], c[3] if lbl == sel else 0.0)
                    for lbl, c in colors.items()}
                kf.label_focus[layer.name] = sel
            return kf

        def _capture_full_state(self):
            kf = self._focus_labels_into(super()._capture_full_state())
            self._log_keyframe("keyframe captured", kf)
            return kf

        # ── logs: everything needed to diagnose a movie from the terminal ──
        def _log_keyframe(self, msg, kf):
            on = {n: round(float(kf.layer_opacity.get(n, 1.0)), 3)
                  for n, v in kf.layer_visibility.items() if v}
            off = [n for n, v in kf.layer_visibility.items() if not v]
            editor.log("  " + msg, params={
                "keyframe": kf.name, "ndisplay": kf.dims.get("ndisplay"),
                "angles": tuple(round(float(a), 1) for a in kf.camera["angles"]),
                "zoom": round(float(kf.camera["zoom"]), 3), "visible(opacity)": on,
                "hidden": off, "label_focus": getattr(kf, "label_focus", {}) or "-"})
            for n, op in on.items():
                if op < 0.05:
                    editor.log("  layer is ON with opacity ~0 here (fine as the start of a fade-in; "
                               "checked against the other keyframes when the movie is built)",
                               params={"keyframe": kf.name, "layer": n, "opacity": op})
            for n, sel in (getattr(kf, "label_focus", {}) or {}).items():
                present = kf.label_colors.get(n, {})
                if sel not in present:
                    editor.log("  highlighted label does not exist in this layer — nothing will "
                               "show for it", level="WARN",
                               params={"keyframe": kf.name, "layer": n, "label": sel,
                                       "labels_in_layer": sorted(present)[:10]})

        def _log_plan(self, n_frames):
            kfs = self.keyframes
            editor.log("Movie plan", params={"keyframes": len(kfs), "frames": n_frames,
                                             "fps": self.spin_fps.value(),
                                             "seconds": round(n_frames / max(1, self.spin_fps.value()), 1),
                                             "interpolation": self.combo_interp.currentText()})
            names = set()
            for k in kfs:
                names |= set(k.layer_visibility)
            for n in sorted(names):
                shown = [k.layer_opacity.get(n, 1.0) for k in kfs if k.layer_visibility.get(n, False)]
                if shown and max(shown) < 0.05:
                    editor.log("  layer is ON but at opacity ~0 in EVERY keyframe — it never shows in "
                               "this movie", level="WARN", params={"layer": n})
            for i in range(len(kfs) - 1):
                a, b = kfs[i], kfs[i + 1]
                spin = get_spin(a)
                fades = {n: ("in" if b.layer_visibility.get(n) else "out")
                         for n in set(a.layer_visibility) | set(b.layer_visibility)
                         if a.layer_visibility.get(n, False) != b.layer_visibility.get(n, False)}
                ramps = {n: (round(float(a.layer_opacity.get(n, 1.0)), 2),
                             round(float(b.layer_opacity.get(n, 1.0)), 2))
                         for n in set(a.layer_visibility) & set(b.layer_visibility)
                         if a.layer_visibility[n] and b.layer_visibility[n]
                         and abs(a.layer_opacity.get(n, 1.0) - b.layer_opacity.get(n, 1.0)) > 0.05}
                focus = (getattr(a, "label_focus", {}) or "-", getattr(b, "label_focus", {}) or "-")
                editor.log("  transition", params={
                    "from": a.name, "to": b.name, "frames": a.duration,
                    "spin": spin["mode"], "degrees": peak_degrees(spin),
                    "axis": spin["axis"], "dir": spin["dir"],
                    "angles": (tuple(round(float(x), 1) for x in a.camera["angles"]),
                               tuple(round(float(x), 1) for x in b.camera["angles"])),
                    "ndisplay": (a.dims.get("ndisplay"), b.dims.get("ndisplay")),
                    "fades": fades or "-", "opacity_ramps": ramps or "-", "label_focus": focus})

        def _generate_frames(self):
            frames = super()._generate_frames()
            self._apply_count = 0
            if frames:
                self._log_plan(len(frames))
            return frames

        def _apply_state(self, kf):
            """Label visibility comes from the keyframe's colours, so selection
            mode must be off; and the Colors tab must not turn it back on
            while the colormap is swapped (see IntegratedState.quiet_colors_tab)."""
            viewer = self.state.viewer
            quiet = getattr(self.state, "quiet_colors_tab", None)
            ctx = quiet() if quiet else _null()
            with ctx:
                for name in kf.label_colors:
                    if name in viewer.layers and getattr(viewer.layers[name],
                                                          "show_selected_label", False):
                        viewer.layers[name].show_selected_label = False
                super()._apply_state(kf)
            # The base class swallows errors while applying a frame; verify the
            # two things that matter and log one line every 15 frames.
            n = getattr(self, "_apply_count", 0)
            self._apply_count = n + 1
            want_nd = kf.dims.get("ndisplay")
            if want_nd is not None and int(viewer.dims.ndisplay) != int(want_nd):
                editor.log("  frame NOT applied as planned (ndisplay)", level="WARN",
                           params={"frame": n, "wanted": want_nd, "actual": int(viewer.dims.ndisplay)})
            if n % 15 == 0:
                fading = {k: round(float(v), 2) for k, v in kf.layer_opacity.items()
                          if 0.0 < v < 1.0 and kf.layer_visibility.get(k, False)}
                editor.log("  frame", params={
                    "n": n, "ndisplay": want_nd,
                    "angles": tuple(round(float(a), 1) for a in kf.camera["angles"]),
                    "zoom": round(float(kf.camera["zoom"]), 3),
                    "visible": sum(bool(v) for v in kf.layer_visibility.values()),
                    "partial_opacity": fading or "-"})

        # ── the spin itself + smooth show/hide ────────────────────────
        def _interpolate_state(self, kf1, kf2, t):
            frame = super()._interpolate_state(kf1, kf2, t)
            e = self._interpolate(t)
            # A layer switched on/off between keyframes fades instead of
            # popping at the midpoint: keep it visible and ramp its opacity.
            for n in set(kf1.layer_visibility) | set(kf2.layer_visibility):
                v1, v2 = kf1.layer_visibility.get(n, False), kf2.layer_visibility.get(n, False)
                if v1 != v2:
                    o1 = kf1.layer_opacity.get(n, 1.0) if v1 else 0.0
                    o2 = kf2.layer_opacity.get(n, 1.0) if v2 else 0.0
                    frame.layer_visibility[n] = True
                    frame.layer_opacity[n] = o1 * (1 - e) + o2 * e
            spin = get_spin(kf1)
            kind = SPIN_MODES.get(spin["mode"], (None, 0))[0]
            frame.camera["angles"] = cam.camera_angles_at(
                kf1.camera["angles"], kf2.camera["angles"], e, self._flips(),
                axis=AXES.get(spin["axis"], 1),
                offset=spin_offset(spin, e) if kind else 0.0, final=final_offset(spin))
            if kind and spin["force3d"]:
                frame.dims["ndisplay"] = 3
            return frame

    return SpinAnimationTab
