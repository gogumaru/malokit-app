@preconcurrency import SceneKit
import simd
import UIKit

nonisolated enum ReconstructionArch: String, Sendable {
    case upper
    case lower
}

nonisolated enum ReconstructionAppearance: String, CaseIterable, Identifiable, Sendable {
    case clinical
    case patient

    var id: String { rawValue }

    var title: String {
        switch self {
        case .clinical: "Clinical"
        case .patient: "Patient"
        }
    }
}

nonisolated enum ReconstructionSceneError: LocalizedError, Equatable, Sendable {
    case missingReference(ReconstructionArch)
    case missingModel(ReconstructionArch)
    case unreadableModel(ReconstructionArch)

    var errorDescription: String? {
        switch self {
        case .missingReference(let arch):
            "The saved reconstruction does not reference a \(arch.rawValue) model."
        case .missingModel(let arch):
            "The saved \(arch.rawValue) model file is missing."
        case .unreadableModel(let arch):
            "The saved \(arch.rawValue) model could not be opened."
        }
    }
}

nonisolated struct ReconstructionAssetURLs: Sendable {
    let upperOBJ: URL
    let lowerOBJ: URL
    let upperTexture: URL?
    let lowerTexture: URL?

    @MainActor
    init(caseID: UUID, reconstruction: ReconstructionRecord) throws {
        guard let upper = reconstruction.upperOBJFilename else {
            throw ReconstructionSceneError.missingReference(.upper)
        }
        guard let lower = reconstruction.lowerOBJFilename else {
            throw ReconstructionSceneError.missingReference(.lower)
        }
        upperOBJ = ImageStore.url(caseID: caseID, filename: upper)
        lowerOBJ = ImageStore.url(caseID: caseID, filename: lower)
        upperTexture = reconstruction.upperTextureFilename.map {
            ImageStore.url(caseID: caseID, filename: $0)
        }
        lowerTexture = reconstruction.lowerTextureFilename.map {
            ImageStore.url(caseID: caseID, filename: $0)
        }
    }
}

nonisolated struct ReconstructionSceneBounds: Sendable {
    let minimum: SCNVector3
    let maximum: SCNVector3

    var center: SCNVector3 {
        SCNVector3(
            (minimum.x + maximum.x) / 2,
            (minimum.y + maximum.y) / 2,
            (minimum.z + maximum.z) / 2
        )
    }

    var width: Float { maximum.x - minimum.x }
    var height: Float { maximum.y - minimum.y }
    var depth: Float { maximum.z - minimum.z }
    var maximumDimension: Float { max(width, height, depth) }

    func cameraDistance(
        verticalFieldOfView: Float,
        viewportAspectRatio: Float
    ) -> Float {
        let halfVerticalAngle = verticalFieldOfView * .pi / 360
        let verticalTangent = tan(halfVerticalAngle)
        let aspect = max(viewportAspectRatio, 0.1)
        let halfHorizontalAngle = atan(verticalTangent * aspect)
        let verticalFit = max(height / 2, 1) / verticalTangent
        let horizontalFit = max(width / 2, 1) / tan(halfHorizontalAngle)
        return (max(verticalFit, horizontalFit) + depth / 2) * 1.12
    }
}

nonisolated enum ReconstructionMeasurement {
    static func distance(from a: SCNVector3, to b: SCNVector3) -> Double {
        let dx = a.x - b.x
        let dy = a.y - b.y
        let dz = a.z - b.z
        return Double(sqrt(dx * dx + dy * dy + dz * dz))
    }
}

nonisolated final class LoadedReconstructionScene: @unchecked Sendable {
    let scene: SCNScene
    let modelRoot: SCNNode
    let upperNode: SCNNode
    let lowerNode: SCNNode
    let bounds: ReconstructionSceneBounds
    let upperTexture: UIImage?
    let lowerTexture: UIImage?
    private(set) var appearance: ReconstructionAppearance = .clinical

    var supportsPatientAppearance: Bool {
        upperTexture != nil && lowerTexture != nil
    }

    init(
        scene: SCNScene,
        modelRoot: SCNNode,
        upperNode: SCNNode,
        lowerNode: SCNNode,
        bounds: ReconstructionSceneBounds,
        upperTexture: UIImage?,
        lowerTexture: UIImage?
    ) {
        self.scene = scene
        self.modelRoot = modelRoot
        self.upperNode = upperNode
        self.lowerNode = lowerNode
        self.bounds = bounds
        self.upperTexture = upperTexture
        self.lowerTexture = lowerTexture
        applyClinicalMaterial(to: upperNode)
        applyClinicalMaterial(to: lowerNode)
    }

    @MainActor
    func apply(_ requestedAppearance: ReconstructionAppearance) {
        let resolved: ReconstructionAppearance = requestedAppearance == .patient && !supportsPatientAppearance
            ? .clinical
            : requestedAppearance
        appearance = resolved
        switch resolved {
        case .clinical:
            applyClinicalMaterial(to: upperNode)
            applyClinicalMaterial(to: lowerNode)
        case .patient:
            applyPatientMaterial(texture: upperTexture!, to: upperNode)
            applyPatientMaterial(texture: lowerTexture!, to: lowerNode)
        }
    }

    @MainActor
    func setVisibility(upper: Bool, lower: Bool) {
        upperNode.isHidden = !upper
        lowerNode.isHidden = !lower
    }
}

nonisolated enum ReconstructionSceneLoader {
    static func load(_ assets: ReconstructionAssetURLs) async throws -> LoadedReconstructionScene {
        try await withCheckedThrowingContinuation { continuation in
            DispatchQueue.global(qos: .userInitiated).async {
                do {
                    continuation.resume(returning: try loadSynchronously(assets))
                } catch {
                    continuation.resume(throwing: error)
                }
            }
        }
    }

    private static func loadSynchronously(
        _ assets: ReconstructionAssetURLs
    ) throws -> LoadedReconstructionScene {
        let upperNode = try archNode(from: assets.upperOBJ, arch: .upper)
        let lowerNode = try archNode(from: assets.lowerOBJ, arch: .lower)
        let scene = SCNScene()
        let modelRoot = SCNNode()
        modelRoot.name = "reconstructionRoot"
        modelRoot.addChildNode(upperNode)
        modelRoot.addChildNode(lowerNode)
        scene.rootNode.addChildNode(modelRoot)

        let box = modelRoot.boundingBox
        let bounds = ReconstructionSceneBounds(minimum: box.min, maximum: box.max)
        let center = bounds.center
        modelRoot.position = SCNVector3(-center.x, -center.y, -center.z)
        installLighting(in: scene)

        return LoadedReconstructionScene(
            scene: scene,
            modelRoot: modelRoot,
            upperNode: upperNode,
            lowerNode: lowerNode,
            bounds: bounds,
            upperTexture: decodedImage(at: assets.upperTexture),
            lowerTexture: decodedImage(at: assets.lowerTexture)
        )
    }

    private static func archNode(from url: URL, arch: ReconstructionArch) throws -> SCNNode {
        guard FileManager.default.fileExists(atPath: url.path) else {
            throw ReconstructionSceneError.missingModel(arch)
        }
        guard let sourceScene = try? SCNScene(url: url) else {
            throw ReconstructionSceneError.unreadableModel(arch)
        }
        let root = SCNNode()
        root.name = "\(arch.rawValue)Arch"
        sourceScene.rootNode.childNodes.forEach { root.addChildNode($0.clone()) }
        guard containsGeometry(root) else {
            throw ReconstructionSceneError.unreadableModel(arch)
        }
        guard prepareNormals(in: root) else {
            throw ReconstructionSceneError.unreadableModel(arch)
        }
        return root
    }

    private static func containsGeometry(_ root: SCNNode) -> Bool {
        if root.geometry != nil { return true }
        var found = false
        root.enumerateChildNodes { node, stop in
            if node.geometry != nil {
                found = true
                stop.pointee = true
            }
        }
        return found
    }

    private static func prepareNormals(in root: SCNNode) -> Bool {
        var nodes: [SCNNode] = []
        if root.geometry != nil { nodes.append(root) }
        root.enumerateChildNodes { node, _ in
            if node.geometry != nil { nodes.append(node) }
        }

        for node in nodes {
            guard let geometry = node.geometry else { continue }
            let sourcesWithoutVertexColours = geometry.sources.filter {
                $0.semantic != .color
            }
            if geometry.sources(for: .normal).contains(where: { $0.vectorCount > 0 }) {
                if sourcesWithoutVertexColours.count != geometry.sources.count {
                    let rebuilt = SCNGeometry(
                        sources: sourcesWithoutVertexColours,
                        elements: geometry.elements
                    )
                    rebuilt.name = geometry.name
                    rebuilt.materials = geometry.materials
                    node.geometry = rebuilt
                }
                continue
            }
            guard let vertexSource = geometry.sources(for: .vertex).first,
                  let vertices = vectors(from: vertexSource) else { return false }
            var accumulated = [SIMD3<Float>](
                repeating: SIMD3<Float>(repeating: 0),
                count: vertices.count
            )
            for element in geometry.elements {
                guard element.primitiveType == .triangles,
                      let indices = triangleIndices(from: element) else { return false }
                for offset in stride(from: 0, to: indices.count, by: 3) {
                    let a = indices[offset]
                    let b = indices[offset + 1]
                    let c = indices[offset + 2]
                    guard a < vertices.count, b < vertices.count, c < vertices.count else {
                        return false
                    }
                    let normal = simd_cross(vertices[b] - vertices[a], vertices[c] - vertices[a])
                    guard simd_length_squared(normal) > 0 else { continue }
                    accumulated[a] += normal
                    accumulated[b] += normal
                    accumulated[c] += normal
                }
            }
            let normals = accumulated.map { value -> SCNVector3 in
                let normalized = simd_length_squared(value) > 0
                    ? simd_normalize(value)
                    : SIMD3<Float>(0, 1, 0)
                return SCNVector3(normalized.x, normalized.y, normalized.z)
            }
            let normalSource = SCNGeometrySource(normals: normals)
            let rebuilt = SCNGeometry(
                sources: sourcesWithoutVertexColours.filter { $0.semantic != .normal }
                    + [normalSource],
                elements: geometry.elements
            )
            rebuilt.name = geometry.name
            rebuilt.materials = geometry.materials
            node.geometry = rebuilt
        }
        return true
    }

    private static func vectors(from source: SCNGeometrySource) -> [SIMD3<Float>]? {
        guard source.usesFloatComponents,
              source.bytesPerComponent == MemoryLayout<Float>.size,
              source.componentsPerVector >= 3 else { return nil }
        return source.data.withUnsafeBytes { bytes in
            (0..<source.vectorCount).map { index in
                let start = source.dataOffset + index * source.dataStride
                return SIMD3<Float>(
                    bytes.loadUnaligned(fromByteOffset: start, as: Float.self),
                    bytes.loadUnaligned(
                        fromByteOffset: start + source.bytesPerComponent,
                        as: Float.self
                    ),
                    bytes.loadUnaligned(
                        fromByteOffset: start + source.bytesPerComponent * 2,
                        as: Float.self
                    )
                )
            }
        }
    }

    private static func triangleIndices(from element: SCNGeometryElement) -> [Int]? {
        let count = element.primitiveCount * 3
        guard element.data.count >= count * element.bytesPerIndex else { return nil }
        return element.data.withUnsafeBytes { bytes -> [Int]? in
            var result: [Int] = []
            result.reserveCapacity(count)
            for index in 0..<count {
                let offset = index * element.bytesPerIndex
                switch element.bytesPerIndex {
                case 1:
                    result.append(Int(bytes.loadUnaligned(fromByteOffset: offset, as: UInt8.self)))
                case 2:
                    let value = bytes.loadUnaligned(fromByteOffset: offset, as: UInt16.self)
                    result.append(Int(UInt16(littleEndian: value)))
                case 4:
                    let value = bytes.loadUnaligned(fromByteOffset: offset, as: UInt32.self)
                    result.append(Int(UInt32(littleEndian: value)))
                default:
                    return nil
                }
            }
            return result
        }
    }

    private static func decodedImage(at url: URL?) -> UIImage? {
        guard let url,
              let data = try? Data(contentsOf: url) else { return nil }
        return UIImage(data: data)
    }

    /// Directional lights, not omni: the meshes are in millimetres, so a light
    /// at a fixed position sat almost inside the arch and lit it flatly. A
    /// direction has no position to get wrong at this scale.
    ///
    /// Key and fill give the crowns a light-to-dark gradient, the rim separates
    /// the arch from the background, and ambient is kept low and neutral —
    /// ambient light carries no direction, so every unit of it flattens the
    /// form and (when tinted) drains the enamel colour.
    private static func installLighting(in scene: SCNScene) {
        func directional(
            _ name: String,
            intensity: CGFloat,
            temperature: CGFloat,
            from position: SCNVector3
        ) -> SCNNode {
            let node = SCNNode()
            node.name = name
            node.light = SCNLight()
            node.light?.type = .directional
            node.light?.intensity = intensity
            node.light?.temperature = temperature
            node.position = position
            node.look(at: SCNVector3Zero)
            return node
        }

        scene.rootNode.addChildNode(
            directional("keyLight", intensity: 780, temperature: 5_200,
                        from: SCNVector3(-70, 95, 120))
        )
        scene.rootNode.addChildNode(
            directional("fillLight", intensity: 260, temperature: 7_200,
                        from: SCNVector3(90, -30, 70))
        )
        scene.rootNode.addChildNode(
            directional("rimLight", intensity: 430, temperature: 6_500,
                        from: SCNVector3(0, 60, -130))
        )

        let ambient = SCNNode()
        ambient.name = "ambientLight"
        ambient.light = SCNLight()
        ambient.light?.type = .ambient
        ambient.light?.intensity = 150
        ambient.light?.color = UIColor(white: 0.98, alpha: 1)
        scene.rootNode.addChildNode(ambient)

        // Physically based materials are mostly specular reflection, so with
        // nothing to reflect they render as flat matte paint. This gives them
        // a sky-to-floor gradient to pick up, which is what makes enamel read
        // as a hard wet surface instead of chalk.
        scene.lightingEnvironment.contents = verticalGradient(
            top: UIColor(white: 1.0, alpha: 1),
            bottom: UIColor(red: 0.55, green: 0.60, blue: 0.62, alpha: 1)
        )
        scene.lightingEnvironment.intensity = 1.15

        scene.background.contents = verticalGradient(
            top: UIColor(red: 0.93, green: 0.95, blue: 0.95, alpha: 1),
            bottom: UIColor(red: 0.76, green: 0.81, blue: 0.81, alpha: 1)
        )
    }

    /// A backdrop that is darker at the bottom does two jobs at once: it stops
    /// the pale arch disappearing into a flat panel of near-identical grey, and
    /// it reads as a ground plane, which is most of the depth cue here.
    private static func verticalGradient(top: UIColor, bottom: UIColor) -> UIImage {
        let size = CGSize(width: 8, height: 256)
        return UIGraphicsImageRenderer(size: size).image { context in
            guard let gradient = CGGradient(
                colorsSpace: CGColorSpaceCreateDeviceRGB(),
                colors: [top.cgColor, bottom.cgColor] as CFArray,
                locations: [0, 1]
            ) else { return }
            context.cgContext.drawLinearGradient(
                gradient,
                start: .zero,
                end: CGPoint(x: 0, y: size.height),
                options: []
            )
        }
    }
}

nonisolated private func applyClinicalMaterial(to root: SCNNode) {
    applyMaterials(to: root) {
        let material = SCNMaterial()
        material.lightingModel = .physicallyBased
        // Enamel is warm and only slightly off-white. The old value was both
        // duller and darker, which under a tinted ambient read as grey-green.
        material.diffuse.contents = UIColor(red: 0.97, green: 0.95, blue: 0.91, alpha: 1)
        // Low roughness plus a clear coat is what gives a crown its wet
        // highlight; at 0.68 every surface scattered light equally and no
        // edge between two touching teeth was visible.
        material.roughness.contents = 0.38
        material.metalness.contents = 0.0
        material.clearCoat.contents = 0.45
        material.clearCoatRoughness.contents = 0.12
        material.isDoubleSided = true
        return material
    }
}

nonisolated private func applyPatientMaterial(texture: UIImage, to root: SCNNode) {
    applyMaterials(to: root) {
        let material = SCNMaterial()
        material.lightingModel = .physicallyBased
        material.diffuse.contents = texture
        material.diffuse.wrapS = .clamp
        material.diffuse.wrapT = .clamp
        material.diffuse.magnificationFilter = .linear
        material.diffuse.minificationFilter = .linear
        material.roughness.contents = 0.5
        material.metalness.contents = 0.0
        material.clearCoat.contents = 0.3
        material.clearCoatRoughness.contents = 0.15
        material.isDoubleSided = true
        return material
    }
}

nonisolated private func applyMaterials(
    to root: SCNNode,
    makeMaterial: () -> SCNMaterial
) {
    func apply(to node: SCNNode) {
        guard let geometry = node.geometry else { return }
        let count = max(geometry.materials.count, 1)
        geometry.materials = (0..<count).map { _ in makeMaterial() }
    }
    apply(to: root)
    root.enumerateChildNodes { node, _ in apply(to: node) }
}
