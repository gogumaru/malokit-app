import SceneKit
import SwiftUI

struct Teeth3DView: View {
    let caseID: UUID
    @Environment(CaseStore.self) private var store

    @State private var showUpper = true
    @State private var showLower = true
    @State private var measuring = false
    @State private var distance: Double?
    @State private var resetToken = 0

    private var modelURL: URL? {
        guard let filename = store.record(caseID)?.result?.model3DFilename else { return nil }
        return ImageStore.url(caseID: caseID, filename: filename)
    }

    var body: some View {
        ZStack(alignment: .bottom) {
            SceneContainer(
                modelURL: modelURL,
                showUpper: showUpper,
                showLower: showLower,
                measuring: measuring,
                resetToken: resetToken,
                distance: $distance
            )
            .ignoresSafeArea(edges: .bottom)

            controls
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
            }
        }
    }

    private var controls: some View {
        VStack(spacing: 10) {
            if modelURL == nil {
                Text("Showing a preview arch. The reconstructed mesh will replace it once the 3D stage produces one.")
                    .font(.caption)
                    .foregroundStyle(Theme.inkSoft)
                    .multilineTextAlignment(.center)
            }

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

            HStack(spacing: 10) {
                Toggle("Upper", isOn: $showUpper)
                Toggle("Lower", isOn: $showLower)
            }
            .toggleStyle(.button)
            .buttonStyle(.bordered)
            .tint(Theme.accent)
        }
        .padding(20)
    }
}

// MARK: - SceneKit bridge

private struct SceneContainer: UIViewRepresentable {
    let modelURL: URL?
    let showUpper: Bool
    let showLower: Bool
    let measuring: Bool
    let resetToken: Int
    @Binding var distance: Double?

    func makeCoordinator() -> Coordinator { Coordinator(self) }

    func makeUIView(context: Context) -> SCNView {
        let view = SCNView()
        view.allowsCameraControl = true
        view.autoenablesDefaultLighting = false
        view.antialiasingMode = .multisampling2X
        view.backgroundColor = UIColor(Theme.surface)

        let tap = UITapGestureRecognizer(
            target: context.coordinator,
            action: #selector(Coordinator.handleTap(_:))
        )
        view.addGestureRecognizer(tap)
        context.coordinator.sceneView = view

        rebuild(view, context: context)
        return view
    }

    func updateUIView(_ uiView: SCNView, context: Context) {
        context.coordinator.parent = self
        if context.coordinator.lastResetToken != resetToken
            || context.coordinator.lastUpper != showUpper
            || context.coordinator.lastLower != showLower {
            context.coordinator.lastResetToken = resetToken
            context.coordinator.lastUpper = showUpper
            context.coordinator.lastLower = showLower
            rebuild(uiView, context: context)
        }
    }

    private func rebuild(_ view: SCNView, context: Context) {
        let scene: SCNScene
        if let modelURL, let loaded = try? SCNScene(url: modelURL) {
            loaded.background.contents = UIColor(Theme.surface)
            scene = loaded
        } else {
            scene = PlaceholderArch.scene(
                PlaceholderArch.Options(showUpper: showUpper, showLower: showLower)
            )
        }

        let camera = SCNNode()
        camera.camera = SCNCamera()
        camera.camera?.zNear = 1
        camera.camera?.zFar = 500
        camera.position = SCNVector3(0, 30, 95)
        camera.look(at: SCNVector3(0, 0, -10))
        scene.rootNode.addChildNode(camera)

        view.scene = scene
        view.pointOfView = camera
        context.coordinator.markers.removeAll()
    }

    final class Coordinator: NSObject {
        var parent: SceneContainer
        weak var sceneView: SCNView?
        var markers: [SCNVector3] = []
        var lastResetToken = 0
        var lastUpper = true
        var lastLower = true

        init(_ parent: SceneContainer) { self.parent = parent }

        @objc func handleTap(_ gesture: UITapGestureRecognizer) {
            guard parent.measuring, let view = sceneView else { return }
            let point = gesture.location(in: view)
            guard let hit = view.hitTest(point, options: [.boundingBoxOnly: false]).first else { return }

            let position = hit.worldCoordinates
            if markers.count >= 2 {
                markers.removeAll()
                view.scene?.rootNode.childNodes
                    .filter { $0.name == "marker" }
                    .forEach { $0.removeFromParentNode() }
            }
            markers.append(position)
            addMarker(at: position, in: view)

            if markers.count == 2 {
                let a = markers[0], b = markers[1]
                let dx = a.x - b.x, dy = a.y - b.y, dz = a.z - b.z
                let value = Double(sqrt(dx * dx + dy * dy + dz * dz))
                DispatchQueue.main.async { self.parent.distance = value }
                addLine(from: a, to: b, in: view)
            }
        }

        private func addMarker(at position: SCNVector3, in view: SCNView) {
            let sphere = SCNSphere(radius: 1.1)
            sphere.firstMaterial?.diffuse.contents = UIColor(Theme.accent)
            let node = SCNNode(geometry: sphere)
            node.position = position
            node.name = "marker"
            view.scene?.rootNode.addChildNode(node)
        }

        private func addLine(from a: SCNVector3, to b: SCNVector3, in view: SCNView) {
            let dx = a.x - b.x, dy = a.y - b.y, dz = a.z - b.z
            let length = CGFloat(sqrt(dx * dx + dy * dy + dz * dz))
            let cylinder = SCNCylinder(radius: 0.3, height: length)
            cylinder.firstMaterial?.diffuse.contents = UIColor(Theme.accent)

            let node = SCNNode(geometry: cylinder)
            node.name = "marker"
            node.position = SCNVector3((a.x + b.x) / 2, (a.y + b.y) / 2, (a.z + b.z) / 2)
            node.look(at: b, up: view.scene?.rootNode.worldUp ?? SCNVector3(0, 1, 0),
                      localFront: SCNVector3(0, 1, 0))
            view.scene?.rootNode.addChildNode(node)
        }
    }
}
