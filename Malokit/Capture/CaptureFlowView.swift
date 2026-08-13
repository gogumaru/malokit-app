import PhotosUI
import SwiftUI

struct CaptureFlowView: View {
    let caseID: UUID
    @Binding var path: [Route]

    @Environment(CaseStore.self) private var store
    @State private var camera = CameraService()
    @State private var current: ToothView = .front
    @State private var flashFrame = false
    @State private var pickerItem: PhotosPickerItem?
    /// Size of the live preview, needed to map the guide frame onto the photo.
    @State private var previewSize: CGSize = .zero

    /// `nil` when the model is missing from the bundle or fails to load, in
    /// which case capture falls back to accepting every photo unvalidated
    /// (same fail-open behaviour `ACCoreMLEngine` uses when its model is
    /// absent) rather than blocking capture entirely.
    @State private var validator: ViewValidatorRegressor? = try? ViewValidatorRegressor()
    @State private var rejection: ViewValidation?
    @State private var showRejection = false

    private var record: CaseRecord? { store.record(caseID) }

    var body: some View {
        ZStack {
            Color.black.ignoresSafeArea()

            switch camera.status {
            case .running:
                GeometryReader { geo in
                    CameraPreview(session: camera.session)
                        .onAppear { previewSize = geo.size }
                        .onChange(of: geo.size) { _, newSize in previewSize = newSize }
                }
                .ignoresSafeArea()

                GuideOverlay(view: current, isReady: camera.liveQuality?.isAcceptable ?? false)
                    .ignoresSafeArea()
            case .denied:
                permissionState
            case .failed(let message):
                messageState(title: "Camera unavailable", detail: message)
            case .idle:
                ProgressView().tint(.white)
            }

            VStack {
                stepStrip
                Spacer()
                instructionPanel
                controls
            }
            .padding(.horizontal, 20)
            .padding(.bottom, 24)

            if flashFrame {
                Color.white.ignoresSafeArea().transition(.opacity)
            }
        }
        .navigationTitle("Capture")
        .navigationBarTitleDisplayMode(.inline)
        .toolbarBackground(.hidden, for: .navigationBar)
        .toolbarColorScheme(.dark, for: .navigationBar)
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                Button {
                    camera.flashOn.toggle()
                } label: {
                    Image(systemName: camera.flashOn ? "bolt.fill" : "bolt.slash")
                }
                .tint(.white)
            }
        }
        .onAppear {
            current = record?.nextViewToCapture ?? .front
            camera.start()
        }
        .onDisappear { camera.stop() }
        .onChange(of: pickerItem) { _, item in
            guard let item else { return }
            Task { await importFromLibrary(item) }
        }
        .alert("Wrong photo for this step", isPresented: $showRejection, presenting: rejection) { _ in
            Button("Retake", role: .cancel) {}
        } message: { rejection in
            Text(rejection.rejectionReason ?? "This photo doesn't match the current step.")
        }
    }

    // MARK: - Pieces

    private var stepStrip: some View {
        HStack(spacing: 8) {
            ForEach(ToothView.allCases) { view in
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

            if let quality = camera.liveQuality {
                HStack(spacing: 6) {
                    Image(systemName: quality.isAcceptable ? "checkmark.circle.fill" : "exclamationmark.triangle.fill")
                    Text(quality.summary)
                }
                .font(.caption.weight(.medium))
                .foregroundStyle(quality.isAcceptable ? Theme.accent : Theme.watch)
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
        }
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
        camera.status == .running && !camera.isCapturing
    }

    private func shoot() {
        let guideRect = GuideFrame.rect(for: current, in: previewSize)
        let size = previewSize

        camera.capturePhoto { image in
            // Crop to what the person actually framed. Falls back to the full
            // frame if the preview size is not known yet, so a photo is never
            // lost to a layout race.
            let framed = size == .zero
                ? image
                : Preprocessor.crop(image, guideRect: guideRect, previewSize: size)
            persist(framed)
        }
    }

    private func importFromLibrary(_ item: PhotosPickerItem) async {
        guard
            let data = try? await item.loadTransferable(type: Data.self),
            let image = UIImage(data: data)
        else { return }
        await MainActor.run {
            persist(Preprocessor.upright(image))
            pickerItem = nil
        }
    }

    /// Gate before a photo is attached to the case: checks it against the
    /// step it was shot for, so a tertukar slot or an out-of-scope photo
    /// never silently reaches DHC/AC/3D. Falls back to accepting the photo
    /// when the model is unavailable rather than blocking capture — see
    /// `validator`'s doc comment.
    private func persist(_ image: UIImage) {
        let prepared = Preprocessor.prepare(image)

        guard let validator else {
            commit(prepared)
            return
        }

        do {
            let result = try validator.validate(image: prepared, expected: current)
            guard result.isValid else {
                rejection = result
                showRejection = true
                return
            }
        } catch {
            // Inference failed for this one photo: don't block the person
            // over a transient model error, same fail-open spirit as a
            // missing model.
        }

        commit(prepared)
    }

    private func commit(_ image: UIImage) {
        withAnimation(.easeOut(duration: 0.08)) { flashFrame = true }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.09) {
            withAnimation(.easeIn(duration: 0.18)) { flashFrame = false }
        }

        store.attach(image, to: caseID, view: current)

        if let next = store.record(caseID)?.nextViewToCapture {
            current = next
        } else {
            path.append(.review(caseID))
        }
    }
}
