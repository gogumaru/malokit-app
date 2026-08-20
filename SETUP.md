# Malokit — Setup

iOS app for the malocclusion project. It captures the five intraoral views,
runs them through a pluggable analysis engine, and presents IOTN DHC, IOTN
AC, and a 3D arch view against one shared case record.

The app itself always runs end to end with `MockEngine` and no server. Real
DHC/Angle detection, the trained AC score, and 3D reconstruction each come
from their own piece, described below.

Target: iOS 17, SwiftUI, no third party dependencies.

---

## Opening the project

1. Clone the repo and open `Malokit.xcodeproj` in Xcode 17.
2. Build and run. The Info.plist keys (camera and photo library usage
   descriptions) are already baked into the project settings, nothing to add
   by hand.
3. The Simulator has no camera, so use the photo library button in the
   capture screen to load dataset images, or run on a real iPhone.

---

## File map

```
Malokit/
  App/            entry point, Route enum, NavigationStack wiring
  Core/Models/    ToothView, MOCDO, AngleResult, ACResult, CaseRecord
  Core/Storage/   CaseStore (JSON), ImageStore (files on disk)
  Core/Design/    Theme, SeverityBand, card chrome
  Capture/        CameraService, live quality checker, guide overlay, review gate
  Analysis/       AnalysisEngine protocol, MockEngine, RemoteEngine,
                  ACCoreMLEngine, ServerSettings, reconstruction clients, pipeline
  Features/       Home, Analysing, Result, DHC, AC, Teeth3D, Overlay, Settings
  Report/         PDF export (ReportBuilder, ReportExportButton)
  MLModels/       ACGrader.mlpackage — the trained on-device AC model

dhc_server/       Python backend: DHC + Angle from the five photos (own README)
SmarteeServer/    Python backend: 3D teeth reconstruction (own readme.md)
```

`dhc_server/` and `SmarteeServer/` are separate Python services, not part of
the Xcode target — they run on a Mac on the same network as the phone.

---

## Running the backend servers

Both are **local dev servers**: plain HTTP, no auth, meant for the phone and
your Mac to be on the same Wi-Fi network — not for deploying anywhere.

Whichever server you run, the phone doesn't discover it automatically — you
have to type that Mac's LAN IP into the app's **Settings screen** (gear icon
→ **Server**) yourself, every time the Mac's IP changes (new network, DHCP
renewal, etc.).

Find it with:

```bash
ipconfig getifaddr en0   # or en1 if you're on Ethernet/USB, not Wi-Fi
```

### DHC server (`dhc_server/`)

1. Start it:

   ```bash
   cd dhc_server
   pip install -r requirements.txt
   uvicorn app:app --host 0.0.0.0 --port 8000
   ```

   - Reads model weights from `model-explore/runs/...` (see
     `dhc_pipeline/config.py`) — four files, ~22 MB total. `GET /v1/health`
     reports which ones are missing.
   - No weights yet? Run in stub mode instead, which replies with a fixed
     example so you can prove the app↔server handshake works:
     `DHC_STUB=1 uvicorn app:app --port 8000`.
   - Full details (endpoints, overlay geometry, known model limitations,
     security notes) are in [`dhc_server/README.md`](dhc_server/README.md).

2. Find the Mac's IP with `ipconfig getifaddr en0` (see above).

3. On the phone: open the app → **Settings → Server** → turn on **"Use the
   DHC server"** → type `http://<that IP>:8000` into **DHC server address**
   → tap **Test connection** (should hit `/v1/health` and come back green).

### 3D reconstruction server (`SmarteeServer/`)

1. Start it:

   ```bash
   cd SmarteeServer
   SMARTEE_EDGE_BACKEND=rfdetr venv_py39/bin/python server.py
   ```

   - Needs a Python **3.9** virtualenv named `venv_py39` in `SmarteeServer/`
     with `requirements.txt` installed — the ML stack here (TensorFlow 2.6,
     Ray, etc.) is pinned to old versions that don't run on newer Python.
     Create it once with `python3.9 -m venv venv_py39 && venv_py39/bin/pip
     install -r requirements.txt`.
   - `SMARTEE_EDGE_BACKEND` selects the edge-mask backend (`rfdetr` or `h5`,
     defaults to `h5` if unset).
   - This spawns `python main.py <tag>` as a subprocess per request rather
     than reconstructing in-process, because the EM-optimization step is
     known to occasionally segfault on macOS/arm64 — a crash then only fails
     that one request. See the header comment in `server.py` for the full
     request flow.
   - Runs on port 8000 too (hardcoded in `server.py`'s `app.run(...)` call)
     — if you need both servers on the same Mac at once, either run them on
     different Macs or edit one of the ports locally.

2. Find the Mac's IP with `ipconfig getifaddr en0` (same command — if both
   servers run on the same Mac, it's the same IP, different port).

3. On the phone: **Settings → Server** → scroll to **"3D model server"** →
   type `http://<that IP>:8000` into the address field → **Test connection**
   (hits `/health`). The bundled default in
   `ServerReconstructor.defaultBaseURL` is one machine's old LAN IP; treat it
   as a placeholder, not something to rely on.

---

## Choosing mock vs. real engines at runtime

Nothing to rebuild for this. `ServerSettings.makeEngine()` picks the engine
based on what's set in the app's Settings screen — see the README's
["How the pieces connect"](README.md#how-the-pieces-connect) for the code.
Short version:

- DHC and Angle come from `RemoteEngine` (talks to `dhc_server`) when "Use
  the DHC server" is on and an address is set, otherwise `MockEngine`.
- AC always runs on device against `MLModels/ACGrader.mlpackage`, regardless
  of that toggle.
- 3D reconstruction is a separate toggle again: it runs whenever a 3D model
  server address is configured, independent of the DHC one.

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

**JSON storage instead of SwiftData.** The result schema keeps moving while
the backend models are iterated on, and a JSON snapshot tolerates that
without migrations. `CaseStore` is small enough to swap for a
`ModelContainer` once the schema settles.

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

`MLModels/ACGrader.mlpackage` is the trained AC model already bundled with
the app — no manual asset drop needed. Retraining it just means swapping
that file for a new `.mlpackage` with the same name.

---

## Known gaps

- **Report narrative isn't generated.** `ReportBuilder` prints
  `AnalysisResult.narrative` when present, but `RemoteEngine` sets it to
  `nil` — the LLM step described in `Core/Models/CaseRecord.swift` isn't
  wired up yet.
- **3D texture orientation hasn't been validated on a physical LiDAR
  iPhone.** The figure-8 sweep and viewer work end to end against recorded
  data; a real-device pass is still outstanding.
- `dhc_server`'s own limitations (canine detector missing ~25% of lateral
  photos, lower-arch crowding thresholds uncalibrated, no auth, etc.) are
  documented in [`dhc_server/README.md`](dhc_server/README.md#batasan-yang-harus-tercermin-di-ui)
  — read that before treating its output as ground truth.
