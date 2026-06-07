# Using the Cryo3D Editor — User Guide

A hands-on guide to cleaning, colouring, rendering and exporting cryo-ET
segmentations with the **Cryo3D Editor** plugin for [napari](https://napari.org).

> **What you will learn**
> - Open napari and load a tomogram and its segmentation.
> - Open the Cryo3D Editor plugin.
> - Use each of the five tabs: **Dust**, **Erase**, **Colors**, **Render**, **Movie**.
> - Export your results as an image or a new `.mrc` file.

---

## Table of contents

1. [Installation](#1-installation)
2. [Getting started — load your data](#2-getting-started--load-your-data)
3. [Open the plugin](#3-open-the-plugin)
4. [The five tabs](#4-the-five-tabs)
5. [Dust — remove small objects & erode](#5--dust--remove-small-objects--erode)
6. [Erase — paint out regions](#6--erase--paint-out-regions)
7. [Colors — recolour, merge & delete labels](#7--colors--recolour-merge--delete-labels)
8. [Render — view & export (incl. Save as MRC)](#8--render--view--export-incl-save-as-mrc)
9. [Movie — animations & spin movies](#9--movie--animations--spin-movies)
10. [A typical workflow](#10-a-typical-workflow)
11. [Troubleshooting](#11-troubleshooting)

---

## 1. Installation

The plugin is **not on PyPI yet**, so install it from the source. Use an
environment that already has napari, then:

```bash
# From a local clone (recommended while editing):
cd cryo3d-editor
pip install -e .

# …or directly from GitHub:
pip install "git+https://github.com/lifeviewspace/cryo3d-editor.git"
```

> A Qt backend (PyQt5/PyQt6) is required — napari already provides one.
> The `[gpu]` extra (CuPy) is optional and **not** available on Apple Silicon;
> the plugin always falls back to CPU.

---

## 2. Getting started — load your data

Launch napari from a terminal:

```bash
napari
```

**Open your file** with **File → Open File(s)…** (or just drag it into the window).

![napari File menu — Open File](images/tut/img1.png)

Select your tomogram (`.mrc`/`.rec`) and/or your segmentation. You can select
several files at once.

![Choosing the .mrc files to open](images/tut/img2.png)

Once loaded, the layer list (bottom-left) shows your layers and the canvas shows
one Z-slice of the volume. Scroll to move through Z.

![Tomogram and segmentation loaded in napari](images/tut/img3.png)

> **Image vs Labels.** An **Image** layer is the raw greyscale density. A
> **Labels** layer is the segmentation: integers where `0` = background and
> `1, 2, 3…` are different objects. Most cleanup tools act on **Labels**.
> If a segmentation loads as an Image, right-click it in the layer list and
> choose **Convert to Labels**.

![Right-click layer menu](images/tut/img4.png)

When displayed as Labels, each object gets its own colour:

![Segmentation shown as coloured labels](images/tut/img5.png)

---

## 3. Open the plugin

Go to the **Plugins** menu and click **Cryo3D Editor**.

![Plugins menu showing Cryo3D Editor](images/tut/img7.png)

The plugin panel docks on the right, with five tabs across the top. Pick the
layer you want to work on in each tab's selector first.

![Cryo3D Editor panel open (Dust tab) next to the data](images/tut/img8.png)

> **Tip — navigation demo.** Scroll through Z and inspect the segmentation:
>
> ![Animated demo of navigating the data](images/plugin_demo.gif)

---

## 4. The five tabs

| Tab | What it does | Typical use |
|-----|--------------|-------------|
| 🧹 **Dust** | Remove small objects; shrink objects (per-object erosion) | Cleaning noisy segmentations |
| ✂️ **Erase** | 2D paint-mask eraser for Labels layers | Manually deleting wrong regions |
| 🎨 **Colors** | Per-label colour, opacity, merge, presets | Making structures readable |
| 💡 **Render** | Lighting, contrast, presets, snapshot, **Save as MRC** | Publication views & export |
| 🎬 **Movie** | Keyframe 3D animation + 360° spin movie | Talks, papers, outreach |

**Natural order:** clean (Dust/Erase) → tidy labels (Colors) → style (Render) →
export → optional animation (Movie).

---

## 5. 🧹 Dust — remove small objects & erode

**Why:** automatic segmentations contain tiny specks ("dust") and structures
that are too thick. This tab cleans both.

1. **1 ▸ Load & Select** — click **📂 Load Segmentation…** or pick a Labels
   layer in the dropdown. Use **↻** to refresh the list.
2. **2 ▸ Performance** — tick **Use GPU** only if you have an NVIDIA GPU.
3. **3 ▸ Erode Thickness** — set the erosion percentage to shrink each object;
   tick **Remove if <** to delete objects that vanish. Click **👁 Preview**,
   then **✓ Apply**.
4. **4 ▸ Hide Dust** — choose a **metric** (`volume`, `area`, `size`, or their
   `rank` versions), set the threshold, then **📊 Analyze** → **👁 Preview** →
   **✓ Apply**.

| Control | What it does | Typical value |
|---------|--------------|---------------|
| Use GPU | Routes erosion/labeling to CuPy if available | Off (macOS) |
| Erode percentage | Shrinks each object by this % of its thickness | 10–30 % |
| Remove if < | Deletes objects that disappear after erosion | On for cleanup |
| Metric | How "small" is measured; `rank` keeps only the top-N largest | volume |
| Connectivity | Which voxels count as touching: 6, 18 or 26 neighbours | 6 or 26 |
| Fill holes < | Closes small holes inside objects | optional |

> **Always Preview before Apply.** Preview shows the result without changing your
> data. Only **✓ Apply** edits the layer; use **↶ Undo** (STATUS section) to revert.

---

## 6. ✂️ Erase — paint out regions

**Why:** some errors are in the wrong place, not just small. Paint a mask by hand
and delete whatever it covers.

1. **1 ▸ Select Layer** — choose the Labels layer.
2. **2 ▸ Paint Mask** — click **🖌 Create Mask**; a red mask layer appears in
   paint mode. Drag on the canvas to paint over regions to remove.
   **🗑 Clear Mask** starts over.
3. **3 ▸ Z Range** — tick **All Z slices**, or set start/end slices to limit the
   depth range.
4. **4 ▸ Actions** — click **✂️ Apply Erase** to delete the painted voxels;
   **↶ Undo** reverts.

> **Brush controls.** While the mask layer is active, change the **brush size**
> with napari's brush slider or the <kbd>[</kbd> / <kbd>]</kbd> keys.

![Painting on the segmentation in napari](images/tut/img6.png)

---

## 7. 🎨 Colors — recolour, merge & delete labels

**Why:** to interpret a segmentation you need to tell structures apart and fix
over-segmentation.

1. **Layer** — pick the Labels layer.
2. **Labels list** — click a label to select it; hold <kbd>Ctrl</kbd> and click
   to select several.
3. **Color & Opacity** — click **🎨 Pick Color** (or a preset) to recolour, and
   use the opacity slider to fade labels.
4. **Actions:**
   - **🎯 Go to** — jump the view to the selected label.
   - **🗑 Erase Label** — delete the selected label(s).
   - **🔗 Merge** — combine several selected labels into one.
   - **🔄 Reset Colors** — restore the default random colour scheme.

> **Merging fixes over-segmentation.** Automatic methods often split one real
> object into several labels. Select the pieces with <kbd>Ctrl</kbd>+click and
> press **🔗 Merge** so they become a single object before measuring or exporting.

![Coloured segmentation with the plugin panel](images/tut/img9.png)

---

## 8. 💡 Render — view & export (incl. Save as MRC)

**Why:** the same data looks flat or striking depending on contrast, lighting and
rendering mode. This tab also exports your results.

1. **1 ▸ Select Layer** (Image or Labels).
2. **2 ▸ Contrast / Opacity & Gamma** — adjust the sliders; **⚡ Auto Contrast**
   picks good limits. For Labels, the sliders control opacity.
3. **3 ▸ Rendering Mode (3D)** — `mip`, `translucent`, `attenuated_mip`, `iso`,
   `average`, `minip`. Set ISO threshold / attenuation when relevant.
4. **4 ▸ Colormap** — pick a colour scheme for Image layers.
5. **5 ▸ Membrane Presets** — **🧬 Membrane**, **🌫 Dense Volume**,
   **🔵 ISO Surface**, or **🔄 Reset to Default**.
6. **6 ▸ Save Snapshot as TIFF** — tick **Canvas only**, then **📸 Save Snapshot…**.
7. **7 ▸ Save as MRC** — tick **Binary mask** to save Labels as 0/1, then
   **💾 Save as MRC…**.

| Rendering mode | Best for |
|----------------|----------|
| `mip` (max intensity) | Bright structures on dark background — the default |
| `attenuated_mip` | Dense/crowded volumes |
| `iso` | Clean surface view of a thresholded object |
| `translucent` / `average` / `minip` | Specialised looks |

> **Save as MRC keeps the voxel size.** The exported `.mrc` writes the voxel size
> into its header (nm → Å) and chooses the right data type automatically:
> `int16` for label masks, `int8` for binary masks, `float32` for tomograms.
> It opens correctly in IMOD, ChimeraX and napari.

---

## 9. 🎬 Movie — animations & spin movies

**Why:** 3D structures are far clearer in motion. This tab has two sub-tabs.

**Keyframe Movie**

1. **1 ▸ Capture Keyframes** — set the 3D view, click **📸 Capture Current
   State**, and repeat for each viewpoint.
2. **2 ▸ Keyframes** — reorder with **↑/↓**, replace with **🔄 Update Selected**,
   or **🗑 Clear All**.
3. **3 ▸ Settings** — format (`MP4`, `GIF`, `PNG Sequence`), interpolation
   (`Smoothstep`, `Linear`, `Ease-in`, `Ease-out`), and fps.
4. **4 ▸ Preview & Export** — **▶ Preview**, then **💾 Export Movie…**.

**Spin Movie**

1. **1 ▸ Rotation Settings** — pick the axis (`Y`, `X`, `Z`) and output format.
2. **2 ▸ Export** — click **🌀 Start Spin Movie…** for an automatic 360°
   rotation. **✕ Cancel** stops it.

> **Set up the look first** in the Render tab — the movie records exactly what is
> on the canvas.

---

## 10. A typical workflow

```
Load data  →  Clean (Dust + Erase)  →  Tidy labels (Colors)
           →  Style view (Render)   →  Export (MRC / TIFF / Movie)
```

Use **Undo** freely at any stage.

---

## 11. Troubleshooting

| Situation | What to do |
|-----------|------------|
| My layer isn't in the dropdown | Click the **↻** refresh button next to the layer selector |
| An operation says "Select layer" | Pick a layer in the tab's selector first |
| I applied something by mistake | Use **↶ Undo** (Dust and Erase tabs keep a history) |
| Preview looks right but nothing changed | Preview never edits data — click **✓ Apply** |
| `No matching distribution found` on install | The package is not on PyPI; install from local or GitHub (see [Installation](#1-installation)) |
| Plugin missing from the Plugins menu | Re-run `pip install -e .` in the active environment |
| 3D view is slow or hangs on large volumes | Switch to 2D, reduce canvas size, or crop the region |
| Colours look wrong after editing (napari 0.7) | Press **🔄 Reset Colors**; make sure you're on the latest version |

---

*Cryo3D Editor v3.0 — tabs: Dust · Erase · Colors · Render · Movie ·
[github.com/lifeviewspace/cryo3d-editor](https://github.com/lifeviewspace/cryo3d-editor) ·
Author: Kennedy Bonjour (lifeviewspace).*
