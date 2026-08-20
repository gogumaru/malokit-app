# Malokit

Base iOS app for the malocclusion project. Captures five intraoral views and
scores them across the IOTN: **DHC** (dental health), **AC** (aesthetic), and
a **3D arch view**. Everything hangs off one shared `CaseRecord`, so the three
features stay one app rather than three.

- Platform: iOS 17, SwiftUI, no third party dependencies
- Inference: pluggable `AnalysisEngine`. `MockEngine` is the default so the
  whole app runs end to end with no server. DHC and Angle can be pointed at
  the real `dhc_server` model via the "Use the DHC server" toggle in Settings,
  and AC always runs on the trained on-device Core ML model.
- Setup and architecture notes: see [SETUP.md](SETUP.md)

---

## Who owns what

| Area | Owner | Files |
|---|---|---|
| DHC (MOCDO) | **Anin** | `Core/Models/MOCDO.swift`, `Features/DHC/` |
| Angle's classification | **Anin** | `Core/Models/AngleResult.swift`, result Angle card |
| AC (aesthetic) | **Nana** | `Core/Models/ACResult.swift`, `Features/AC/` |
| 3D reconstruction | **Nico** | `Features/Teeth3D/`, mesh export |
| Report + PDF export | **Anin** | `Report/ReportBuilder.swift`, `Report/ReportExportButton.swift` |
| Backend / model serving | **Nico** | `Analysis/RemoteEngine.swift`, `Analysis/ServerSettings.swift`, `dhc_server/`, `SmarteeServer/` |

> Have a question about a specific area? Ask the owner listed above.

---

## Progress

Legend: **done** shipped and working, **wip** in progress, **todo** not started.

### App shell and capture — done
- [x] Navigation, routing, case storage (JSON + image files)
- [x] Five view camera with per view guide overlay
- [x] Live photo quality check (blur and brightness)
- [x] Review and retake gate before analysis
- [x] Analysing screen with per stage progress
- [x] Result summary with verdict and three feature cards
- [x] `MockEngine` driving the full flow

### DHC — done (Anin)
- [x] MOCDO model: missing, overjet, crossbite, displacement, overbite
- [x] "Take one, the most severe" rule in `DHCResult.decide(from:)`
- [x] DHC detail screen: deciding case, detected list, checked and clear
- [x] Millimetre thresholds shown per component
- [x] Wire to real detector output, via `RemoteEngine` against `dhc_server`
      (toggle "Use the DHC server" in Settings)

### Angle — done (Anin)
- [x] Per side classification: Class I, II div 1, II div 2, III
- [x] Angle card on the result screen with confidence
- [x] Wire to real classifier output, same `dhc_server` response as DHC

### AC — done (Nana)
- [x] Score model and 1 to 10 severity bands
- [x] AC detail screen
- [x] Wire to the real model: `ACGraderRegressor` Core ML model
      (`MLModels/ACGrader.mlpackage`), always runs on device regardless of
      DHC's engine
- Note: the reference-photo strip (`ac-1` … `ac-10`) was dropped in favour
  of the Core ML score and is commented out in `ACDetailView.swift`

### 3D — done (Nico)
- [x] SceneKit viewer, rotate and zoom
- [x] Two point measuring tool in millimetres
- [x] Load Smartee upper/lower OBJ meshes and patient textures in millimetres
      (the placeholder arch is gone; the viewer only shows a real reconstruction)
- [x] Figure-8 LiDAR sweep after each direct intraoral capture, uploaded with
      the photos, with live server stage progress on the 3D card

### Report — done (Anin)
- [x] PDF export of the full case

### Backend — done (Nico)
- [x] `RemoteEngine` against the `AnalysisEngine` protocol
- [x] Runtime toggle between `MockEngine` and `RemoteEngine` via
      `ServerSettings.useRemote` (Settings screen), no rebuild needed

---

## How the pieces connect

```
Capture (5 views)
      │
      ▼
AnalysisPipeline ── engine ──> AnalysisResult ──> stored on CaseRecord
      │                              │
      │                              ├─ AngleResult
      │                              ├─ DHCResult
      │                              ├─ ACResult
      │                              └─ model3D URL
      ▼
Result summary ──> DHC / AC / 3D detail screens
```

The single swap point for real models is `ServerSettings.makeEngine()` in
`Analysis/ServerSettings.swift`:

```swift
func makeEngine() -> AnalysisEngine {
    let dhcSource: AnalysisEngine = (useRemote && isConfigured) ? RemoteEngine(settings: self) : MockEngine()
    return ACCoreMLEngine(fallback: dhcSource)
}
```

DHC and Angle come from `dhcSource`, whichever it is; AC is a separate,
on-device pipeline (`ACCoreMLEngine`'s own Core ML model) and always runs
regardless of that choice. `dhcSource` picks `MockEngine` or `RemoteEngine`
based on the "Use the DHC server" toggle in Settings, at run time rather than
compile time, so no rebuild is needed to switch between them. No view knows
where the numbers came from, so plugging in the real models does not touch
any UI.

---

## Working together without stepping on each other

- Each feature lives in its own folder under `Features/`, so two people editing
  DHC and AC rarely touch the same file.
- Shared models are in `Core/Models/`. Changing a shared struct affects
  everyone, so mention it in the commit message.
- Branch per feature: `dhc-detector`, `ac-model`, `teeth-3d`. Open a pull
  request into `main` so others can glance at the change before it lands.
- After pulling someone else's work: Product > Clean Build Folder
  (Shift+Cmd+K) if the build acts strange.

---

## Running it today

1. Open `Malokit.xcodeproj` in Xcode 17.
2. The Simulator has no camera. Use the photo library button in the capture
   screen to load dataset images, or run on a real iPhone.
3. Shoot or import all five views, run analysis, and you get the mock result
   (Class II division 1, overjet 9.5 mm, AC 8).

See [SETUP.md](SETUP.md) for the Info.plist keys, calibration notes, and the
backend contract.
