# Malokit

Base iOS app for the malocclusion project. Captures five intraoral views and
scores them across the IOTN: **DHC** (dental health), **AC** (aesthetic), and
a **3D arch view**. Everything hangs off one shared `CaseRecord`, so the three
features stay one app rather than three.

- Platform: iOS 17, SwiftUI, no third party dependencies
- Inference: pluggable `AnalysisEngine`. Currently `MockEngine` returns a
  worked example, so the whole app runs end to end before any model is trained.
- Setup and architecture notes: see [SETUP.md](SETUP.md)

---

## Who owns what

| Area | Owner | Files |
|---|---|---|
| DHC (MOCDO) | **Anin** | `Core/Models/MOCDO.swift`, `Features/DHC/` |
| Angle's classification | **Anin** | `Core/Models/AngleResult.swift`, result Angle card |
| AC (aesthetic) | **Nana** | `Core/Models/ACResult.swift`, `Features/AC/` |
| 3D reconstruction | **Nico** | `Features/Teeth3D/`, mesh export |
| Report + PDF export | _TBD_ | not started |
| Backend / model serving | _TBD_ | `RemoteEngine` (to be written) |

> Update the owner names once the team is assigned. Keep this table honest, it
> is the fastest way for anyone to know who to ask.

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
- [ ] Wire to real detector output (waiting on model)

### Angle — done (Anin)
- [x] Per side classification: Class I, II div 1, II div 2, III
- [x] Angle card on the result screen with confidence
- [ ] Wire to real classifier output (waiting on model)

### AC — wip (Nana)
- [x] Score model and 1 to 10 severity bands
- [x] AC detail screen with reference strip placeholder
- [ ] Drop the 10 reference photographs into Assets as `ac-1` … `ac-10`
- [ ] Wire to real similarity model output

### 3D — wip (Nico)
- [x] SceneKit viewer, rotate and zoom
- [x] Two point measuring tool in millimetres
- [x] Placeholder arch so the screen is usable now
- [ ] Load real reconstructed mesh (`.usdz` / `.obj`), export in mm

### Report — todo (TBD)
- [ ] PDF export of the full case
- [ ] LLM narrative (currently hardcoded in `MockEngine`)

### Backend — todo (TBD)
- [ ] `RemoteEngine` against the `AnalysisEngine` protocol
- [ ] Swap `MockEngine()` for `RemoteEngine()` in `AnalysisPipeline.swift`

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

The single swap point for real models is one line in
`Analysis/AnalysisPipeline.swift`:

```swift
init(engine: AnalysisEngine = MockEngine())   // change to RemoteEngine()
```

No view knows where the numbers came from, so plugging in the real models does
not touch any UI.

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
