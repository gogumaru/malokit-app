# RF-DETR tooth segmentation

This directory contains the replacement-model experiment for Smartee's 2D tooth segmentation. It does not modify the existing ASPP U-Net or its weights.

## 1. Prepare the Roboflow export

`prepare_dataset.py` uses only the Python standard library. It:

1. reads all `train`, `valid`, and `test` COCO files from the Roboflow ZIP;
2. infers a patient ID from each original image name;
3. merges the source classes `teeth` and `tooth` into one `tooth` class;
4. creates deterministic 70/15/15 patient-level splits;
5. copies the referenced images and writes normalized COCO annotations; and
6. writes `split_summary.json` so the split can be audited and reproduced.

From the Smartee directory, run:

```bash
python3 seg/rfdetr/prepare_dataset.py
```

The script automatically finds the only ZIP under `seg/datasets/roboflow/`. To select paths explicitly:

```bash
python3 seg/rfdetr/prepare_dataset.py \
  --archive "seg/datasets/roboflow/Upper and Lower Teeth.v1i.coco-segmentation.zip" \
  --output seg/rfdetr/prepared \
  --seed 42
```

The output layout is compatible with COCO-based training:

```text
prepared/
├── train/
│   ├── _annotations.coco.json
│   └── images...
├── valid/
│   ├── _annotations.coco.json
│   └── images...
├── test/
│   ├── _annotations.coco.json
│   └── images...
└── split_summary.json
```

The program refuses to replace an existing output directory. This protects an earlier prepared dataset from accidental overwrite; choose another `--output` path if you want a different split.

## 2. Install RF-DETR

RF-DETR uses modern PyTorch dependencies, so it has its own environment rather than changing Smartee's working `venv_py39` environment:

```bash
python3.11 -m venv .venv-rfdetr
.venv-rfdetr/bin/python -m pip install "rfdetr[train]==1.9.0"
```

You do not need to activate the environment when using its Python path directly.

## 3. Test training

First run a one-epoch smoke test on a tiny temporary subset:

```bash
.venv-rfdetr/bin/python seg/rfdetr/train.py --smoke-test
```

The smoke test answers only whether model loading, mask decoding, gradient computation, validation, and checkpoint writing work together on this computer. It is not expected to produce an accurate dental model.

After the smoke test passes, start the initial full training run:

```bash
.venv-rfdetr/bin/python seg/rfdetr/train.py \
  --epochs 50 \
  --output seg/rfdetr/runs/small-baseline
```

The default device is `auto`: Apple Silicon uses MPS, NVIDIA systems use CUDA, and other systems fall back to CPU.

## 4. Evaluate the selected checkpoint

Use the `checkpoint_best_total.pth` file selected from validation performance, then evaluate it once on the untouched test patients:

```bash
.venv-rfdetr/bin/python seg/rfdetr/evaluate.py
```

This writes `test_metrics.json` next to the training checkpoints. Test metrics must not influence another training run or model-selection decision.

## 5. Generate edge-mask previews

The RF-DETR model predicts a filled mask for each tooth. `predict_edges.py` traces every individual mask perimeter and combines those perimeters into one binary edge image, which is the representation Smartee needs.

```bash
.venv-rfdetr/bin/python seg/rfdetr/predict_edges.py \
  --input seg/rfdetr/prepared/test/*.jpg \
  --output seg/rfdetr/runs/small-baseline/test-edge-previews
```

Each input produces a binary `*_edge.png`, a different-colour
`*_overlay.png`, one binary `<stem>-instance-<NNN>.png` per detected tooth,
and an entry in the schema-versioned worker `manifest.json`. The individual
masks retain source RGB geometry; the combined edge remains the legacy
reconstruction input.

## 6. Use RF-DETR in Smartee

The existing `.h5` model remains the default. Select the optional RF-DETR mode for a manual reconstruction with:

```bash
venv_py39/bin/python main.py PATIENT_ID --edge-backend rfdetr
```

Or start the local server in RF-DETR mode:

```bash
SMARTEE_EDGE_BACKEND=rfdetr venv_py39/bin/python server.py
```

RF-DETR runs as a subprocess through `.venv-rfdetr`, so its PyTorch dependencies do not alter Smartee's Python 3.9 environment. The selected multiview checkpoint handles all five views.

For server requests, the policy is:

```text
Take 5 Pictures: modelMode=baseline-only -> RF-DETR first -> .h5 fallback
Upload 5 Photos: no modelMode -> SMARTEE_EDGE_BACKEND unchanged
```

Valid RF-DETR views retain their per-instance mask PNGs under
`demo/_temp/instance_masks/<model-tag>/`; each request also has
`instances.json` and a coloured inspection overlay. An invalid RF-DETR output
falls back only for that view when the process and top-level manifest remain
valid; a subprocess failure falls back the attempted batch. Local instance IDs
are storage identifiers, not FDI labels or cross-view tooth identities.

### Milestone 2 inventory

```text
instance-000 is view-local storage, never FDI.
observed is direct valid RF-DETR evidence.
unknown is insufficient or contradictory patient evidence.
inferred is a design-only completion record, not measured anatomy.
confirmedAbsent requires supplied clinical confirmation metadata.
The inventory does not change EM optimization or tooth-existence masks.
```

## 7. Train the combined multiview model

When multiple Roboflow COCO ZIPs are present in `seg/datasets/roboflow`, prepare a new combined dataset without replacing the baseline split:

```bash
python3 seg/rfdetr/prepare_dataset.py \
  --output seg/rfdetr/prepared-multiview
```

Ambiguous filenames are retained as training-only samples, while images with no annotations are reported and excluded. Start from the successful baseline weights while creating a fresh optimizer and training state:

```bash
.venv-rfdetr/bin/python seg/rfdetr/train.py \
  --dataset seg/rfdetr/prepared-multiview \
  --initial-checkpoint seg/rfdetr/runs/small-baseline/checkpoint_best_total.pth \
  --epochs 50 \
  --output seg/rfdetr/runs/small-multiview
```

The selected multiview checkpoint is `small-multiview/checkpoint_best_regular.pth`. Evaluate it once on the untouched combined test split with:

```bash
.venv-rfdetr/bin/python seg/rfdetr/evaluate.py \
  --checkpoint seg/rfdetr/runs/small-multiview/checkpoint_best_regular.pth \
  --dataset seg/rfdetr/prepared-multiview \
  --output seg/rfdetr/runs/small-multiview/test_metrics.json
```
