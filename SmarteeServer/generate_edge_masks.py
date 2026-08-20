"""
Generate teeth boundary edge masks for a given patient.
Shows what the segmentation model sees as tooth outlines.

Post-processing recovers faint boundaries the model saw but the default 0.5
cutoff discarded, then bridges small gaps so broken tooth loops close up.

Outputs per view in demo/edge_masks/{patient_id}/:
  {id}-{view}.png                 <- consumable by main.py (no suffix) when
                                     present as an override mask.
  {id}-{view}-{name}_raw.png      thin skeleton (inspection)
  {id}-{view}-{name}_enhanced.png thick line (inspection)
  {id}-{view}-{name}_overlay.png  green line on the photo (inspection)
"""

import os
import sys
import glob
import numpy as np
import skimage.io
import skimage.transform
import skimage.morphology as morph
import cv2

os.environ["CUDA_VISIBLE_DEVICES"] = "-1"

from seg.seg_const import IMG_SHAPE, EXPANSION_RATE
from seg.seg_model import ASPP_UNet
from const import PHOTO_TYPES, PHOTO_DIR, RECONS_IMG_WIDTH

OUTPUT_DIR = "./demo/edge_masks"
os.makedirs(OUTPUT_DIR, exist_ok=True)

WEIGHT_CKPT = "./seg/weights/weights-teeth-boundary-model.h5"

VIEW_NAMES = {0: "upper", 1: "lower", 2: "left", 3: "right", 4: "frontal"}

# --- tunables: sweep these per patient if molars are still missing/merged ---
THRESH = 0.3        # boundary prob cutoff (was 0.5). Lower = recover faint edges, but more noise.
CLOSE_RADIUS = 3    # bridge gaps up to ~2*radius px. Too big merges neighbouring teeth into blobs.
MIN_SIZE = 30       # drop connected components smaller than this many px (denoise).


def prob_to_edge(prob_map, mask_shape):
    """probability map -> clean thin boundary (bool), gaps closed, specks removed."""
    p = skimage.transform.resize(prob_map, mask_shape)
    mask = p > THRESH
    mask = morph.binary_closing(mask, morph.disk(CLOSE_RADIUS))  # bridge broken loops
    mask = morph.remove_small_objects(mask, min_size=MIN_SIZE)   # kill false attractors
    return morph.skeletonize(mask)


def raw_probability_map(model, imgfile):
    """model boundary probability at native photo aspect (before thresholding)."""
    img = skimage.io.imread(imgfile)[..., :3]  # drop alpha, see seg/utils.py
    h, w = img.shape[:2]
    scale = RECONS_IMG_WIDTH / w
    rimg = skimage.transform.resize(img, IMG_SHAPE)
    prob = np.squeeze(model.predict(rimg[None, :]))
    return prob, (int(scale * h), int(scale * w))


def generate_edge_masks(patient_id):
    print(f"\n{'='*60}")
    print(f"Generating edge masks for patient {patient_id}  (thresh={THRESH})")
    print(f"{'='*60}")

    print("Loading segmentation model...")
    model = ASPP_UNet(IMG_SHAPE, filters=[16, 32, 64, 128, 256])
    model.load_weights(WEIGHT_CKPT)
    print("Model loaded.")

    patient_dir = os.path.join(OUTPUT_DIR, str(patient_id))
    os.makedirs(patient_dir, exist_ok=True)

    for phtype in PHOTO_TYPES:
        view_id = phtype.value
        view_name = VIEW_NAMES[view_id]

        imgfile = glob.glob(os.path.join(PHOTO_DIR, f"{patient_id}-{view_id}.png"))
        if not imgfile:
            print(f"  ❌ Image not found: {patient_id}-{view_id}.png")
            continue
        imgfile = imgfile[0]
        print(f"\n  Processing view {view_id} ({view_name})...")

        prob, mask_shape = raw_probability_map(model, imgfile)
        edge = prob_to_edge(prob, mask_shape)                       # thin bool line
        edge_thin = (255 * edge).astype(np.uint8)

        # thicken to match the boundary expansion the model was trained/eval'd with
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        edge_thick = cv2.dilate(edge_thin, kernel, iterations=EXPANSION_RATE)

        # THE file main.py actually reads (override hook, no suffix):
        skimage.io.imsave(os.path.join(patient_dir, f"{patient_id}-{view_id}.png"), edge_thick)

        # inspection copies:
        base = os.path.join(patient_dir, f"{patient_id}-{view_id}-{view_name}")
        skimage.io.imsave(f"{base}_raw.png", edge_thin)
        skimage.io.imsave(f"{base}_enhanced.png", edge_thick)

        orig = skimage.io.imread(imgfile)
        orig = (skimage.transform.resize(orig, (edge_thick.shape[0], edge_thick.shape[1]),
                                         anti_aliasing=True) * 255).astype(np.uint8)[..., :3]
        orig[edge_thick > 0] = [0, 255, 0]
        skimage.io.imsave(f"{base}_overlay.png", orig)

        print(f"  ✅ {patient_id}-{view_id}.png (used by main.py) + raw/enhanced/overlay")

    print(f"\n✅ All edge masks saved to: {patient_dir}/")
    return patient_dir


if __name__ == "__main__":
    patient_id = "0"
    if "--patient" in sys.argv:
        idx = sys.argv.index("--patient")
        if idx + 1 < len(sys.argv):
            patient_id = sys.argv[idx + 1]
    if "--help" in sys.argv:
        print("Usage: python generate_edge_masks.py [--patient ID]")
        print("Example: python generate_edge_masks.py --patient 5")
        sys.exit(0)

    output_dir = generate_edge_masks(patient_id)
    os.system(f'open "{output_dir}"')
