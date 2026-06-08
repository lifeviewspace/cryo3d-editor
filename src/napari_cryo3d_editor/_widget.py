# -*- coding: utf-8 -*-
"""
====================================================================
Cryo3D Editor  v3.0
====================================================================
napari plugin for 3D cryo-ET visualization, label post-processing,
and high-impact movie production.

Tabs:
  🧹 Dust    — hide/remove small objects (per-object erosion)
  ✂️ Erase   — 2D paint-mask eraser for Labels layers
  🎨 Colors  — per-label colour, opacity, merge, presets
  💡 Render  — lighting, contrast & membrane enhancement
  🎬 Movie   — keyframe-based 3D animation + Spin Movie

NEW in v3.0:
  • Skill-based layout: dark theme, style constants, helper factories
  • 💾 Save Snapshot — export current tomogram view as TIFF
  • 🌀 Spin Movie — automatic 360° rotation export (ChimeraX-style)
  • 💡 Render tab — ambient/directional lighting, gamma, contrast,
      membrane enhancement preset, blending mode controls

Autor: Kennedy Bonjour
====================================================================
"""

import napari
import numpy as np
from napari.layers import Labels, Image
from napari.utils.notifications import show_info, show_warning, show_error

from qtpy.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QComboBox, QSpinBox, QDoubleSpinBox, QProgressBar, QGroupBox,
    QCheckBox, QFileDialog, QTabWidget, QSlider, QListWidget,
    QListWidgetItem, QColorDialog, QAbstractItemView, QScrollArea,
    QSplitter, QFrame, QGridLayout, QSizePolicy, QApplication,
    QRadioButton, QButtonGroup, QToolButton, QMenu, QAction,
    QInputDialog, QMessageBox, QStackedWidget, QTextEdit
)
from qtpy.QtCore import Qt, Signal, QThread, QTimer, QSize
from qtpy.QtGui import QColor, QPixmap, QImage, QIcon

from pathlib import Path
from typing import List, Tuple, Optional, Dict, Any
from dataclasses import dataclass, field
import warnings
import traceback
import time
import os
import multiprocessing
import copy
import subprocess
import sys

from scipy import ndimage as ndi
from skimage.morphology import remove_small_objects, remove_small_holes
from skimage.measure import regionprops

warnings.filterwarnings("ignore")

# ====================================================================
# OPTIONAL DEPENDENCIES
# ====================================================================

try:
    import mrcfile
    HAS_MRCFILE = True
except ImportError:
    HAS_MRCFILE = False

try:
    from napari.utils.colormaps import DirectLabelColormap
    HAS_DIRECT_COLORMAP = True
except ImportError:
    HAS_DIRECT_COLORMAP = False

try:
    import imageio
    HAS_IMAGEIO = True
except ImportError:
    HAS_IMAGEIO = False

try:
    import tifffile
    HAS_TIFFFILE = True
except ImportError:
    HAS_TIFFFILE = False

# ====================================================================
# HARDWARE DETECTION
# ====================================================================

def _detect_cpu_count():
    """Number of CPUs actually available to this process.

    On Linux (e.g. HPC clusters with cgroup/affinity limits or
    resource oversubscription), os.sched_getaffinity reflects the real
    allocation, unlike multiprocessing.cpu_count() which reports all
    physical cores. Falls back to os.cpu_count() on macOS/Windows.
    """
    try:
        return len(os.sched_getaffinity(0))
    except AttributeError:
        return os.cpu_count() or 1


N_CPU = _detect_cpu_count()

try:
    import cupy as cp
    from cupyx.scipy import ndimage as cp_ndi
    HAS_CUPY = True
    try:
        GPU_NAME = cp.cuda.runtime.getDeviceProperties(0)['name'].decode()
    except Exception:
        GPU_NAME = "GPU"
except ImportError:
    HAS_CUPY = False
    GPU_NAME = None

_LOG_SESSION_START = time.time()

# ====================================================================
# STYLE CONSTANTS  (Skill: define once, use everywhere)
# ====================================================================

BG_DARK   = "#0d1520"
BG_MID    = "#111820"
BG_PANEL  = "#141e2c"
BG_HOVER  = "#1a2535"
BORDER    = "#2a3a4a"
TEXT_MAIN = "#b0c4de"
TEXT_DIM  = "#6a7d95"
TEXT_INFO = "#7fb3d3"
ACCENT    = "#2e86c1"
ACCENT2   = "#1a5276"
SUCCESS   = "#1e8449"
SUCCESS2  = "#145a32"
DANGER    = "#922b21"
DANGER2   = "#641e16"
WARN      = "#b7950b"
WARN2     = "#7d6608"

INPUT_STYLE = (
    f"background:{BG_DARK};color:{TEXT_MAIN};"
    f"border:1px solid {BORDER};border-radius:3px;padding:3px;"
)
GROUP_STYLE = (
    f"QGroupBox{{color:{TEXT_INFO};font-size:11px;font-weight:bold;"
    f"border:1px solid {BORDER};border-radius:4px;"
    f"margin-top:8px;padding-top:6px;background:{BG_PANEL};}}"
    f"QGroupBox::title{{subcontrol-origin:margin;left:8px;padding:0 4px;}}"
)
TAB_STYLE = (
    f"QTabWidget::pane{{border:1px solid {BORDER};background:{BG_MID};}}"
    f"QTabBar::tab{{background:{BG_PANEL};color:{TEXT_DIM};"
    f"border:1px solid {BORDER};border-bottom:none;"
    f"padding:4px 8px;border-radius:3px 3px 0 0;margin-right:2px;}}"
    f"QTabBar::tab:selected{{background:{BG_DARK};color:{TEXT_MAIN};"
    f"border-bottom:2px solid {ACCENT};}}"
    f"QTabBar::tab:hover{{background:{BG_HOVER};color:{TEXT_MAIN};}}"
)
SCROLL_STYLE = (
    f"QScrollArea{{background:{BG_MID};border:none;}}"
    f"QScrollBar:vertical{{background:{BG_MID};width:8px;border-radius:4px;}}"
    f"QScrollBar::handle:vertical{{background:{BORDER};border-radius:4px;min-height:20px;}}"
)
PROGRESS_STYLE = (
    f"QProgressBar{{border:1px solid {BORDER};border-radius:3px;"
    f"background:{BG_MID};height:16px;text-align:center;color:{TEXT_MAIN};}}"
    f"QProgressBar::chunk{{background:qlineargradient(x1:0,y1:0,x2:1,y2:0,"
    f"stop:0 {ACCENT2},stop:1 {ACCENT});border-radius:2px;}}"
)

# ====================================================================
# UI HELPER FACTORIES  (Skill pattern)
# ====================================================================

def _lbl(text, bold=False, color=TEXT_MAIN, size=None):
    w = QLabel(text)
    style = f"color:{color};"
    if bold:
        style += "font-weight:bold;"
    if size:
        style += f"font-size:{size}px;"
    w.setStyleSheet(style)
    return w


def _info(text):
    w = QLabel(text)
    w.setStyleSheet(f"color:{TEXT_DIM};font-size:11px;")
    w.setWordWrap(True)
    return w


def _btn(text, variant="secondary", icon=None):
    b = QPushButton(text)
    base = "border-radius:3px;padding:4px 10px;font-weight:bold;"
    styles = {
        "primary":   f"{base}background:{ACCENT2};color:#d6eaf8;border:1px solid {ACCENT};",
        "run":       f"{base}background:{SUCCESS2};color:#d5f5e3;border:1px solid {SUCCESS};font-size:13px;",
        "danger":    f"{base}background:{DANGER2};color:#f5b7b1;border:1px solid {DANGER};",
        "warning":   f"{base}background:{WARN2};color:#fef9e7;border:1px solid {WARN};",
        "secondary": f"{base}background:{BG_HOVER};color:{TEXT_DIM};border:1px solid {BORDER};",
        "blue":      f"{base}background:#1a3a6a;color:#aaddff;border:1px solid #2a5a9a;",
        "capture":   f"{base}background:#1a3a6a;color:#aaddff;border:1px solid #2a5a9a;font-size:12px;",
    }
    b.setStyleSheet(styles.get(variant, styles["secondary"]))
    return b


def _progress_row():
    bar = QProgressBar()
    bar.setRange(0, 100)
    bar.setValue(0)
    bar.setTextVisible(True)
    bar.setStyleSheet(PROGRESS_STYLE)
    stat = QLabel("Ready")
    stat.setStyleSheet(f"color:{TEXT_DIM};font-size:11px;")
    return bar, stat


def _info_box(text="—"):
    w = QLabel(text)
    w.setStyleSheet(
        f"color:{TEXT_INFO};background:{BG_DARK};border-radius:3px;"
        f"padding:6px;font-size:11px;font-family:monospace;"
    )
    w.setWordWrap(True)
    return w


def _group(title):
    g = QGroupBox(title)
    g.setStyleSheet(GROUP_STYLE)
    return g


def _scrollable(inner_widget):
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.NoFrame)
    scroll.setStyleSheet(SCROLL_STYLE)
    scroll.setWidget(inner_widget)
    outer = QWidget()
    lay = QVBoxLayout(outer)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.addWidget(scroll)
    return outer


def _slider(lo, hi, val, tick=1):
    s = QSlider(Qt.Horizontal)
    s.setRange(lo, hi)
    s.setValue(val)
    s.setTickInterval(tick)
    s.setStyleSheet(
        f"QSlider::groove:horizontal{{background:{BORDER};height:4px;border-radius:2px;}}"
        f"QSlider::handle:horizontal{{background:{ACCENT};width:12px;height:12px;"
        f"margin:-4px 0;border-radius:6px;}}"
    )
    return s


# ====================================================================
# LOGGING
# ====================================================================

def log(msg, level="INFO", params=None, t0: float = None):
    now = time.time()
    wall = time.strftime("%H:%M:%S")
    session_sec = int(now - _LOG_SESSION_START)
    s_mm = session_sec // 60
    s_ss = session_sec % 60
    session_tag = f"+{s_mm:02d}m{s_ss:02d}s"
    parts = [f"[{wall}]", f"[{session_tag}]", f"[{level}]", msg]
    if t0 is not None:
        elapsed = now - t0
        parts.append(f"elapsed={elapsed:.2f}s" if elapsed < 60 else f"elapsed={int(elapsed)//60}m{int(elapsed)%60:02d}s")
    if params:
        parts.append(", ".join(f"{k}={v}" for k, v in params.items()))
    print("  ".join(parts))


# ====================================================================
# MOVIE / FRAME HELPERS
# ====================================================================

def _normalize_frame(frame, target_hw=None):
    """Return an RGB uint8 frame with even H/W, optionally matched to
    target_hw=(H, W). Movie encoders (ffmpeg/H.264) require every frame
    to share the same size and even dimensions, otherwise the writer
    raises. napari screenshots can differ by a pixel between frames when
    the canvas re-renders, which is the #1 cause of export failures."""
    frame = np.asarray(frame)
    if frame.ndim == 2:
        frame = np.stack([frame] * 3, axis=-1)
    if frame.shape[2] == 4:          # drop alpha
        frame = frame[:, :, :3]
    if frame.dtype != np.uint8:
        frame = np.clip(frame, 0, 255).astype(np.uint8)

    h, w = frame.shape[:2]
    if target_hw is not None:
        th, tw = target_hw
        frame = frame[:th, :tw]
        h, w = frame.shape[:2]
        if h < th or w < tw:
            pad = np.zeros((th, tw, 3), dtype=np.uint8)
            pad[:h, :w] = frame
            frame = pad
    else:
        eh, ew = h - (h % 2), w - (w % 2)
        if (eh, ew) != (h, w):
            frame = frame[:eh, :ew]
    return np.ascontiguousarray(frame)


def _open_movie_writer(path, fmt, fps):
    """Create an imageio writer with player-compatible settings.
    MP4 -> H.264 + yuv420p so QuickTime/VLC/browsers can play it."""
    if fmt == "MP4":
        return imageio.get_writer(
            str(path), fps=fps, codec="libx264",
            macro_block_size=2, pixelformat="yuv420p",
            output_params=["-pix_fmt", "yuv420p"],
        )
    return imageio.get_writer(str(path), fps=max(10, fps), mode="I")


_HARDWARE_CHECKED = False

def check_hardware():
    import os, platform
    global _HARDWARE_CHECKED
    if _HARDWARE_CHECKED:
        return
    _HARDWARE_CHECKED = True
    print("\n" + "=" * 60)
    print("  HARDWARE CONFIGURATION")
    print("=" * 60)
    print(f"  CPU Cores: {N_CPU}")
    print(f"  GPU: {GPU_NAME + ' (CuPy)' if HAS_CUPY else 'Not available'}")
    print(f"  DirectLabelColormap: {'Yes' if HAS_DIRECT_COLORMAP else 'No'}")
    print(f"  imageio: {'Yes' if HAS_IMAGEIO else 'No'}")
    print(f"  tifffile: {'Yes' if HAS_TIFFFILE else 'No'}")

    # ── macOS Metal GPU Hang mitigation ──────────────────────────────
    # Large cryo-ET volumes (>512^3) can trigger Metal command buffer
    # completion errors (kIOGPUCommandBufferCallbackErrorHang) on Apple
    # Silicon and AMD GPUs. Setting the vispy backend to 'pyqt5' and
    # limiting the OpenGL context to software rendering fallback helps.
    if platform.system() == 'Darwin':
        # Match the vispy backend to the actually-installed Qt binding.
        # Hardcoding 'pyqt5' breaks Qt6 environments (napari >= 0.5 / 0.7).
        try:
            from qtpy import API_NAME
            _vispy_backend = {
                'PyQt5': 'pyqt5', 'PySide2': 'pyside2',
                'PyQt6': 'pyqt6', 'PySide6': 'pyside6',
            }.get(API_NAME)
            if _vispy_backend:
                os.environ.setdefault('VISPY_BACKEND', _vispy_backend)
        except Exception:
            pass
        # Limit Metal command buffer count to reduce GPU queue pressure
        os.environ.setdefault('MTL_MAX_COMMAND_BUFFER_COUNT', '32')
        # Disable GPU-accelerated compositing for the Qt window
        os.environ.setdefault('QT_MAC_WANTS_LAYER', '1')
        print("  macOS: Metal hang mitigations applied")
        print("  Tip: For large volumes (>512^3), use 2D mode or")
        print("       reduce canvas size to avoid GPU Hang errors.")

    print("=" * 60 + "\n")

# ====================================================================
# COLOR PRESETS
# ====================================================================

COLOR_PRESETS = {
    "Red":     (255, 0, 0, 255),
    "Green":   (0, 255, 0, 255),
    "Blue":    (0, 0, 255, 255),
    "Yellow":  (255, 255, 0, 255),
    "Cyan":    (0, 255, 255, 255),
    "Magenta": (255, 0, 255, 255),
    "Orange":  (255, 165, 0, 255),
    "Purple":  (128, 0, 128, 255),
    "White":   (255, 255, 255, 255),
    "Pink":    (255, 192, 203, 255),
    "Lime":    (50, 205, 50, 255),
    "Teal":    (0, 128, 128, 255),
    "Gold":    (255, 215, 0, 255),
    "Coral":   (255, 127, 80, 255),
}

# ====================================================================
# GPU-ACCELERATED HELPERS
# ====================================================================

def distance_transform_edt_auto(binary, use_gpu=False):
    if use_gpu and HAS_CUPY:
        try:
            dist_gpu = cp_ndi.distance_transform_edt(cp.asarray(binary))
            result = cp.asnumpy(dist_gpu)
            cp.get_default_memory_pool().free_all_blocks()
            return result
        except Exception as e:
            log(f"GPU EDT error, fallback to CPU: {e}", "WARN")
    return ndi.distance_transform_edt(binary)


def label_auto(binary, structure=None, use_gpu=False):
    if use_gpu and HAS_CUPY:
        try:
            labeled_gpu, n = cp_ndi.label(cp.asarray(binary))
            result = cp.asnumpy(labeled_gpu)
            cp.get_default_memory_pool().free_all_blocks()
            return result, int(n)
        except Exception as e:
            log(f"GPU label error, fallback to CPU: {e}", "WARN")
    return ndi.label(binary, structure=structure)

# ====================================================================
# CORE PROCESSING FUNCTIONS
# ====================================================================

def erode_by_percentage_per_object(mask, percentage, connectivity=1, min_size_after=0,
                                    progress_callback=None, abort_check=None, use_gpu=False):
    t0 = time.time()
    if percentage <= 0:
        return mask.copy()
    if percentage >= 100:
        return np.zeros_like(mask)
    struct = ndi.generate_binary_structure(3, connectivity)
    binary = mask > 0
    if progress_callback:
        progress_callback("Labeling...", 5)
    labeled, n = label_auto(binary, structure=struct, use_gpu=use_gpu)
    if n == 0:
        return mask.copy()
    log("Per-object erosion", params={"objects": n, "percentage": percentage})
    if progress_callback:
        progress_callback("Distance transform...", 15)
    dist = distance_transform_edt_auto(binary, use_gpu=use_gpu)
    if abort_check and abort_check():
        return np.zeros_like(mask)
    if progress_callback:
        progress_callback("Computing thresholds...", 50)
    labels_list = np.arange(1, n + 1)
    max_dists = ndi.maximum(dist, labeled, index=labels_list)
    max_dists_lut = np.zeros(n + 1, dtype=np.float32)
    max_dists_lut[labels_list] = max_dists
    thresholds = (percentage / 100.0) * max_dists_lut[labeled]
    thresholds = np.maximum(1.0, thresholds)
    if progress_callback:
        progress_callback("Applying erosion...", 75)
    survive = (dist > thresholds) & (labeled > 0)
    if min_size_after > 0:
        if progress_callback:
            progress_callback("Removing fragments...", 90)
        survive = remove_small_objects(survive, min_size=min_size_after, connectivity=connectivity)
    result = np.where(survive, mask, 0).astype(mask.dtype)
    log("Erosion done", t0=t0)
    return result


def analyze_objects_sync(mask, connectivity=1, voxel_size=1.0, progress_callback=None,
                         abort_check=None, use_gpu=False):
    t0 = time.time()
    struct = ndi.generate_binary_structure(3, connectivity)
    if progress_callback:
        progress_callback("Labeling...", 5)
    labeled, n = label_auto(mask > 0, structure=struct, use_gpu=use_gpu)
    if n == 0:
        return {'n_objects': 0, 'labeled': labeled, 'labels': [], 'volume': [], 'area': [], 'size': []}
    regions = regionprops(labeled)
    labels, volumes, areas, sizes = [], [], [], []
    for idx, r in enumerate(regions):
        if abort_check and abort_check():
            break
        if progress_callback and idx % 50 == 0:
            progress_callback(f"Object {idx+1}/{len(regions)}...", 10 + int(85 * idx / len(regions)))
        labels.append(r.label)
        volumes.append(r.area)
        bbox = r.bbox
        sizes.append(max(bbox[3]-bbox[0], bbox[4]-bbox[1], bbox[5]-bbox[2]))
        pad = 1
        sl = (slice(max(0, bbox[0]-pad), min(labeled.shape[0], bbox[3]+pad)),
              slice(max(0, bbox[1]-pad), min(labeled.shape[1], bbox[4]+pad)),
              slice(max(0, bbox[2]-pad), min(labeled.shape[2], bbox[5]+pad)))
        roi = labeled[sl] == r.label
        eroded = ndi.binary_erosion(roi, structure=struct)
        areas.append(roi.sum() - eroded.sum())
    log("Analysis complete", t0=t0, params={"n_objects": n})
    return {'n_objects': n, 'labeled': labeled, 'labels': labels,
            'volume': volumes, 'area': areas, 'size': sizes}


def apply_2d_mask_to_3d(seg_data, erase_mask, z_range=None):
    result = seg_data.copy()
    mask_2d = np.max(erase_mask, axis=0) > 0 if erase_mask.ndim == 3 else erase_mask > 0
    z0, z1 = (0, result.shape[0]) if z_range is None else (max(0, z_range[0]), min(result.shape[0], z_range[1]))
    result[z0:z1, mask_2d] = 0
    return result

# ====================================================================
# KEYFRAME DATA STRUCTURE
# ====================================================================

@dataclass
class Keyframe:
    camera: Dict[str, Any]
    dims: Dict[str, Any]
    layer_visibility: Dict[str, bool]
    layer_opacity: Dict[str, float]
    thumbnail: Optional[np.ndarray] = None
    name: str = ""
    duration: int = 60

    def copy(self):
        return Keyframe(
            camera=copy.deepcopy(self.camera),
            dims=copy.deepcopy(self.dims),
            layer_visibility=copy.deepcopy(self.layer_visibility),
            layer_opacity=copy.deepcopy(self.layer_opacity),
            thumbnail=self.thumbnail.copy() if self.thumbnail is not None else None,
            name=self.name,
            duration=self.duration,
        )

# ====================================================================
# PLUGIN STATE
# ====================================================================

class PluginState:
    MAX_HISTORY = 10

    def __init__(self, viewer: napari.Viewer):
        self.viewer = viewer
        self.voxel_nm = 1.0
        self.history: List[Tuple[str, np.ndarray]] = []
        self.history_idx = -1
        self.preview_layer = None
        self.erase_layer = None
        self.label_colors: Dict[str, Dict[int, Tuple[float, float, float, float]]] = {}
        self.label_opacities: Dict[str, Dict[int, float]] = {}

    def scale(self):
        # napari's MRC readers (e.g. napari-mrcfile-reader) set the layer
        # scale in Angstrom, straight from the MRC header. We match that so
        # plugin-loaded layers line up with File > Open layers and report the
        # same pixel size. voxel_nm stays in nm for volume/threshold maths.
        return (self.voxel_nm * 10.0,) * 3

    def rm(self, name):
        if self.viewer and name in self.viewer.layers:
            self.viewer.layers.remove(name)

    def get_labels(self):
        return [l for l in self.viewer.layers if isinstance(l, Labels)] if self.viewer else []

    def get_images(self):
        return [l for l in self.viewer.layers if isinstance(l, Image)] if self.viewer else []

    def get_all_layers(self):
        return list(self.viewer.layers) if self.viewer else []

    def get_labels_layer(self, name: str) -> Optional[Labels]:
        for l in self.viewer.layers:
            if l.name == name and isinstance(l, Labels):
                return l
        return None

    def get_image_layer(self, name: str) -> Optional[Image]:
        for l in self.viewer.layers:
            if l.name == name and isinstance(l, Image):
                return l
        return None

    def save_history(self, name, data):
        if self.history_idx < len(self.history) - 1:
            self.history = self.history[:self.history_idx + 1]
        self.history.append((name, data.copy()))
        self.history_idx = len(self.history) - 1
        while len(self.history) > self.MAX_HISTORY:
            self.history.pop(0)
            self.history_idx -= 1

    def can_undo(self):
        return self.history_idx >= 0

    def _rgba_int_to_float(self, rgba_int):
        return tuple(c / 255.0 for c in rgba_int)

    def _rgba_float_to_int(self, rgba_float):
        return tuple(int(c * 255) for c in rgba_float)

    def _ensure_colors_initialized(self, layer_name):
        """Give every existing label a colour the first time we touch this
        layer. Without this, switching to a DirectLabelColormap that only
        lists the edited label would make every OTHER label transparent
        (they vanish from the canvas)."""
        if not hasattr(self, "_color_init_done"):
            self._color_init_done = set()
        if layer_name in self._color_init_done:
            return
        self._color_init_done.add(layer_name)
        self.initialize_layer_colors(layer_name)

    def set_label_color(self, layer_name, label_value, color_rgba):
        self._ensure_colors_initialized(layer_name)
        if layer_name not in self.label_colors:
            self.label_colors[layer_name] = {}
        self.label_colors[layer_name][label_value] = self._rgba_int_to_float(color_rgba)
        self._apply_colormap(layer_name)

    def set_label_opacity(self, layer_name, label_value, opacity):
        if layer_name not in self.label_opacities:
            self.label_opacities[layer_name] = {}
        self.label_opacities[layer_name][label_value] = opacity
        if layer_name in self.label_colors and label_value in self.label_colors[layer_name]:
            r, g, b, _ = self.label_colors[layer_name][label_value]
            self.label_colors[layer_name][label_value] = (r, g, b, opacity)
            self._apply_colormap(layer_name)

    def get_label_color(self, layer_name, label_value):
        color_float = self.label_colors.get(layer_name, {}).get(label_value)
        if color_float:
            return self._rgba_float_to_int(color_float)
        return None

    def get_label_opacity(self, layer_name, label_value):
        return self.label_opacities.get(layer_name, {}).get(label_value, 1.0)

    def _apply_colormap(self, layer_name):
        layer = self.get_labels_layer(layer_name)
        if layer is None:
            return
        colors = self.label_colors.get(layer_name, {})
        if not colors:
            return
        if HAS_DIRECT_COLORMAP:
            # `None` is the fallback colour for any label not explicitly
            # listed. We keep it transparent only for value 0 (background);
            # all real labels are filled in by _ensure_colors_initialized so
            # nothing disappears when a single label is recoloured.
            color_dict = {0: (0, 0, 0, 0), None: (0, 0, 0, 0)}
            color_dict.update(colors)
            try:
                layer.colormap = DirectLabelColormap(color_dict=color_dict)
                return
            except Exception:
                pass
        # Legacy fallback (napari <= 0.4.x); Labels.color removed in 0.5+.
        try:
            layer.color = {k: self._rgba_float_to_int(v) for k, v in colors.items()}
        except Exception:
            pass

    def reset_colors(self, layer_name):
        self.label_colors.pop(layer_name, None)
        self.label_opacities.pop(layer_name, None)
        layer = self.get_labels_layer(layer_name)
        if layer is None:
            return
        # napari 0.7 removed the 'auto' string shortcut for Labels
        # colormaps (it now tries to read it as a color sequence and
        # raises KeyError: 'colors'). Regenerate a fresh cyclic colormap
        # instead, with fallbacks across napari versions.
        try:
            from napari.utils.colormaps import label_colormap
            layer.colormap = label_colormap(49)
        except Exception:
            try:
                layer.new_colormap()          # napari >= 0.4.19
            except Exception:
                try:
                    layer.colormap = 'auto'   # legacy napari <= 0.4.18
                except Exception:
                    pass

    def initialize_layer_colors(self, layer_name):
        layer = self.get_labels_layer(layer_name)
        if layer is None:
            return
        # Avoid boolean fancy-indexing (layer.data[layer.data>0]) which
        # allocates a full-size copy of huge tomograms; filter the small
        # unique array instead.
        uniq = np.unique(layer.data)
        existing_labels = set(int(v) for v in uniq if v > 0)
        if not existing_labels:
            return
        if layer_name not in self.label_colors:
            self.label_colors[layer_name] = {}
        from napari.utils.colormaps import label_colormap
        cmap = label_colormap(49)
        for lbl in sorted(existing_labels):
            if lbl not in self.label_colors[layer_name]:
                rgba = cmap.map(lbl % 49)
                if hasattr(rgba, '__iter__') and len(rgba) >= 4:
                    self.label_colors[layer_name][lbl] = tuple(float(c) for c in rgba[:4])
                else:
                    self.label_colors[layer_name][lbl] = (1.0, 1.0, 1.0, 1.0)
        self._apply_colormap(layer_name)


# ====================================================================
# WORKER THREADS  (Skill: QThread with progress/finished/error)
# ====================================================================

class AnalysisWorker(QThread):
    finished = Signal(dict)
    error    = Signal(str)
    progress = Signal(str, int)

    def __init__(self, mask, connectivity, voxel_size, use_gpu):
        super().__init__()
        self.mask, self.connectivity = mask, connectivity
        self.voxel_size, self.use_gpu = voxel_size, use_gpu
        self._abort = False

    def abort(self):
        self._abort = True

    def run(self):
        try:
            stats = analyze_objects_sync(self.mask, self.connectivity, self.voxel_size,
                                         self.progress.emit, lambda: self._abort, self.use_gpu)
            if not self._abort:
                self.progress.emit("Done!", 100)
                self.finished.emit(stats)
        except Exception as e:
            self.error.emit(traceback.format_exc())


class ErosionWorker(QThread):
    finished = Signal(np.ndarray, int, int)
    error    = Signal(str)
    progress = Signal(str, int)

    def __init__(self, mask, percentage, connectivity, min_size_after, use_gpu):
        super().__init__()
        self.mask, self.percentage, self.connectivity = mask, percentage, connectivity
        self.min_size_after, self.use_gpu = min_size_after, use_gpu
        self._abort = False

    def abort(self):
        self._abort = True

    def run(self):
        try:
            before = np.count_nonzero(self.mask)
            result = erode_by_percentage_per_object(
                self.mask, self.percentage, self.connectivity,
                self.min_size_after, self.progress.emit,
                lambda: self._abort, self.use_gpu)
            if not self._abort:
                self.progress.emit("Done!", 100)
                self.finished.emit(result, before, np.count_nonzero(result))
        except Exception as e:
            self.error.emit(traceback.format_exc())


class CleaningWorker(QThread):
    finished = Signal(np.ndarray, int, int)
    error    = Signal(str)
    progress = Signal(str, int)

    def __init__(self, mask, threshold, metric, connectivity, fill_holes, hole_size,
                 voxel_size, min_volume, use_gpu):
        super().__init__()
        self.mask, self.threshold, self.metric = mask, threshold, metric
        self.connectivity, self.fill_holes = connectivity, fill_holes
        self.hole_size, self.voxel_size = hole_size, voxel_size
        self.min_volume, self.use_gpu = min_volume, use_gpu
        self._abort = False

    def abort(self):
        self._abort = True

    def run(self):
        try:
            before = np.count_nonzero(self.mask)
            stats = analyze_objects_sync(
                self.mask, self.connectivity, self.voxel_size,
                lambda m, p: self.progress.emit(m, int(p * 0.4)),
                lambda: self._abort, self.use_gpu)
            if self._abort or stats['n_objects'] == 0:
                if not self._abort:
                    self.finished.emit(self.mask.copy(), before, before)
                return
            labeled = stats['labeled']
            labels  = np.array(stats['labels'])
            volumes = np.array(stats['volume'])
            if self.metric == 'volume':
                keep_mask = volumes >= self.threshold
            elif self.metric == 'area':
                keep_mask = np.array(stats['area']) >= self.threshold
            elif self.metric == 'size':
                keep_mask = np.array(stats['size']) >= self.threshold
            elif 'rank' in self.metric:
                base = self.metric.replace('_rank', '')
                values = np.array(stats[base])
                n_keep = min(int(self.threshold), len(labels))
                keep_mask = np.zeros(len(labels), dtype=bool)
                keep_mask[np.argsort(values)[::-1][:n_keep]] = True
                if self.min_volume:
                    keep_mask &= (volumes >= self.min_volume)
            else:
                keep_mask = volumes >= self.threshold
            self.progress.emit("Building result...", 60)
            keep_lut = np.zeros(int(labeled.max()) + 1, dtype=bool)
            for lbl in labels[keep_mask]:
                keep_lut[lbl] = True
            result = np.where(keep_lut[labeled], self.mask, 0).astype(self.mask.dtype)
            if self.fill_holes and result.max() > 0:
                self.progress.emit("Filling holes...", 80)
                binary = result > 0
                filled = remove_small_holes(binary, area_threshold=self.hole_size,
                                            connectivity=self.connectivity)
                result = np.where(filled & ~binary, 1, result)
            self.progress.emit("Done!", 100)
            self.finished.emit(result, before, np.count_nonzero(result))
        except Exception as e:
            self.error.emit(traceback.format_exc())


from qtpy.QtCore import QObject

class SpinMovieController(QObject):
    """
    Generates a 360° rotation movie entirely on the main thread using a
    QTimer, so that viewer.screenshot() (which requires an active OpenGL
    context) is always called from the GUI thread.
    """
    progress = Signal(int, str)
    finished = Signal(str)
    error    = Signal(str)

    def __init__(self, viewer, output_path, n_frames, fps, axis, fmt, parent=None):
        super().__init__(parent)
        self.viewer      = viewer
        self.output_path = output_path
        self.n_frames    = n_frames
        self.fps         = fps
        self.axis        = axis
        self.fmt         = fmt
        self._abort      = False
        self._frame_idx  = 0
        self._writer     = None
        self._orig_angles = None
        self._path       = None
        self._t0         = None
        self._target_hw  = None
        self._timer      = QTimer(self)
        self._timer.timeout.connect(self._step)

    def abort(self):
        self._abort = True

    def isRunning(self):
        return self._timer.isActive()

    def start(self):
        if not HAS_IMAGEIO:
            self.error.emit("imageio not installed. Run: pip install imageio imageio-ffmpeg")
            return
        self._path = Path(self.output_path)
        self._orig_angles = np.array(self.viewer.camera.angles).copy()
        self._frame_idx = 0
        self._abort = False
        self._target_hw = None
        self._t0 = time.perf_counter()
        try:
            if self.fmt in ("MP4", "GIF"):
                self._writer = _open_movie_writer(self._path, self.fmt, self.fps)
            else:
                self._path.mkdir(parents=True, exist_ok=True)
                self._writer = None
        except Exception as e:
            self.error.emit(traceback.format_exc())
            return
        log("SpinMovie START", params={"frames": self.n_frames,
                                        "axis": self.axis, "fmt": self.fmt})
        # Interval: give the viewer 80 ms per frame to render before screenshot
        self._timer.start(80)

    def _step(self):
        if self._abort:
            self._finish(aborted=True)
            return
        i = self._frame_idx
        if i >= self.n_frames:
            self._finish(aborted=False)
            return
        try:
            # Rotate camera
            angles = self._orig_angles.copy()
            delta  = i * (360.0 / self.n_frames)
            if self.axis == 'Y':
                angles[1] = (self._orig_angles[1] + delta) % 360
            elif self.axis == 'X':
                angles[0] = (self._orig_angles[0] + delta) % 360
            else:
                angles[2] = (self._orig_angles[2] + delta) % 360
            self.viewer.camera.angles = tuple(float(a) for a in angles)
            QApplication.processEvents()

            # Capture frame (safe: we are on the main/GUI thread)
            raw = self.viewer.screenshot(canvas_only=True)
            if self._target_hw is None:
                frame = _normalize_frame(raw)
                self._target_hw = frame.shape[:2]
            else:
                frame = _normalize_frame(raw, self._target_hw)

            if self.fmt in ("MP4", "GIF"):
                self._writer.append_data(frame)
            else:
                if HAS_TIFFFILE:
                    import tifffile as tf
                    tf.imwrite(str(self._path / f"spin_{i:04d}.tif"), frame)
                elif HAS_IMAGEIO:
                    imageio.imwrite(str(self._path / f"spin_{i:04d}.png"), frame)

            self._frame_idx += 1
            pct = int(100 * self._frame_idx / self.n_frames)
            self.progress.emit(pct, f"Frame {self._frame_idx}/{self.n_frames}")
        except Exception:
            self._timer.stop()
            self.error.emit(traceback.format_exc())

    def _finish(self, aborted=False):
        self._timer.stop()
        # Restore camera
        if self._orig_angles is not None:
            self.viewer.camera.angles = tuple(float(a) for a in self._orig_angles)
        if self._writer is not None:
            try:
                self._writer.close()
            except Exception:
                pass
        if not aborted:
            log("SpinMovie DONE", t0=self._t0,
                params={"output": str(self._path)})
            self.finished.emit(str(self._path))
        else:
            self.progress.emit(0, "Cancelled")


# Keep a thin alias so existing code that references SpinMovieWorker still works
SpinMovieWorker = SpinMovieController


# ====================================================================
# 🧹 DUST TAB
# ====================================================================

class HideDustTab(QWidget):
    def __init__(self, state: PluginState):
        super().__init__()
        self.state = state
        self._worker = None
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout()
        layout.setSpacing(6)
        self.setStyleSheet(f"background:{BG_MID};")

        # ── 1. LOAD & SELECT ──────────────────────────────────────────
        g1 = _group("1 ▸ LOAD & SELECT")
        l1 = QVBoxLayout()
        btn_load = _btn("📂  Load Segmentation…", "primary")
        btn_load.clicked.connect(self._load_file)
        l1.addWidget(btn_load)
        self.label_file = _info("No file loaded")
        l1.addWidget(self.label_file)

        row = QHBoxLayout()
        row.addWidget(_lbl("Layer:"))
        self.combo_layer = QComboBox()
        self.combo_layer.setStyleSheet(INPUT_STYLE)
        self.combo_layer.currentTextChanged.connect(self._sync_voxel_from_layer)
        row.addWidget(self.combo_layer)
        btn_r = _btn("↻", "secondary")
        btn_r.setFixedWidth(30)
        btn_r.clicked.connect(self._refresh_layers)
        row.addWidget(btn_r)
        l1.addLayout(row)

        row = QHBoxLayout()
        row.addWidget(_lbl("Voxel (nm):"))
        self.spin_voxel = QDoubleSpinBox()
        self.spin_voxel.setRange(0.01, 100)
        self.spin_voxel.setValue(1.0)
        self.spin_voxel.setStyleSheet(INPUT_STYLE)
        self.spin_voxel.valueChanged.connect(lambda v: setattr(self.state, 'voxel_nm', v))
        row.addWidget(self.spin_voxel)
        l1.addLayout(row)
        g1.setLayout(l1)
        layout.addWidget(g1)

        # ── 2. PERFORMANCE ────────────────────────────────────────────
        g2 = _group("2 ▸ PERFORMANCE")
        l2 = QHBoxLayout()
        self.chk_gpu = QCheckBox("Use GPU")
        self.chk_gpu.setEnabled(HAS_CUPY)
        self.chk_gpu.setStyleSheet(f"color:{TEXT_MAIN};")
        l2.addWidget(self.chk_gpu)
        l2.addWidget(_info(f"({N_CPU} cores)"))
        g2.setLayout(l2)
        layout.addWidget(g2)

        # ── 3. ERODE THICKNESS ────────────────────────────────────────
        g3 = _group("3 ▸ ERODE THICKNESS")
        l3 = QVBoxLayout()
        row = QHBoxLayout()
        row.addWidget(_lbl("Erode %:"))
        self.spin_erode = QDoubleSpinBox()
        self.spin_erode.setRange(0, 99)
        self.spin_erode.setSingleStep(5)
        self.spin_erode.setStyleSheet(INPUT_STYLE)
        row.addWidget(self.spin_erode)
        l3.addLayout(row)
        row = QHBoxLayout()
        self.chk_rm_small = QCheckBox("Remove if <")
        self.chk_rm_small.setChecked(True)
        self.chk_rm_small.setStyleSheet(f"color:{TEXT_MAIN};")
        row.addWidget(self.chk_rm_small)
        self.spin_min_size = QSpinBox()
        self.spin_min_size.setRange(0, 1000000)
        self.spin_min_size.setValue(1000)
        self.spin_min_size.setStyleSheet(INPUT_STYLE)
        row.addWidget(self.spin_min_size)
        row.addWidget(_lbl("vox"))
        l3.addLayout(row)
        row = QHBoxLayout()
        btn_ep = _btn("👁  Preview", "secondary")
        btn_ep.clicked.connect(self._preview_erosion)
        row.addWidget(btn_ep)
        btn_ea = _btn("✓  Apply", "run")
        btn_ea.clicked.connect(self._apply_erosion)
        row.addWidget(btn_ea)
        l3.addLayout(row)
        g3.setLayout(l3)
        layout.addWidget(g3)

        # ── 4. HIDE DUST ──────────────────────────────────────────────
        g4 = _group("4 ▸ HIDE DUST")
        l4 = QVBoxLayout()
        row = QHBoxLayout()
        row.addWidget(_lbl("Based on:"))
        self.combo_metric = QComboBox()
        self.combo_metric.addItems(["volume", "area", "size", "volume rank", "area rank", "size rank"])
        self.combo_metric.setStyleSheet(INPUT_STYLE)
        self.combo_metric.currentTextChanged.connect(self._on_metric_changed)
        row.addWidget(self.combo_metric)
        l4.addLayout(row)
        row = QHBoxLayout()
        self.label_thresh = _lbl("Min volume:")
        row.addWidget(self.label_thresh)
        self.spin_thresh = QSpinBox()
        self.spin_thresh.setRange(1, 10000000)
        self.spin_thresh.setValue(5000)
        self.spin_thresh.setStyleSheet(INPUT_STYLE)
        row.addWidget(self.spin_thresh)
        l4.addLayout(row)
        row = QHBoxLayout()
        self.chk_minvol = QCheckBox("+min vol:")
        self.chk_minvol.setStyleSheet(f"color:{TEXT_MAIN};")
        row.addWidget(self.chk_minvol)
        self.spin_minvol = QSpinBox()
        self.spin_minvol.setRange(1, 10000000)
        self.spin_minvol.setValue(10000)
        self.spin_minvol.setEnabled(False)
        self.spin_minvol.setStyleSheet(INPUT_STYLE)
        self.chk_minvol.toggled.connect(self.spin_minvol.setEnabled)
        row.addWidget(self.spin_minvol)
        row.addWidget(_lbl("Conn:"))
        self.combo_conn = QComboBox()
        self.combo_conn.addItems(["6", "18", "26"])
        self.combo_conn.setStyleSheet(INPUT_STYLE)
        row.addWidget(self.combo_conn)
        l4.addLayout(row)
        row = QHBoxLayout()
        self.chk_fill = QCheckBox("Fill holes <")
        self.chk_fill.setStyleSheet(f"color:{TEXT_MAIN};")
        row.addWidget(self.chk_fill)
        self.spin_hole = QSpinBox()
        self.spin_hole.setRange(1, 1000000)
        self.spin_hole.setValue(1000)
        self.spin_hole.setStyleSheet(INPUT_STYLE)
        row.addWidget(self.spin_hole)
        row.addWidget(_lbl("vox"))
        l4.addLayout(row)
        row = QHBoxLayout()
        btn_an = _btn("📊  Analyze", "secondary")
        btn_an.clicked.connect(self._analyze)
        row.addWidget(btn_an)
        btn_dp = _btn("👁  Preview", "secondary")
        btn_dp.clicked.connect(self._preview_dust)
        row.addWidget(btn_dp)
        btn_da = _btn("✓  Apply", "run")
        btn_da.clicked.connect(self._apply_dust)
        row.addWidget(btn_da)
        l4.addLayout(row)
        g4.setLayout(l4)
        layout.addWidget(g4)

        # ── STATUS ────────────────────────────────────────────────────
        g5 = _group("STATUS")
        l5 = QVBoxLayout()
        self.label_stats = _info_box("—")
        l5.addWidget(self.label_stats)
        self.progress, self.label_status = _progress_row()
        self.progress.setStyleSheet(PROGRESS_STYLE)
        l5.addWidget(self.progress)
        l5.addWidget(self.label_status)
        row = QHBoxLayout()
        self.btn_undo = _btn("↶  Undo", "warning")
        self.btn_undo.clicked.connect(self._undo)
        self.btn_undo.setEnabled(False)
        row.addWidget(self.btn_undo)
        self.btn_cancel = _btn("✕  Cancel", "danger")
        self.btn_cancel.clicked.connect(self._cancel)
        self.btn_cancel.setEnabled(False)
        row.addWidget(self.btn_cancel)
        l5.addLayout(row)
        g5.setLayout(l5)
        layout.addWidget(g5)

        layout.addStretch()
        self.setLayout(layout)
        self._refresh_layers()

    # ── Helpers ───────────────────────────────────────────────────────

    def _refresh_layers(self):
        self.combo_layer.clear()
        layers = [l.name for l in self.state.get_labels()
                  if not l.name.endswith('_preview') and l.name != 'Erase_Mask']
        self.combo_layer.addItems(layers if layers else ["—"])

    def _get_layer(self):
        name = self.combo_layer.currentText()
        return self.state.get_labels_layer(name) if name and name != "—" else None

    def _sync_voxel_from_layer(self, name=None):
        """Read the pixel size from the selected layer's napari scale.

        napari / its MRC readers store the scale in Angstrom, so we divide
        by 10 to get nm. This keeps the plugin in sync with layers opened
        via File > Open (otherwise voxel size would stay at the 1.0 default)."""
        layer = self._get_layer()
        if layer is None:
            return
        try:
            sc = [float(s) for s in np.atleast_1d(layer.scale) if float(s) > 0]
            if not sc:
                return
            voxel_nm = (sum(sc) / len(sc)) / 10.0   # Angstrom -> nm, mean of axes
            if voxel_nm <= 0 or abs(voxel_nm - self.state.voxel_nm) < 1e-6:
                return
            self.state.voxel_nm = voxel_nm
            self.spin_voxel.blockSignals(True)
            self.spin_voxel.setValue(round(voxel_nm, 4))
            self.spin_voxel.blockSignals(False)
        except Exception:
            pass

    def _on_metric_changed(self, text):
        is_rank = 'rank' in text
        self.label_thresh.setText("Top N:" if is_rank else f"Min {text}:")

    def _load_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Load Segmentation",
                                               "", "Seg Files (*.mrc *.tif *.tiff *.npy);;All (*)")
        if not path:
            return
        try:
            p = Path(path)
            pixel_nm = None   # will be set if metadata found

            if p.suffix in ('.tif', '.tiff'):
                if HAS_TIFFFILE:
                    import tifffile as tf
                    tif = tf.TiffFile(path)
                    data = tif.asarray()
                    # Try to read pixel size from ImageJ / OME / XResolution metadata
                    try:
                        page = tif.pages[0]
                        tags = page.tags
                        # ImageJ metadata (resolution in pixels/unit)
                        if tif.is_imagej:
                            ij = tif.imagej_metadata or {}
                            unit = ij.get('unit', '').lower()
                            # XResolution tag: pixels per unit
                            if 'XResolution' in tags:
                                xres = tags['XResolution'].value
                                if isinstance(xres, tuple) and xres[1] != 0:
                                    res = xres[0] / xres[1]   # pixels/unit
                                    if res > 0:
                                        nm_per_px = 1.0 / res
                                        # Convert to nm based on unit
                                        if unit in ('um', 'micron', 'micrometer', '\u00b5m'):
                                            nm_per_px *= 1000
                                        elif unit in ('cm',):
                                            nm_per_px *= 1e7
                                        elif unit in ('m',):
                                            nm_per_px *= 1e9
                                        elif unit in ('angstrom', '\u00c5', 'a'):
                                            nm_per_px *= 0.1
                                        # else assume nm already
                                        pixel_nm = nm_per_px
                        # OME-TIFF: PhysicalSizeX in OME XML
                        elif tif.is_ome:
                            import xml.etree.ElementTree as ET
                            ome_xml = tif.ome_metadata
                            if ome_xml:
                                root = ET.fromstring(ome_xml)
                                ns = root.tag.split('}')[0].lstrip('{') if '}' in root.tag else ''
                                prefix = f'{{{ns}}}' if ns else ''
                                px_el = root.find(f'.//{prefix}Pixels')
                                if px_el is not None:
                                    psx = px_el.get('PhysicalSizeX')
                                    psx_unit = px_el.get('PhysicalSizeXUnit', 'nm')
                                    if psx:
                                        val = float(psx)
                                        unit = psx_unit.lower()
                                        if unit in ('um', '\u00b5m', 'micrometer'):
                                            val *= 1000
                                        elif unit in ('angstrom', '\u00c5', 'a'):
                                            val *= 0.1
                                        elif unit in ('m',):
                                            val *= 1e9
                                        pixel_nm = val
                    except Exception:
                        pass
                else:
                    import imageio as iio
                    data = np.array(iio.volread(path))

            elif p.suffix == '.npy':
                data = np.load(path)

            elif p.suffix == '.mrc' and HAS_MRCFILE:
                with mrcfile.open(path, permissive=True) as mrc:
                    data = mrc.data.copy()
                    # MRC voxel size: voxel_size.x in Angstroms
                    try:
                        vx = float(mrc.voxel_size.x)
                        if vx > 0:
                            pixel_nm = vx / 10.0   # Angstrom -> nm
                    except Exception:
                        pass
            else:
                show_error(f"Unsupported format: {p.suffix}")
                return

            # Apply detected pixel size
            if pixel_nm and pixel_nm > 0:
                self.state.voxel_nm = pixel_nm
                self.spin_voxel.blockSignals(True)
                self.spin_voxel.setValue(round(pixel_nm, 4))
                self.spin_voxel.blockSignals(False)
                show_info(f"Pixel size read from file: {pixel_nm:.4f} nm")

            name = p.stem
            existing = {l.name for l in self.state.viewer.layers}
            if name in existing:
                name = f"{name}_2"
            self.state.viewer.add_labels(data.astype(np.int32), name=name,
                                          scale=self.state.scale())
            self.label_file.setText(
                f"{p.name}  [{self.state.voxel_nm:.4f} nm/vox]")
            self._refresh_layers()
            idx = self.combo_layer.findText(name)
            if idx >= 0:
                self.combo_layer.setCurrentIndex(idx)
            log(f"Loaded: {p.name}", params={"shape": data.shape,
                                              "pixel_nm": self.state.voxel_nm})
        except Exception as e:
            show_error(str(e))

    def _cancel(self):
        if self._worker and self._worker.isRunning():
            self._worker.abort()
            self._worker.wait()
        self.btn_cancel.setEnabled(False)
        self.label_status.setText("Cancelled")

    def _undo(self):
        if self.state.can_undo():
            name, data = self.state.history[self.state.history_idx]
            self.state.history_idx -= 1
            layer = self.state.get_labels_layer(name)
            if layer:
                layer.data = data
            self.btn_undo.setEnabled(self.state.can_undo())

    def _run_worker(self, worker):
        self._worker = worker
        worker.progress.connect(lambda m, p: (self.label_status.setText(m), self.progress.setValue(p)))
        worker.error.connect(lambda e: (show_error(e[:300]), self.btn_cancel.setEnabled(False)))
        self.btn_cancel.setEnabled(True)
        worker.start()

    def _preview_erosion(self):
        layer = self._get_layer()
        if not layer:
            return show_warning("Select a layer first")
        pct = self.spin_erode.value()
        min_s = self.spin_min_size.value() if self.chk_rm_small.isChecked() else 0
        conn = int(self.combo_conn.currentText()) if hasattr(self, 'combo_conn') else 6
        connectivity = {6: 1, 18: 2, 26: 3}.get(conn, 1)
        worker = ErosionWorker(layer.data.copy(), pct, connectivity, min_s,
                               self.chk_gpu.isChecked())
        def on_done(result, before, after):
            self.state.rm(layer.name + "_preview")
            existing = {l.name for l in self.state.viewer.layers}
            pname = layer.name + "_preview"
            self.state.viewer.add_labels(result, name=pname, scale=self.state.scale(), opacity=0.6)
            self.label_stats.setText(f"Preview: {before:,} → {after:,} vox")
            self.btn_cancel.setEnabled(False)
        worker.finished.connect(on_done)
        self._run_worker(worker)

    def _apply_erosion(self):
        layer = self._get_layer()
        if not layer:
            return show_warning("Select a layer first")
        pct = self.spin_erode.value()
        min_s = self.spin_min_size.value() if self.chk_rm_small.isChecked() else 0
        conn = int(self.combo_conn.currentText()) if hasattr(self, 'combo_conn') else 6
        connectivity = {6: 1, 18: 2, 26: 3}.get(conn, 1)
        self.state.save_history(layer.name, layer.data)
        worker = ErosionWorker(layer.data.copy(), pct, connectivity, min_s,
                               self.chk_gpu.isChecked())
        def on_done(result, before, after):
            layer.data = result
            self.state.rm(layer.name + "_preview")
            self.label_stats.setText(f"Eroded: {before:,} → {after:,} vox")
            self.btn_undo.setEnabled(True)
            self.btn_cancel.setEnabled(False)
        worker.finished.connect(on_done)
        self._run_worker(worker)

    def _analyze(self):
        layer = self._get_layer()
        if not layer:
            return show_warning("Select a layer first")
        conn = int(self.combo_conn.currentText())
        connectivity = {6: 1, 18: 2, 26: 3}.get(conn, 1)
        worker = AnalysisWorker(layer.data.copy(), connectivity,
                                self.state.voxel_nm, self.chk_gpu.isChecked())
        def on_done(stats):
            n = stats['n_objects']
            vols = stats['volume']
            if vols:
                self.label_stats.setText(
                    f"Objects: {n}  |  Min: {min(vols):,}  |  Max: {max(vols):,}  |  Median: {int(np.median(vols)):,} vox")
            else:
                self.label_stats.setText("No objects found")
            self.btn_cancel.setEnabled(False)
        worker.finished.connect(on_done)
        self._run_worker(worker)

    def _preview_dust(self):
        layer = self._get_layer()
        if not layer:
            return show_warning("Select a layer first")
        conn = int(self.combo_conn.currentText())
        connectivity = {6: 1, 18: 2, 26: 3}.get(conn, 1)
        metric = self.combo_metric.currentText().replace(' ', '_')
        threshold = self.spin_thresh.value()
        min_vol = self.spin_minvol.value() if self.chk_minvol.isChecked() else 0
        worker = CleaningWorker(layer.data.copy(), threshold, metric, connectivity,
                                self.chk_fill.isChecked(), self.spin_hole.value(),
                                self.state.voxel_nm, min_vol, self.chk_gpu.isChecked())
        def on_done(result, before, after):
            self.state.rm(layer.name + "_preview")
            self.state.viewer.add_labels(result, name=layer.name + "_preview",
                                          scale=self.state.scale(), opacity=0.6)
            self.label_stats.setText(f"Preview: {before:,} → {after:,} vox  ({before-after:,} removed)")
            self.btn_cancel.setEnabled(False)
        worker.finished.connect(on_done)
        self._run_worker(worker)

    def _apply_dust(self):
        layer = self._get_layer()
        if not layer:
            return show_warning("Select a layer first")
        conn = int(self.combo_conn.currentText())
        connectivity = {6: 1, 18: 2, 26: 3}.get(conn, 1)
        metric = self.combo_metric.currentText().replace(' ', '_')
        threshold = self.spin_thresh.value()
        min_vol = self.spin_minvol.value() if self.chk_minvol.isChecked() else 0
        self.state.save_history(layer.name, layer.data)
        worker = CleaningWorker(layer.data.copy(), threshold, metric, connectivity,
                                self.chk_fill.isChecked(), self.spin_hole.value(),
                                self.state.voxel_nm, min_vol, self.chk_gpu.isChecked())
        def on_done(result, before, after):
            layer.data = result
            self.state.rm(layer.name + "_preview")
            self.label_stats.setText(f"Applied: {before:,} → {after:,} vox")
            self.btn_undo.setEnabled(True)
            self.btn_cancel.setEnabled(False)
        worker.finished.connect(on_done)
        self._run_worker(worker)


# ====================================================================
# ✂️ ERASE TAB
# ====================================================================

class EraseTab(QWidget):
    def __init__(self, state: PluginState):
        super().__init__()
        self.state = state
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout()
        layout.setSpacing(6)
        self.setStyleSheet(f"background:{BG_MID};")

        # ── 1. SELECT ─────────────────────────────────────────────────
        g1 = _group("1 ▸ SELECT LAYER")
        l1 = QVBoxLayout()
        row = QHBoxLayout()
        row.addWidget(_lbl("Layer:"))
        self.combo_layer = QComboBox()
        self.combo_layer.setStyleSheet(INPUT_STYLE)
        row.addWidget(self.combo_layer)
        btn_r = _btn("↻", "secondary")
        btn_r.setFixedWidth(30)
        btn_r.clicked.connect(self._refresh_layers)
        row.addWidget(btn_r)
        l1.addLayout(row)
        g1.setLayout(l1)
        layout.addWidget(g1)

        # ── 2. MASK ───────────────────────────────────────────────────
        g2 = _group("2 ▸ PAINT MASK")
        l2 = QVBoxLayout()
        l2.addWidget(_info("Create mask → paint red regions → Apply Erase"))
        row = QHBoxLayout()
        btn_cm = _btn("🖌  Create Mask", "primary")
        btn_cm.clicked.connect(self._create_mask)
        row.addWidget(btn_cm)
        btn_clr = _btn("🗑  Clear Mask", "danger")
        btn_clr.clicked.connect(self._clear_mask)
        row.addWidget(btn_clr)
        l2.addLayout(row)
        g2.setLayout(l2)
        layout.addWidget(g2)

        # ── 3. Z RANGE ────────────────────────────────────────────────
        g3 = _group("3 ▸ Z RANGE")
        l3 = QVBoxLayout()
        self.chk_all_z = QCheckBox("All Z slices")
        self.chk_all_z.setChecked(True)
        self.chk_all_z.setStyleSheet(f"color:{TEXT_MAIN};")
        self.chk_all_z.toggled.connect(self._toggle_z)
        l3.addWidget(self.chk_all_z)
        row = QHBoxLayout()
        row.addWidget(_lbl("Z from:"))
        self.spin_z0 = QSpinBox()
        self.spin_z0.setRange(0, 9999)
        self.spin_z0.setEnabled(False)
        self.spin_z0.setStyleSheet(INPUT_STYLE)
        row.addWidget(self.spin_z0)
        row.addWidget(_lbl("to:"))
        self.spin_z1 = QSpinBox()
        self.spin_z1.setRange(0, 9999)
        self.spin_z1.setValue(100)
        self.spin_z1.setEnabled(False)
        self.spin_z1.setStyleSheet(INPUT_STYLE)
        row.addWidget(self.spin_z1)
        l3.addLayout(row)
        g3.setLayout(l3)
        layout.addWidget(g3)

        # ── 4. ACTIONS ────────────────────────────────────────────────
        g4 = _group("4 ▸ ACTIONS")
        l4 = QVBoxLayout()
        btn_ap = _btn("✂️  Apply Erase", "run")
        btn_ap.clicked.connect(self._apply_erase)
        l4.addWidget(btn_ap)
        row = QHBoxLayout()
        self.btn_undo = _btn("↶  Undo", "warning")
        self.btn_undo.clicked.connect(self._undo)
        row.addWidget(self.btn_undo)
        g4.setLayout(l4)
        layout.addWidget(g4)

        self.label_status = _info_box("Ready")
        layout.addWidget(self.label_status)
        layout.addStretch()
        self.setLayout(layout)
        self._refresh_layers()

    def _refresh_layers(self):
        self.combo_layer.clear()
        layers = [l.name for l in self.state.get_labels()
                  if not l.name.endswith('_preview') and l.name != 'Erase_Mask']
        self.combo_layer.addItems(layers if layers else ["—"])

    def _get_layer(self):
        name = self.combo_layer.currentText()
        return self.state.get_labels_layer(name) if name and name != "—" else None

    def _toggle_z(self, all_z):
        self.spin_z0.setEnabled(not all_z)
        self.spin_z1.setEnabled(not all_z)

    def _create_mask(self):
        layer = self._get_layer()
        if not layer:
            return show_warning("Select layer")
        self.state.rm("Erase_Mask")
        shape = layer.data.shape
        self.state.erase_layer = self.state.viewer.add_labels(
            np.zeros(shape, dtype=np.uint8), name="Erase_Mask",
            scale=self.state.scale(), opacity=0.5)
        # napari 0.5+ removed Labels.color; use a DirectLabelColormap.
        try:
            from napari.utils.colormaps import DirectLabelColormap
            self.state.erase_layer.colormap = DirectLabelColormap(
                color_dict={1: (1.0, 0.0, 0.0, 1.0),
                            0: (0.0, 0.0, 0.0, 0.0),
                            None: (0.0, 0.0, 0.0, 0.0)})
        except Exception:
            try:
                self.state.erase_layer.color = {1: 'red', 0: 'transparent'}
            except Exception:
                pass
        self.state.viewer.layers.selection.active = self.state.erase_layer
        self.state.erase_layer.mode = 'paint'
        self.state.erase_layer.selected_label = 1
        self.state.erase_layer.brush_size = 10
        self.spin_z1.setValue(shape[0])

    def _clear_mask(self):
        if self.state.erase_layer and "Erase_Mask" in self.state.viewer.layers:
            self.state.erase_layer.data = np.zeros_like(self.state.erase_layer.data)

    def _apply_erase(self):
        layer = self._get_layer()
        if not layer:
            return show_warning("Select layer")
        if not self.state.erase_layer:
            return show_warning("Create mask first")
        if np.count_nonzero(self.state.erase_layer.data) == 0:
            return show_warning("Draw on mask first")
        self.state.save_history(layer.name, layer.data)
        z_range = None if self.chk_all_z.isChecked() else (self.spin_z0.value(), self.spin_z1.value())
        before = np.count_nonzero(layer.data)
        layer.data = apply_2d_mask_to_3d(layer.data, self.state.erase_layer.data, z_range)
        after = np.count_nonzero(layer.data)
        self.state.erase_layer.data = np.zeros_like(self.state.erase_layer.data)
        self.label_status.setText(f"Erased {before-after:,} vox")

    def _undo(self):
        if self.state.can_undo():
            name, data = self.state.history[self.state.history_idx]
            self.state.history_idx -= 1
            layer = self.state.get_labels_layer(name)
            if layer:
                layer.data = data


# ====================================================================
# 🎨 COLORS TAB
# ====================================================================

class ColorTab(QWidget):
    def __init__(self, state: PluginState):
        super().__init__()
        self.state = state
        self._pick_layer = None     # layer whose selected_label we listen to
        self._syncing = False       # guard against canvas<->list feedback loops
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout()
        layout.setSpacing(6)
        self.setStyleSheet(f"background:{BG_MID};")

        # ── LAYER ─────────────────────────────────────────────────────
        g1 = _group("LAYER")
        l1 = QVBoxLayout()
        row = QHBoxLayout()
        row.addWidget(_lbl("Layer:"))
        self.combo_layer = QComboBox()
        self.combo_layer.setStyleSheet(INPUT_STYLE)
        self.combo_layer.currentTextChanged.connect(self._refresh_labels)
        row.addWidget(self.combo_layer)
        btn = _btn("↻", "secondary")
        btn.setFixedWidth(30)
        btn.clicked.connect(self._refresh_layers)
        row.addWidget(btn)
        l1.addLayout(row)
        g1.setLayout(l1)
        layout.addWidget(g1)

        # ── LABELS ────────────────────────────────────────────────────
        g2 = _group("LABELS  (Ctrl+click for multi-select)")
        l2 = QVBoxLayout()
        self.list_labels = QListWidget()
        self.list_labels.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.list_labels.setMaximumHeight(110)
        self.list_labels.setStyleSheet(
            f"background:{BG_DARK};color:{TEXT_MAIN};border:1px solid {BORDER};"
            f"border-radius:3px;")
        self.list_labels.itemSelectionChanged.connect(self._on_list_selection)
        l2.addWidget(self.list_labels)
        self.chk_highlight = QCheckBox("Highlight picked label on canvas")
        self.chk_highlight.setChecked(True)
        self.chk_highlight.setStyleSheet(f"color:{TEXT_MAIN};")
        self.chk_highlight.toggled.connect(self._on_highlight_toggled)
        l2.addWidget(self.chk_highlight)
        l2.addWidget(_info("Tip: press 5 (picker) and click a membrane — its "
                           "label is selected here and highlighted on the canvas"))
        g2.setLayout(l2)
        layout.addWidget(g2)

        # ── COLOR & OPACITY ───────────────────────────────────────────
        g3 = _group("COLOR & OPACITY")
        l3 = QVBoxLayout()
        row = QHBoxLayout()
        self.color_preview = QLabel()
        self.color_preview.setFixedSize(30, 25)
        self.color_preview.setStyleSheet(f"background:white;border:1px solid {BORDER};border-radius:3px;")
        row.addWidget(self.color_preview)
        btn_col = _btn("🎨  Pick Color", "primary")
        btn_col.clicked.connect(self._choose_color)
        row.addWidget(btn_col)
        l3.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(_lbl("Opacity:"))
        self.slider_opacity = _slider(0, 100, 100)
        self.slider_opacity.valueChanged.connect(lambda v: self.label_opacity.setText(f"{v}%"))
        row.addWidget(self.slider_opacity)
        self.label_opacity = _lbl("100%")
        row.addWidget(self.label_opacity)
        l3.addLayout(row)
        l3.addWidget(_lbl("Presets:", bold=True))
        preset_row = QHBoxLayout()
        for name, rgba in list(COLOR_PRESETS.items())[:8]:
            b = QPushButton()
            b.setFixedSize(25, 25)
            b.setStyleSheet(f"background:rgb({rgba[0]},{rgba[1]},{rgba[2]});border-radius:3px;")
            b.setToolTip(name)
            b.clicked.connect(lambda _, n=name: self._apply_preset(n))
            preset_row.addWidget(b)
        l3.addLayout(preset_row)
        preset_row2 = QHBoxLayout()
        for name, rgba in list(COLOR_PRESETS.items())[8:]:
            b = QPushButton()
            b.setFixedSize(25, 25)
            b.setStyleSheet(f"background:rgb({rgba[0]},{rgba[1]},{rgba[2]});border-radius:3px;")
            b.setToolTip(name)
            b.clicked.connect(lambda _, n=name: self._apply_preset(n))
            preset_row2.addWidget(b)
        l3.addLayout(preset_row2)
        g3.setLayout(l3)
        layout.addWidget(g3)

        # ── ACTIONS ───────────────────────────────────────────────────
        g4 = _group("ACTIONS")
        l4 = QVBoxLayout()
        row = QHBoxLayout()
        btn_goto = _btn("🎯  Go to", "secondary")
        btn_goto.clicked.connect(self._goto)
        row.addWidget(btn_goto)
        btn_erase = _btn("🗑  Erase Label", "danger")
        btn_erase.clicked.connect(self._erase)
        row.addWidget(btn_erase)
        l4.addLayout(row)
        row = QHBoxLayout()
        btn_merge = _btn("🔗  Merge", "warning")
        btn_merge.clicked.connect(self._merge)
        row.addWidget(btn_merge)
        btn_reset = _btn("🔄  Reset Colors", "secondary")
        btn_reset.clicked.connect(self._reset)
        row.addWidget(btn_reset)
        l4.addLayout(row)
        g4.setLayout(l4)
        layout.addWidget(g4)

        self.status_label = _info_box("Ready")
        layout.addWidget(self.status_label)
        layout.addStretch()
        self.setLayout(layout)
        self._refresh_layers()

    def _refresh_layers(self):
        self.combo_layer.clear()
        layers = [l.name for l in self.state.get_labels()
                  if not l.name.endswith('_preview') and l.name != 'Erase_Mask']
        self.combo_layer.addItems(layers if layers else ["—"])

    def _get_layer(self):
        name = self.combo_layer.currentText()
        return self.state.get_labels_layer(name) if name and name != "—" else None

    def _connect_pick(self, layer):
        """Listen to the layer's selected_label so the napari picker (key 5)
        drives the list selection + canvas highlight."""
        if self._pick_layer is layer:
            return
        if self._pick_layer is not None:
            try:
                self._pick_layer.events.selected_label.disconnect(self._on_label_picked)
            except Exception:
                pass
        self._pick_layer = layer
        if layer is not None:
            try:
                layer.events.selected_label.connect(self._on_label_picked)
            except Exception:
                pass

    def _on_label_picked(self, event=None):
        if self._syncing:
            return
        layer = self._get_layer()
        if layer is None:
            return
        try:
            val = int(layer.selected_label)
        except Exception:
            return
        if val <= 0:
            return
        self._syncing = True
        try:
            self.list_labels.clearSelection()
            for i in range(self.list_labels.count()):
                it = self.list_labels.item(i)
                if it.data(Qt.UserRole) == val:
                    it.setSelected(True)
                    self.list_labels.setCurrentItem(it)
                    self.list_labels.scrollToItem(it)
                    break
            if self.chk_highlight.isChecked():
                layer.show_selected_label = True
            self.status_label.setText(f"Picked label {val}")
        finally:
            self._syncing = False

    def _on_list_selection(self):
        if self._syncing:
            return
        layer = self._get_layer()
        if layer is None:
            return
        labels = self._get_selected_labels()
        if not labels:
            return
        self._syncing = True
        try:
            layer.selected_label = int(labels[0])
            if self.chk_highlight.isChecked():
                layer.show_selected_label = True
        except Exception:
            pass
        finally:
            self._syncing = False

    def _on_highlight_toggled(self, checked):
        layer = self._get_layer()
        if layer is None:
            return
        try:
            if not checked:
                layer.show_selected_label = False        # show all labels again
            elif self._get_selected_labels():
                layer.show_selected_label = True
        except Exception:
            pass

    def _refresh_labels(self):
        self.list_labels.clear()
        layer = self._get_layer()
        self._connect_pick(layer)
        if not layer:
            return
        _uniq = np.unique(layer.data)
        for lbl in _uniq[_uniq > 0]:
            item = QListWidgetItem(f"Label {int(lbl)}")
            item.setData(Qt.UserRole, int(lbl))
            color = self.state.get_label_color(layer.name, int(lbl))
            if color:
                item.setBackground(QColor(*color[:3]))
            self.list_labels.addItem(item)

    def _get_selected_labels(self):
        return [item.data(Qt.UserRole) for item in self.list_labels.selectedItems()]

    def _choose_color(self):
        layer = self._get_layer()
        labels = self._get_selected_labels()
        if not layer or not labels:
            return show_warning("Select layer and label(s)")
        qc = QColorDialog.getColor()
        if qc.isValid():
            opacity = self.slider_opacity.value() / 100.0
            rgba = (qc.red(), qc.green(), qc.blue(), int(opacity * 255))
            for lbl in labels:
                self.state.set_label_color(layer.name, lbl, rgba)
            self.color_preview.setStyleSheet(
                f"background:rgb({qc.red()},{qc.green()},{qc.blue()});border:1px solid {BORDER};border-radius:3px;")
            self._refresh_labels()

    def _apply_preset(self, name):
        layer = self._get_layer()
        labels = self._get_selected_labels()
        if not layer or not labels:
            return
        rgba = COLOR_PRESETS.get(name)
        if rgba:
            for lbl in labels:
                self.state.set_label_color(layer.name, lbl, rgba)
            self._refresh_labels()

    def _goto(self):
        layer = self._get_layer()
        labels = self._get_selected_labels()
        if not layer or not labels:
            return
        mask = layer.data == labels[0]
        coords = np.argwhere(mask)
        if coords.size:
            self.state.viewer.camera.center = tuple(coords.mean(axis=0))

    def _erase(self):
        layer = self._get_layer()
        labels = self._get_selected_labels()
        if not layer or not labels:
            return
        self.state.save_history(layer.name, layer.data)
        for lbl in labels:
            layer.data = np.where(layer.data == lbl, 0, layer.data)
        self._refresh_labels()

    def _merge(self):
        layer = self._get_layer()
        labels = self._get_selected_labels()
        if not layer or len(labels) < 2:
            return show_warning("Select 2+ labels to merge")
        self.state.save_history(layer.name, layer.data)
        target = labels[0]
        for src in labels[1:]:
            layer.data = np.where(layer.data == src, target, layer.data)
        self._refresh_labels()

    def _reset(self):
        layer = self._get_layer()
        if layer:
            self.state.reset_colors(layer.name)
            self._refresh_labels()


# ====================================================================
# 💡 RENDER TAB  (NEW in v3.0)
# ====================================================================

class RenderTab(QWidget):
    """
    Controls for lighting, contrast and membrane enhancement.
    Works with both Image and Labels layers.
    """
    def __init__(self, state: PluginState):
        super().__init__()
        self.state = state
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout()
        layout.setSpacing(6)
        self.setStyleSheet(f"background:{BG_MID};")

        # ── 1. SELECT LAYER ───────────────────────────────────────────
        g1 = _group("1 ▸ SELECT LAYER")
        l1 = QVBoxLayout()
        row = QHBoxLayout()
        row.addWidget(_lbl("Layer:"))
        self.combo_layer = QComboBox()
        self.combo_layer.setStyleSheet(INPUT_STYLE)
        self.combo_layer.currentTextChanged.connect(self._on_layer_changed)
        row.addWidget(self.combo_layer)
        btn_r = _btn("↻", "secondary")
        btn_r.setFixedWidth(30)
        btn_r.clicked.connect(self._refresh_layers)
        row.addWidget(btn_r)
        l1.addLayout(row)
        l1.addWidget(_info("Accepts Image and Labels layers"))
        self.lbl_info = _info("Select a layer to adjust rendering")
        l1.addWidget(self.lbl_info)
        g1.setLayout(l1)
        layout.addWidget(g1)

        # ── 2. CONTRAST & GAMMA ───────────────────────────────────────
        g2 = _group("2 ▸ CONTRAST / OPACITY & GAMMA")
        l2 = QVBoxLayout()
        l2.addWidget(_info("Image: contrast limits  |  Labels: max slider = opacity"))

        row = QHBoxLayout()
        row.addWidget(_lbl("Gamma:"))
        self.slider_gamma = _slider(10, 300, 100)
        self.slider_gamma.valueChanged.connect(self._apply_gamma)
        row.addWidget(self.slider_gamma)
        self.lbl_gamma = _lbl("1.00")
        self.lbl_gamma.setFixedWidth(36)
        row.addWidget(self.lbl_gamma)
        l2.addLayout(row)

        row = QHBoxLayout()
        row.addWidget(_lbl("Contrast min:"))
        self.slider_cmin = _slider(0, 1000, 0)
        self.slider_cmin.valueChanged.connect(self._apply_contrast)
        row.addWidget(self.slider_cmin)
        self.lbl_cmin = _lbl("0")
        self.lbl_cmin.setFixedWidth(40)
        row.addWidget(self.lbl_cmin)
        l2.addLayout(row)

        row = QHBoxLayout()
        row.addWidget(_lbl("Contrast max:"))
        self.slider_cmax = _slider(0, 1000, 1000)
        self.slider_cmax.valueChanged.connect(self._apply_contrast)
        row.addWidget(self.slider_cmax)
        self.lbl_cmax = _lbl("1000")
        self.lbl_cmax.setFixedWidth(40)
        row.addWidget(self.lbl_cmax)
        l2.addLayout(row)

        btn_auto = _btn("⚡  Auto Contrast", "secondary")
        btn_auto.clicked.connect(self._auto_contrast)
        l2.addWidget(btn_auto)
        g2.setLayout(l2)
        layout.addWidget(g2)

        # ── 3. RENDERING MODE ─────────────────────────────────────────
        g3 = _group("3 ▸ RENDERING MODE  (3D)")
        l3 = QVBoxLayout()
        l3.addWidget(_info("Rendering mode affects 3D view only"))
        row = QHBoxLayout()
        row.addWidget(_lbl("Mode:"))
        self.combo_render = QComboBox()
        self.combo_render.addItems(["mip", "translucent", "attenuated_mip",
                                    "iso", "average", "minip"])
        self.combo_render.setStyleSheet(INPUT_STYLE)
        self.combo_render.currentTextChanged.connect(self._apply_render_mode)
        row.addWidget(self.combo_render)
        l3.addLayout(row)

        row = QHBoxLayout()
        row.addWidget(_lbl("ISO threshold:"))
        self.slider_iso = _slider(0, 1000, 500)
        self.slider_iso.valueChanged.connect(self._apply_iso)
        row.addWidget(self.slider_iso)
        self.lbl_iso = _lbl("0.50")
        self.lbl_iso.setFixedWidth(36)
        row.addWidget(self.lbl_iso)
        l3.addLayout(row)

        row = QHBoxLayout()
        row.addWidget(_lbl("Attenuation:"))
        self.slider_atten = _slider(0, 200, 50)
        self.slider_atten.valueChanged.connect(self._apply_attenuation)
        row.addWidget(self.slider_atten)
        self.lbl_atten = _lbl("0.05")
        self.lbl_atten.setFixedWidth(36)
        row.addWidget(self.lbl_atten)
        l3.addLayout(row)
        g3.setLayout(l3)
        layout.addWidget(g3)

        # ── 4. COLORMAP ───────────────────────────────────────────────
        g4 = _group("4 ▸ COLORMAP")
        l4 = QVBoxLayout()
        row = QHBoxLayout()
        row.addWidget(_lbl("Colormap:"))
        self.combo_cmap = QComboBox()
        self.combo_cmap.addItems([
            "gray", "grays", "gray_r", "inferno", "magma", "plasma",
            "viridis", "turbo", "hot", "bone", "copper", "green",
            "cyan", "red", "blue", "yellow"
        ])
        self.combo_cmap.setStyleSheet(INPUT_STYLE)
        self.combo_cmap.currentTextChanged.connect(self._apply_colormap)
        row.addWidget(self.combo_cmap)
        l4.addLayout(row)
        g4.setLayout(l4)
        layout.addWidget(g4)

        # ── 5. MEMBRANE PRESETS ───────────────────────────────────────
        g5 = _group("5 ▸ MEMBRANE ENHANCEMENT PRESETS")
        l5 = QVBoxLayout()
        l5.addWidget(_info("Quick presets optimized for cryo-ET membrane visualization"))

        btn_mem = _btn("🧬  Membrane Preset", "primary")
        btn_mem.setToolTip("MIP + gray_r + high gamma — highlights membrane edges")
        btn_mem.clicked.connect(self._preset_membrane)
        l5.addWidget(btn_mem)

        btn_den = _btn("🌫  Dense Volume Preset", "secondary")
        btn_den.setToolTip("Attenuated MIP + inferno — good for dense organelles")
        btn_den.clicked.connect(self._preset_dense)
        l5.addWidget(btn_den)

        btn_iso = _btn("🔵  ISO Surface Preset", "secondary")
        btn_iso.setToolTip("ISO rendering — clean surface view")
        btn_iso.clicked.connect(self._preset_iso)
        l5.addWidget(btn_iso)

        btn_rst = _btn("🔄  Reset to Default", "warning")
        btn_rst.clicked.connect(self._reset_render)
        l5.addWidget(btn_rst)
        g5.setLayout(l5)
        layout.addWidget(g5)

        # ── 6. SNAPSHOT ───────────────────────────────────────────────
        g6 = _group("6 ▸ SAVE SNAPSHOT AS TIFF")
        l6 = QVBoxLayout()
        l6.addWidget(_info("Saves the current viewer canvas as a TIFF file"))
        row = QHBoxLayout()
        self.chk_canvas_only = QCheckBox("Canvas only")
        self.chk_canvas_only.setChecked(True)
        self.chk_canvas_only.setStyleSheet(f"color:{TEXT_MAIN};")
        row.addWidget(self.chk_canvas_only)
        l6.addLayout(row)
        btn_snap = _btn("📸  Save Snapshot…", "run")
        btn_snap.clicked.connect(self._save_snapshot)
        l6.addWidget(btn_snap)
        self.lbl_snap = _info_box("—")
        l6.addWidget(self.lbl_snap)
        g6.setLayout(l6)
        layout.addWidget(g6)

        # ── 7. SAVE AS MRC ────────────────────────────────────────────
        g7 = _group("7 ▸ SAVE AS MRC")
        l7 = QVBoxLayout()
        l7.addWidget(_info("Exports the selected layer to a new .mrc file "
                           "(voxel size written to header)"))
        row = QHBoxLayout()
        self.chk_binary_mrc = QCheckBox("Binary mask (Labels → 0/1)")
        self.chk_binary_mrc.setChecked(False)
        self.chk_binary_mrc.setStyleSheet(f"color:{TEXT_MAIN};")
        row.addWidget(self.chk_binary_mrc)
        l7.addLayout(row)
        btn_mrc = _btn("💾  Save as MRC…", "run")
        btn_mrc.clicked.connect(self._save_mrc)
        l7.addWidget(btn_mrc)
        self.lbl_mrc = _info_box("—")
        l7.addWidget(self.lbl_mrc)
        g7.setLayout(l7)
        layout.addWidget(g7)

        layout.addStretch()
        self.setLayout(layout)
        self._refresh_layers()

    # ── Helpers ───────────────────────────────────────────────────────

    def _is_labels(self, layer):
        return isinstance(layer, Labels)

    def _refresh_layers(self):
        """Populate combo — Labels first, then Images."""
        self.combo_layer.blockSignals(True)
        prev = self.combo_layer.currentText()
        self.combo_layer.clear()
        labels = [l.name for l in self.state.viewer.layers
                  if isinstance(l, Labels)
                  and not l.name.endswith('_preview')
                  and l.name != 'Erase_Mask']
        images = [l.name for l in self.state.viewer.layers
                  if isinstance(l, Image)
                  and not l.name.endswith('_preview')]
        names = labels + images
        self.combo_layer.addItems(names if names else ["—"])
        idx = self.combo_layer.findText(prev)
        if idx >= 0:
            self.combo_layer.setCurrentIndex(idx)
        self.combo_layer.blockSignals(False)
        self._on_layer_changed(self.combo_layer.currentText())

    def _get_layer(self):
        """Return the currently selected Image or Labels layer."""
        name = self.combo_layer.currentText()
        if not name or name == "—":
            return None
        for l in self.state.viewer.layers:
            if l.name == name and isinstance(l, (Image, Labels)):
                return l
        return None

    def _on_layer_changed(self, name):
        layer = self._get_layer()
        if layer is None:
            return
        is_lbl = self._is_labels(layer)
        kind = "Labels" if is_lbl else "Image"
        self.lbl_info.setText(
            f"Type: {kind}  |  Shape: {layer.data.shape}  |  dtype: {layer.data.dtype}")

        # Sync gamma
        try:
            g = float(layer.gamma)
            self.slider_gamma.blockSignals(True)
            self.slider_gamma.setValue(int(g * 100))
            self.lbl_gamma.setText(f"{g:.2f}")
            self.slider_gamma.blockSignals(False)
        except Exception:
            pass

        # Sync opacity / contrast sliders
        if is_lbl:
            # Labels: both sliders map to opacity (0–1)
            try:
                op = float(layer.opacity)
                self.slider_cmin.blockSignals(True)
                self.slider_cmax.blockSignals(True)
                self.slider_cmin.setValue(0)
                self.slider_cmax.setValue(int(op * 1000))
                self.lbl_cmin.setText("opacity")
                self.lbl_cmax.setText(f"{op:.2f}")
                self.slider_cmin.blockSignals(False)
                self.slider_cmax.blockSignals(False)
            except Exception:
                pass
        else:
            try:
                lo, hi = layer.contrast_limits
                data_min = float(layer.data.min())
                data_max = float(layer.data.max())
                span = data_max - data_min if data_max != data_min else 1.0
                self.slider_cmin.blockSignals(True)
                self.slider_cmax.blockSignals(True)
                self.slider_cmin.setValue(int(1000 * (lo - data_min) / span))
                self.slider_cmax.setValue(int(1000 * (hi - data_min) / span))
                self.lbl_cmin.setText(f"{lo:.0f}")
                self.lbl_cmax.setText(f"{hi:.0f}")
                self.slider_cmin.blockSignals(False)
                self.slider_cmax.blockSignals(False)
            except Exception:
                pass

    # ── Apply methods ─────────────────────────────────────────────────

    def _apply_gamma(self, val):
        layer = self._get_layer()
        if layer is None:
            return
        g = val / 100.0
        try:
            layer.gamma = g
        except Exception:
            pass
        self.lbl_gamma.setText(f"{g:.2f}")

    def _apply_contrast(self):
        """For Labels: slider_cmax = global opacity.  For Image: contrast limits."""
        layer = self._get_layer()
        if layer is None:
            return
        if self._is_labels(layer):
            try:
                op = max(0.01, min(1.0, self.slider_cmax.value() / 1000.0))
                layer.opacity = op
                self.lbl_cmax.setText(f"{op:.2f}")
                self.lbl_cmin.setText("opacity")
            except Exception as e:
                show_error(str(e))
        else:
            try:
                data_min = float(layer.data.min())
                data_max = float(layer.data.max())
                span = data_max - data_min if data_max != data_min else 1.0
                lo = data_min + (self.slider_cmin.value() / 1000.0) * span
                hi = data_min + (self.slider_cmax.value() / 1000.0) * span
                if hi <= lo:
                    hi = lo + 1
                layer.contrast_limits = (lo, hi)
                self.lbl_cmin.setText(f"{lo:.0f}")
                self.lbl_cmax.setText(f"{hi:.0f}")
            except Exception:
                pass

    def _auto_contrast(self):
        layer = self._get_layer()
        if layer is None:
            return
        if self._is_labels(layer):
            try:
                layer.opacity = 1.0
                self._on_layer_changed(layer.name)
                show_info("Labels opacity reset to 1.0")
            except Exception as e:
                show_error(str(e))
        else:
            try:
                p2, p98 = np.percentile(layer.data, [2, 98])
                layer.contrast_limits = (float(p2), float(p98))
                self._on_layer_changed(layer.name)
            except Exception as e:
                show_error(str(e))

    def _apply_render_mode(self, mode):
        """Rendering mode: applies to Image layers only (Labels have no rendering attr)."""
        layer = self._get_layer()
        if layer is None:
            return
        if not self._is_labels(layer):
            try:
                layer.rendering = mode
            except Exception:
                pass

    def _apply_iso(self, val):
        layer = self._get_layer()
        if layer is None:
            return
        v = val / 1000.0
        self.lbl_iso.setText(f"{v:.2f}")
        if not self._is_labels(layer):
            try:
                layer.iso_threshold = v
            except Exception:
                pass

    def _apply_attenuation(self, val):
        layer = self._get_layer()
        if layer is None:
            return
        v = val / 1000.0
        self.lbl_atten.setText(f"{v:.3f}")
        if not self._is_labels(layer):
            try:
                layer.attenuation = v
            except Exception:
                pass

    def _apply_colormap(self, cmap):
        """Colormap: applies to Image layers only (Labels colors managed in Colors tab)."""
        layer = self._get_layer()
        if layer is None:
            return
        if not self._is_labels(layer):
            try:
                layer.colormap = cmap
            except Exception:
                pass

    # ── Presets ───────────────────────────────────────────────────────

    def _preset_membrane(self):
        """Membrane preset: for Labels boosts opacity+gamma; for Image uses MIP+gray_r."""
        layer = self._get_layer()
        if layer is None:
            return show_warning("Select a layer first")
        try:
            if self._is_labels(layer):
                layer.opacity = 1.0
                layer.gamma   = 1.5
                self.slider_gamma.setValue(150)
                self.slider_cmax.setValue(1000)
                self.lbl_cmax.setText("1.00")
            else:
                layer.rendering = "mip"
                layer.colormap  = "gray_r"
                layer.gamma     = 1.5
                self._auto_contrast()
                self.combo_render.setCurrentText("mip")
                self.combo_cmap.setCurrentText("gray_r")
                self.slider_gamma.setValue(150)
            show_info("Membrane preset applied")
        except Exception as e:
            show_error(str(e))

    def _preset_dense(self):
        """Dense volume preset."""
        layer = self._get_layer()
        if layer is None:
            return show_warning("Select a layer first")
        try:
            if self._is_labels(layer):
                layer.opacity = 0.7
                layer.gamma   = 1.0
                self.slider_gamma.setValue(100)
                self.slider_cmax.setValue(700)
                self.lbl_cmax.setText("0.70")
            else:
                layer.rendering  = "attenuated_mip"
                layer.colormap   = "inferno"
                layer.gamma      = 1.0
                layer.attenuation = 0.05
                self._auto_contrast()
                self.combo_render.setCurrentText("attenuated_mip")
                self.combo_cmap.setCurrentText("inferno")
                self.slider_gamma.setValue(100)
            show_info("Dense volume preset applied")
        except Exception as e:
            show_error(str(e))

    def _preset_iso(self):
        """ISO surface preset."""
        layer = self._get_layer()
        if layer is None:
            return show_warning("Select a layer first")
        try:
            if self._is_labels(layer):
                layer.opacity = 0.9
                layer.gamma   = 1.0
                self.slider_gamma.setValue(100)
                self.slider_cmax.setValue(900)
                self.lbl_cmax.setText("0.90")
            else:
                layer.rendering = "iso"
                layer.colormap  = "gray"
                layer.gamma     = 1.0
                self._auto_contrast()
                self.combo_render.setCurrentText("iso")
                self.combo_cmap.setCurrentText("gray")
                self.slider_gamma.setValue(100)
            show_info("ISO surface preset applied")
        except Exception as e:
            show_error(str(e))

    def _reset_render(self):
        layer = self._get_layer()
        if layer is None:
            return
        try:
            if self._is_labels(layer):
                layer.opacity = 1.0
                layer.gamma   = 1.0
                self.slider_gamma.setValue(100)
                self.slider_cmax.setValue(1000)
                self.lbl_cmax.setText("1.00")
            else:
                layer.rendering = "mip"
                layer.colormap  = "gray"
                layer.gamma     = 1.0
                layer.contrast_limits_range = (float(layer.data.min()), float(layer.data.max()))
                layer.contrast_limits       = (float(layer.data.min()), float(layer.data.max()))
                self.combo_render.setCurrentText("mip")
                self.combo_cmap.setCurrentText("gray")
                self.slider_gamma.setValue(100)
            self._on_layer_changed(layer.name)
        except Exception as e:
            show_error(str(e))

    def _save_snapshot(self):
        """Save current viewer canvas as TIFF."""
        if not HAS_TIFFFILE and not HAS_IMAGEIO:
            return show_error("Install tifffile or imageio to save snapshots")
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Snapshot", "snapshot.tif",
            "TIFF (*.tif *.tiff);;PNG (*.png);;All (*)")
        if not path:
            return
        try:
            canvas_only = self.chk_canvas_only.isChecked()
            img = self.state.viewer.screenshot(canvas_only=canvas_only)
            p = Path(path)
            if p.suffix.lower() in ('.tif', '.tiff'):
                if HAS_TIFFFILE:
                    import tifffile as tf
                    tf.imwrite(str(p), img)
                else:
                    imageio.imwrite(str(p), img)
            else:
                imageio.imwrite(str(p), img)
            self.lbl_snap.setText(f"Saved: {p.name}  ({img.shape[1]}×{img.shape[0]} px)")
            log(f"Snapshot saved: {p.name}", params={"shape": img.shape})
            show_info(f"Snapshot saved: {p}")
        except Exception as e:
            show_error(str(e))

    def _save_mrc(self):
        """Save the selected Image/Labels layer to a new .mrc file,
        writing the voxel size into the MRC header."""
        if not HAS_MRCFILE:
            return show_error("Install mrcfile to export MRC files "
                              "(pip install mrcfile)")
        layer = self._get_layer()
        if layer is None:
            return show_warning("Select a layer first")

        is_lbl = self._is_labels(layer)
        default = f"{layer.name}.mrc"
        path, _ = QFileDialog.getSaveFileName(
            self, "Save as MRC", default, "MRC Files (*.mrc);;All (*)")
        if not path:
            return
        if not path.lower().endswith(".mrc"):
            path += ".mrc"

        try:
            data = np.asarray(layer.data)
            if is_lbl:
                if self.chk_binary_mrc.isChecked():
                    out = (data > 0).astype(np.int8)
                else:
                    out = data.astype(np.int16)
            else:
                out = data.astype(np.float32)
            # MRC expects C-contiguous arrays
            out = np.ascontiguousarray(out)

            with mrcfile.new(path, overwrite=True) as mrc:
                mrc.set_data(out)
                ang = float(self.state.voxel_nm) * 10.0   # nm -> Angstrom
                if ang > 0:
                    mrc.voxel_size = (ang, ang, ang)
                mrc.update_header_from_data()
                mrc.update_header_stats()

            p = Path(path)
            self.lbl_mrc.setText(
                f"Saved: {p.name}  [{out.shape}, {out.dtype}, "
                f"{self.state.voxel_nm:.4f} nm/vox]")
            log(f"MRC saved: {p.name}", params={"shape": out.shape,
                                                "dtype": str(out.dtype),
                                                "voxel_nm": self.state.voxel_nm})
            show_info(f"Saved MRC: {p}")
        except Exception as e:
            show_error(str(e))


# ====================================================================
# 🎬 ANIMATION TAB  (Movie Maker + Spin Movie)
# ====================================================================

class KeyframeWidget(QWidget):
    clicked          = Signal(int)
    delete_requested = Signal(int)

    def __init__(self, index: int, keyframe: Keyframe, parent=None):
        super().__init__(parent)
        self.index    = index
        self.keyframe = keyframe
        self._init_ui()

    def _init_ui(self):
        layout = QHBoxLayout()
        layout.setContentsMargins(4, 2, 4, 2)

        # Thumbnail
        self.thumb_label = QLabel()
        self.thumb_label.setFixedSize(80, 60)
        self.thumb_label.setStyleSheet(f"border:1px solid {BORDER};background:black;border-radius:2px;")
        if self.keyframe.thumbnail is not None:
            self._set_thumbnail(self.keyframe.thumbnail)
        layout.addWidget(self.thumb_label)

        # Info
        info_layout = QVBoxLayout()
        name = self.keyframe.name or f"KF {self.index + 1}"
        self.name_label = _lbl(f"<b>{name}</b>")
        info_layout.addWidget(self.name_label)
        mode = "3D" if self.keyframe.dims.get('ndisplay', 3) == 3 else "2D"
        pt   = self.keyframe.dims.get('point', [0, 0, 0])
        sl   = int(pt[0]) if len(pt) > 0 else 0
        self.info_label = _info(f"{mode} | Z={sl} | {self.keyframe.duration}f")
        info_layout.addWidget(self.info_label)
        layout.addLayout(info_layout)
        layout.addStretch()

        btn_del = QPushButton("×")
        btn_del.setFixedSize(20, 20)
        btn_del.setStyleSheet(f"background:{DANGER2};color:#f5b7b1;border:none;border-radius:3px;")
        btn_del.clicked.connect(lambda: self.delete_requested.emit(self.index))
        layout.addWidget(btn_del)

        self.setLayout(layout)
        self.setStyleSheet(f"QWidget{{background:{BG_PANEL};border-radius:3px;}}"
                           f"QWidget:hover{{background:{BG_HOVER};}}")
        self.setCursor(Qt.PointingHandCursor)

    def _set_thumbnail(self, img_array):
        if img_array is None:
            return
        arr = np.ascontiguousarray(img_array)
        h, w = arr.shape[:2]
        if arr.ndim == 3 and arr.shape[2] == 3:
            fmt = QImage.Format_RGB888
            bytes_per_line = 3 * w
            qimg = QImage(arr.tobytes(), w, h, bytes_per_line, fmt)
        elif arr.ndim == 3 and arr.shape[2] == 4:
            fmt = QImage.Format_RGBA8888
            bytes_per_line = 4 * w
            qimg = QImage(arr.tobytes(), w, h, bytes_per_line, fmt)
        else:
            qimg = QImage(arr.tobytes(), w, h, w, QImage.Format_Grayscale8)
        pixmap = QPixmap.fromImage(qimg).scaled(80, 60, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.thumb_label.setPixmap(pixmap)

    def mousePressEvent(self, event):
        self.clicked.emit(self.index)
        super().mousePressEvent(event)

    def set_selected(self, selected: bool):
        if selected:
            self.setStyleSheet(f"QWidget{{background:#2a2a6a;border:2px solid {ACCENT};"
                               f"border-radius:3px;}}")
        else:
            self.setStyleSheet(f"QWidget{{background:{BG_PANEL};border-radius:3px;}}"
                               f"QWidget:hover{{background:{BG_HOVER};}}")


class AnimationTab(QWidget):
    def __init__(self, state: PluginState):
        super().__init__()
        self.state = state
        self.keyframes: List[Keyframe] = []
        self.selected_index = -1
        self._preview_running = False
        self._preview_timer = None
        self._current_frame = 0
        self._frames: List[Keyframe] = []
        self._spin_worker = None
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout()
        layout.setSpacing(6)
        self.setStyleSheet(f"background:{BG_MID};")

        # ── Sub-tabs: Keyframe Movie / Spin Movie ─────────────────────
        self.sub_tabs = QTabWidget()
        self.sub_tabs.setStyleSheet(TAB_STYLE)
        self.sub_tabs.addTab(self._build_keyframe_tab(), "Keyframe Movie")
        self.sub_tabs.addTab(self._build_spin_tab(),     "Spin Movie")
        layout.addWidget(self.sub_tabs)

        self.setLayout(layout)

        # Timer for mode indicator
        self._mode_timer = QTimer()
        self._mode_timer.timeout.connect(self._update_mode_display)
        self._mode_timer.start(500)

    # ── KEYFRAME MOVIE SUB-TAB ────────────────────────────────────────

    def _build_keyframe_tab(self):
        w = QWidget()
        w.setStyleSheet(f"background:{BG_MID};")
        layout = QVBoxLayout(w)
        layout.setSpacing(6)

        if not HAS_IMAGEIO:
            layout.addWidget(_info("⚠️  Install: pip install imageio imageio-ffmpeg"))
            return w

        # 1. CAPTURE
        g1 = _group("1 ▸ CAPTURE KEYFRAMES")
        l1 = QVBoxLayout()
        btn_cap = _btn("📸  Capture Current State", "capture")
        btn_cap.clicked.connect(self._capture_keyframe)
        l1.addWidget(btn_cap)
        row = QHBoxLayout()
        row.addWidget(_lbl("Mode:"))
        self.label_mode = _lbl("3D", bold=True, color=ACCENT)
        row.addWidget(self.label_mode)
        row.addWidget(_lbl("  Z:"))
        self.label_slice = _lbl("0")
        row.addWidget(self.label_slice)
        row.addStretch()
        l1.addLayout(row)
        g1.setLayout(l1)
        layout.addWidget(g1)

        # 2. KEYFRAME LIST
        g2 = _group("2 ▸ KEYFRAMES")
        l2 = QVBoxLayout()
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setMinimumHeight(150)
        self.scroll_area.setMaximumHeight(200)
        self.scroll_area.setStyleSheet(SCROLL_STYLE)
        self.keyframe_container = QWidget()
        self.keyframe_layout = QVBoxLayout()
        self.keyframe_layout.setSpacing(2)
        self.keyframe_layout.addStretch()
        self.keyframe_container.setLayout(self.keyframe_layout)
        self.scroll_area.setWidget(self.keyframe_container)
        l2.addWidget(self.scroll_area)
        row = QHBoxLayout()
        btn_clr = _btn("🗑  Clear All", "danger")
        btn_clr.clicked.connect(self._clear_keyframes)
        row.addWidget(btn_clr)
        btn_upd = _btn("🔄  Update Selected", "secondary")
        btn_upd.clicked.connect(self._update_selected)
        row.addWidget(btn_upd)
        l2.addLayout(row)
        row = QHBoxLayout()
        btn_up = _btn("↑", "secondary")
        btn_up.setFixedWidth(30)
        btn_up.clicked.connect(self._move_up)
        row.addWidget(btn_up)
        btn_dn = _btn("↓", "secondary")
        btn_dn.setFixedWidth(30)
        btn_dn.clicked.connect(self._move_down)
        row.addWidget(btn_dn)
        row.addWidget(_lbl("Duration:"))
        self.spin_duration = QSpinBox()
        self.spin_duration.setRange(10, 300)
        self.spin_duration.setValue(60)
        self.spin_duration.setStyleSheet(INPUT_STYLE)
        self.spin_duration.valueChanged.connect(self._update_duration)
        row.addWidget(self.spin_duration)
        row.addWidget(_lbl("frames"))
        l2.addLayout(row)
        g2.setLayout(l2)
        layout.addWidget(g2)

        # 3. SETTINGS
        g3 = _group("3 ▸ SETTINGS")
        l3 = QVBoxLayout()
        row = QHBoxLayout()
        row.addWidget(_lbl("FPS:"))
        self.spin_fps = QSpinBox()
        self.spin_fps.setRange(10, 60)
        self.spin_fps.setValue(30)
        self.spin_fps.setStyleSheet(INPUT_STYLE)
        row.addWidget(self.spin_fps)
        row.addWidget(_lbl("Format:"))
        self.combo_format = QComboBox()
        self.combo_format.addItems(["MP4", "GIF", "PNG Sequence"])
        self.combo_format.setStyleSheet(INPUT_STYLE)
        row.addWidget(self.combo_format)
        l3.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(_lbl("Interpolation:"))
        self.combo_interp = QComboBox()
        self.combo_interp.addItems(["Smoothstep", "Linear", "Ease-in", "Ease-out"])
        self.combo_interp.setStyleSheet(INPUT_STYLE)
        row.addWidget(self.combo_interp)
        l3.addLayout(row)
        g3.setLayout(l3)
        layout.addWidget(g3)

        # 4. PREVIEW & EXPORT
        g4 = _group("4 ▸ PREVIEW & EXPORT")
        l4 = QVBoxLayout()
        row = QHBoxLayout()
        self.btn_preview = _btn("▶  Preview", "primary")
        self.btn_preview.clicked.connect(self._start_preview)
        row.addWidget(self.btn_preview)
        self.btn_stop = _btn("⏹  Stop", "danger")
        self.btn_stop.clicked.connect(self._stop_preview)
        self.btn_stop.setEnabled(False)
        row.addWidget(self.btn_stop)
        l4.addLayout(row)
        btn_exp = _btn("💾  Export Movie…", "run")
        btn_exp.clicked.connect(self._export)
        l4.addWidget(btn_exp)
        self.kf_progress = QProgressBar()
        self.kf_progress.setVisible(False)
        self.kf_progress.setStyleSheet(PROGRESS_STYLE)
        l4.addWidget(self.kf_progress)
        g4.setLayout(l4)
        layout.addWidget(g4)

        self.status_label = _info_box("Capture keyframes to begin")
        layout.addWidget(self.status_label)
        layout.addStretch()
        return w

    # ── SPIN MOVIE SUB-TAB ────────────────────────────────────────────

    def _build_spin_tab(self):
        w = QWidget()
        w.setStyleSheet(f"background:{BG_MID};")
        layout = QVBoxLayout(w)
        layout.setSpacing(6)

        # Info
        layout.addWidget(_info(
            "Spin Movie rotates the camera 360° around the selected axis "
            "and exports each frame — similar to ChimeraX's 'movie spin' command."
        ))

        # 1. ROTATION SETTINGS
        g1 = _group("1 ▸ ROTATION SETTINGS")
        l1 = QVBoxLayout()

        row = QHBoxLayout()
        row.addWidget(_lbl("Axis:"))
        self.combo_spin_axis = QComboBox()
        self.combo_spin_axis.addItems(["Y  (horizontal)", "X  (vertical)", "Z  (depth)"])
        self.combo_spin_axis.setStyleSheet(INPUT_STYLE)
        row.addWidget(self.combo_spin_axis)
        l1.addLayout(row)

        row = QHBoxLayout()
        row.addWidget(_lbl("Frames:"))
        self.spin_spin_frames = QSpinBox()
        self.spin_spin_frames.setRange(12, 720)
        self.spin_spin_frames.setValue(120)
        self.spin_spin_frames.setSingleStep(12)
        self.spin_spin_frames.setStyleSheet(INPUT_STYLE)
        row.addWidget(self.spin_spin_frames)
        row.addWidget(_lbl("FPS:"))
        self.spin_spin_fps = QSpinBox()
        self.spin_spin_fps.setRange(10, 60)
        self.spin_spin_fps.setValue(30)
        self.spin_spin_fps.setStyleSheet(INPUT_STYLE)
        row.addWidget(self.spin_spin_fps)
        l1.addLayout(row)

        row = QHBoxLayout()
        row.addWidget(_lbl("Format:"))
        self.combo_spin_fmt = QComboBox()
        self.combo_spin_fmt.addItems(["MP4", "GIF", "PNG Sequence"])
        self.combo_spin_fmt.setStyleSheet(INPUT_STYLE)
        row.addWidget(self.combo_spin_fmt)
        l1.addLayout(row)

        # Estimated duration
        self.lbl_spin_est = _info("Estimated: 4.0 s at 30 fps")
        l1.addWidget(self.lbl_spin_est)
        self.spin_spin_frames.valueChanged.connect(self._update_spin_estimate)
        self.spin_spin_fps.valueChanged.connect(self._update_spin_estimate)
        g1.setLayout(l1)
        layout.addWidget(g1)

        # 2. EXPORT
        g2 = _group("2 ▸ EXPORT")
        l2 = QVBoxLayout()
        btn_spin = _btn("🌀  Start Spin Movie…", "run")
        btn_spin.clicked.connect(self._start_spin)
        l2.addWidget(btn_spin)
        self.btn_spin_cancel = _btn("✕  Cancel", "danger")
        self.btn_spin_cancel.clicked.connect(self._cancel_spin)
        self.btn_spin_cancel.setEnabled(False)
        l2.addWidget(self.btn_spin_cancel)
        self.spin_progress = QProgressBar()
        self.spin_progress.setVisible(False)
        self.spin_progress.setStyleSheet(PROGRESS_STYLE)
        l2.addWidget(self.spin_progress)
        self.lbl_spin_status = _info_box("Ready")
        l2.addWidget(self.lbl_spin_status)
        g2.setLayout(l2)
        layout.addWidget(g2)

        layout.addStretch()
        return w

    # ── SPIN MOVIE LOGIC ──────────────────────────────────────────────

    def _update_spin_estimate(self):
        n = self.spin_spin_frames.value()
        fps = self.spin_spin_fps.value()
        dur = n / fps
        self.lbl_spin_est.setText(f"Estimated: {dur:.1f} s  ({n} frames at {fps} fps)")

    def _start_spin(self):
        if not HAS_IMAGEIO:
            return show_error("Install imageio: pip install imageio imageio-ffmpeg")
        fmt = self.combo_spin_fmt.currentText()
        if fmt == "MP4":
            path, _ = QFileDialog.getSaveFileName(self, "Save Spin Movie",
                                                   "spin_movie.mp4", "MP4 (*.mp4)")
        elif fmt == "GIF":
            path, _ = QFileDialog.getSaveFileName(self, "Save Spin Movie",
                                                   "spin_movie.gif", "GIF (*.gif)")
        else:
            path = QFileDialog.getExistingDirectory(self, "Select Output Folder for PNG Sequence")
        if not path:
            return

        axis_text = self.combo_spin_axis.currentText()
        axis = axis_text[0]  # 'Y', 'X', or 'Z'
        n_frames = self.spin_spin_frames.value()
        fps = self.spin_spin_fps.value()

        # Ensure 3D mode
        try:
            self.state.viewer.dims.ndisplay = 3
        except Exception:
            pass

        self._spin_worker = SpinMovieWorker(
            self.state.viewer, path, n_frames, fps, axis, fmt)
        self._spin_worker.progress.connect(self._on_spin_progress)
        self._spin_worker.finished.connect(self._on_spin_done)
        self._spin_worker.error.connect(self._on_spin_error)
        self.spin_progress.setVisible(True)
        self.spin_progress.setValue(0)
        self.btn_spin_cancel.setEnabled(True)
        self.lbl_spin_status.setText("Spinning…")
        self._spin_worker.start()

    def _on_spin_progress(self, pct, msg):
        self.spin_progress.setValue(pct)
        self.lbl_spin_status.setText(msg)

    def _on_spin_done(self, path):
        self.spin_progress.setValue(100)
        self.lbl_spin_status.setText(f"Done! Saved: {Path(path).name}")
        self.btn_spin_cancel.setEnabled(False)
        show_info(f"Spin Movie saved: {path}")

    def _on_spin_error(self, err):
        self.lbl_spin_status.setText("Error — see console")
        self.btn_spin_cancel.setEnabled(False)
        show_error(err[:300])

    def _cancel_spin(self):
        if self._spin_worker and self._spin_worker.isRunning():
            self._spin_worker.abort()
        self.btn_spin_cancel.setEnabled(False)
        self.lbl_spin_status.setText("Cancelled")

    # ── KEYFRAME MOVIE LOGIC ──────────────────────────────────────────

    def _update_mode_display(self):
        try:
            ndisplay = self.state.viewer.dims.ndisplay
            self.label_mode.setText("3D" if ndisplay == 3 else "2D")
            point = self.state.viewer.dims.point
            self.label_slice.setText(str(int(point[0])) if len(point) > 0 else "0")
        except Exception:
            pass

    def _capture_full_state(self) -> Keyframe:
        viewer = self.state.viewer
        camera = {
            'center': np.array(viewer.camera.center).copy(),
            'zoom':   float(viewer.camera.zoom),
            'angles': np.array(viewer.camera.angles).copy(),
        }
        dims = {
            'ndisplay': int(viewer.dims.ndisplay),
            'point':    np.array(viewer.dims.point).copy(),
        }
        layer_visibility = {l.name: l.visible for l in viewer.layers}
        layer_opacity    = {l.name: l.opacity for l in viewer.layers}
        QApplication.processEvents()
        QThread.msleep(50)
        thumbnail = viewer.screenshot(canvas_only=True, size=(120, 160))
        if thumbnail.shape[2] == 4:
            thumbnail = thumbnail[:, :, :3]
        return Keyframe(
            camera=camera, dims=dims,
            layer_visibility=layer_visibility,
            layer_opacity=layer_opacity,
            thumbnail=thumbnail,
            name=f"KF {len(self.keyframes) + 1}",
            duration=self.spin_duration.value(),
        )

    def _apply_state(self, kf: Keyframe):
        viewer = self.state.viewer
        # Apply camera — always use plain Python tuples of floats to avoid
        # leaving a 3-element numpy array in vispy's ArcBall _event_value,
        # which would cause "too many values to unpack" on the next mouse drag.
        center = tuple(float(v) for v in kf.camera['center'])
        angles = tuple(float(v) for v in kf.camera['angles'])
        viewer.camera.center = center
        viewer.camera.zoom   = float(kf.camera['zoom'])
        viewer.camera.angles = angles
        # Reset vispy ArcBall internal state so the next mouse drag starts
        # from a clean 2-element (x, y) position instead of a stale 3-tuple.
        try:
            vispy_cam = viewer.window._qt_viewer.canvas.view.camera
            if hasattr(vispy_cam, '_event_value'):
                vispy_cam._event_value = None
        except Exception:
            pass
        viewer.dims.ndisplay = kf.dims['ndisplay']
        if len(kf.dims['point']) > 0:
            viewer.dims.point = tuple(float(v) for v in kf.dims['point'])
        for name, visible in kf.layer_visibility.items():
            if name in viewer.layers:
                viewer.layers[name].visible = visible
        for name, opacity in kf.layer_opacity.items():
            if name in viewer.layers:
                viewer.layers[name].opacity = opacity

    def _capture_keyframe(self):
        kf = self._capture_full_state()
        self.keyframes.append(kf)
        self._refresh_keyframe_list()
        self.status_label.setText(f"Captured keyframe {len(self.keyframes)}")

    def _refresh_keyframe_list(self):
        while self.keyframe_layout.count() > 1:
            item = self.keyframe_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for i, kf in enumerate(self.keyframes):
            widget = KeyframeWidget(i, kf)
            widget.clicked.connect(self._on_keyframe_clicked)
            widget.delete_requested.connect(self._delete_keyframe)
            self.keyframe_layout.insertWidget(i, widget)
            if i == self.selected_index:
                widget.set_selected(True)

    def _on_keyframe_clicked(self, index: int):
        self.selected_index = index
        for i in range(self.keyframe_layout.count() - 1):
            w = self.keyframe_layout.itemAt(i).widget()
            if isinstance(w, KeyframeWidget):
                w.set_selected(i == index)
        if 0 <= index < len(self.keyframes):
            self._apply_state(self.keyframes[index])
            self.spin_duration.setValue(self.keyframes[index].duration)

    def _delete_keyframe(self, index: int):
        if 0 <= index < len(self.keyframes):
            self.keyframes.pop(index)
            if self.selected_index >= len(self.keyframes):
                self.selected_index = len(self.keyframes) - 1
            self._refresh_keyframe_list()

    def _clear_keyframes(self):
        self.keyframes = []
        self.selected_index = -1
        self._refresh_keyframe_list()
        self.status_label.setText("Keyframes cleared")

    def _update_selected(self):
        if 0 <= self.selected_index < len(self.keyframes):
            kf = self._capture_full_state()
            kf.name     = self.keyframes[self.selected_index].name
            kf.duration = self.spin_duration.value()
            self.keyframes[self.selected_index] = kf
            self._refresh_keyframe_list()
            self.status_label.setText(f"Updated keyframe {self.selected_index + 1}")

    def _move_up(self):
        if self.selected_index > 0:
            i = self.selected_index
            self.keyframes[i], self.keyframes[i-1] = self.keyframes[i-1], self.keyframes[i]
            self.selected_index -= 1
            self._refresh_keyframe_list()

    def _move_down(self):
        if self.selected_index < len(self.keyframes) - 1:
            i = self.selected_index
            self.keyframes[i], self.keyframes[i+1] = self.keyframes[i+1], self.keyframes[i]
            self.selected_index += 1
            self._refresh_keyframe_list()

    def _update_duration(self, value):
        if 0 <= self.selected_index < len(self.keyframes):
            self.keyframes[self.selected_index].duration = value

    def _interpolate(self, t: float) -> float:
        interp = self.combo_interp.currentText()
        if interp == "Linear":
            return t
        elif interp == "Smoothstep":
            return t * t * (3 - 2 * t)
        elif interp == "Ease-in":
            return t * t
        elif interp == "Ease-out":
            return 1 - (1 - t) * (1 - t)
        return t

    def _interpolate_state(self, kf1: Keyframe, kf2: Keyframe, t: float) -> Keyframe:
        t = self._interpolate(t)
        camera = {
            'center': kf1.camera['center'] * (1 - t) + kf2.camera['center'] * t,
            'zoom':   kf1.camera['zoom']   * (1 - t) + kf2.camera['zoom']   * t,
            'angles': kf1.camera['angles'] * (1 - t) + kf2.camera['angles'] * t,
        }
        ndisplay = kf1.dims['ndisplay'] if t < 0.5 else kf2.dims['ndisplay']
        point    = kf1.dims['point'] * (1 - t) + kf2.dims['point'] * t
        dims     = {'ndisplay': ndisplay, 'point': point}
        layer_visibility = kf1.layer_visibility.copy() if t < 0.5 else kf2.layer_visibility.copy()
        all_layers = set(kf1.layer_opacity) | set(kf2.layer_opacity)
        layer_opacity = {n: kf1.layer_opacity.get(n, 1.0) * (1 - t) +
                            kf2.layer_opacity.get(n, 1.0) * t
                         for n in all_layers}
        return Keyframe(camera=camera, dims=dims,
                        layer_visibility=layer_visibility,
                        layer_opacity=layer_opacity)

    def _generate_frames(self) -> List[Keyframe]:
        if len(self.keyframes) < 2:
            return []
        frames = []
        for i in range(len(self.keyframes) - 1):
            kf1 = self.keyframes[i]
            kf2 = self.keyframes[i + 1]
            n   = kf1.duration
            for f in range(n):
                t = f / n
                frames.append(self._interpolate_state(kf1, kf2, t))
        frames.append(self.keyframes[-1])
        return frames

    def _start_preview(self):
        if len(self.keyframes) < 2:
            return show_warning("Add at least 2 keyframes")
        self._frames = self._generate_frames()
        self._current_frame = 0
        self._preview_running = True
        self.btn_preview.setEnabled(False)
        self.btn_stop.setEnabled(True)
        interval = max(16, int(1000 / self.spin_fps.value()))
        self._preview_timer = QTimer()
        self._preview_timer.timeout.connect(self._preview_step)
        self._preview_timer.start(interval)

    def _preview_step(self):
        if not self._preview_running or self._current_frame >= len(self._frames):
            self._stop_preview()
            return
        self._apply_state(self._frames[self._current_frame])
        self.status_label.setText(f"Preview: frame {self._current_frame+1}/{len(self._frames)}")
        self._current_frame += 1

    def _stop_preview(self):
        self._preview_running = False
        if self._preview_timer:
            self._preview_timer.stop()
        self.btn_preview.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.status_label.setText("Preview stopped")

    def _export(self):
        if not HAS_IMAGEIO:
            return show_error("Install imageio: pip install imageio imageio-ffmpeg")
        if len(self.keyframes) < 2:
            return show_warning("Add at least 2 keyframes")
        fmt = self.combo_format.currentText()
        if fmt == "MP4":
            path, _ = QFileDialog.getSaveFileName(self, "Export Movie", "movie.mp4", "MP4 (*.mp4)")
        elif fmt == "GIF":
            path, _ = QFileDialog.getSaveFileName(self, "Export Movie", "movie.gif", "GIF (*.gif)")
        else:
            path = QFileDialog.getExistingDirectory(self, "Select Output Folder")
        if not path:
            return
        frames = self._generate_frames()
        if not frames:
            return show_warning("No frames to export")
        fps = self.spin_fps.value()
        self.kf_progress.setVisible(True)
        self.kf_progress.setValue(0)
        self.status_label.setText("Exporting…")
        log("KeyframeMovie EXPORT START",
            params={"frames": len(frames), "fmt": fmt, "fps": fps})
        writer = None
        target_hw = None
        t0 = time.perf_counter()
        try:
            if fmt in ("MP4", "GIF"):
                writer = _open_movie_writer(path, fmt, fps)
            for i, kf in enumerate(frames):
                self._apply_state(kf)
                QApplication.processEvents()
                QThread.msleep(30)
                raw = self.state.viewer.screenshot(canvas_only=True)
                if target_hw is None:
                    frame = _normalize_frame(raw)
                    target_hw = frame.shape[:2]
                else:
                    frame = _normalize_frame(raw, target_hw)
                if fmt in ("MP4", "GIF"):
                    writer.append_data(frame)
                else:
                    p = Path(path)
                    if HAS_TIFFFILE:
                        import tifffile as tf
                        tf.imwrite(str(p / f"frame_{i:04d}.tif"), frame)
                    else:
                        imageio.imwrite(str(p / f"frame_{i:04d}.png"), frame)
                self.kf_progress.setValue(int(100 * (i + 1) / len(frames)))
                QApplication.processEvents()
            if writer is not None:
                writer.close()
                writer = None
            log("KeyframeMovie EXPORT DONE", t0=t0, params={"output": path})
            self.status_label.setText(f"Exported: {Path(path).name}")
            show_info(f"Movie exported: {path}")
        except Exception as e:
            tb = traceback.format_exc()
            log("KeyframeMovie EXPORT FAILED", level="ERROR")
            print(tb)
            self.status_label.setText("Export failed — see terminal log")
            show_error(f"Movie export failed: {e}\n(full traceback in terminal)")
        finally:
            if writer is not None:
                try:
                    writer.close()
                except Exception:
                    pass
            self.kf_progress.setVisible(False)


# ====================================================================
# MAIN PLUGIN WIDGET
# ====================================================================

class Cryo3DEditorWidget(QWidget):
    """Root widget — hosts the tab bar and all sub-tabs."""

    def __init__(self, viewer: napari.Viewer):
        super().__init__()
        # Safe to call here: env mitigations use setdefault and the
        # hardware summary prints only once per process.
        check_hardware()
        self.viewer = viewer
        self.state  = PluginState(viewer)
        self._init_ui()

    def _init_ui(self):
        self.setStyleSheet(f"background:{BG_DARK};color:{TEXT_MAIN};")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # Header
        header = QLabel("🔬  Cryo3D Editor  v3.0")
        header.setStyleSheet(
            f"color:{ACCENT};font-size:14px;font-weight:bold;"
            f"padding:6px;background:{BG_PANEL};border-radius:4px;"
            f"border-bottom:2px solid {ACCENT2};"
        )
        layout.addWidget(header)

        # Main tabs
        tabs = QTabWidget()
        tabs.setStyleSheet(TAB_STYLE)

        self.dust_tab   = HideDustTab(self.state)
        self.erase_tab  = EraseTab(self.state)
        self.color_tab  = ColorTab(self.state)
        self.render_tab = RenderTab(self.state)
        self.anim_tab   = AnimationTab(self.state)

        tabs.addTab(_scrollable(self.dust_tab),   "Dust")
        tabs.addTab(_scrollable(self.erase_tab),  "Erase")
        tabs.addTab(_scrollable(self.color_tab),  "Colors")
        tabs.addTab(_scrollable(self.render_tab), "Render")
        tabs.addTab(_scrollable(self.anim_tab),   "Movie")

        layout.addWidget(tabs)

        # Footer
        footer = _info(f"CPU: {N_CPU} cores  |  GPU: {'✓ ' + GPU_NAME if HAS_CUPY else '✗'}"
                       f"  |  imageio: {'✓' if HAS_IMAGEIO else '✗'}"
                       f"  |  tifffile: {'✓' if HAS_TIFFFILE else '✗'}")
        footer.setStyleSheet(
            f"color:{TEXT_DIM};font-size:10px;padding:2px;"
            f"background:{BG_PANEL};border-radius:3px;")
        layout.addWidget(footer)


# ====================================================================
# NAPARI ENTRY POINT
# ====================================================================

def cryo3d_editor_widget(viewer: napari.Viewer):
    """Factory function registered as a napari widget contribution."""
    check_hardware()
    return Cryo3DEditorWidget(viewer)


# ====================================================================
# STANDALONE LAUNCH
# ====================================================================

if __name__ == "__main__":
    import napari
    # check_hardware MUST run before napari.Viewer() so that macOS Metal
    # environment variables are set before the OpenGL context is created.
    check_hardware()
    viewer = napari.Viewer(title="Cryo3D Editor v3.0")
    widget = Cryo3DEditorWidget(viewer)
    viewer.window.add_dock_widget(widget, name="Cryo3D Editor", area="right")
    napari.run()
