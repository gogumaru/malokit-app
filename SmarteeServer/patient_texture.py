"""Project patient photo color onto reconstructed SSM arch meshes.

This module deliberately uses per-vertex color instead of a UV atlas. Observed
vertices receive a confidence-weighted blend from calibrated views; unseen
vertices receive a smooth patient-enamel fallback.
"""

import glob
import os

import h5py
import cv2
import numpy as np
import skimage.io
import skimage.transform
import trimesh
import xatlas
from scipy.spatial import cKDTree
from scipy.spatial.transform import Rotation

from const import PHOTO_TYPES, PHOTO_DIR, RECONS_IMG_WIDTH


DEFAULT_ENAMEL = np.array([0.82, 0.78, 0.68], dtype=np.float64)


def project_vertices(vertices, rotation_vector, translation, focal_pixels, principal_point):
    """Project world-space row-vector vertices using EMOpt camera parameters."""
    rotation = Rotation.from_rotvec(np.asarray(rotation_vector)).as_matrix()
    camera = np.asarray(vertices) @ rotation.T + np.asarray(translation)
    depth = camera[:, 2]
    safe_depth = np.where(depth > 1e-8, depth, np.nan)
    uv = np.column_stack(
        (
            focal_pixels * camera[:, 0] / safe_depth + principal_point[0],
            focal_pixels * camera[:, 1] / safe_depth + principal_point[1],
        )
    )
    return uv, depth


def _enamel_mask(colors):
    colors = np.asarray(colors, dtype=np.float64)
    maximum = colors.max(axis=1)
    minimum = colors.min(axis=1)
    saturation = (maximum - minimum) / np.maximum(maximum, 1e-6)
    # Teeth range from bright neutral enamel to warm/yellow dentine. The red
    # dominance guard rejects gingiva even when exposure makes it fairly bright.
    return (
        (maximum > 0.28)
        & (saturation < 0.48)
        & ((colors[:, 0] - colors[:, 1]) < 0.24)
        & (colors[:, 1] > colors[:, 2] * 0.78)
    )


def patient_enamel_color(samples, weights):
    """Return a robust weighted patient enamel color, excluding non-tooth pixels."""
    samples = np.asarray(samples, dtype=np.float64)
    weights = np.asarray(weights, dtype=np.float64)
    if samples.size == 0:
        return DEFAULT_ENAMEL.copy()
    keep = _enamel_mask(samples) & np.isfinite(weights) & (weights > 0)
    if not np.any(keep):
        return DEFAULT_ENAMEL.copy()
    samples = samples[keep]
    weights = weights[keep]
    # Replication approximates a weighted median and is much less sensitive to
    # flash highlights than a weighted mean.
    scaled = weights / max(weights.max(), 1e-8)
    repeats = np.clip(np.rint(scaled * 20), 1, 20).astype(int)
    return np.median(np.repeat(samples, repeats, axis=0), axis=0)


def fill_unobserved_colors(vertices, colors, observed):
    """Fill hidden vertices from nearest observed color plus patient median."""
    vertices = np.asarray(vertices, dtype=np.float64)
    result = np.asarray(colors, dtype=np.float64).copy()
    observed = np.asarray(observed, dtype=bool)
    if not np.any(observed):
        result[:] = DEFAULT_ENAMEL
        return result
    palette = np.median(result[observed], axis=0)
    missing = ~observed
    if np.any(missing):
        tree = cKDTree(vertices[observed])
        _, nearest = tree.query(vertices[missing], k=1)
        local = result[observed][nearest]
        result[missing] = 0.65 * local + 0.35 * palette
    return np.clip(result, 0.0, 1.0)


def write_colored_obj(path, colors):
    """Rewrite OBJ vertex records with normalized RGB, preserving all topology lines."""
    colors = np.asarray(colors, dtype=np.float64)
    with open(path, "r", encoding="utf-8") as file:
        lines = file.readlines()
    output = []
    vertex_index = 0
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("v "):
            if vertex_index >= len(colors):
                raise ValueError("OBJ has more vertices than supplied colors")
            parts = stripped.split()
            if len(parts) < 4:
                raise ValueError(f"Invalid OBJ vertex record: {stripped}")
            color = np.clip(colors[vertex_index], 0.0, 1.0)
            output.append(
                f"v {parts[1]} {parts[2]} {parts[3]} "
                f"{color[0]:.6f} {color[1]:.6f} {color[2]:.6f}\n"
            )
            vertex_index += 1
        else:
            output.append(line)
    if vertex_index != len(colors):
        raise ValueError("Supplied colors do not match OBJ vertex count")
    with open(path, "w", encoding="utf-8") as file:
        file.writelines(output)


def build_texture_atlas(vertices, faces, colors, obj_path, png_path, size=2048):
    """Unwrap a mesh and bake its patient colors into a padded PNG atlas."""
    vertices = np.asarray(vertices, dtype=np.float32)
    faces = np.asarray(faces, dtype=np.uint32)
    colors = np.asarray(colors, dtype=np.float64)
    mapping, atlas_faces, uvs = xatlas.parametrize(vertices, faces)
    atlas_vertices = vertices[mapping]
    atlas_colors = colors[mapping]
    image = np.zeros((size, size, 3), dtype=np.float64)
    coverage = np.zeros((size, size), dtype=np.uint8)

    pixels = np.column_stack((uvs[:, 0] * (size - 1), (1.0 - uvs[:, 1]) * (size - 1)))
    for triangle in atlas_faces:
        points = pixels[triangle]
        minimum = np.maximum(np.floor(points.min(axis=0)).astype(int), 0)
        maximum = np.minimum(np.ceil(points.max(axis=0)).astype(int), size - 1)
        if np.any(maximum < minimum):
            continue
        xs, ys = np.meshgrid(
            np.arange(minimum[0], maximum[0] + 1),
            np.arange(minimum[1], maximum[1] + 1),
        )
        sample = np.column_stack((xs.ravel() + 0.5, ys.ravel() + 0.5))
        a, b, c = points
        denominator = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
        if abs(denominator) < 1e-8:
            continue
        w0 = ((b[1] - c[1]) * (sample[:, 0] - c[0]) + (c[0] - b[0]) * (sample[:, 1] - c[1])) / denominator
        w1 = ((c[1] - a[1]) * (sample[:, 0] - c[0]) + (a[0] - c[0]) * (sample[:, 1] - c[1])) / denominator
        w2 = 1.0 - w0 - w1
        inside = (w0 >= -1e-5) & (w1 >= -1e-5) & (w2 >= -1e-5)
        if not np.any(inside):
            continue
        sample = sample[inside].astype(int)
        barycentric = np.column_stack((w0[inside], w1[inside], w2[inside]))
        image[sample[:, 1], sample[:, 0]] = barycentric @ atlas_colors[triangle]
        coverage[sample[:, 1], sample[:, 0]] = 255

    # Pad islands to avoid dark seams under bilinear sampling.
    kernel = np.ones((3, 3), np.uint8)
    for _ in range(6):
        missing = (cv2.dilate(coverage, kernel) > 0) & (coverage == 0)
        if not np.any(missing):
            break
        for channel in range(3):
            dilated = cv2.dilate(image[..., channel].astype(np.float32), kernel)
            image[..., channel][missing] = dilated[missing]
        coverage[missing] = 255
    skimage.io.imsave(png_path, np.rint(np.clip(image, 0, 1) * 255).astype(np.uint8))

    with open(obj_path, "w", encoding="utf-8") as file:
        file.write(f"# Patient texture atlas: {os.path.basename(png_path)}\n")
        for vertex, color in zip(atlas_vertices, atlas_colors):
            file.write(
                "v {:.8f} {:.8f} {:.8f} {:.6f} {:.6f} {:.6f}\n".format(
                    *vertex, *np.clip(color, 0, 1)
                )
            )
        for uv in uvs:
            file.write("vt {:.8f} {:.8f}\n".format(*uv))
        for face in atlas_faces:
            refs = [f"{int(index) + 1}/{int(index) + 1}" for index in face]
            file.write("f " + " ".join(refs) + "\n")


def _load_resized_photos(tag, source_tag=None):
    source_tag = source_tag or tag
    photos = []
    for photo_type in PHOTO_TYPES:
        matches = glob.glob(
            os.path.join(PHOTO_DIR, f"{source_tag}-{photo_type.value}.*")
        )
        if not matches:
            raise FileNotFoundError(f"Missing texture photo for view {photo_type.value}")
        image = skimage.io.imread(matches[0])[..., :3]
        if image.dtype.kind in "ui":
            image = image.astype(np.float64) / np.iinfo(image.dtype).max
        else:
            image = np.clip(image.astype(np.float64), 0.0, 1.0)
        height, width = image.shape[:2]
        scale = RECONS_IMG_WIDTH / width
        photos.append(
            skimage.transform.resize(
                image,
                (int(round(height * scale)), RECONS_IMG_WIDTH, 3),
                preserve_range=True,
                anti_aliasing=True,
            )
        )
    return photos


def _visible_samples(uv, depth, normals_camera, image, combined_uv, combined_depth):
    height, width = image.shape[:2]
    rounded = np.rint(uv).astype(np.int64)
    valid = (
        np.isfinite(uv).all(axis=1)
        & (depth > 1e-6)
        & (rounded[:, 0] >= 0)
        & (rounded[:, 0] < width)
        & (rounded[:, 1] >= 0)
        & (rounded[:, 1] < height)
    )
    # A vertex z-buffer rejects points hidden by the opposite arch/tooth. The
    # tolerance accommodates the final Poisson surface's uneven sampling.
    z_buffer = np.full((height, width), np.inf)
    all_pixels = np.rint(combined_uv).astype(np.int64)
    all_valid = (
        np.isfinite(combined_uv).all(axis=1)
        & (combined_depth > 1e-6)
        & (all_pixels[:, 0] >= 0)
        & (all_pixels[:, 0] < width)
        & (all_pixels[:, 1] >= 0)
        & (all_pixels[:, 1] < height)
    )
    np.minimum.at(
        z_buffer,
        (all_pixels[all_valid, 1], all_pixels[all_valid, 0]),
        combined_depth[all_valid],
    )
    indices = np.flatnonzero(valid)
    if len(indices) == 0:
        return indices, np.empty((0, 3)), np.empty(0)
    pixels = rounded[indices]
    nearest_depth = z_buffer[pixels[:, 1], pixels[:, 0]]
    depth_tolerance = np.maximum(0.75, nearest_depth * 0.015)
    visible = depth[indices] <= nearest_depth + depth_tolerance
    indices = indices[visible]
    pixels = rounded[indices]
    sampled = image[pixels[:, 1], pixels[:, 0]]
    facing = np.clip(np.abs(normals_camera[indices, 2]), 0.12, 1.0)
    enamel = _enamel_mask(sampled)
    return indices[enamel], sampled[enamel], facing[enamel]


def colorize_reconstructed_meshes(h5_file, mesh_dir, tag, photo_source_tag=None):
    """Color upper/lower final meshes from five calibrated patient photographs."""
    paths = [
        os.path.join(mesh_dir, tag, f"Pred_Upper_Mesh_Tag={tag}.obj"),
        os.path.join(mesh_dir, tag, f"Pred_Lower_Mesh_Tag={tag}.obj"),
    ]
    meshes = [trimesh.load(path, process=False, maintain_order=True) for path in paths]
    vertices = [np.asarray(mesh.vertices) for mesh in meshes]
    normals = [np.asarray(mesh.vertex_normals) for mesh in meshes]
    photos = _load_resized_photos(tag, source_tag=photo_source_tag)

    with h5py.File(h5_file, "r") as file:
        group = file["EMOPT"]
        ex_rxyz = group["EX_RXYZ"][:]
        ex_txyz = group["EX_TXYZ"][:]
        focal_pixels = group["FOCLTH"][:] / group["DPIX"][:]
        u0 = group["U0"][:]
        v0 = group["V0"][:]
        relative_rotation = group["RELA_R"][:]
        relative_translation = group["RELA_T"][:]

    color_sums = [np.zeros((len(item), 3)) for item in vertices]
    weight_sums = [np.zeros(len(item)) for item in vertices]
    palette_samples = []
    palette_weights = []

    for view_index, image in enumerate(photos):
        transformed_vertices = []
        transformed_normals = []
        projected = []
        depths = []
        for arch_index in range(2):
            view_vertices = vertices[arch_index]
            view_normals = normals[arch_index]
            # Occlusal photos see one arch. Bite photos use the optimizer's
            # relative lower-to-upper pose before the common camera transform.
            applicable = view_index == arch_index or view_index >= 2
            if not applicable:
                transformed_vertices.append(None)
                transformed_normals.append(None)
                projected.append(None)
                depths.append(None)
                continue
            if arch_index == 1 and view_index >= 2:
                view_vertices = view_vertices @ relative_rotation + relative_translation
                view_normals = view_normals @ relative_rotation
            camera_rotation = Rotation.from_rotvec(ex_rxyz[view_index]).as_matrix()
            camera_normals = view_normals @ camera_rotation.T
            uv, depth = project_vertices(
                view_vertices,
                ex_rxyz[view_index],
                ex_txyz[view_index],
                focal_pixels[view_index],
                (u0[view_index], v0[view_index]),
            )
            transformed_vertices.append(view_vertices)
            transformed_normals.append(camera_normals)
            projected.append(uv)
            depths.append(depth)

        combined_uv = np.concatenate([item for item in projected if item is not None])
        combined_depth = np.concatenate([item for item in depths if item is not None])
        for arch_index in range(2):
            if projected[arch_index] is None:
                continue
            indices, samples, weights = _visible_samples(
                projected[arch_index],
                depths[arch_index],
                transformed_normals[arch_index],
                image,
                combined_uv,
                combined_depth,
            )
            if len(indices) == 0:
                continue
            color_sums[arch_index][indices] += samples * weights[:, None]
            weight_sums[arch_index][indices] += weights
            palette_samples.append(samples)
            palette_weights.append(weights)

    if palette_samples:
        palette = patient_enamel_color(
            np.concatenate(palette_samples), np.concatenate(palette_weights)
        )
    else:
        palette = DEFAULT_ENAMEL.copy()

    for arch_index, path in enumerate(paths):
        observed = weight_sums[arch_index] > 0
        colors = np.tile(palette, (len(vertices[arch_index]), 1))
        colors[observed] = (
            color_sums[arch_index][observed]
            / weight_sums[arch_index][observed, None]
        )
        colors = fill_unobserved_colors(vertices[arch_index], colors, observed)
        texture_path = os.path.join(
            mesh_dir,
            tag,
            "Pred_{}_Texture_Tag={}.png".format("Upper" if arch_index == 0 else "Lower", tag),
        )
        build_texture_atlas(
            vertices[arch_index],
            np.asarray(meshes[arch_index].faces),
            colors,
            path,
            texture_path,
        )
