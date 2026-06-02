"""napari-cryo3d-editor: napari plugin for 3D cryo-ET visualization,
label post-processing, and movie production."""

__version__ = "3.0.0"

from ._widget import Cryo3DEditorWidget, cryo3d_editor_widget

__all__ = ["Cryo3DEditorWidget", "cryo3d_editor_widget"]
