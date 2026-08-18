# Malokit Teeth3D Viewer Design

## Goal

Display Smartee's saved upper and lower OBJ reconstructions in Malokit's existing Teeth3D screen without adopting TeethLidar's screen layout.

## Experience

- Keep Malokit's navigation, clinical grey surface, rounded control card, ruler action, measurement readout, and SceneKit rotate/zoom gestures.
- Show both bite-registered arches together by default.
- Add a `Clinical` / `Patient` appearance selector to the existing bottom card. `Clinical` is the default; `Patient` is available only when both saved PNG textures decode.
- Keep the existing Upper and Lower visibility controls. Visibility changes preserve the camera but clear measurement markers; appearance changes preserve both.
- Centre and frame the combined millimetre-scale bounds once after loading. Do not add a synthetic lower-arch offset because Smartee already applies bite registration.

## Loading and failure behavior

- Resolve upper/lower OBJ and optional texture URLs from `AnalysisResult.reconstruction` rather than the legacy single `model3DFilename` field.
- Load both OBJ scenes away from the main UI path, combine their geometry under stable `upperArch` and `lowerArch` nodes, and retain the OBJ UV coordinates.
- Apply Malokit's neutral PBR enamel material in Clinical mode and the corresponding PNG diffuse texture in Patient mode.
- Keep the current preview arch when the case has no completed reconstruction.
- If a completed reconstruction is recorded but either OBJ is missing or malformed, show a Malokit warning state instead of silently substituting the preview.

## Constraints

- iOS/SwiftUI/SceneKit only; no new dependency and no server contract change.
- Scene units remain millimetres, so the ruler continues to report direct Euclidean distance in mm.
- TeethLidar may inform mesh handling, but no TeethLidar black background, flat white panels, titles, or control layout are copied.

## Verification

- Unit-test asset resolution, paired OBJ loading, UV retention, appearance availability, combined bounds, and missing/corrupt artifact failures with temporary fixtures.
- Re-run the complete Malokit test target and a generic iOS build.
- Load one real Smartee OBJ/PNG pair for a manual simulator/device visual check; final texture orientation and touch feel require physical-device confirmation.
