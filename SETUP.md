# Malokit

iOS base app for the malocclusion project. It captures the five intraoral
views, runs them through a pluggable analysis engine, and presents IOTN DHC,
IOTN AC, and a 3D arch view against one shared case record.

This drop covers **Phase 0 and Phase 1**: the whole app runs end to end today
using `MockEngine`, which returns the worked example from the pipeline
document (Class II division 1 bilateral, overjet 9.5 mm, AC 8).

Target: iOS 17, SwiftUI, no third party dependencies.

---

## Setting up the Xcode project

1. Xcode, File > New > Project > iOS > App.
2. Product name `Malokit`, interface SwiftUI, language Swift, minimum
   deployment iOS 17.0.
3. Delete the generated `ContentView.swift` and the generated
   `MalokitApp.swift`.
4. Drag the `App`, `Core`, `Capture`, `Analysis`, and `Features` folders into
   the project navigator. Choose **Create groups**, and tick your app target.
5. In the target's Info tab add these keys:

   | Key | Value |
   |---|---|
   | `NSCameraUsageDescription` | Malokit uses the camera to capture the five intraoral views used for IOTN scoring. |
   | `NSPhotoLibraryUsageDescription` | Import existing intraoral photos instead of shooting new ones. |

6. Build and run on a device. The Simulator has no camera, so use the photo
   library button in the capture screen to load dataset images.

---

## File map

```
App/          entry point, Route enum, NavigationStack wiring
Core/Models/  ToothView, MOCDO, AngleResult, ACResult, CaseRecord
Core/Storage/ CaseStore (JSON), ImageStore (files on disk)
Core/Design/  Theme, SeverityBand, card chrome
Capture/      CameraService, live quality checker, guide overlay, review gate
Analysis/     AnalysisEngine protocol, MockEngine, Preprocessor, pipeline
Features/     Home, Analysing, Result summary, DHC, AC, 3D
```

## The one line that swaps in real models

`Analysis/AnalysisPipeline.swift`:

```swift
init(engine: AnalysisEngine = MockEngine())
```

Write `RemoteEngine` or `CoreMLEngine` against the `AnalysisEngine` protocol
and change that default. No view has to move, because no view knows where the
numbers came from.

Suggested server contract when you get there:

```
POST /v1/analyze
  multipart: front, right, left, maxillary, mandibular
  200: { angle, findings[], deciding_component, ac_score, model_3d_url, narrative }

GET  /v1/cases/{id}/model.usdz
```

---

## Decisions baked into the code

**No horizontal flip, ever.** `Preprocessor.prepare` resizes and nothing else.
Angle's classification is scored per side, and a mirrored buccal frame turns a
Class II right into a Class II left with no way to detect it downstream.
Rotation and brightness normalisation are safe, flipping is not. There is a
comment on that function saying so.

**DHC reports MOCDO cases, not 30 grades.** `DHCResult` holds the findings, the
deciding component, and a severity band. `DHCResult.decide(from:)` is the
"take one, the most severe" rule and is the only place that logic lives.

**JSON storage instead of SwiftData.** The result schema will keep moving while
the models are trained, and a JSON snapshot tolerates that without migrations.
`CaseStore` is small enough to swap for a `ModelContainer` once the schema
settles.

**Quality is measured, not assumed.** `QualityChecker` computes Laplacian
variance on the luma plane, live at about 4 fps during capture and again on
every stored photo in the review screen. A blurred occlusal photo quietly
degrades crowding and crossbite detection, and nothing downstream would report
that.

---

## Things you need to calibrate

`Capture/QualityChecker.swift`, `QualityThresholds`:

```swift
static let minSharpness: Double = 55
static let minBrightness: Double = 0.22
static let maxBrightness: Double = 0.88
```

These are starting points. Shoot twenty real intraoral photos, log the
readings, and set the sharpness floor just under your worst acceptable frame.

`Features/AC/ACDetailView.swift` looks for image assets named `ac-1` through
`ac-10` for the reference series. They are not bundled, since the standard
photographs are licensed. Drop yours into the asset catalogue with those names
and the placeholders resolve automatically.

---

## Roadmap from here

| Phase | Work | Status |
|---|---|---|
| 0 | Skeleton, models, mock engine | done |
| 1 | Camera, quality gate, storage | done |
| 2 | DHC and AC detail screens | done |
| 3 | 3D viewer with measuring tool | preview arch in place, needs real mesh |
| 4 | PDF export and LLM narrative | not started |
| 5 | Swap to CoreML or the API | protocol ready |

Phase 3 is functional against a real file already: put a `.usdz`, `.obj`, or
`.scn` in the case folder and set `AnalysisResult.model3DFilename`. Scene units
are millimetres, so the measuring tool needs no rescaling as long as your
reconstruction exports in millimetres too.
