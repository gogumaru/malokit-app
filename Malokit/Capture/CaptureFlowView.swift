import ARKit
import PhotosUI
import SwiftUI

struct CaptureFlowView: View {
    let caseID: UUID
    @Binding var path: [Route]

    @Environment(CaseStore.self) private var store
    @State private var camera = CameraService()
    @StateObject private var lidarCamera = WorldLiDARCaptureController()
    @State private var current: ToothView = .front
    @State private var flashFrame = false
    @State private var pickerItem: PhotosPickerItem?
    @State private var previewSize: CGSize = .zero
    @State private var captureMessage: String?

    private var record: CaseRecord? { store.record(caseID) }
    private var usesLiDAR: Bool {
        ARWorldTrackingConfiguration.supportsFrameSemantics(.sceneDepth)
    }
    private var isSweeping: Bool { lidarCamera.sweepState == .accumulating }
    private var isInteractionLocked: Bool {
        (usesLiDAR ? lidarCamera.isCapturing : camera.isCapturing) || pickerItem != nil
    }
    private var liveQuality: QualityReading? {
        usesLiDAR ? lidarCamera.liveQuality : camera.liveQuality
    }

    var body: some View {
        GeometryReader { geometry in
            ZStack {
                Color.black.ignoresSafeArea()
                preview

                if isSweeping {
                    centreCrosshair(tint: sweepGuidanceTint)
                    sweepOverlay
                } else {
                    GuideOverlay(view: current, isReady: liveQuality?.isAcceptable ?? false)
                        .ignoresSafeArea()
                    VStack {
                        stepStrip
                        Spacer()
                        instructionPanel
                        controls
                    }
                    .padding(.horizontal, 20)
                    .padding(.bottom, 24)
                }

                if flashFrame {
                    Color.white.ignoresSafeArea().transition(.opacity)
                }
            }
            .onAppear { previewSize = geometry.size }
            .onChange(of: geometry.size) { _, size in previewSize = size }
        }
        .navigationTitle("Capture")
        .navigationBarTitleDisplayMode(.inline)
        .toolbarBackground(.hidden, for: .navigationBar)
        .toolbarColorScheme(.dark, for: .navigationBar)
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                Button {
                    if usesLiDAR {
                        lidarCamera.toggleTorch()
                    } else {
                        camera.flashOn.toggle()
                    }
                } label: {
                    let torchOn = usesLiDAR ? lidarCamera.isTorchOn : camera.flashOn
                    Image(systemName: torchOn ? "bolt.fill" : "bolt.slash")
                }
                .tint(.white)
                .disabled(isInteractionLocked)
            }
        }
        .onAppear {
            current = record?.nextViewToCapture ?? .front
            if !usesLiDAR { camera.start() }
        }
        .onDisappear {
            camera.stop()
            if usesLiDAR { lidarCamera.stop() }
        }
        .onChange(of: pickerItem) { _, item in
            guard let item else { return }
            let captureView = current
            Task { await importFromLibrary(item, for: captureView) }
        }
    }

    @ViewBuilder
    private var preview: some View {
        if usesLiDAR {
            WorldLiDARARCameraView(controller: lidarCamera)
                .ignoresSafeArea()
            if !lidarCamera.isConfigured, let message = lidarCamera.statusMessage {
                messageState(title: "Preparing LiDAR camera", detail: message)
            }
        } else {
            switch camera.status {
            case .running:
                CameraPreview(session: camera.session).ignoresSafeArea()
            case .denied:
                permissionState
            case .failed(let message):
                messageState(title: "Camera unavailable", detail: message)
            case .idle:
                ProgressView().tint(.white)
            }
        }
    }

    // MARK: - Pieces

    private var stepStrip: some View {
        HStack(spacing: 8) {
            ForEach(ToothView.captureOrder) { view in
                let done = record?.filename(for: view) != nil
                Button {
                    current = view
                } label: {
                    VStack(spacing: 5) {
                        Text("\(view.step)")
                            .font(.footnote.weight(.semibold))
                            .frame(width: 26, height: 26)
                            .background(
                                Circle().fill(
                                    done ? Theme.accent
                                    : view == current ? .white.opacity(0.9)
                                    : .white.opacity(0.18)
                                )
                            )
                            .foregroundStyle(done ? .white : view == current ? Theme.ink : .white)
                        Text(view.title)
                            .font(.system(size: 9, weight: .medium))
                            .foregroundStyle(.white.opacity(view == current ? 1 : 0.6))
                            .lineLimit(1)
                    }
                }
                .frame(maxWidth: .infinity)
                .disabled(isInteractionLocked)
            }
        }
        .padding(.vertical, 10)
        .padding(.horizontal, 8)
        .background(.black.opacity(0.35), in: Capsule())
        .padding(.top, 8)
    }

    private var instructionPanel: some View {
        VStack(alignment: .leading, spacing: 6) {
            Eyebrow(text: "Step \(current.step) of 5", tint: .white.opacity(0.7))
            Text(current.instruction)
                .font(.headline)
                .foregroundStyle(.white)
            Text("Feeds: \(current.feeds)")
                .font(.caption)
                .foregroundStyle(.white.opacity(0.65))

            if let quality = liveQuality {
                HStack(spacing: 6) {
                    Image(systemName: quality.isAcceptable ? "checkmark.circle.fill" : "exclamationmark.triangle.fill")
                    Text(quality.summary)
                }
                .font(.caption.weight(.medium))
                .foregroundStyle(quality.isAcceptable ? Theme.accent : Theme.watch)
                .padding(.top, 2)
            }

            if let captureMessage {
                Text(captureMessage)
                    .font(.caption.weight(.medium))
                    .foregroundStyle(Theme.watch)
                    .padding(.top, 2)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(14)
        .background(.black.opacity(0.45), in: RoundedRectangle(cornerRadius: 16, style: .continuous))
        .padding(.bottom, 18)
    }

    private var controls: some View {
        HStack {
            PhotosPicker(selection: $pickerItem, matching: .images) {
                Image(systemName: "photo.on.rectangle")
                    .font(.title3)
                    .foregroundStyle(.white)
                    .frame(width: 52, height: 52)
                    .background(.white.opacity(0.15), in: Circle())
            }
            .disabled(isInteractionLocked)

            Spacer()

            Button(action: shoot) {
                ZStack {
                    Circle().stroke(.white, lineWidth: 3).frame(width: 74, height: 74)
                    Circle().fill(shutterEnabled ? .white : .white.opacity(0.4)).frame(width: 60, height: 60)
                }
            }
            .disabled(!shutterEnabled)

            Spacer()

            Button {
                path.append(.review(caseID))
            } label: {
                Image(systemName: "square.grid.2x2")
                    .font(.title3)
                    .foregroundStyle(.white)
                    .frame(width: 52, height: 52)
                    .background(.white.opacity(0.15), in: Circle())
            }
            .disabled(isInteractionLocked)
        }
    }

    private var sweepGuidanceTint: Color {
        if lidarCamera.sweepGuidance?.mode != nil { return Theme.watch }
        return lidarCamera.sweepTargetReached ? Theme.calm : .white
    }

    private var sweepOverlay: some View {
        let guidance = lidarCamera.sweepGuidance ?? Figure8SweepGuidance(
            mode: nil,
            normalizedPosition: .zero,
            screenPositionMetres: .zero,
            target: nil,
            targetRadiusMetres: nil,
            targetReached: false,
            instruction: "Move the phone"
        )
        let direction = guidance.mode == nil && !guidance.targetReached
            ? SweepMovementDirection.from(
                current: guidance.normalizedPosition,
                target: guidance.target?.normalizedPosition
            )
            : .holdStill
        let positionGuide = guidance.mode == nil
            ? guidance.target.flatMap { target in
                guidance.targetRadiusMetres.map {
                    SweepPositionGuide.from(
                        phonePositionMetres: lidarCamera.sweepLiveScreenPositionMetres,
                        targetPositionMetres: target.positionMetres,
                        targetRadiusMetres: $0
                    )
                }
            }
            : nil

        return VStack(spacing: 0) {
            VStack(spacing: 5) {
                Eyebrow(text: current.title, tint: .white.opacity(0.7))
                HStack(spacing: 10) {
                    Image(systemName: direction.systemImageName)
                        .font(.system(size: 18, weight: .bold))
                    Text(guidance.instruction)
                        .font(.subheadline.weight(.semibold))
                }
                .foregroundStyle(sweepGuidanceTint)
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 12)
            .frame(maxWidth: .infinity)
            .background(.black.opacity(0.58))

            if let positionGuide {
                targetPositionGuide(positionGuide, reached: lidarCamera.sweepTargetReached)
                    .padding(.top, 14)
            }

            Spacer(minLength: 0)

            HStack {
                Text("\(lidarCamera.sweepFrameCount) of 7 recorded")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.white)
                Spacer()
                Button("Cancel", role: .destructive) {
                    lidarCamera.cancelSweep()
                }
                .buttonStyle(.bordered)
                .tint(.red)
            }
            .padding(.horizontal, 20)
            .padding(.vertical, 14)
            .background(.black.opacity(0.58))
        }
        .ignoresSafeArea(edges: .horizontal)
    }

    private func centreCrosshair(tint: Color) -> some View {
        ZStack {
            Rectangle().frame(width: 22, height: 2)
            Rectangle().frame(width: 2, height: 22)
        }
        .foregroundStyle(tint.opacity(0.9))
        .shadow(color: .black.opacity(0.5), radius: 2)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("Phone aim point; align it with the teeth target")
    }

    private func targetPositionGuide(
        _ guide: SweepPositionGuide,
        reached: Bool
    ) -> some View {
        GeometryReader { proxy in
            let side = min(proxy.size.width, proxy.size.height)
            let centre = CGPoint(x: proxy.size.width / 2, y: proxy.size.height / 2)
            let travel = max(0, side / 2 - 20)
            let point: (SIMD2<Float>) -> CGPoint = { position in
                CGPoint(
                    x: centre.x + CGFloat(position.x) * travel,
                    y: centre.y - CGFloat(position.y) * travel
                )
            }

            ZStack {
                Circle().fill(.black.opacity(0.45))
                Circle().stroke(.white.opacity(0.25), lineWidth: 2)
                Circle()
                    .stroke(reached ? Theme.calm : .white.opacity(0.9), lineWidth: 4)
                    .frame(width: side * 0.30, height: side * 0.30)
                    .position(point(guide.targetPosition))
                Circle()
                    .fill(reached ? Theme.calm : .white)
                    .frame(width: 22, height: 22)
                    .shadow(color: .black.opacity(0.4), radius: 3)
                    .position(point(guide.cursorPosition))
            }
        }
        .frame(width: 140, height: 140)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(
            reached ? "Phone is at the target position" : "Move the phone cursor into the target ring"
        )
    }

    private var permissionState: some View {
        messageState(
            title: "Camera access is off",
            detail: "Turn on the camera for Malokit in Settings to shoot the five intraoral views. You can still import photos from your library."
        )
    }

    private func messageState(title: String, detail: String) -> some View {
        VStack(spacing: 10) {
            Image(systemName: "camera.metering.unknown").font(.largeTitle)
            Text(title).font(.headline)
            Text(detail)
                .font(.footnote)
                .multilineTextAlignment(.center)
                .foregroundStyle(.white.opacity(0.7))
        }
        .foregroundStyle(.white)
        .padding(32)
    }

    // MARK: - Actions

    private var shutterEnabled: Bool {
        if usesLiDAR {
            return lidarCamera.isConfigured && !lidarCamera.isCapturing
        }
        return camera.status == .running && !camera.isCapturing
    }

    private func shoot() {
        captureMessage = nil
        let captureView = current
        if usesLiDAR {
            lidarCamera.capture(
                type: captureView.lidarPhotoType,
                previewSize: previewSize
            ) { result in
                switch result {
                case .success(let capture):
                    persist(capture, for: captureView)
                case .failure(let error):
                    if !error.localizedDescription.localizedCaseInsensitiveContains("cancel") {
                        captureMessage = error.localizedDescription
                    }
                }
            }
        } else {
            camera.capturePhoto { image in
                persist(image, for: captureView)
            }
        }
    }

    private func importFromLibrary(_ item: PhotosPickerItem, for captureView: ToothView) async {
        let data = try? await item.loadTransferable(type: Data.self)
        let image = data.flatMap(UIImage.init(data:))
        await MainActor.run {
            pickerItem = nil
            if let image { persist(image, for: captureView) }
        }
    }

    private func persist(_ image: UIImage, for captureView: ToothView) {
        let prepared = preparedThreeByTwo(image, previewSize: previewSize)
        withAnimation(.easeOut(duration: 0.08)) { flashFrame = true }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.09) {
            withAnimation(.easeIn(duration: 0.18)) { flashFrame = false }
        }

        do {
            try store.attach(prepared, to: caseID, view: captureView)
            advanceAfterSaving()
        } catch {
            captureMessage = error.localizedDescription
        }
    }

    private func persist(_ capture: CapturedPhoto, for captureView: ToothView) {
        // ARKit already cropped the high-resolution K0 image to the exact
        // visible guide. Cropping again would shrink it by the guide inset.
        let prepared = Preprocessor.prepare(Preprocessor.upright(capture.image))
        let storedCapture = CapturedPhoto(
            image: prepared,
            timestamp: capture.timestamp,
            type: capture.type,
            depthData: capture.depthData,
            lidarCapture: capture.lidarCapture,
            figure8Capture: capture.figure8Capture
        )
        do {
            try store.attach(storedCapture, to: caseID, view: captureView)
            advanceAfterSaving()
        } catch {
            captureMessage = error.localizedDescription
        }
    }

    private func preparedThreeByTwo(_ image: UIImage, previewSize: CGSize) -> UIImage {
        let upright = Preprocessor.upright(image)
        guard let cgImage = upright.cgImage,
              let crop = try? CaptureCropGeometry.landscapeThreeByTwo(
                originalWidth: cgImage.width,
                originalHeight: cgImage.height,
                previewWidth: previewSize.width,
                previewHeight: previewSize.height
              ),
              let cropped = try? upright.cropped(using: crop) else {
            return Preprocessor.prepare(upright)
        }
        return Preprocessor.prepare(cropped)
    }

    private func advanceAfterSaving() {
        captureMessage = nil

        if let next = store.record(caseID)?.nextViewToCapture {
            current = next
        } else {
            path.append(.review(caseID))
        }
    }
}
