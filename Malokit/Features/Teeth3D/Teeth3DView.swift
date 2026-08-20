import SceneKit
import SwiftUI

struct Teeth3DView: View {
    let caseID: UUID
    @Environment(CaseStore.self) private var store

    @State private var showUpper = true
    @State private var showLower = true
    @State private var appearance: ReconstructionAppearance = .clinical
    @State private var measuring = false
    @State private var distance: Double?
    @State private var resetToken = 0
    @State private var loadState: Teeth3DLoadState = .loading

    private var reconstruction: ReconstructionRecord? {
        store.record(caseID)?.result?.reconstruction
    }

    var body: some View {
        ZStack(alignment: .bottom) {
            content

            switch loadState {
            case .loading:
                loadingCard
            case .failed(let message):
                failureCard(message)
            case .ready:
                controls
            }
        }
        .screenBackground()
        .navigationTitle("3D view")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                Button {
                    measuring.toggle()
                    distance = nil
                    resetToken += 1
                } label: {
                    Image(systemName: measuring ? "ruler.fill" : "ruler")
                }
                .disabled(!loadState.isInteractive)
            }
        }
        .task(id: reconstruction) {
            await loadReconstruction()
        }
    }

    @ViewBuilder
    private var content: some View {
        switch loadState {
        case .ready(let reconstruction):
            GeometryReader { proxy in
                SceneContainer(
                    reconstruction: reconstruction,
                    appearance: appearance,
                    showUpper: showUpper,
                    showLower: showLower,
                    measuring: measuring,
                    resetToken: resetToken,
                    viewportAspectRatio: Float(proxy.size.width / max(proxy.size.height, 1)),
                    distance: $distance
                )
            }
            .ignoresSafeArea(edges: .bottom)
        case .loading, .failed:
            Theme.surface.ignoresSafeArea()
        }
    }

    private var controls: some View {
        VStack(spacing: 10) {
            if measuring {
                HStack(spacing: 10) {
                    Image(systemName: "hand.tap")
                    Text(distance.map { String(format: "%.1f mm", $0) } ?? "Tap two points on the arch")
                        .font(.subheadline.weight(.semibold))
                        .monospacedDigit()
                    Spacer()
                    Button("Clear") {
                        distance = nil
                        resetToken += 1
                    }
                    .font(.caption.weight(.semibold))
                }
                .foregroundStyle(Theme.ink)
                .card(padding: 12)
            }

            VStack(alignment: .leading, spacing: 10) {
                if supportsPatientAppearance {
                    Eyebrow(text: "Surface")
                    Picker("Surface appearance", selection: $appearance) {
                        ForEach(ReconstructionAppearance.allCases) { option in
                            Text(option.title).tag(option)
                        }
                    }
                    .pickerStyle(.segmented)

                    Divider()
                }

                HStack(spacing: 10) {
                    Toggle("Upper", isOn: $showUpper)
                    Toggle("Lower", isOn: $showLower)
                }
                .toggleStyle(.button)
                .buttonStyle(.bordered)
                .tint(Theme.accent)
            }
            .card(padding: 12)
        }
        .padding(20)
    }

    private var supportsPatientAppearance: Bool {
        guard case .ready(let loaded) = loadState else { return false }
        return loaded.supportsPatientAppearance
    }

    private var loadingCard: some View {
        HStack(spacing: 12) {
            ProgressView()
                .tint(Theme.accent)
            VStack(alignment: .leading, spacing: 2) {
                Text("Loading reconstructed arches")
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(Theme.ink)
                Text("Preparing the upper and lower models.")
                    .font(.caption)
                    .foregroundStyle(Theme.inkSoft)
            }
        }
        .card(padding: 14)
        .padding(20)
    }

    private func failureCard(_ message: String) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 8) {
                Image(systemName: "exclamationmark.triangle.fill")
                    .foregroundStyle(Theme.watch)
                Text("3D model unavailable")
                    .font(.headline)
                    .foregroundStyle(Theme.ink)
            }
            Text(message)
                .font(.subheadline)
                .foregroundStyle(Theme.inkSoft)
            Text("The saved case and its analysis results are unchanged.")
                .font(.caption)
                .foregroundStyle(Theme.inkSoft)
        }
        .card(padding: 16)
        .padding(20)
    }

    @MainActor
    private func loadReconstruction() async {
        measuring = false
        distance = nil
        resetToken += 1
        appearance = .clinical
        showUpper = true
        showLower = true

        guard let reconstruction else {
            loadState = .failed(
                "This case has no saved 3D reconstruction. Return to the result and tap Retry reconstruction."
            )
            return
        }
        if reconstruction.status == .processing {
            loadState = .failed(
                "This 3D model is still being built. Go back to the result to follow its progress."
            )
            return
        }
        guard reconstruction.status == .complete else {
            loadState = .failed(
                reconstruction.errorMessage ?? "Building the 3D model failed. Go back to the result and try again."
            )
            return
        }

        loadState = .loading
        do {
            let assets = try ReconstructionAssetURLs(
                caseID: caseID,
                reconstruction: reconstruction
            )
            let loaded = try await ReconstructionSceneLoader.load(assets)
            guard !Task.isCancelled else { return }
            loaded.apply(.clinical)
            loadState = .ready(loaded)
        } catch {
            guard !Task.isCancelled else { return }
            loadState = .failed(error.localizedDescription)
        }
    }
}

private enum Teeth3DLoadState {
    case loading
    case ready(LoadedReconstructionScene)
    case failed(String)

    var isInteractive: Bool {
        switch self {
        case .ready: true
        case .loading, .failed: false
        }
    }
}

// MARK: - SceneKit bridge

private struct SceneContainer: UIViewRepresentable {
    let reconstruction: LoadedReconstructionScene
    let appearance: ReconstructionAppearance
    let showUpper: Bool
    let showLower: Bool
    let measuring: Bool
    let resetToken: Int
    let viewportAspectRatio: Float
    @Binding var distance: Double?

    func makeCoordinator() -> Coordinator { Coordinator(self) }

    func makeUIView(context: Context) -> SCNView {
        let view = SCNView()
        view.allowsCameraControl = true
        view.autoenablesDefaultLighting = false
        view.antialiasingMode = .multisampling4X
        view.backgroundColor = UIColor(Theme.surface)
        view.defaultCameraController.inertiaEnabled = true

        let tap = UITapGestureRecognizer(
            target: context.coordinator,
            action: #selector(Coordinator.handleTap(_:))
        )
        view.addGestureRecognizer(tap)
        context.coordinator.sceneView = view
        context.coordinator.installScene(in: view)
        return view
    }

    func updateUIView(_ uiView: SCNView, context: Context) {
        let previous = context.coordinator.parent
        context.coordinator.parent = self

        let previousID = ObjectIdentifier(previous.reconstruction)
        let currentID = ObjectIdentifier(reconstruction)
        if previousID != currentID {
            context.coordinator.installScene(in: uiView)
        } else if abs(previous.viewportAspectRatio - viewportAspectRatio) > 0.01 {
            context.coordinator.fitCamera(in: uiView)
        }

        reconstruction.apply(appearance)
        reconstruction.setVisibility(upper: showUpper, lower: showLower)

        if previous.resetToken != resetToken
            || previous.showUpper != showUpper
            || previous.showLower != showLower {
            context.coordinator.clearMeasurements()
        }
    }

    final class Coordinator: NSObject {
        var parent: SceneContainer
        weak var sceneView: SCNView?
        var markers: [SCNVector3] = []

        init(_ parent: SceneContainer) { self.parent = parent }

        func installScene(in view: SCNView) {
            let scene = parent.reconstruction.scene
            scene.rootNode.childNode(withName: "malokitViewerCamera", recursively: false)?
                .removeFromParentNode()

            let camera = SCNNode()
            camera.name = "malokitViewerCamera"
            camera.camera = SCNCamera()
            camera.camera?.fieldOfView = 45
            camera.camera?.zNear = 0.1
            // Ambient occlusion is what makes two touching teeth read as two
            // teeth: it darkens the narrow gap between them. Without it the
            // arch renders as one continuous surface, which is most of why the
            // model looked like a single grey blob. The radius is in scene
            // units, so it is millimetres here — roughly one interdental gap.
            camera.camera?.screenSpaceAmbientOcclusionIntensity = 1.6
            camera.camera?.screenSpaceAmbientOcclusionRadius = 2.5
            camera.camera?.screenSpaceAmbientOcclusionDepthThreshold = 0.4

            let target = SCNVector3Zero
            parent.reconstruction.apply(parent.appearance)
            parent.reconstruction.setVisibility(upper: parent.showUpper, lower: parent.showLower)
            camera.look(at: target)
            scene.rootNode.addChildNode(camera)

            view.scene = scene
            view.pointOfView = camera
            view.defaultCameraController.target = target
            fitCamera(in: view)
            markers.removeAll()
        }

        func fitCamera(in view: SCNView) {
            guard let camera = view.scene?.rootNode.childNode(
                    withName: "malokitViewerCamera",
                    recursively: false
                  ) else { return }
            let reconstruction = parent.reconstruction
            let dimension = reconstruction.bounds.maximumDimension
            let distance = reconstruction.bounds.cameraDistance(
                verticalFieldOfView: 45,
                viewportAspectRatio: parent.viewportAspectRatio
            )
            camera.camera?.zFar = Double(max(distance * 10, 500))
            camera.position = SCNVector3(0, dimension * 0.18, distance)
            camera.look(at: SCNVector3Zero)
            view.defaultCameraController.target = SCNVector3Zero
        }

        @objc func handleTap(_ gesture: UITapGestureRecognizer) {
            guard parent.measuring, let view = sceneView else { return }
            let point = gesture.location(in: view)
            let hit = view.hitTest(point, options: [.boundingBoxOnly: false])
                .first { $0.node.name != "measurementMarker" && $0.node.name != "measurementLine" }
            guard let hit else { return }

            if markers.count >= 2 {
                clearMeasurements()
            }
            let position = hit.worldCoordinates
            markers.append(position)
            addMarker(at: position, in: view)

            if markers.count == 2 {
                let value = ReconstructionMeasurement.distance(from: markers[0], to: markers[1])
                DispatchQueue.main.async { self.parent.distance = value }
                addLine(from: markers[0], to: markers[1], in: view)
            }
        }

        func clearMeasurements() {
            markers.removeAll()
            sceneView?.scene?.rootNode.childNodes
                .filter { $0.name == "measurementMarker" || $0.name == "measurementLine" }
                .forEach { $0.removeFromParentNode() }
            if parent.distance != nil {
                DispatchQueue.main.async { self.parent.distance = nil }
            }
        }

        private func addMarker(at position: SCNVector3, in view: SCNView) {
            let sphere = SCNSphere(radius: 1.1)
            sphere.firstMaterial?.diffuse.contents = UIColor(Theme.accent)
            let node = SCNNode(geometry: sphere)
            node.position = position
            node.name = "measurementMarker"
            view.scene?.rootNode.addChildNode(node)
        }

        private func addLine(from a: SCNVector3, to b: SCNVector3, in view: SCNView) {
            let length = CGFloat(ReconstructionMeasurement.distance(from: a, to: b))
            let cylinder = SCNCylinder(radius: 0.3, height: length)
            cylinder.firstMaterial?.diffuse.contents = UIColor(Theme.accent)

            let node = SCNNode(geometry: cylinder)
            node.name = "measurementLine"
            node.position = SCNVector3((a.x + b.x) / 2, (a.y + b.y) / 2, (a.z + b.z) / 2)
            node.look(at: b, up: view.scene?.rootNode.worldUp ?? SCNVector3(0, 1, 0),
                      localFront: SCNVector3(0, 1, 0))
            view.scene?.rootNode.addChildNode(node)
        }
    }
}
