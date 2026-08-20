"""
Image preparation pipeline for 3D Teeth Reconstruction
- Auto-detects any image format (JPG, JPEG, PNG, etc.)
- Converts to proper PNG
- Upscales to 1440x1080
- Enhances sharpness and contrast
- Backs up originals
"""

import os
import glob
import shutil
import sys
from PIL import Image, ImageFilter, ImageEnhance

INPUT_DIR = "./seg/valid/image"
OUTPUT_DIR = "./seg/valid/image_upscaled"
BACKUP_DIR = "./seg/valid/image_backup"
TARGET_WIDTH = 1440
TARGET_HEIGHT = 1080

os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(BACKUP_DIR, exist_ok=True)


def find_image(patient_id, view_id):
    """Find image file regardless of extension (JPG, JPEG, PNG, etc.)"""
    for ext in ["png", "PNG", "jpg", "JPG", "jpeg", "JPEG"]:
        path = os.path.join(INPUT_DIR, f"{patient_id}-{view_id}.{ext}")
        if os.path.exists(path):
            return path
    return None


def process_image(image_path, patient_id, view_id):
    """Convert, upscale and enhance a single image"""
    print(f"\nProcessing {os.path.basename(image_path)}...")

    img = Image.open(image_path)

    # Convert to RGB (handles JPEG, RGBA, grayscale, etc.)
    if img.mode != "RGB":
        img = img.convert("RGB")

    original_size = img.size
    print(f"  Original: {original_size[0]}x{original_size[1]}, mode={img.mode}")

    # Scale up to cover target dimensions
    scale = max(TARGET_WIDTH / original_size[0], TARGET_HEIGHT / original_size[1])
    new_w = int(original_size[0] * scale)
    new_h = int(original_size[1] * scale)
    print(f"  Upscaling to: {new_w}x{new_h} ({scale:.2f}x)")
    img = img.resize((new_w, new_h), Image.LANCZOS)

    # Center crop to exact 1440x1080
    left = (new_w - TARGET_WIDTH) // 2
    top  = (new_h - TARGET_HEIGHT) // 2
    img = img.crop((left, top, left + TARGET_WIDTH, top + TARGET_HEIGHT))
    print(f"  Cropped to: {TARGET_WIDTH}x{TARGET_HEIGHT}")

    # Enhance sharpness and contrast
    img = img.filter(ImageFilter.SHARPEN)
    img = ImageEnhance.Contrast(img).enhance(1.1)
    img = ImageEnhance.Sharpness(img).enhance(1.2)

    # Save as true PNG
    out_path = os.path.join(OUTPUT_DIR, f"{patient_id}-{view_id}.png")
    img.save(out_path, "PNG", compress_level=0)
    print(f"  ✅ Saved → {out_path}")
    return out_path


def backup_originals(patient_id):
    """Back up all original files (any extension) for this patient"""
    print(f"\n📦 Backing up originals for patient {patient_id}...")
    count = 0
    for view_id in range(5):
        src = find_image(patient_id, view_id)
        if src:
            dst = os.path.join(BACKUP_DIR, os.path.basename(src))
            shutil.copy2(src, dst)
            count += 1
    print(f"  ✅ Backed up {count} files → {BACKUP_DIR}/")


def replace_originals(patient_id):
    """Copy upscaled PNGs into INPUT_DIR and remove old files"""
    print(f"\n🔄 Replacing originals with upscaled PNGs...")
    count = 0
    for view_id in range(5):
        # Remove any old version (any extension)
        for ext in ["png", "PNG", "jpg", "JPG", "jpeg", "JPEG"]:
            old = os.path.join(INPUT_DIR, f"{patient_id}-{view_id}.{ext}")
            if os.path.exists(old):
                os.remove(old)

        # Copy upscaled PNG in
        src = os.path.join(OUTPUT_DIR, f"{patient_id}-{view_id}.png")
        dst = os.path.join(INPUT_DIR,  f"{patient_id}-{view_id}.png")
        if os.path.exists(src):
            shutil.copy2(src, dst)
            count += 1
    print(f"  ✅ Replaced {count} images in {INPUT_DIR}/")


def verify(patient_id):
    """Verify all upscaled images are correct size and format"""
    print(f"\n🔍 Verifying upscaled images...")
    ok = True
    for view_id in range(5):
        path = os.path.join(OUTPUT_DIR, f"{patient_id}-{view_id}.png")
        if os.path.exists(path):
            img = Image.open(path)
            status = "✅" if img.size == (TARGET_WIDTH, TARGET_HEIGHT) else "❌"
            print(f"  {status} {os.path.basename(path)}: {img.size[0]}x{img.size[1]} PNG")
            if img.size != (TARGET_WIDTH, TARGET_HEIGHT):
                ok = False
        else:
            print(f"  ❌ {patient_id}-{view_id}.png: NOT FOUND")
            ok = False
    return ok


def main(patient_id, auto_replace):
    print("=" * 70)
    print("🦷 Image Preparation Pipeline")
    print("=" * 70)
    print(f"\nPatient ID : {patient_id}")
    print(f"Target     : {TARGET_WIDTH}x{TARGET_HEIGHT} PNG")

    # Check all 5 images exist (any format)
    images = []
    for view_id in range(5):
        path = find_image(patient_id, view_id)
        if path:
            images.append((path, view_id))
        else:
            print(f"\n❌ Missing image for view {view_id}.")
            print(f"   Expected: {patient_id}-{view_id}.png/jpg in {INPUT_DIR}/")
            return

    print(f"\n✅ Found {len(images)} images:")
    for p, v in images:
        print(f"   {os.path.basename(p)}")

    backup_originals(patient_id)

    for path, view_id in images:
        try:
            process_image(path, patient_id, view_id)
        except Exception as e:
            print(f"  ❌ Failed on view {view_id}: {e}")
            return

    if not verify(patient_id):
        print("\n❌ Verification failed.")
        return

    print("\n" + "=" * 70)
    print("✅ All images processed and verified!")
    print("=" * 70)

    if auto_replace:
        replace_originals(patient_id)
        print(f"\n✅ Done! Images replaced in {INPUT_DIR}/")
        print(f"   Originals backed up in {BACKUP_DIR}/")
    else:
        print(f"\n� Upscaled images saved to: {OUTPUT_DIR}/")
        print(f"   Review them, then run with --replace to apply:")
        print(f"   python simple_upscale.py --patient {patient_id} --replace")


if __name__ == "__main__":
    patient_id   = "3"
    auto_replace = False

    if "--help" in sys.argv or "-h" in sys.argv:
        print("Usage: python simple_upscale.py [--patient ID] [--replace]")
        print("\nOptions:")
        print("  --patient ID    Patient ID to process (default: 3)")
        print("  --replace, -r   Replace originals after processing")
        print("\nExamples:")
        print("  python simple_upscale.py --patient 4 --replace")
        sys.exit(0)

    if "--replace" in sys.argv or "-r" in sys.argv:
        auto_replace = True

    if "--patient" in sys.argv:
        idx = sys.argv.index("--patient")
        if idx + 1 < len(sys.argv):
            patient_id = sys.argv[idx + 1]

    main(patient_id, auto_replace)
