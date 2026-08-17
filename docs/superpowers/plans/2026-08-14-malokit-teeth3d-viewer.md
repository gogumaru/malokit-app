# Malokit Teeth3D Viewer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Malokit's preview-only Teeth3D path with a reliable two-arch textured Smartee viewer while preserving Malokit's UI.

**Architecture:** A focused `ReconstructionSceneLoader` resolves and validates the four saved reconstruction artifacts, loads both OBJ scenes, and exposes stable upper/lower SceneKit nodes plus appearance capability. `Teeth3DView` owns loading/error/preview state and the existing SceneKit bridge updates visibility and materials without rebuilding the scene or resetting the camera.

**Tech Stack:** SwiftUI, SceneKit, UIKit, Swift Testing, iOS 26.5 project target; no third-party dependencies.

## Global Constraints

- Preserve the existing Malokit screen chrome and design tokens.
- Show both arches together and Clinical appearance by default.
- Patient appearance requires two valid PNG textures.
- Preserve millimetre scale and Smartee's existing bite registration.
- Do not change the Smartee HTTP/storage contract.

---

### Task 1: Reconstruction asset and scene contract

**Files:**
- Create: `Malokit/Features/Teeth3D/ReconstructionSceneLoader.swift`
- Test: `MalokitTests/Teeth3DTests.swift`

**Interfaces:**
- Produces `ReconstructionAssetURLs`, `ReconstructionAppearance`, `LoadedReconstructionScene`, and `ReconstructionSceneLoader.load(_:)`.

- [x] Write fixture-based tests proving two OBJ files load under named upper/lower nodes, retain UV sources, expose combined millimetre bounds, and allow Patient appearance only with two valid textures.
- [x] Run only `Teeth3DTests` and confirm failure because the loader contract does not exist.
- [x] Implement the minimal loader and asset resolver.
- [x] Run `Teeth3DTests` and confirm the success cases pass.
- [x] Add missing/corrupt OBJ and missing/corrupt texture tests; confirm failures, then implement explicit errors and Clinical-only fallback.

### Task 2: Malokit-styled viewer integration

**Files:**
- Modify: `Malokit/Features/Teeth3D/Teeth3DView.swift`
- Modify: `Malokit/Features/Result/ResultSummaryView.swift`
- Test: `MalokitTests/Teeth3DTests.swift`

**Interfaces:**
- Consumes the Task 1 loader and loaded scene.
- Produces preview, loading, ready, and artifact-error screen states.

- [x] Add failing state/visibility tests for defaults: Clinical, upper visible, lower visible, Patient unavailable without both textures.
- [x] Replace `model3DFilename` lookup with the reconstruction record's upper/lower OBJ and texture filenames.
- [x] Load asynchronously, show Malokit progress/error cards, and preserve the preview only for cases without completed reconstruction.
- [x] Add the Clinical/Patient segmented control inside the existing bottom card and keep the Upper/Lower controls below it.
- [x] Update named arch nodes in place so appearance and visibility changes preserve camera state; clear measurements only after visibility or measuring-mode changes.
- [x] Change the result card detail from “viewer integration is next” to “Tap to inspect the reconstructed arches.”

### Task 3: Camera, materials, and measurement hardening

**Files:**
- Modify: `Malokit/Features/Teeth3D/ReconstructionSceneLoader.swift`
- Modify: `Malokit/Features/Teeth3D/Teeth3DView.swift`
- Test: `MalokitTests/Teeth3DTests.swift`

- [x] Add failing tests for combined-centre/radius calculations and direct millimetre distance.
- [x] Centre the combined root, fit the camera from the combined bounds, retain rotate/zoom controls, and install Malokit key/ambient lighting.
- [x] Apply neutral enamel PBR materials in Clinical mode and clamped linear PNG textures in Patient mode.
- [x] Keep hit-testing and ruler calculations on visible arch geometry; do not scale the model root.
- [x] Re-run `Teeth3DTests` after the refactor.

### Task 4: Final verification

- [x] Run the full Malokit test target and confirm zero failures.
- [x] Build for `generic/platform=iOS` with signing disabled and confirm exit 0.
- [x] Run `git diff --check`.
- [x] Inspect one real Smartee upper/lower OBJ + PNG pair for UV presence, millimetre bounds, and load success; record physical-device texture/gesture validation as the only deferred check if no device is connected.
