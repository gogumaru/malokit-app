"""Standalone open3d mesh builder, run as a throwaway subprocess by main.py.

open3d 0.16.0's Poisson surface reconstruction segfaults intermittently on
macOS/arm64 (~1 in 6 runs), even in a clean process. Isolating it here lets
main.py retry on a crash instead of losing the whole optimization run, whose
result is already saved to the input h5 file.

Usage: python build_mesh.py <h5File> <meshDir> <tag>
"""
import os

os.environ.setdefault("OMP_NUM_THREADS", "1")
import sys

import h5py
import numpy as np

import pcd_mesh_utils as pm_util


def create_mesh(h5File, meshDir, tag):
    with h5py.File(h5File, "r") as f:
        grp = f["EMOPT"]
        X_Pred_Upper = grp["UPPER_PRED"][:]
        X_Pred_Lower = grp["LOWER_PRED"][:]
        RELA_R = grp["RELA_R"][:]
        RELA_T = grp["RELA_T"][:]

    # Apply the fitted bite relative pose (from frontal/lateral photo
    # evidence) so the lower arch lands in bite contact with the upper
    # arch instead of its own independent optimization frame.
    X_Pred_Lower = X_Pred_Lower @ RELA_R + RELA_T

    upper = pm_util.mergeO3dTriangleMeshes(
        [pm_util.surfaceVertices2WatertightO3dMesh(pg) for pg in X_Pred_Upper]
    )
    lower = pm_util.mergeO3dTriangleMeshes(
        [pm_util.surfaceVertices2WatertightO3dMesh(pg) for pg in X_Pred_Lower]
    )

    outDir = os.path.join(meshDir, "{}/".format(tag))
    os.makedirs(outDir, exist_ok=True)
    pm_util.exportTriMeshObj(
        np.asarray(upper.vertices),
        np.asarray(upper.triangles),
        os.path.join(outDir, "Pred_Upper_Mesh_Tag={}.obj".format(tag)),
    )
    pm_util.exportTriMeshObj(
        np.asarray(lower.vertices),
        np.asarray(lower.triangles),
        os.path.join(outDir, "Pred_Lower_Mesh_Tag={}.obj".format(tag)),
    )


if __name__ == "__main__":
    create_mesh(sys.argv[1], sys.argv[2], sys.argv[3])
