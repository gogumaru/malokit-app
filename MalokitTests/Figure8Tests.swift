import Foundation
import simd
import Testing
@testable import Malokit

struct Figure8Tests {
    private let dwell = Figure8SweepConfiguration.developmentDefault.boundaryDwellSampleCount

    @Test func straightTravelAndWrongOrderDoNotComplete() {
        var gate = Figure8CoverageGate(configuration: .developmentDefault)
        gate.begin(directView: true, referenceTransform: matrix_identity_float4x4)
        for x in stride(from: Float(0), through: 0.05, by: 0.01) {
            _ = gate.accept(sample: sample(x, 0))
        }
        #expect(gate.state != .complete)

        for _ in 0..<dwell { _ = gate.accept(sample: sample(0.012, 0.005)) }
        #expect(gate.state == .idle)
    }

    @Test func orderedLobesAndReturnSelectTheWholeSweep() {
        var gate = Figure8CoverageGate(configuration: .developmentDefault)
        gate.begin(directView: true, referenceTransform: matrix_identity_float4x4)
        drive(&gate, [
            (-0.012, 0.005, true), (-0.012, -0.005, true), (0, 0, false),
            (0.012, 0.005, true), (0.012, -0.005, true), (0, 0, false)
        ])
        #expect(gate.state == .complete)
    }

    @Test func completingOnlyOneLobeCannotCompleteTheSweep() {
        var gate = Figure8CoverageGate(configuration: .developmentDefault)
        gate.begin(directView: true, referenceTransform: matrix_identity_float4x4)
        drive(&gate, [
            (-0.012, 0.005, true),
            (-0.012, -0.005, true),
            (0, 0, false)
        ])

        #expect(gate.state == .centreCrossing)
        #expect(gate.state != .complete)
    }

    @Test func limitedTrackingDistanceDriftAndAimFailurePauseCoverage() {
        var gate = Figure8CoverageGate(configuration: .developmentDefault)
        gate.begin(directView: true, referenceTransform: matrix_identity_float4x4)
        #expect(!gate.accept(sample: Figure8FrameSample(
            cameraTransform: transform(-0.01, 0.004),
            trackingIsNormal: false
        )).accepted)
        #expect(!gate.accept(sample: sample(-0.01, 0.004, 0.016)).accepted)

        var sideAnchor = matrix_identity_float4x4
        sideAnchor.columns.3 = SIMD4<Float>(1, 0, 0, 1)
        #expect(!gate.accept(sample: Figure8FrameSample(
            cameraTransform: transform(-0.01, 0.004),
            trackingIsNormal: true,
            teethAnchorWorldTransform: sideAnchor
        )).accepted)
        #expect(gate.state == .idle)
    }

    @Test func boundaryTargetsRequireDwellAndLeavingResetsIt() {
        var gate = Figure8CoverageGate(configuration: .developmentDefault)
        gate.begin(directView: true, referenceTransform: matrix_identity_float4x4)
        for _ in 0..<(dwell - 1) { _ = gate.accept(sample: sample(-0.01, 0.004)) }
        #expect(gate.state == .idle)
        _ = gate.accept(sample: sample(0, 0))
        for _ in 0..<(dwell - 1) { _ = gate.accept(sample: sample(-0.01, 0.004)) }
        #expect(gate.state == .idle)
        _ = gate.accept(sample: sample(-0.01, 0.004))
        #expect(gate.state == .leftUpper)
    }

    @Test func cancellationResetDiscardsInProgressSelection() throws {
        var session = Figure8CaptureSession(configuration: .developmentDefault)
        _ = session.begin(k0: try artifact(.k0), referenceTransform: matrix_identity_float4x4)
        #expect(session.selector.selected[.k0] != nil)
        session.reset()
        #expect(session.selector.selected.isEmpty)
        #expect(session.completedBundle == nil)
    }

    @Test func completeK0ThroughK6BundleRoundTrips() throws {
        let bundle = try Figure8CaptureBundle(
            keyframes: try Figure8KeyframeID.allCases.map(artifact)
        )
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent("malokit-figure8-\(UUID().uuidString)", isDirectory: true)
        defer { try? FileManager.default.removeItem(at: directory) }

        try Figure8CaptureStore.write(bundle, to: directory)
        let restored = try Figure8CaptureStore.load(from: directory)

        #expect(restored?.isComplete == true)
        #expect(restored?.keyframes[.k6]?.depthFloat32 == bundle.keyframes[.k6]?.depthFloat32)
        #expect(FileManager.default.fileExists(
            atPath: directory.appendingPathComponent("figure8_manifest.json").path
        ))
    }

    @Test func multipartUsesBaselineModeAndExplicitNames() {
        var builder = SmarteeMultipartBuilder(boundary: "fixture")
        builder.addField(name: "modelMode", value: "baseline-only")
        for view in ToothView.allCases {
            builder.addFile(
                name: view.smarteeFieldName,
                filename: "\(view.smarteeFieldName).png",
                mimeType: "image/png",
                data: Data([1])
            )
        }
        let text = String(decoding: builder.finalize(), as: UTF8.self)
        #expect(text.contains("name=\"modelMode\"\r\n\r\nbaseline-only"))
        #expect(text.contains("name=\"rightLateral\""))
        #expect(text.contains("name=\"leftLateral\""))
        #expect(text.contains("name=\"maxillary\""))
        #expect(text.contains("name=\"mandibular\""))
    }

    private func drive(
        _ gate: inout Figure8CoverageGate,
        _ path: [(Float, Float, Bool)]
    ) {
        for (x, y, boundary) in path {
            for _ in 0..<(boundary ? dwell : 1) {
                _ = gate.accept(sample: sample(x, y))
            }
        }
    }

    private func transform(_ x: Float, _ y: Float, _ z: Float = 0) -> simd_float4x4 {
        var value = matrix_identity_float4x4
        value.columns.3 = SIMD4<Float>(x, y, z, 1)
        return value
    }

    private func sample(_ x: Float, _ y: Float, _ z: Float = 0) -> Figure8FrameSample {
        Figure8FrameSample(cameraTransform: transform(x, y, z), trackingIsNormal: true)
    }

    private func artifact(_ id: Figure8KeyframeID) throws -> Figure8KeyframeArtifact {
        let snapshot = WorldLiDARFrameSnapshot(
            depthValues: [0.25, 0.5],
            confidenceValues: [2, 1],
            width: 2,
            height: 1,
            cameraImageWidth: 2,
            cameraImageHeight: 1,
            intrinsics: simd_float3x3(diagonal: SIMD3<Float>(1, 1, 1)),
            cameraTransform: matrix_identity_float4x4,
            timestamp: 10
        )
        let encoded = try ARDepthBundleEncoder.encode(
            snapshot: snapshot,
            rgbTimestamp: 10,
            ssmDepthEligible: true,
            exclusionReason: nil,
            rgbCrop: RGBCropMetadata(
                originalWidth: 3,
                originalHeight: 2,
                x: 0,
                y: 0,
                width: 3,
                height: 2,
                targetAspectRatio: 1.5
            )
        )
        var metadata = encoded.metadata
        metadata.figure8KeyframeID = id.wireName
        metadata.isDirectView = true
        return Figure8KeyframeArtifact(
            id: id,
            rgbPNG: Data([0x89, 0x50, 0x4E, 0x47]),
            depthFloat32: encoded.depthFloat32,
            metadata: metadata,
            confidenceUInt8: encoded.confidenceUInt8,
            depthCoverage: 1,
            blurScore: 100,
            poseSeparation: 0.01,
            isDirectView: true
        )
    }
}
