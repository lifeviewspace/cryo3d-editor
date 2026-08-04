"""napari reader contribution — makes File > Open accept .obj / .ply meshes.

Reads a Wavefront OBJ or PLY mesh and returns it as a napari Surface layer,
so meshes exported from the Membrane/manual-seg tools (or elsewhere) can be
opened directly and animated with the Movie tab.
"""
from pathlib import Path

import numpy as np

from ._widget import load_mesh, _reference_scale


def napari_get_reader(path):
    """Return a reader function if `path` is a mesh we can read, else None."""
    p = path[0] if isinstance(path, (list, tuple)) else path
    if isinstance(p, str) and p.lower().endswith((".obj", ".ply")):
        return reader_function
    return None


def _layer_data(path):
    import napari
    verts, faces = load_mesh(path)          # already z,y,x order
    d = verts[:, 0].astype(np.float32)
    rng = float(d.max() - d.min()) or 1.0
    values = (d - d.min()) / rng            # depth shading so it reads as 3D
    try:
        scale = _reference_scale(napari.current_viewer())
    except Exception:
        scale = (1.0, 1.0, 1.0)
    meta = {"name": Path(path).stem, "shading": "smooth", "colormap": "viridis",
            "scale": scale}
    return ((verts, faces, values), meta, "surface")


def reader_function(path):
    """Read one or more mesh paths into napari Surface layer-data tuples."""
    paths = [path] if isinstance(path, str) else list(path)
    return [_layer_data(p) for p in paths]
