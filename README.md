# napari-cryo3d-editor

A [napari] plugin for 3D cryo-electron tomography (cryo-ET) visualization,
label post-processing, and high-impact movie production.

## Features

The plugin adds a dockable **Cryo3D Editor** widget with five tabs:

- 🧹 **Dust** — hide/remove small objects (per-object erosion)
- ✂️ **Erase** — 2D paint-mask eraser for Labels layers
- 🎨 **Colors** — per-label colour, opacity, merge, presets
- 💡 **Render** — lighting, contrast & membrane enhancement
- 🎬 **Movie** — keyframe-based 3D animation + 360° Spin Movie export

Optional GPU acceleration via CuPy is detected automatically when available.

📖 **New here? See the illustrated [User Guide (USAGE.md)](USAGE.md)** — how to
load data, open the plugin, and use each tab, with screenshots.

## Installation

Requires Python ≥ 3.9 and a Qt backend (e.g. PyQt5).

### From source

```bash
git clone https://github.com/lifeviewspace/cryo3d-editor.git
cd cryo3d-editor
pip install -e .
```

Or install the dependencies directly:

```bash
pip install -r requirements.txt
pip install -e .
```

## Usage

1. Launch napari: `napari`
2. Open **Plugins → Cryo3D Editor**.
3. Load a tomogram (`.mrc`/`.rec`) and/or a Labels layer, then use the tabs.

You can also run it standalone:

```bash
python -m napari_cryo3d_editor._widget
```

## Dependencies

Core: napari, numpy, scipy, scikit-image, qtpy, mrcfile, imageio,
imageio-ffmpeg, tifffile.

Optional GPU acceleration (NVIDIA, CUDA 12.x): `pip install cupy-cuda12x`.
Not available on Apple Silicon — the plugin falls back to CPU automatically.

## License

Distributed under the terms of the [BSD-3-Clause] license.

## Author

Kennedy Bonjour

[napari]: https://napari.org
[BSD-3-Clause]: https://opensource.org/licenses/BSD-3-Clause
