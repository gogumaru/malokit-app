//
//  MalokitTests.swift
//  MalokitTests
//
//  Created by Benedikta Anin on 10/08/26.
//

import Foundation
import simd
import Testing
import UIKit
@testable import Malokit

struct MalokitTests {

    @Test func figure8EligibilityAndSmarteeNamesMatchServerContract() {
        #expect(ToothView.captureOrder == [
            .front,
            .right,
            .left,
            .maxillary,
            .mandibular
        ])
        #expect(ToothView.front.requiresFigure8)
        #expect(ToothView.right.requiresFigure8)
        #expect(ToothView.left.requiresFigure8)
        #expect(!ToothView.maxillary.requiresFigure8)
        #expect(ToothView.mandibular.requiresFigure8)

        #expect(ToothView.front.smarteeFieldName == "front")
        #expect(ToothView.right.smarteeFieldName == "rightLateral")
        #expect(ToothView.left.smarteeFieldName == "leftLateral")
        #expect(ToothView.maxillary.smarteeFieldName == "maxillary")
        #expect(ToothView.mandibular.smarteeFieldName == "mandibular")
    }

    @MainActor
    @Test func freshSettingsPreconfigureOnlyTheSmarteeReconstructionServer() {
        // Its own suite, so a test running in parallel cannot write these keys
        // underneath this one.
        let suiteName = "malokit.tests.\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suiteName)!
        defer { defaults.removePersistentDomain(forName: suiteName) }
        let key = "server.reconstructionBaseURL"

        // Asserted against the source of truth, not a literal: the lab address
        // changes whenever the server moves, and that must not fail the suite.
        let expected = ServerReconstructor.defaultBaseURL
        let settings = ServerSettings(defaults: defaults)

        #expect(settings.reconstructionBaseURL == expected)
        #expect(settings.baseURL.isEmpty)
        #expect(!settings.useRemote)

        defaults.set("", forKey: key)
        let upgradedSettings = ServerSettings(defaults: defaults)
        #expect(upgradedSettings.reconstructionBaseURL == expected)

        // A device still holding a previous default must be migrated onto the
        // current one, since nothing in the app can repoint it by hand.
        #expect(!ServerReconstructor.retiredDefaultBaseURLs.contains(expected))
        for retired in ServerReconstructor.retiredDefaultBaseURLs {
            defaults.set(retired, forKey: key)
            #expect(ServerSettings(defaults: defaults).reconstructionBaseURL == expected)
        }
    }

    @Test func everyVisibleGuideUsesThePersistedLandscapeThreeByTwoCrop() {
        for view in ToothView.allCases {
            #expect(abs(view.guideAspect - 1.5) < 0.0001)
        }
    }

    @MainActor
    @Test func loadingListsDHCAndACBeforeBackground3DReconstruction() {
        let pipeline = AnalysisPipeline(
            engine: ACCoreMLEngine(fallback: MockEngine(stageDelay: .zero)),
            reconstructor: FailingReconstructor()
        )

        #expect(pipeline.stages == [
            .preprocess,
            .angle,
            .dhc,
            .ac,
            .report
        ])
    }

    @MainActor
    @Test func oldCaseJSONDecodesWithoutLiDARRecords() throws {
        let json = """
        {
          "id": "00000000-0000-0000-0000-000000000001",
          "label": "Legacy case",
          "createdAt": "2026-08-10T00:00:00Z",
          "status": "draft",
          "imageFilenames": {"front": "front.jpg"}
        }
        """.data(using: .utf8)!
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601

        let record = try decoder.decode(CaseRecord.self, from: json)

        #expect(record.lidarViewRecords.isEmpty)
        #expect(record.filename(for: .front) == "front.jpg")
    }

    @Test func reconstructionFailureCanCoexistWithCompletedAnalysis() {
        let record = ReconstructionRecord.failed("Smartee was offline")

        #expect(record.status == .failed)
        #expect(record.errorMessage == "Smartee was offline")
        #expect(record.upperOBJFilename == nil)
    }

    @MainActor
    @Test func smarteeFailureDoesNotDiscardSuccessfulAnalysis() async throws {
        let store = CaseStore()
        let record = try store.createCase(label: "Non-fatal reconstruction fixture")
        defer { try? store.delete(record.id) }
        let image = UIGraphicsImageRenderer(size: CGSize(width: 30, height: 20)).image { context in
            UIColor.white.setFill()
            context.fill(CGRect(x: 0, y: 0, width: 30, height: 20))
        }
        for view in ToothView.allCases {
            try store.attach(image, to: record.id, view: view)
        }
        let reconstructionService = ReconstructionService()
        let pipeline = AnalysisPipeline(
            engine: MockEngine(stageDelay: .zero),
            reconstructor: FailingReconstructor(),
            reconstructionService: reconstructionService
        )

        await pipeline.run(caseID: record.id, store: store)

        for _ in 0..<100 {
            if store.record(record.id)?.result?.reconstruction?.status == .failed { break }
            try? await Task.sleep(nanoseconds: 10_000_000)
        }

        #expect(pipeline.state == .finished)
        #expect(store.record(record.id)?.status == .complete)
        #expect(store.record(record.id)?.result?.reconstruction?.status == .failed)
        #expect(store.record(record.id)?.result?.dhc.reliableCount != nil)
        #expect(!pipeline.completedStages.contains(.model3D))
    }

    @MainActor
    @Test func photoFallbackRollsBackFilesAndRecordWhenCaseIndexWriteFails() throws {
        let caseIDURL = FileManager.default.temporaryDirectory
            .appendingPathComponent("malokit-case-index-\(UUID().uuidString).json")
        var rejectWrites = false
        let store = CaseStore(fileURL: caseIDURL) { data, url in
            if rejectWrites { throw CocoaError(.fileWriteNoPermission) }
            try data.write(to: url, options: .atomic)
        }
        let record = try store.createCase(label: "Rollback fixture")
        defer {
            ImageStore.deleteFolder(for: record.id)
            try? FileManager.default.removeItem(at: caseIDURL)
        }
        let oldImage = solidImage(.red)
        let newImage = solidImage(.blue)
        try store.attach(oldImage, to: record.id, view: .front)
        let photoURL = ImageStore.url(caseID: record.id, filename: "front.jpg")
        let oldJPEG = try Data(contentsOf: photoURL)

        let lidarDirectory = LiDARCaseStore.directory(caseID: record.id, view: .front)
        try FileManager.default.createDirectory(at: lidarDirectory, withIntermediateDirectories: true)
        try Data([1]).write(to: lidarDirectory.appendingPathComponent("marker"))
        var withLiDAR = store.record(record.id)!
        withLiDAR.setLiDARRecord(
            LiDARViewRecord(kind: .figure8, relativeDirectory: "lidar/front", keyframeCount: 7),
            for: .front
        )
        try store.update(withLiDAR)

        rejectWrites = true
        #expect(throws: (any Error).self) {
            try store.attach(newImage, to: record.id, view: .front)
        }

        #expect(store.record(record.id)?.lidarRecord(for: .front)?.keyframeCount == 7)
        #expect(FileManager.default.fileExists(
            atPath: lidarDirectory.appendingPathComponent("marker").path
        ))
        #expect(try Data(contentsOf: photoURL) == oldJPEG)
    }

    @MainActor
    @Test func lidarCaptureCannotBeStoredUnderAViewDifferentFromItsCaptureType() throws {
        let indexURL = temporaryCaseIndexURL()
        let store = CaseStore(fileURL: indexURL)
        let record = try store.createCase(label: "Capture target fixture")
        defer {
            ImageStore.deleteFolder(for: record.id)
            try? FileManager.default.removeItem(at: indexURL)
        }
        let capture = try diagnosticCapture(type: .front)

        #expect(throws: (any Error).self) {
            try store.attach(capture, to: record.id, view: .right)
        }
        #expect(store.record(record.id)?.filename(for: .right) == nil)
        #expect(store.record(record.id)?.lidarRecord(for: .right) == nil)
    }

    @MainActor
    @Test func statusMutationRollsBackWhenCaseIndexWriteFails() throws {
        let indexURL = temporaryCaseIndexURL()
        var rejectWrites = false
        let store = CaseStore(fileURL: indexURL) { data, url in
            if rejectWrites { throw CocoaError(.fileWriteNoPermission) }
            try data.write(to: url, options: .atomic)
        }
        let record = try store.createCase(label: "Status rollback fixture")
        defer {
            ImageStore.deleteFolder(for: record.id)
            try? FileManager.default.removeItem(at: indexURL)
        }

        rejectWrites = true
        #expect(throws: (any Error).self) {
            try store.setStatus(.analyzing, for: record.id)
        }
        #expect(store.record(record.id)?.status == .draft)
    }

    @MainActor
    @Test func caseDeletionRollsBackFolderAndRecordWhenIndexWriteFails() throws {
        let indexURL = temporaryCaseIndexURL()
        var rejectWrites = false
        let store = CaseStore(fileURL: indexURL) { data, url in
            if rejectWrites { throw CocoaError(.fileWriteNoPermission) }
            try data.write(to: url, options: .atomic)
        }
        let record = try store.createCase(label: "Delete rollback fixture")
        defer {
            ImageStore.deleteFolder(for: record.id)
            try? FileManager.default.removeItem(at: indexURL)
        }
        try store.attach(solidImage(.green), to: record.id, view: .front)
        let caseFolder = ImageStore.folder(for: record.id)

        rejectWrites = true
        #expect(throws: (any Error).self) {
            try store.delete(record.id)
        }

        #expect(store.record(record.id) != nil)
        #expect(FileManager.default.fileExists(atPath: caseFolder.path))
        #expect(ImageStore.load(caseID: record.id, view: .front) != nil)
    }

    @Test func guideRectAndPersistedCropDescribeTheSameInsetThreeByTwoRegion() throws {
        let preview = CGSize(width: 390, height: 844)
        let source = CGSize(width: 1920, height: 1440)
        let guide = CaptureCropGeometry.guideRect(
            previewWidth: preview.width,
            previewHeight: preview.height
        )
        let crop = try CaptureCropGeometry.landscapeThreeByTwo(
            originalWidth: Int(source.width),
            originalHeight: Int(source.height),
            previewWidth: preview.width,
            previewHeight: preview.height
        )
        let aspectFillScale = max(preview.width / source.width, preview.height / source.height)

        #expect(abs(guide.width / guide.height - 1.5) < 0.0001)
        #expect(crop.width * 2 == crop.height * 3)
        let oneExactThreeByTwoStep = aspectFillScale * 3
        #expect(abs(CGFloat(crop.width) * aspectFillScale - guide.width) < oneExactThreeByTwoStep)
        #expect(abs(CGFloat(crop.height) * aspectFillScale - guide.height) < oneExactThreeByTwoStep)
    }

    @Test func libraryImportKeepsTheWholeFrameInsteadOfTheGuideCrop() throws {
        let crop = try CaptureCropGeometry.landscapeThreeByTwo(
            originalWidth: 4032,
            originalHeight: 3024,
            previewWidth: 0,
            previewHeight: 0
        )
        // No preview means no guide, so only the 3:2 letterbox is removed.
        #expect(crop.width == 4032)
        #expect(crop.x == 0)
        #expect(crop.width * 2 == crop.height * 3)
    }

    @MainActor
    @Test func successfulLiDARRetakeReplacesTheWholeBundle() throws {
        let indexURL = temporaryCaseIndexURL()
        let store = CaseStore(fileURL: indexURL)
        let record = try store.createCase(label: "LiDAR retake fixture")
        defer {
            ImageStore.deleteFolder(for: record.id)
            try? FileManager.default.removeItem(at: indexURL)
        }
        let first = try figure8Capture(type: .front, marker: 1)
        let replacement = try figure8Capture(type: .front, marker: 2)

        try store.attach(first, to: record.id, view: .front)
        try store.attach(replacement, to: record.id, view: .front)

        let lidarRecord = try #require(store.record(record.id)?.lidarRecord(for: .front))
        let loadedBundle = try LiDARCaseStore.figure8(caseID: record.id, record: lidarRecord)
        let restored = try #require(loadedBundle)
        #expect(restored.keyframes[.k0]?.rgbPNG == Data([2, 0]))
        #expect(lidarRecord.keyframeCount == 7)
    }

    @MainActor
    @Test func photoFallbackRemovesThePreviousLiDARBundle() throws {
        let indexURL = temporaryCaseIndexURL()
        let store = CaseStore(fileURL: indexURL)
        let record = try store.createCase(label: "Photo fallback fixture")
        defer {
            ImageStore.deleteFolder(for: record.id)
            try? FileManager.default.removeItem(at: indexURL)
        }
        try store.attach(
            figure8Capture(type: .front, marker: 1),
            to: record.id,
            view: .front
        )

        try store.attach(solidImage(.yellow), to: record.id, view: .front)

        #expect(store.record(record.id)?.lidarRecord(for: .front) == nil)
        #expect(!FileManager.default.fileExists(
            atPath: LiDARCaseStore.directory(caseID: record.id, view: .front).path
        ))
    }

    @MainActor
    @Test func successfulCaseDeletionRemovesItsWholeFolder() throws {
        let indexURL = temporaryCaseIndexURL()
        let store = CaseStore(fileURL: indexURL)
        let record = try store.createCase(label: "Delete fixture")
        defer {
            ImageStore.deleteFolder(for: record.id)
            try? FileManager.default.removeItem(at: indexURL)
        }
        try store.attach(solidImage(.purple), to: record.id, view: .front)
        let caseFolder = ImageStore.folder(for: record.id)

        try store.delete(record.id)

        #expect(store.record(record.id) == nil)
        #expect(!FileManager.default.fileExists(atPath: caseFolder.path))
    }

    @MainActor
    @Test func reconstructionUploadContainsOrderedFigure8AndAllNamedPhotos() throws {
        let indexURL = temporaryCaseIndexURL()
        let store = CaseStore(fileURL: indexURL)
        let record = try store.createCase(label: "Multipart fixture")
        // Own defaults suite: writing the shared one races parallel tests.
        let suiteName = "malokit.tests.\(UUID().uuidString)"
        let settings = ServerSettings(defaults: UserDefaults(suiteName: suiteName)!)
        settings.reconstructionBaseURL = "http://127.0.0.1:8000"
        defer {
            UserDefaults().removePersistentDomain(forName: suiteName)
            ImageStore.deleteFolder(for: record.id)
            try? FileManager.default.removeItem(at: indexURL)
        }
        for view in ToothView.allCases {
            try store.attach(solidImage(.white), to: record.id, view: view)
        }
        for view in ToothView.allCases where view.requiresFigure8 {
            try store.attach(
                figure8Capture(type: view.lidarPhotoType, marker: UInt8(view.step)),
                to: record.id,
                view: view
            )
        }
        try store.attach(
            diagnosticCapture(type: .maxillary),
            to: record.id,
            view: .maxillary
        )
        let completeRecord = try #require(store.record(record.id))

        let upload = try SmarteeReconstructionClient(settings: settings).makeUpload(
            caseID: record.id,
            record: completeRecord,
            requestTag: "fixturetag01",
            boundary: "fixture-boundary"
        )
        let bodyText = String(decoding: upload.body, as: UTF8.self)

        #expect(bodyText.contains("name=\"modelMode\"\r\n\r\nbaseline-only"))
        // The tag the app will poll /progress/<tag> with must reach the server.
        #expect(bodyText.contains("name=\"requestTag\"\r\n\r\nfixturetag01"))
        for view in ToothView.allCases {
            #expect(bodyText.contains("name=\"\(view.smarteeFieldName)\""))
        }
        #expect(bodyText.contains("name=\"maxillaryDepth\""))
        for view in ToothView.allCases where view.requiresFigure8 {
            #expect(bodyText.contains("name=\"\(view.smarteeFieldName)Figure8Manifest\""))
        }
        let positions = try Figure8KeyframeID.allCases.map { id in
            try #require(bodyText.range(of: "name=\"frontFigure8\(id.wireName)RGB\"")?.lowerBound)
        }
        #expect(zip(positions, positions.dropFirst()).allSatisfy { pair in
            pair.0 < pair.1
        })
    }

    @MainActor
    @Test func reconstructionUploadRejectsAnIndexedButIncompleteFigure8Bundle() throws {
        let indexURL = temporaryCaseIndexURL()
        let store = CaseStore(fileURL: indexURL)
        let record = try store.createCase(label: "Incomplete bundle fixture")
        // Own defaults suite: writing the shared one races parallel tests.
        let suiteName = "malokit.tests.\(UUID().uuidString)"
        let settings = ServerSettings(defaults: UserDefaults(suiteName: suiteName)!)
        settings.reconstructionBaseURL = "http://127.0.0.1:8000"
        defer {
            UserDefaults().removePersistentDomain(forName: suiteName)
            ImageStore.deleteFolder(for: record.id)
            try? FileManager.default.removeItem(at: indexURL)
        }
        for view in ToothView.allCases {
            try store.attach(solidImage(.white), to: record.id, view: view)
        }
        var incomplete = try #require(store.record(record.id))
        incomplete.setLiDARRecord(
            LiDARViewRecord(kind: .figure8, relativeDirectory: "lidar/front", keyframeCount: 7),
            for: .front
        )
        try store.update(incomplete)

        #expect(throws: (any Error).self) {
            try SmarteeReconstructionClient(settings: settings).makeUpload(
                caseID: record.id,
                record: incomplete,
                boundary: "fixture-boundary"
            )
        }
    }

    @MainActor
    @Test func reconstructionResponsePersistsModelsAndTexturesInCaseFolder() throws {
        let caseID = UUID()
        defer { ImageStore.deleteFolder(for: caseID) }

        let saved = try ReconstructionStore.save(
            caseID: caseID,
            upperOBJ: "o upper",
            lowerOBJ: "o lower",
            upperTexture: Data([1, 2, 3]),
            lowerTexture: Data([4, 5, 6]),
            serverModelID: "pc10-lidar",
            captureTag: "fixture-tag"
        )

        #expect(saved.status == .complete)
        #expect(saved.serverModelID == "pc10-lidar")
        #expect(saved.captureTag == "fixture-tag")
        #expect(try String(contentsOf: ImageStore.url(
            caseID: caseID,
            filename: saved.upperOBJFilename!
        ), encoding: .utf8) == "o upper")
        #expect(try Data(contentsOf: ImageStore.url(
            caseID: caseID,
            filename: saved.lowerTextureFilename!
        )) == Data([4, 5, 6]))
    }

}

private func solidImage(_ color: UIColor) -> UIImage {
    UIGraphicsImageRenderer(size: CGSize(width: 30, height: 20)).image { context in
        color.setFill()
        context.fill(CGRect(x: 0, y: 0, width: 30, height: 20))
    }
}

private func temporaryCaseIndexURL() -> URL {
    FileManager.default.temporaryDirectory
        .appendingPathComponent("malokit-case-index-\(UUID().uuidString).json")
}

private func diagnosticCapture(type: IntraoralPhotoType) throws -> CapturedPhoto {
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
        ssmDepthEligible: false,
        exclusionReason: "test fixture",
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
    return CapturedPhoto(
        image: solidImage(.white),
        timestamp: Date(),
        type: type,
        depthData: nil,
        lidarCapture: LiDARCaptureData(
            depthFloat32: encoded.depthFloat32,
            confidenceUInt8: encoded.confidenceUInt8,
            metadata: encoded.metadata
        )
    )
}

private func figure8Capture(type: IntraoralPhotoType, marker: UInt8) throws -> CapturedPhoto {
    let keyframes = try Figure8KeyframeID.allCases.enumerated().map { index, id in
        let snapshot = WorldLiDARFrameSnapshot(
            depthValues: [0.25, 0.5],
            confidenceValues: [2, 1],
            width: 2,
            height: 1,
            cameraImageWidth: 2,
            cameraImageHeight: 1,
            intrinsics: simd_float3x3(diagonal: SIMD3<Float>(1, 1, 1)),
            cameraTransform: matrix_identity_float4x4,
            timestamp: Double(index)
        )
        let encoded = try ARDepthBundleEncoder.encode(
            snapshot: snapshot,
            rgbTimestamp: Double(index),
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
        metadata.trackingState = "normal"
        return Figure8KeyframeArtifact(
            id: id,
            rgbPNG: Data([marker, UInt8(index)]),
            depthFloat32: encoded.depthFloat32,
            metadata: metadata,
            confidenceUInt8: encoded.confidenceUInt8,
            depthCoverage: 1,
            blurScore: 100,
            poseSeparation: Float(index) * 0.01,
            isDirectView: true
        )
    }
    let bundle = try Figure8CaptureBundle(keyframes: keyframes)
    let k0 = try #require(bundle.keyframes[.k0])
    return CapturedPhoto(
        image: solidImage(.white),
        timestamp: Date(),
        type: type,
        depthData: nil,
        lidarCapture: LiDARCaptureData(
            depthFloat32: k0.depthFloat32,
            confidenceUInt8: k0.confidenceUInt8,
            metadata: k0.metadata
        ),
        figure8Capture: bundle
    )
}

private struct FailingReconstructor: ReconstructionClient {
    let name = "Offline fixture"

    func reconstruct(caseID: UUID, record: CaseRecord) async throws -> ReconstructionRecord {
        throw SmarteeReconstructionError(message: "Smartee was offline")
    }
}
