# -*- coding: utf-8 -*-
"""Cryo3DEditor v2.0.

Combines manual segmentation, density brush and particle lists with the
Colors and Movie tabs from Cryo3D Editor.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from contextlib import contextmanager
from typing import Dict, List, Tuple

import numpy as np
import napari
from qtpy.QtWidgets import QApplication

def _load_module(module_name, source):
    """Load a Python module by its path, including names that contain dots."""
    if not source.is_file():
        raise ImportError(f"Required source file was not found: {source}")
    spec = importlib.util.spec_from_file_location(module_name, source)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load source from {source}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


_manual_source = Path(__file__).with_name("manu_seg_3d.py")
_editor_source = (
    Path(__file__).resolve().parent.parent
    / "3d_editor"
    / "3D Editor"
    / "cryo3d_editor_2.py"
)

manual = _load_module("manual_segmentation_with_particles", _manual_source)
editor = _load_module("cryo3d_editor_v2_source", _editor_source)
project = _load_module("c3d_project", Path(__file__).with_name("c3d_project.py"))
movie_spin = _load_module("c3d_movie_spin", Path(__file__).with_name("c3d_movie_spin.py"))
SpinAnimationTab = movie_spin.build_tab_class(editor)


class IntegratedState(manual.PluginState):
    """State shared by manual segmentation, Colors and Movie.

    The manual plugin only needs ``viewer``.  Colors also needs label colour
    metadata and a small volume-history stack; Movie reads the viewer plus
    these colour settings when capturing a keyframe.
    """

    MAX_HISTORY = 10

    def __init__(self, viewer: napari.Viewer):
        super().__init__(viewer)
        self.history: List[Tuple[str, np.ndarray]] = []
        self.history_idx = -1
        self.label_colors: Dict[str, Dict[int, Tuple[float, float, float, float]]] = {}
        self.label_opacities: Dict[str, Dict[int, float]] = {}
        self._color_init_done = set()
        self.colors_tab = None          # set by the widget; see quiet_colors_tab()

    @contextmanager
    def quiet_colors_tab(self):
        """Replacing a Labels colormap makes napari emit `selected_label`;
        the Colors tab answers that by turning `show_selected_label` back
        on (its highlight feature), which on napari 0.7 left label layers
        painted with the selected label's colour over the whole slice.
        Use the tab's own `_syncing` guard so only real picks highlight."""
        tab = self.colors_tab
        prev = getattr(tab, "_syncing", False)
        if tab is not None:
            tab._syncing = True
        try:
            yield
        finally:
            if tab is not None:
                tab._syncing = prev

    def get_labels(self):
        return [layer for layer in self.viewer.layers if isinstance(layer, manual.Labels)]

    def get_labels_layer(self, name: str):
        for layer in self.get_labels():
            if layer.name == name:
                return layer
        return None

    def save_history(self, name, data):
        if self.history_idx < len(self.history) - 1:
            self.history = self.history[: self.history_idx + 1]
        self.history.append((name, np.asarray(data).copy()))
        self.history_idx = len(self.history) - 1
        while len(self.history) > self.MAX_HISTORY:
            self.history.pop(0)
            self.history_idx -= 1

    def can_undo(self):
        return self.history_idx >= 0

    @staticmethod
    def _rgba_int_to_float(rgba):
        return tuple(float(value) / 255.0 for value in rgba)

    @staticmethod
    def _rgba_float_to_int(rgba):
        return tuple(int(round(float(value) * 255.0)) for value in rgba)

    def _ensure_colors_initialized(self, layer_name):
        if layer_name not in self._color_init_done:
            self._color_init_done.add(layer_name)
            self.initialize_layer_colors(layer_name)

    def set_label_color(self, layer_name, label_value, color_rgba):
        self._ensure_colors_initialized(layer_name)
        self.label_colors.setdefault(layer_name, {})[int(label_value)] = (
            self._rgba_int_to_float(color_rgba)
        )
        self._apply_colormap(layer_name)

    def set_label_opacity(self, layer_name, label_value, opacity):
        self.label_opacities.setdefault(layer_name, {})[int(label_value)] = float(opacity)
        color = self.label_colors.get(layer_name, {}).get(int(label_value))
        if color is not None:
            self.label_colors[layer_name][int(label_value)] = (*color[:3], float(opacity))
            self._apply_colormap(layer_name)

    def get_label_color(self, layer_name, label_value):
        color = self.label_colors.get(layer_name, {}).get(int(label_value))
        return self._rgba_float_to_int(color) if color is not None else None

    def get_label_opacity(self, layer_name, label_value):
        return self.label_opacities.get(layer_name, {}).get(int(label_value), 1.0)

    def _apply_colormap(self, layer_name):
        layer = self.get_labels_layer(layer_name)
        colors = self.label_colors.get(layer_name, {})
        if layer is None or not colors:
            return
        if editor.HAS_DIRECT_COLORMAP:
            try:
                color_dict = {0: (0, 0, 0, 0), None: (0, 0, 0, 0)}
                color_dict.update(colors)
                with self.quiet_colors_tab():
                    layer.colormap = editor.DirectLabelColormap(
                        color_dict=color_dict,
                        use_selection=bool(getattr(layer, "show_selected_label", False)),
                        selection=int(getattr(layer, "selected_label", 1)))
                return
            except Exception:
                pass
        try:
            layer.color = {key: self._rgba_float_to_int(value) for key, value in colors.items()}
        except Exception:
            pass

    def reset_colors(self, layer_name):
        self.label_colors.pop(layer_name, None)
        self.label_opacities.pop(layer_name, None)
        self._color_init_done.discard(layer_name)
        layer = self.get_labels_layer(layer_name)
        if layer is None:
            return
        try:
            from napari.utils.colormaps import label_colormap

            layer.colormap = label_colormap(49)
        except Exception:
            try:
                layer.new_colormap()
            except Exception:
                pass

    def initialize_layer_colors(self, layer_name):
        layer = self.get_labels_layer(layer_name)
        if layer is None:
            return
        values = [int(value) for value in np.unique(layer.data) if value > 0]
        if not values:
            return
        colors = self.label_colors.setdefault(layer_name, {})
        try:
            from napari.utils.colormaps import label_colormap

            palette = label_colormap(49)
            for value in values:
                colors.setdefault(value, tuple(float(c) for c in palette.map(value % 49)[:4]))
        except Exception:
            for value in values:
                colors.setdefault(value, (1.0, 1.0, 1.0, 1.0))
        self._apply_colormap(layer_name)


class Cryo3DEditorV2Widget(manual.QWidget):
    """Dock widget with manual segmentation, Colors and Movie."""

    def __init__(self, viewer: napari.Viewer):
        super().__init__()
        self.state = IntegratedState(viewer)
        self.project_path = None
        self._init_ui()

    def _init_ui(self):
        layout = manual.QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        title = manual.QLabel("══  Cryo3DEditor v2.0  ══")
        title.setAlignment(manual.Qt.AlignCenter)
        title.setStyleSheet(
            "font-weight:bold; font-size:13px; background:#0d1a24; color:#7ff0ff; "
            "padding:6px; border-radius:4px;"
        )
        layout.addWidget(title)

        self.tabs = manual.QTabWidget()
        self.tabs.setStyleSheet(editor.TAB_STYLE)
        self.segmentation_tab = manual.MembraneTab(self.state)
        self.colors_tab = editor.ColorTab(self.state)
        self.state.colors_tab = self.colors_tab
        self.movie_tab = SpinAnimationTab(self.state)

        self.tabs.addTab(editor._scrollable(self.segmentation_tab), "Segmentation")
        self.tabs.addTab(editor._scrollable(self.colors_tab), "Colors")
        self.tabs.addTab(editor._scrollable(self.movie_tab), "Movie")
        layout.addWidget(self.tabs)

        row = manual.QHBoxLayout()
        btn_save = editor._btn("💾  Salvar", "primary")
        btn_save.setToolTip("Salva tudo no projeto atual (.c3dproj)")
        btn_save.clicked.connect(self._save)
        btn_save_as = editor._btn("Salvar como…")
        btn_save_as.clicked.connect(self._save_as)
        btn_open = editor._btn("📂  Abrir projeto")
        btn_open.clicked.connect(self._open)
        for b in (btn_save, btn_save_as, btn_open):
            row.addWidget(b)
        self.lbl_project = editor._info("Projeto: (não salvo)")
        layout.addWidget(self.lbl_project)
        self.chk_embed = manual.QCheckBox("Incluir tomogramas no arquivo (projeto completo)")
        self.chk_embed.setChecked(True)
        self.chk_embed.setToolTip(
            "Ligado: o projeto abre em qualquer computador, mesmo sem o .mrc original "
            "(arquivo maior).\nDesligado: guarda só o caminho do tomograma.")
        layout.addWidget(self.chk_embed)
        layout.addLayout(row)

    # ── project save / open ──────────────────────────────────────────
    def _set_project(self, path):
        self.project_path = path
        self.lbl_project.setText(f"Projeto: {Path(path).name}")

    def _save(self):
        if self.project_path is None:
            return self._save_as()
        self._write(self.project_path)

    def _save_as(self):
        path, _ = manual.QFileDialog.getSaveFileName(
            self, "Salvar projeto", "", f"Projeto Cryo3D (*{project.EXTENSION})")
        if not path:
            return
        if not path.endswith(project.EXTENSION):
            path += project.EXTENSION
        self._write(path)

    def _write(self, path):
        QApplication.setOverrideCursor(manual.Qt.WaitCursor)
        try:
            project.save_project(self, path, embed_images=self.chk_embed.isChecked(),
                                 log=manual.log)
        except Exception as exc:
            project.log_exception(manual.log, "━━ SAVE FAILED ━━", exc, {"file": path})
            manual.show_error(f"Não consegui salvar o projeto: {exc} (detalhes no terminal)")
            return
        finally:
            QApplication.restoreOverrideCursor()
        self._set_project(path)
        manual.show_info(f"Projeto salvo: {Path(path).name}")

    def _locate(self, name, old_path):
        manual.QMessageBox.information(
            self, "Tomograma não encontrado",
            f"'{name}' não está mais em:\n{old_path}\n\nMostre onde ele está agora.")
        path, _ = manual.QFileDialog.getOpenFileName(self, f"Onde está {name}?")
        return path or None

    def _open(self):
        if len(self.state.viewer.layers) and manual.QMessageBox.question(
            self, "Abrir projeto",
            "Abrir um projeto substitui tudo o que está aberto agora. Continuar?",
            manual.QMessageBox.Yes | manual.QMessageBox.No,
        ) != manual.QMessageBox.Yes:
            return
        path, _ = manual.QFileDialog.getOpenFileName(
            self, "Abrir projeto", "", f"Projeto Cryo3D (*{project.EXTENSION})")
        if path:
            self.open_project(path)

    def open_project(self, path, locate=None):
        QApplication.setOverrideCursor(manual.Qt.WaitCursor)
        try:
            warnings = project.load_project(self, path, manual, editor,
                                            locate=locate or self._locate, log=manual.log)
        except Exception as exc:
            project.log_exception(manual.log, "━━ OPEN FAILED ━━", exc, {"file": path})
            manual.show_error(f"Não consegui abrir o projeto: {exc} (detalhes no terminal)")
            return
        finally:
            QApplication.restoreOverrideCursor()
        self._set_project(path)
        for w in warnings:
            manual.show_warning(w)
        manual.show_info(f"Projeto aberto: {Path(path).name}")


def make_widget(viewer: napari.Viewer) -> Cryo3DEditorV2Widget:
    """Napari dock-widget entry point."""
    return Cryo3DEditorV2Widget(viewer)


if __name__ == "__main__":
    viewer = napari.Viewer(title="Cryo3DEditor v2.0")
    widget = Cryo3DEditorV2Widget(viewer)
    viewer.window.add_dock_widget(widget, area="right", name="Cryo3DEditor v2.0")
    napari.run()
