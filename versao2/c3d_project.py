# -*- coding: utf-8 -*-
"""Save / open a Cryo3DEditor v2.0 project (.c3dproj).

One file holds the whole session: every viewer layer (tomograms embedded by
default, so the project opens on any machine), the Segmentation tab's
contours / particles / template / settings, the Colors tab's per-label
colours and the Movie tab's keyframes.  Archive format and layer I/O live
in c3d_project_layers.py.

The scale each layer was used with is written to the manifest and
re-applied on open.  For a tomogram re-read from disk the MRC header voxel
size is compared against it and any mismatch is logged.

Not persisted (recomputed on demand): scalar-field smoothing caches,
membrane-distance results, preview/worker state, movie preview frames.
"""

from __future__ import annotations

import importlib.util
from contextlib import nullcontext as _nullcontext
import json
import sys
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional

import numpy as np


def _sibling(name):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(f"{name}.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


io = _sibling("c3d_project_layers")
default_log, log_exception, array_desc = io.default_log, io.log_exception, io.array_desc

FORMAT = "cryo3d-project"
VERSION = 2
EXTENSION = ".c3dproj"
DRAW_LAYER = "_membrane_draw"   # rebuilt from the contours, never saved

# Segmentation-tab controls that are plain settings.  Excluded on purpose:
# per-contour Surface Effects sliders (stored on each contour), the brush
# on/off toggle, the template-invert box (re-applied with the template) and
# the Efeitos 3D object combo (changing it can promote a layer).
_SEG_SETTINGS = [
    "_rb_load", "_rb_draw", "_rb_open", "_rb_closed",
    "_combo_interp", "_spin_chain_thresh", "_spin_gap_z_warn",
    "_combo_output_type", "_chk_fx_export", "_chk_surface", "_chk_export_visible",
    "_chk_auto_align", "_chk_flip_x", "_chk_flip_y", "_chk_flip_z", "_chk_swap_yx",
    "_combo_brush_method", "_combo_brush_image", "_combo_brush_labels",
    "_rb_brush_single", "_rb_brush_multi", "_rb_brush_lower", "_rb_brush_upper",
    "_spin_brush_c", "_spin_brush_label", "_spin_brush_nz", "_spin_brush_size",
    "_spin_brush_window",
    "_spin_particle_bin", "_spin_particle_size", "_cmb_particle_color",
    "_chk_particle_out_of_slice", "_sl_particle_score",
    "_cmb_orient_axes", "_chk_orient_centred", "_spin_orient_len", "_spin_orient_width",
    "_spin_template_scale", "_sl_template_iso", "_cmb_template_detail",
    "_chk_template_largest", "_cmb_membrane_layer",
    "_cmb_range_mode", "_spin_range_min", "_spin_range_max", "_chk_range_everywhere",
    "_combo_export_layer", "_combo_export_srf", "_combo_mesh_fmt", "_cmb_export_fmt",
]


def _f(seq):
    return [float(v) for v in seq]


def _widget_value(w):
    cls = type(w).__name__
    if cls in ("QCheckBox", "QRadioButton"):
        return bool(w.isChecked())
    if cls == "QComboBox":
        return w.currentText()
    if cls in ("QSpinBox", "QDoubleSpinBox", "QSlider"):
        return w.value()
    return None


# ────────────────────────────────────────────────────────────────────────────
# SAVE
# ────────────────────────────────────────────────────────────────────────────

def _save_segmentation(seg, arrays, log) -> dict:
    contours = []
    for i, c in enumerate(seg._contours):
        e = dict(name=c.name, closed=bool(c.closed), color=[int(v) for v in c.color],
                 visible=bool(c.visible), external=bool(c.external),
                 fx_sigma=_f(c.fx_sigma), fx_offset=float(c.fx_offset),
                 fx_grain_on=bool(c.fx_grain_on), fx_grain_scale=float(c.fx_grain_scale),
                 fx_grain_intensity=float(c.fx_grain_intensity), strokes=[])
        for z, shapes in c.slices.items():
            for j, sh in enumerate(shapes):
                k = f"contour{i}/z{int(z)}_{j}"
                arrays[k] = np.asarray(sh, dtype=np.float64)
                e["strokes"].append([int(z), k])
        if c.external and c.raw_field is not None:
            arrays[f"contour{i}/raw_field"] = np.asarray(c.raw_field)
            e["bbox"] = [int(v) for v in c.bbox]
            e["field_key"] = [c.field_key[0], c.field_key[1], list(c.field_key[2])]
        elif c.external:
            log("  promoted contour has NO field — it will be empty after reopening",
                level="WARN", params={"contour": c.name})
        contours.append(e)
        log("  contour saved", params={
            "contour": c.name, "type": "closed" if c.closed else "open",
            "external": c.external, "visible": c.visible, "slices": len(c.slices),
            "strokes": len(e["strokes"]), "fx_sigma": tuple(e["fx_sigma"]),
            "fx_offset": e["fx_offset"], "grain": (e["fx_grain_on"], e["fx_grain_scale"],
                                                   e["fx_grain_intensity"]),
            **({"field": array_desc(c.raw_field), "bbox": tuple(e["bbox"])}
               if "bbox" in e else {})})

    out = dict(contours=contours, active_idx=int(seg._active_idx),
               color_cycle_idx=int(seg._color_cycle_idx),
               last_labels_layer=seg._last_labels_layer,
               last_output_type=seg._last_output_type, settings={})
    for name in _SEG_SETTINGS:
        w = getattr(seg, name, None)
        if w is not None:
            val = _widget_value(w)
            if val is not None:
                out["settings"][name] = val
    log("  segmentation settings saved", params={"count": len(out["settings"]),
                                                 "values": out["settings"]})

    ps = seg._particles
    if ps is not None:
        arrays["particles/coords_zyx"] = np.asarray(ps.coords_zyx)
        for fld in ("scores", "angles", "raw_motl"):
            if getattr(ps, fld) is not None:
                arrays[f"particles/{fld}"] = np.asarray(getattr(ps, fld))
        if ps.tomo_ids is not None:
            arrays["particles/tomo_ids"] = np.asarray(ps.tomo_ids).astype(np.float64)
        out["particles"] = dict(angle_convention=ps.angle_convention, source=ps.source,
                                fmt=ps.fmt, notes=list(ps.notes))
        log("  particles saved", params={"source": ps.source, "fmt": ps.fmt, "n": len(ps),
                                         "scores": ps.scores is not None,
                                         "angles": ps.angle_convention or "none"})
    if seg._template is not None and seg._template_path:
        out["template"] = dict(path=str(Path(seg._template_path).resolve()),
                               inverted=bool(seg._template.inverted))
        log("  template reference saved", params=out["template"])
    return out


def _save_keyframes(movie, arrays, log) -> List[dict]:
    kfs = []
    for i, kf in enumerate(movie.keyframes):
        e = dict(name=kf.name, duration=int(kf.duration),
                 camera=dict(center=_f(kf.camera["center"]), zoom=float(kf.camera["zoom"]),
                             angles=_f(kf.camera["angles"])),
                 dims=dict(ndisplay=int(kf.dims["ndisplay"]), point=_f(kf.dims["point"])),
                 layer_visibility={k: bool(v) for k, v in kf.layer_visibility.items()},
                 layer_opacity={k: float(v) for k, v in kf.layer_opacity.items()},
                 layer_contrast_limits={k: _f(v) for k, v in kf.layer_contrast_limits.items()},
                 layer_rendering=dict(kf.layer_rendering),
                 label_colors={n: {str(l): _f(c) for l, c in cols.items()}
                               for n, cols in kf.label_colors.items()})
        if getattr(kf, "spin", None):
            e["spin"] = dict(kf.spin)
        if getattr(kf, "label_focus", None):
            e["label_focus"] = {k: int(v) for k, v in kf.label_focus.items()}
        if kf.thumbnail is not None:
            arrays[f"keyframe{i}/thumbnail"] = np.asarray(kf.thumbnail)
        kfs.append(e)
        log("  keyframe saved", params={"keyframe": kf.name, "duration": kf.duration,
                                        "ndisplay": e["dims"]["ndisplay"],
                                        "zoom": round(e["camera"]["zoom"], 3),
                                        "layers": len(e["layer_visibility"]),
                                        "spin": e.get("spin", {}).get("mode", "Nenhum"),
                                        "focus": getattr(kf, "label_focus", {}) or "-"})
    return kfs


def save_project(widget, path: str, embed_images: bool = True, log=None) -> None:
    """Write the whole session of a Cryo3DEditorV2Widget to ``path``."""
    log = log or default_log
    t0 = time.time()
    state, viewer = widget.state, widget.state.viewer
    log("━━ SAVE PROJECT ━━", params={"file": path, "layers": len(viewer.layers),
                                       "embed_tomograms": embed_images})
    arrays: Dict[str, np.ndarray] = {}
    stored: set = set()
    layers = []
    for i, layer in enumerate(viewer.layers):
        if layer.name == DRAW_LAYER:
            log("  layer skipped (draw layer is rebuilt from contours)", params={"layer": layer.name})
            continue
        try:
            e = io.save_layer(layer, f"layer{i}", arrays, stored, embed_images, log)
        except Exception as exc:
            log_exception(log, "  layer NOT saved", exc, {"layer": layer.name})
            continue
        if e is not None:
            e["key"] = f"layer{i}"
            layers.append(e)

    manifest = dict(
        format=FORMAT, version=VERSION, saved_at=time.strftime("%Y-%m-%d %H:%M:%S"),
        platform=sys.platform, layers=layers,
        viewer=dict(ndisplay=int(viewer.dims.ndisplay),
                    current_step=[int(v) for v in viewer.dims.current_step],
                    camera=dict(center=_f(viewer.camera.center), zoom=float(viewer.camera.zoom),
                                angles=_f(viewer.camera.angles))),
        colors=dict(label_colors={n: {str(l): _f(c) for l, c in cols.items()}
                                  for n, cols in state.label_colors.items()},
                    label_opacities={n: {str(l): float(o) for l, o in ops.items()}
                                     for n, ops in state.label_opacities.items()}),
        segmentation=_save_segmentation(widget.segmentation_tab, arrays, log),
        keyframes=_save_keyframes(widget.movie_tab, arrays, log),
    )
    log("  colours saved", params={n: len(c) for n, c in manifest["colors"]["label_colors"].items()})
    arrays["__manifest__"] = np.array(json.dumps(manifest))
    io.write_archive(path, arrays, stored, log)
    log("━━ SAVE DONE ━━", t0=t0, params={"layers": len(layers),
                                          "contours": len(manifest["segmentation"]["contours"]),
                                          "keyframes": len(manifest["keyframes"])})


# ────────────────────────────────────────────────────────────────────────────
# OPEN
# ────────────────────────────────────────────────────────────────────────────

def _restore_widget(w, val):
    cls = type(w).__name__
    if cls == "QCheckBox":
        w.setChecked(bool(val))
    elif cls == "QRadioButton":
        if val:
            w.setChecked(True)
    elif cls == "QComboBox":
        idx = w.findText(str(val))
        if idx < 0:
            raise ValueError(f"option '{val}' is not in the list now")
        w.setCurrentIndex(idx)
    elif cls in ("QSpinBox", "QSlider"):
        w.setValue(int(val))
    elif cls == "QDoubleSpinBox":
        w.setValue(float(val))


def _restore_segmentation(seg, s, z, manual, warnings, log):
    contours = []
    for i, e in enumerate(s.get("contours", [])):
        c = manual.ContourObject(name=e["name"], closed=e["closed"], color=tuple(e["color"]),
                                 visible=e["visible"], external=e["external"])
        c.fx_sigma = tuple(e["fx_sigma"])
        c.fx_offset = e["fx_offset"]
        c.fx_grain_on = e["fx_grain_on"]
        c.fx_grain_scale = e["fx_grain_scale"]
        c.fx_grain_intensity = e["fx_grain_intensity"]
        for zz, k in e["strokes"]:
            c.slices.setdefault(int(zz), []).append(z[k])
        if c.external and f"contour{i}/raw_field" in z:
            c.raw_field = z[f"contour{i}/raw_field"]
            c.bbox = tuple(e["bbox"])
            fk = e["field_key"]
            c.field_key = (fk[0], fk[1], tuple(fk[2]))
        contours.append(c)
        log("  contour restored", params={"contour": c.name, "external": c.external,
                                          "slices": len(c.slices), "strokes": len(e["strokes"]),
                                          "has_field": c.raw_field is not None})
    seg._contours = contours
    seg._fx_target = []
    seg._color_cycle_idx = s.get("color_cycle_idx", 0)
    seg._last_labels_layer = s.get("last_labels_layer")
    seg._last_output_type = s.get("last_output_type", "labels")

    tpl = s.get("template")
    if tpl and Path(tpl["path"]).exists():
        ok = seg._load_template_file(tpl["path"], invert=tpl["inverted"])
        log("  template reloaded" if ok else "  template reload FAILED",
            level="INFO" if ok else "WARN", params=tpl)
    else:
        if tpl:
            warnings.append(f"Template não encontrado em {tpl['path']}.")
            log("  template file missing", level="WARN", params=tpl)
        seg._template, seg._template_path, seg._template_mesh_cache = None, None, {}
        seg._refresh_template_buttons()

    p = s.get("particles")
    if p is not None:
        get = lambda f: z[f"particles/{f}"] if f"particles/{f}" in z else None
        ps = manual.ParticleSet(coords_zyx=z["particles/coords_zyx"], scores=get("scores"),
                                angles=get("angles"), angle_convention=p["angle_convention"],
                                tomo_ids=get("tomo_ids"), source=p["source"], fmt=p["fmt"],
                                notes=list(p["notes"]), raw_motl=get("raw_motl"))
        seg._adopt_particle_set(ps)
        log("  particles restored", params={"source": ps.source, "n": len(ps)})
    else:
        seg._particles, seg._particle_dist, seg._particle_axes_cache = None, None, None
        seg._btn_show_particles.setEnabled(False)
        seg._btn_show_orient.setEnabled(False)
        seg._refresh_particle_info()

    # The combos list the layers that are open now, so they must be filled
    # BEFORE their saved selection is applied (it was failing with
    # "option 'L53_Position_2' is not in the list now").
    for fn in ("_refresh_ext_seg_list", "_refresh_brush_image_combo", "_refresh_brush_labels_combo",
               "_refresh_membrane_layer_combo", "_refresh_export_layer_combo",
               "_refresh_export_srf_combo"):
        try:
            getattr(seg, fn)()
        except Exception as exc:
            log_exception(log, "  combo refresh failed", exc, {"function": fn})

    n_ok = 0
    for name, val in s.get("settings", {}).items():
        w = getattr(seg, name, None)
        if w is None:
            log("  setting skipped (control no longer exists)", level="WARN", params={"control": name})
            continue
        if val == "":
            continue                     # nothing was selected in that combo
        try:
            _restore_widget(w, val)
            n_ok += 1
        except Exception as exc:         # terminal only: a stale combo is not worth a popup
            log_exception(log, "  setting NOT restored", exc, {"control": name, "value": val})
    log("  segmentation settings restored", params={"ok": n_ok, "saved": len(s.get("settings", {}))})

    seg._active_idx = -1
    seg._refresh_list()
    act = s.get("active_idx", -1)
    if 0 <= act < len(contours):
        seg._list_widget.setCurrentRow(act)
    try:
        seg._update_status_bar()
    except Exception as exc:
        log_exception(log, "  UI refresh failed", exc, {"function": "_update_status_bar"})


def _restore_keyframes(movie, kfs, z, editor, log):
    out = []
    for i, e in enumerate(kfs):
        key = f"keyframe{i}/thumbnail"
        out.append(editor.Keyframe(
            camera=dict(center=np.array(e["camera"]["center"]), zoom=e["camera"]["zoom"],
                        angles=np.array(e["camera"]["angles"])),
            dims=dict(ndisplay=e["dims"]["ndisplay"], point=np.array(e["dims"]["point"])),
            layer_visibility=e["layer_visibility"], layer_opacity=e["layer_opacity"],
            layer_contrast_limits={k: tuple(v) for k, v in e["layer_contrast_limits"].items()},
            layer_rendering=e["layer_rendering"],
            label_colors={n: {int(l): tuple(c) for l, c in cols.items()}
                          for n, cols in e["label_colors"].items()},
            thumbnail=z[key] if key in z else None,
            name=e["name"], duration=e["duration"]))
        if e.get("spin"):
            out[-1].spin = dict(e["spin"])
        if e.get("label_focus"):
            out[-1].label_focus = dict(e["label_focus"])
    movie.keyframes = out
    movie.selected_index = -1
    movie._refresh_keyframe_list()
    log("  keyframes restored", params={"count": len(out), "names": [k.name for k in out],
                                        "spins": [getattr(k, "spin", {}).get("mode", "Nenhum") for k in out]})


def _rebuild_label_colormaps(viewer, log, state=None):
    """Leave every Labels layer in plain 'show all labels' mode.

    While the project loads, the Colors tab rebuilds its label list and its
    highlight feature turns on ``show_selected_label`` (selection = first
    label).  In napari 0.7 that selection mode on a DirectLabelColormap
    paints the background with the selected label's colour and shifts the
    others by one — the whole slice turned cyan (label 1) on real data,
    0.563 of the canvas painted instead of 0.015.  Switching the mode off
    and re-assigning an equal colormap with ``use_selection=False`` brings
    the layer back to exactly what was saved."""
    from napari.layers import Labels
    try:
        from napari.utils.colormaps import DirectLabelColormap
    except ImportError:
        return
    for layer in viewer.layers:
        if not isinstance(layer, Labels):
            continue
        cm = layer.colormap
        was = {"show_selected_label": bool(getattr(layer, "show_selected_label", False)),
               "use_selection": bool(getattr(cm, "use_selection", False)),
               "selected_label": int(getattr(layer, "selected_label", 0))}
        quiet = state.quiet_colors_tab() if state is not None else _nullcontext()
        try:
            with quiet:
                layer.show_selected_label = False
                if isinstance(cm, DirectLabelColormap):
                    layer.colormap = DirectLabelColormap(color_dict=dict(cm.color_dict),
                                                         use_selection=False)
                layer.refresh()
            cm = layer.colormap
            log("  label display reset to 'show all labels'",
                level="WARN" if was["show_selected_label"] or was["use_selection"] else "INFO",
                params={"layer": layer.name, "before": was,
                        "after_use_selection": bool(getattr(cm, "use_selection", False)),
                        "colormap": type(cm).__name__,
                        "colors": len(getattr(cm, "color_dict", {}) or {}),
                        "label0_rgba": tuple(round(float(c), 3) for c in
                                             cm.map(np.array([0], np.uint32))[0])})
        except Exception as exc:
            log_exception(log, "  label display reset failed", exc, {"layer": layer.name})


def load_project(widget, path: str, manual, editor,
                 locate: Optional[Callable[[str, str], Optional[str]]] = None, log=None) -> List[str]:
    """Replace the current session with the project at ``path``.

    A tomogram stored by path that moved is first searched for automatically
    (works across Windows/Mac OneDrive roots), then ``locate(name, old_path)``
    is asked; return None to skip.  Returns non-fatal warnings.
    """
    log = log or default_log
    t0 = time.time()
    log("━━ OPEN PROJECT ━━", params={"file": path})
    warnings: List[str] = []
    z = io.read_archive(path, log)
    manifest = json.loads(str(z.pop("__manifest__")))
    if manifest.get("format") != FORMAT:
        raise ValueError("Este arquivo não é um projeto do Cryo3DEditor.")
    log("  manifest", params={"version": manifest.get("version"), "saved_at": manifest.get("saved_at"),
                              "saved_on": manifest.get("platform"), "layers": len(manifest["layers"]),
                              "contours": len(manifest.get("segmentation", {}).get("contours", [])),
                              "keyframes": len(manifest.get("keyframes", []))})

    state, viewer = widget.state, widget.state.viewer
    seg = widget.segmentation_tab
    seg._deactivate_density_brush()
    log("  clearing current session", params={"layers_removed": len(viewer.layers)})
    viewer.layers.clear()
    seg._shapes_layer = None
    seg._particle_layer = seg._orientation_layer = seg._surfaces_layer = None

    n_ok = 0
    for e in manifest["layers"]:
        n_before = len(viewer.layers)
        try:
            io.restore_layer(viewer, e, z, warnings, locate, log, project_path=path)
        except Exception as exc:
            warnings.append(f"Camada '{e['name']}' não restaurada ({io.tb_last(exc)})")
            log_exception(log, "  layer NOT restored", exc, {"layer": e["name"], "type": e["type"]})
        n_ok += len(viewer.layers) > n_before

    colors = manifest.get("colors", {})
    state.label_colors = {n: {int(l): tuple(c) for l, c in cols.items()}
                          for n, cols in colors.get("label_colors", {}).items()}
    state.label_opacities = {n: {int(l): float(o) for l, o in ops.items()}
                             for n, ops in colors.get("label_opacities", {}).items()}
    state._color_init_done = set(state.label_colors)
    state.history, state.history_idx = [], -1
    for name in state.label_colors:
        if state.get_labels_layer(name) is None:
            log("  colours kept for a layer that is not open", level="WARN", params={"layer": name})
        state._apply_colormap(name)
    log("  Colors tab restored", params={n: len(c) for n, c in state.label_colors.items()})

    for step, fn in (("segmentation", lambda: _restore_segmentation(
                         seg, manifest.get("segmentation", {}), z, manual, warnings, log)),
                     ("keyframes", lambda: _restore_keyframes(
                         widget.movie_tab, manifest.get("keyframes", []), z, editor, log)),
                     ("colors tab list", widget.colors_tab._refresh_layers)):
        try:
            fn()
        except Exception as exc:
            warnings.append(f"{step} não restaurado ({io.tb_last(exc)})")
            log_exception(log, f"  {step} NOT restored", exc)

    v = manifest.get("viewer", {})
    try:
        viewer.dims.ndisplay = v.get("ndisplay", viewer.dims.ndisplay)
        if len(v.get("current_step", [])) == viewer.dims.ndim:
            viewer.dims.current_step = tuple(v["current_step"])
        cam = v.get("camera", {})
        if cam:
            viewer.camera.center = tuple(cam["center"])
            viewer.camera.zoom = cam["zoom"]
            viewer.camera.angles = tuple(cam["angles"])
        log("  camera restored", params={"ndisplay": viewer.dims.ndisplay, **cam})
    except Exception as exc:
        warnings.append(f"Câmera não restaurada ({io.tb_last(exc)})")
        log_exception(log, "  camera NOT restored", exc)

    _rebuild_label_colormaps(viewer, log, state)
    log("━━ OPEN DONE ━━", t0=t0, params={"layers_restored": f"{n_ok}/{len(manifest['layers'])}",
                                          "warnings": len(warnings)})
    for w in warnings:
        log("  warning summary", level="WARN", params={"msg": w})
    return warnings
