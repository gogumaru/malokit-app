import SceneKit
import Testing
import UIKit
@testable import Malokit

@MainActor
struct Teeth3DTests {
    @Test func pairedOBJFilesLoadWithUVsNormalsAndMillimetreBounds() async throws {
        let fixture = try reconstructionFixture()
        defer { ImageStore.deleteFolder(for: fixture.caseID) }

        let assets = try ReconstructionAssetURLs(
            caseID: fixture.caseID,
            reconstruction: fixture.record
        )
        let loaded = try await ReconstructionSceneLoader.load(assets)

        #expect(loaded.upperNode.name == "upperArch")
        #expect(loaded.lowerNode.name == "lowerArch")
        #expect(textureCoordinateCount(in: loaded.upperNode) == 3)
        #expect(textureCoordinateCount(in: loaded.lowerNode) == 3)
        #expect(normalCount(in: loaded.upperNode) == 3)
        #expect(normalCount(in: loaded.lowerNode) == 3)
        #expect(abs(loaded.bounds.width - 20) < 0.001)
        #expect(abs(loaded.bounds.height - 8) < 0.001)
        #expect(loaded.supportsPatientAppearance)
        #expect(!loaded.upperNode.isHidden)
        #expect(!loaded.lowerNode.isHidden)

        loaded.setVisibility(upper: false, lower: true)
        #expect(loaded.upperNode.isHidden)
        #expect(!loaded.lowerNode.isHidden)
        loaded.setVisibility(upper: true, lower: true)

        loaded.apply(.patient)
        #expect(loaded.appearance == .patient)
        #expect(materialContents(in: loaded.upperNode).allSatisfy { $0 is UIImage })
        #expect(materialContents(in: loaded.lowerNode).allSatisfy { $0 is UIImage })

        loaded.apply(.clinical)
        #expect(loaded.appearance == .clinical)
        #expect(materialContents(in: loaded.upperNode).allSatisfy { $0 is UIColor })
    }

    @Test func patientAppearanceRequiresTwoDecodableTextures() async throws {
        let fixture = try reconstructionFixture(lowerTexture: nil)
        defer { ImageStore.deleteFolder(for: fixture.caseID) }

        let assets = try ReconstructionAssetURLs(
            caseID: fixture.caseID,
            reconstruction: fixture.record
        )
        let loaded = try await ReconstructionSceneLoader.load(assets)

        #expect(!loaded.supportsPatientAppearance)
        loaded.apply(.patient)
        #expect(loaded.appearance == .clinical)
    }

    @Test func embeddedVertexColoursDoNotTintClinicalOrPatientSurfaces() async throws {
        let fixture = try reconstructionFixture()
        defer { ImageStore.deleteFolder(for: fixture.caseID) }

        let assets = try ReconstructionAssetURLs(
            caseID: fixture.caseID,
            reconstruction: fixture.record
        )
        let loaded = try await ReconstructionSceneLoader.load(assets)

        #expect(colourCount(in: loaded.upperNode) == 0)
        #expect(colourCount(in: loaded.lowerNode) == 0)
        #expect(textureCoordinateCount(in: loaded.upperNode) == 3)
        #expect(normalCount(in: loaded.upperNode) == 3)
    }

    @Test func corruptTextureFallsBackToClinicalWithoutRejectingValidMeshes() async throws {
        let fixture = try reconstructionFixture(upperTexture: Data([0x00, 0x01]))
        defer { ImageStore.deleteFolder(for: fixture.caseID) }

        let assets = try ReconstructionAssetURLs(
            caseID: fixture.caseID,
            reconstruction: fixture.record
        )
        let loaded = try await ReconstructionSceneLoader.load(assets)

        #expect(!loaded.supportsPatientAppearance)
        #expect(loaded.appearance == .clinical)
    }

    @Test func missingRecordedOBJIsAnArtifactErrorInsteadOfAPreviewFallback() async throws {
        let fixture = try reconstructionFixture()
        defer { ImageStore.deleteFolder(for: fixture.caseID) }
        let lowerURL = ImageStore.url(
            caseID: fixture.caseID,
            filename: fixture.record.lowerOBJFilename!
        )
        try FileManager.default.removeItem(at: lowerURL)

        let assets = try ReconstructionAssetURLs(
            caseID: fixture.caseID,
            reconstruction: fixture.record
        )
        do {
            _ = try await ReconstructionSceneLoader.load(assets)
            Issue.record("A recorded reconstruction with a missing lower OBJ must fail to load.")
        } catch let error as ReconstructionSceneError {
            #expect(error == .missingModel(.lower))
        }
    }

    @Test func malformedRecordedOBJIsAnArtifactErrorInsteadOfAnEmptyScene() async throws {
        let fixture = try reconstructionFixture()
        defer { ImageStore.deleteFolder(for: fixture.caseID) }
        let upperURL = ImageStore.url(
            caseID: fixture.caseID,
            filename: fixture.record.upperOBJFilename!
        )
        try Data("this is not an OBJ mesh".utf8).write(to: upperURL, options: .atomic)

        let assets = try ReconstructionAssetURLs(
            caseID: fixture.caseID,
            reconstruction: fixture.record
        )
        do {
            _ = try await ReconstructionSceneLoader.load(assets)
            Issue.record("A malformed upper OBJ must not produce an empty patient scene.")
        } catch let error as ReconstructionSceneError {
            #expect(error == .unreadableModel(.upper))
        }
    }

    @Test func combinedBoundsDriveCameraFitWithoutChangingMillimetreDistance() {
        let bounds = ReconstructionSceneBounds(
            minimum: SCNVector3(-32, -13, -28),
            maximum: SCNVector3(32, 5, 19)
        )

        #expect(abs(bounds.center.x) < 0.001)
        #expect(abs(bounds.center.y + 4) < 0.001)
        #expect(abs(bounds.center.z + 4.5) < 0.001)
        #expect(bounds.maximumDimension == 64)
        let portraitDistance = bounds.cameraDistance(
            verticalFieldOfView: 45,
            viewportAspectRatio: 390.0 / 844.0
        )
        let landscapeDistance = bounds.cameraDistance(
            verticalFieldOfView: 45,
            viewportAspectRatio: 844.0 / 390.0
        )
        #expect(portraitDistance > 180)
        #expect(portraitDistance > landscapeDistance)
        #expect(abs(ReconstructionMeasurement.distance(
            from: SCNVector3(1, 2, 3),
            to: SCNVector3(4, 6, 3)
        ) - 5) < 0.001)
    }
}

private enum FixtureArch {
    case upper
    case lower
}

private func reconstructionFixture(
    upperTexture: Data? = texturePNG(.systemPink),
    lowerTexture: Data? = texturePNG(.systemTeal)
) throws -> (caseID: UUID, record: ReconstructionRecord) {
    let caseID = UUID()
    let record = try ReconstructionStore.save(
        caseID: caseID,
        upperOBJ: fixtureOBJ(.upper),
        lowerOBJ: fixtureOBJ(.lower),
        upperTexture: upperTexture,
        lowerTexture: lowerTexture,
        serverModelID: "fixture",
        captureTag: nil
    )
    return (caseID, record)
}

private func fixtureOBJ(_ arch: FixtureArch) -> String {
    switch arch {
    case .upper:
        """
        v -10 1 0 0.8 0.2 0.2
        v 10 1 0 0.2 0.8 0.2
        v 0 3 -5 0.2 0.2 0.8
        vt 0 0
        vt 1 0
        vt 0.5 1
        f 1/1 2/2 3/3
        """
    case .lower:
        """
        v -8 -5 0 0.8 0.2 0.2
        v 8 -5 0 0.2 0.8 0.2
        v 0 -3 4 0.2 0.2 0.8
        vt 0 0
        vt 1 0
        vt 0.5 1
        f 1/1 2/2 3/3
        """
    }
}

private func texturePNG(_ color: UIColor) -> Data {
    let image = UIGraphicsImageRenderer(size: CGSize(width: 2, height: 2)).image { context in
        color.setFill()
        context.fill(CGRect(x: 0, y: 0, width: 2, height: 2))
    }
    return image.pngData()!
}

private func textureCoordinateCount(in root: SCNNode) -> Int {
    var count = 0
    root.enumerateChildNodes { node, _ in
        count += node.geometry?.sources(for: .texcoord).reduce(0) { $0 + $1.vectorCount } ?? 0
    }
    return count
}

private func normalCount(in root: SCNNode) -> Int {
    var count = 0
    root.enumerateChildNodes { node, _ in
        count += node.geometry?.sources(for: .normal).reduce(0) { $0 + $1.vectorCount } ?? 0
    }
    return count
}

private func colourCount(in root: SCNNode) -> Int {
    var count = 0
    root.enumerateChildNodes { node, _ in
        count += node.geometry?.sources(for: .color).reduce(0) { $0 + $1.vectorCount } ?? 0
    }
    return count
}

private func materialContents(in root: SCNNode) -> [Any] {
    var contents: [Any] = []
    root.enumerateChildNodes { node, _ in
        contents.append(contentsOf: node.geometry?.materials.compactMap(\.diffuse.contents) ?? [])
    }
    return contents
}
