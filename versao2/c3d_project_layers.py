# -*- coding: utf-8 -*-
"""Layer + archive I/O for .c3dproj projects (see c3d_project.py).

Archive = a zip of ``.npy`` entries readable by ``np.load``.  Each entry
picks its own compression: tomograms are STORED (deflating a multi-GB
float volume freezes the UI for minutes and saves little), everything else
(labels, meshes, strokes) is DEFLATED, which shrinks label volumes ~50x.

Every step is logged through ``log(msg, level, params, t0)`` (the same
signature as manu_seg_3d.log) so a failed save/open can be diagnosed from
the terminal alone.
"""

from __future__ import annotations

import os
import tempfile
import time
import traceback
import zipfile
from pathlib import Path
from typing import Callable, Dict, List, Optional

import numpy as np
from napari.layers import Image, Labels, Points, Shapes, Surface, Vectors

MRC_SUFFIXES = {".mrc", ".rec", ".st", ".map", ".mrcs", ".ali"}


def default_log(msg, level="INFO", params=None, t0=None):
    parts = [f"[{time.strftime('%H:%M:%S')}]", f"[{level}]", msg]
    if t0 is not None:
        parts.append(f"elapsed={time.time() - t0:.2f}s")
    if params:
        parts.append(", ".join(f"{k}={v}" for k, v in params.items()))
    print("  ".join(parts))


def tb_last(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"


def log_exception(log, msg, exc, params=None):
    """WARN line with the short reason, then the full traceback."""
    log(msg, level="WARN", params={**(params or {}), "error": tb_last(exc)})
    for line in traceback.format_exception(type(exc), exc, exc.__traceback__):
        for sub in line.rstrip().splitlines():
            print(f"      | {sub}")


def _mb(nbytes) -> str:
    return f"{nbytes / 1e6:.1f}MB"


def _f(seq):
    return [float(v) for v in seq]


def _cmap_name(layer):
    try:
        return str(layer.colormap.name)
    except Exception:
        return None


def compact_labels(a, name: str, log) -> np.ndarray:
    """Smallest unsigned dtype that holds every label value exactly.

    Label volumes arrive as uint32 (4 bytes/voxel) even when the largest
    label is 5; uint8 holds the same values in a quarter of the RAM/GPU
    memory.  Values are checked first, so nothing is ever clipped: a layer
    with negative or >65535 labels keeps its dtype."""
    a = np.asarray(a)
    if a.dtype.kind not in "ui" or a.size == 0:
        return a
    lo, hi = int(a.min()), int(a.max())
    if lo < 0:
        return a
    target = np.uint8 if hi <= 255 else np.uint16 if hi <= 65535 else a.dtype
    if np.dtype(target).itemsize >= a.dtype.itemsize:
        return a
    t0 = time.time()
    out = a.astype(target)
    log("  labels compacted (values unchanged)", t0=t0, params={
        "layer": name, "max_label": hi, "from": str(a.dtype), "to": str(out.dtype),
        "before": _mb(a.nbytes), "after": _mb(out.nbytes)})
    return out


def array_desc(a) -> dict:
    a = np.asarray(a)
    return {"shape": tuple(a.shape), "dtype": str(a.dtype), "size": _mb(a.nbytes)}


# ────────────────────────────────────────────────────────────────────────────
# archive
# ────────────────────────────────────────────────────────────────────────────

def write_archive(target: str, arrays: Dict[str, np.ndarray], stored: set, log) -> None:
    """Atomic write: build next to the target, then rename over it."""
    t0 = time.time()
    target = Path(target)
    fd, tmp = tempfile.mkstemp(suffix=".c3dproj.tmp", dir=str(target.parent))
    os.close(fd)
    small_n, small_bytes = 0, 0
    try:
        with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED,
                             compresslevel=1, allowZip64=True) as zf:
            for key, arr in arrays.items():
                arr = np.asanyarray(arr)
                info = zipfile.ZipInfo(key + ".npy", date_time=time.localtime()[:6])
                info.compress_type = zipfile.ZIP_STORED if key in stored else zipfile.ZIP_DEFLATED
                # ZipInfo uses __slots__; the level slot was renamed in 3.13
                for slot in ("compress_level", "_compresslevel"):
                    if slot in getattr(zipfile.ZipInfo, "__slots__", ()):
                        setattr(info, slot, 1)
                t1 = time.time()
                with zf.open(info, "w", force_zip64=True) as fh:
                    np.lib.format.write_array(fh, arr, allow_pickle=False)
                if arr.nbytes >= 1e6:
                    stored_size = zf.getinfo(key + ".npy").compress_size
                    log("  wrote array", t0=t1, params={
                        "key": key, **array_desc(arr),
                        "compression": "stored" if key in stored else "deflate",
                        "on_disk": _mb(stored_size)})
                else:
                    small_n += 1
                    small_bytes += arr.nbytes
        os.replace(tmp, target)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
    log("  wrote small arrays", params={"count": small_n, "total": _mb(small_bytes)})
    log("Archive written", t0=t0, params={"file": target.name,
                                         "file_size": _mb(target.stat().st_size)})


def read_archive(path: str, log) -> Dict[str, np.ndarray]:
    t0 = time.time()
    with np.load(path, allow_pickle=False) as npz:
        files = list(npz.files)
        z = {}
        for k in files:
            t1 = time.time()
            z[k] = npz[k]
            if z[k].nbytes >= 1e6:
                log("  read array", t0=t1, params={"key": k, **array_desc(z[k])})
    log("Archive read", t0=t0, params={"file": Path(path).name, "entries": len(files),
                                      "file_size": _mb(Path(path).stat().st_size)})
    return z


# ────────────────────────────────────────────────────────────────────────────
# save
# ────────────────────────────────────────────────────────────────────────────

def save_layer(layer, key: str, arrays, stored: set, embed_images: bool, log) -> Optional[dict]:
    e = dict(name=layer.name, visible=bool(layer.visible),
             opacity=float(layer.opacity), blending=str(layer.blending),
             scale=_f(layer.scale), translate=_f(layer.translate))

    if isinstance(layer, Image):
        e["type"] = "image"
        src = getattr(layer, "source", None)
        path = getattr(src, "path", None)
        reader = getattr(src, "reader_plugin", None)
        if path:
            e["path"] = str(Path(path).resolve())
            e["reader"] = reader
        data = layer.data[0] if getattr(layer, "multiscale", False) else layer.data
        if embed_images or not path or not Path(path).exists():
            t1 = time.time()
            arrays[f"{key}/data"] = np.asarray(data)
            stored.add(f"{key}/data")
            e["embedded"] = True
            log("  image data embedded", t0=t1, params={"layer": layer.name,
                                                         **array_desc(arrays[f"{key}/data"])})
        e.update(colormap=_cmap_name(layer), contrast_limits=_f(layer.contrast_limits),
                 gamma=float(layer.gamma), rendering=str(layer.rendering),
                 iso_threshold=float(getattr(layer, "iso_threshold", 0.5)),
                 attenuation=float(getattr(layer, "attenuation", 0.05)),
                 rgb=bool(getattr(layer, "rgb", False)),
                 multiscale=bool(getattr(layer, "multiscale", False)))
        detail = {"source_path": path, "reader": reader, "embedded": e.get("embedded", False),
                  "colormap": e["colormap"], "contrast": tuple(round(v, 4) for v in e["contrast_limits"]),
                  "rendering": e["rendering"], "multiscale": e["multiscale"]}
    elif isinstance(layer, Labels):
        e["type"] = "labels"
        arrays[f"{key}/data"] = compact_labels(layer.data, layer.name, log)
        e["rendering"] = str(getattr(layer, "rendering", "iso_categorical"))
        cdict = getattr(layer.colormap, "color_dict", None)
        if cdict:
            e["color_dict"] = [[None if k is None else int(k), _f(v)] for k, v in cdict.items()]
        detail = {"colormap": type(layer.colormap).__name__,
                  "n_colors": len(e.get("color_dict", [])), "rendering": e["rendering"]}
    elif isinstance(layer, Surface):
        e["type"] = "surface"
        for i, part in enumerate(layer.data):
            arrays[f"{key}/data{i}"] = np.asarray(part)
        e["n_parts"] = len(layer.data)
        vc = getattr(layer, "vertex_colors", None)
        if vc is not None:
            arrays[f"{key}/vertex_colors"] = np.asarray(vc)
        e.update(colormap=_cmap_name(layer), contrast_limits=_f(layer.contrast_limits),
                 gamma=float(layer.gamma), shading=str(layer.shading))
        detail = {"vertices": len(layer.data[0]), "faces": len(layer.data[1]),
                  "vertex_colors": vc is not None, "colormap": e["colormap"]}
    elif isinstance(layer, Points):
        e["type"] = "points"
        arrays[f"{key}/data"] = np.asarray(layer.data)
        arrays[f"{key}/size"] = np.asarray(layer.size, dtype=np.float32)
        arrays[f"{key}/face_color"] = np.asarray(layer.face_color)
        border = getattr(layer, "border_color", None)
        if border is None:
            border = getattr(layer, "edge_color", None)
        if border is not None:
            arrays[f"{key}/border_color"] = np.asarray(border)
        sym = np.atleast_1d(np.asarray(layer.symbol, dtype=object))
        e["symbol"] = str(getattr(sym[0], "value", sym[0])) if sym.size else "o"
        e["out_of_slice_display"] = bool(layer.out_of_slice_display)
        detail = {"points": len(layer.data), "symbol": e["symbol"]}
    elif isinstance(layer, Vectors):
        e["type"] = "vectors"
        arrays[f"{key}/data"] = np.asarray(layer.data)
        arrays[f"{key}/edge_color"] = np.asarray(layer.edge_color)
        e.update(edge_width=float(layer.edge_width), length=float(layer.length))
        detail = {"vectors": len(layer.data)}
    elif isinstance(layer, Shapes):
        e["type"] = "shapes"
        for i, d in enumerate(layer.data):
            arrays[f"{key}/shape{i}"] = np.asarray(d)
        e["n_shapes"] = len(layer.data)
        e["shape_type"] = [str(t) for t in layer.shape_type]
        arrays[f"{key}/edge_color"] = np.asarray(layer.edge_color)
        arrays[f"{key}/face_color"] = np.asarray(layer.face_color)
        e["edge_width"] = _f(layer.edge_width)
        detail = {"shapes": len(layer.data)}
    else:
        log("  layer SKIPPED (type not supported)", level="WARN",
            params={"layer": layer.name, "type": type(layer).__name__})
        return None

    data_key = f"{key}/data" if f"{key}/data" in arrays else None
    log("  layer saved", params={
        "layer": layer.name, "type": e["type"], "visible": e["visible"],
        "opacity": round(e["opacity"], 3), "blending": e["blending"],
        "scale": tuple(round(v, 4) for v in e["scale"]),
        "translate": tuple(round(v, 4) for v in e["translate"]),
        **({"data": array_desc(arrays[data_key])} if data_key else {}), **detail})
    return e


# ────────────────────────────────────────────────────────────────────────────
# open
# ────────────────────────────────────────────────────────────────────────────

def _common_kwargs(e):
    return dict(name=e["name"], visible=e["visible"], opacity=e["opacity"],
                blending=e["blending"], scale=e["scale"], translate=e["translate"])


def set_props(layer, props: dict, warnings: List[str], log):
    for k, v in props.items():
        if v is None:
            continue
        try:
            setattr(layer, k, v)
        except Exception as exc:
            msg = f"'{layer.name}': não restaurei {k}"
            warnings.append(f"{msg} ({tb_last(exc)})")
            log_exception(log, f"  property not restored: {k}", exc,
                          {"layer": layer.name, "value": v})


def resolve_moved_path(old: str, project_path: Optional[str], log) -> Optional[str]:
    """Find a file whose saved path no longer exists — e.g. a project saved
    on Windows (C:\\Users\\...\\OneDrive - Institut Pasteur Paris\\PAPERS\\...)
    and opened on a Mac (~/Library/CloudStorage/OneDrive-...\\PAPERS\\...).
    Tries every tail of the old path (…/PAPERS/x/y.mrc, …/x/y.mrc, y.mrc)
    under every folder above the project file; first hit wins."""
    from pathlib import PureWindowsPath, PurePosixPath
    parts = (PureWindowsPath(old) if ("\\" in old or ":" in old[:3]) else PurePosixPath(old)).parts
    parts = [p for p in parts if p not in ("\\", "/") and not p.endswith(":\\")]
    if not parts or project_path is None:
        return None
    for base in Path(project_path).resolve().parents:
        for i in range(len(parts)):
            cand = base.joinpath(*parts[i:])
            if cand.is_file():
                log("  moved file found automatically", params={
                    "old_path": old, "new_path": str(cand), "matched_tail": "/".join(parts[i:])})
                return str(cand)
    log("  automatic search did not find the file", level="WARN",
        params={"old_path": old, "searched_from": str(Path(project_path).parent)})
    return None


def _mrc_voxel_A(path) -> Optional[float]:
    try:
        import mrcfile
        with mrcfile.open(path, header_only=True, permissive=True) as m:
            vs = float(m.voxel_size.x)
        return vs if vs > 0 else None
    except Exception:
        return None


def _open_image_from_path(viewer, e, path, log):
    """Try every way to read a tomogram from disk; log each attempt."""
    attempts = []
    if e.get("reader"):
        attempts.append((f"napari reader '{e['reader']}'", lambda: viewer.open(path, plugin=e["reader"])))
    attempts.append(("napari (any compatible reader)", lambda: viewer.open(path)))
    if Path(path).suffix.lower() in MRC_SUFFIXES:
        def _mrc():
            import mrcfile
            with mrcfile.open(path, permissive=True) as m:
                data = np.asarray(m.data).copy()
            return [viewer.add_image(data, name=e["name"])]
        attempts.append(("mrcfile direct read", _mrc))

    for label, fn in attempts:
        t1 = time.time()
        try:
            layers = fn()
            if layers:
                log("  tomogram read from disk", t0=t1, params={
                    "layer": e["name"], "method": label, "path": path,
                    **array_desc(layers[0].data if not getattr(layers[0], "multiscale", False)
                                 else layers[0].data[0])})
                return layers
            log("  read attempt returned nothing", level="WARN",
                params={"layer": e["name"], "method": label})
        except Exception as exc:
            log_exception(log, "  read attempt FAILED", exc,
                          {"layer": e["name"], "method": label, "path": path})
    return None


def restore_layer(viewer, e, z, warnings, locate, log, project_path=None):
    key, kind = e["key"], e["type"]
    t0 = time.time()
    if kind == "image":
        if f"{key}/data" in z:
            layer = viewer.add_image(z[f"{key}/data"], rgb=e.get("rgb", False), **_common_kwargs(e))
            log("  tomogram restored from embedded data", params={
                "layer": e["name"], **array_desc(z[f"{key}/data"])})
        else:
            path = e.get("path")
            if path and not Path(path).exists():
                log("  tomogram path missing", level="WARN", params={"layer": e["name"], "path": path})
                found = resolve_moved_path(path, project_path, log)
                if found:
                    path = found
                elif locate is not None:
                    path = locate(e["name"], path)
                    log("  user located tomogram", params={"layer": e["name"], "new_path": path})
            layers = _open_image_from_path(viewer, e, path, log) if path and Path(path).exists() else None
            if not layers:
                msg = (f"Tomograma '{e['name']}' não pôde ser aberto ({e.get('path')}). "
                       f"Salve o projeto com 'Incluir tomogramas' ligado para não depender do arquivo.")
                warnings.append(msg)
                log("  layer NOT restored", level="ERROR", params={"layer": e["name"], "path": e.get("path")})
                return
            layer = layers[0]
            for extra in layers[1:]:
                viewer.layers.remove(extra)
            hdr = _mrc_voxel_A(path) if Path(path).suffix.lower() in MRC_SUFFIXES else None
            if hdr is not None and abs(hdr - e["scale"][-1]) > 1e-3 * max(hdr, 1):
                log("  header voxel size differs from the scale saved in the project — "
                    "using the saved one (the one your data was made with)", level="WARN",
                    params={"layer": e["name"], "header_A": round(hdr, 4),
                            "saved_scale": tuple(e["scale"])})
            set_props(layer, dict(name=e["name"], scale=e["scale"], translate=e["translate"],
                                  visible=e["visible"], opacity=e["opacity"],
                                  blending=e["blending"]), warnings, log)
        set_props(layer, dict(colormap=e.get("colormap"), contrast_limits=e["contrast_limits"],
                              gamma=e["gamma"], rendering=e["rendering"],
                              iso_threshold=e["iso_threshold"], attenuation=e["attenuation"]),
                  warnings, log)
    elif kind == "labels":
        data = compact_labels(z[f"{key}/data"], e["name"], log)   # older projects saved uint32
        z[f"{key}/data"] = None                                     # drop the wide copy
        layer = viewer.add_labels(data, **_common_kwargs(e))
        set_props(layer, dict(rendering=e.get("rendering")), warnings, log)
        if e.get("color_dict"):
            try:
                from napari.utils.colormaps import DirectLabelColormap
                layer.colormap = DirectLabelColormap(color_dict={k: tuple(v) for k, v in e["color_dict"]})
            except Exception as exc:
                warnings.append(f"'{e['name']}': cores dos labels não restauradas ({tb_last(exc)})")
                log_exception(log, "  label colours not restored", exc, {"layer": e["name"]})
    elif kind == "surface":
        data = tuple(z[f"{key}/data{i}"] for i in range(e["n_parts"]))
        layer = viewer.add_surface(data, **_common_kwargs(e))
        if f"{key}/vertex_colors" in z:
            set_props(layer, dict(vertex_colors=z[f"{key}/vertex_colors"]), warnings, log)
        set_props(layer, dict(colormap=e.get("colormap"), contrast_limits=e["contrast_limits"],
                              gamma=e["gamma"], shading=e["shading"]), warnings, log)
    elif kind == "points":
        layer = viewer.add_points(z[f"{key}/data"], size=z[f"{key}/size"],
                                  face_color=z[f"{key}/face_color"], symbol=e["symbol"],
                                  out_of_slice_display=e["out_of_slice_display"], **_common_kwargs(e))
        if f"{key}/border_color" in z:
            attr = "border_color" if hasattr(layer, "border_color") else "edge_color"
            set_props(layer, {attr: z[f"{key}/border_color"]}, warnings, log)
    elif kind == "vectors":
        layer = viewer.add_vectors(z[f"{key}/data"], edge_color=z[f"{key}/edge_color"],
                                   edge_width=e["edge_width"], length=e["length"], **_common_kwargs(e))
    elif kind == "shapes":
        data = [z[f"{key}/shape{i}"] for i in range(e["n_shapes"])]
        layer = viewer.add_shapes(data, shape_type=e["shape_type"], edge_width=e["edge_width"],
                                  edge_color=z[f"{key}/edge_color"], face_color=z[f"{key}/face_color"],
                                  **_common_kwargs(e))
    else:
        log("  unknown layer type in project — skipped", level="WARN",
            params={"layer": e["name"], "type": kind})
        return
    log("  layer restored", t0=t0, params={
        "layer": layer.name, "type": kind, "visible": layer.visible,
        "opacity": round(float(layer.opacity), 3), "blending": str(layer.blending),
        "scale": tuple(round(float(v), 4) for v in layer.scale),
        "translate": tuple(round(float(v), 4) for v in layer.translate),
        "ndim": layer.ndim})
