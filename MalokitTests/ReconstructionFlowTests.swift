import Foundation
import Testing
import UIKit
@testable import Malokit

@MainActor
struct ReconstructionFlowTests {
    @Test func processingReconstructionExposesProgressInsteadOfAPlaceholder() {
        let reconstruction = ReconstructionRecord.processing(.stage23)

        #expect(ReconstructionAvailability.resolve(reconstruction) == .processing(.stage23))
        #expect(reconstruction.progress?.completedSteps == 7)
        #expect(reconstruction.progress?.totalSteps == 9)
        #expect(reconstruction.progress?.percentComplete == 77)
    }

    /// The server's stage ids are a wire contract; a rename on either side has
    /// to fail here rather than silently freeze the label mid-reconstruction.
    @Test func serverStageIdsMapOntoAdvancingProgressSteps() {
        let ids = ["queued", "segmenting", "stage0", "stage1", "gridSearch", "stage23"]
        let stages = ids.compactMap(ReconstructionProgress.serverStage)

        let steps = stages.map { $0.completedSteps }
        #expect(stages.count == ids.count)
        #expect(steps == [2, 3, 4, 5, 6, 7])
        #expect(ReconstructionProgress.serverStage("saving") == nil)
        #expect(ReconstructionProgress.serverStage("nonsense") == nil)
    }

    /// The tag names files on the server, which rejects anything outside
    /// `[A-Za-z0-9-]`, so a generated tag has to stay inside that alphabet.
    @Test func generatedRequestTagsAreSafeServerFilenames() {
        let tag = SmarteeReconstructionClient.makeRequestTag()
        let isServerSafe = tag.allSatisfy { $0.isHexDigit }

        #expect(tag.count == 12)
        #expect(isServerSafe)
    }

    /// A case saved mid-reconstruction by an older build must not lose its DHC
    /// and AC results just because its progress value no longer exists.
    @Test func retiredProgressValueDecodesInsteadOfFailingTheWholeResult() throws {
        let record = try JSONDecoder().decode(
            ReconstructionRecord.self,
            from: Data(#"{"status":"processing","progress":"reconstructing"}"#.utf8)
        )

        #expect(record.progress == .queued)
    }

    @Test func reconstructionAvailabilityNeverUsesAPreviewForMissingData() {
        #expect(ReconstructionAvailability.resolve(nil) == .needsReconstruction)
        #expect(ReconstructionAvailability.resolve(.failed("offline")) == .failed("offline"))
        #expect(ReconstructionAvailability.resolve(completeReconstruction()) == .ready)
    }

    @Test func attachingReconstructionPreservesExistingDHCAndAC() async throws {
        let fixture = try await completedAnalysisFixture()
        defer { fixture.cleanup() }
        let before = try #require(fixture.store.record(fixture.caseID)?.result)
        let reconstruction = completeReconstruction()

        try fixture.store.attach(reconstruction, to: fixture.caseID)

        let after = try #require(fixture.store.record(fixture.caseID)?.result)
        #expect(after.dhc == before.dhc)
        #expect(after.ac == before.ac)
        #expect(after.reconstruction == reconstruction)
        #expect(after.model3DFilename == "reconstruction/upper.obj")
    }

    @Test func backgroundServiceReplacesOnlyTheFailedReconstruction() async throws {
        let fixture = try await completedAnalysisFixture()
        defer { fixture.cleanup() }
        let before = try #require(fixture.store.record(fixture.caseID)?.result)
        let service = ReconstructionService()

        service.start(
            caseID: fixture.caseID,
            store: fixture.store,
            reconstructor: SuccessfulReconstructor()
        )
        await waitUntil {
            fixture.store.record(fixture.caseID)?.result?.reconstruction?.status == .complete
        }

        let after = try #require(fixture.store.record(fixture.caseID)?.result)
        #expect(after.dhc == before.dhc)
        #expect(after.ac == before.ac)
        #expect(after.reconstruction?.status == .complete)
    }

    @Test func backgroundFailurePersistsItsErrorWithoutReplacingDHCOrAC() async throws {
        let fixture = try await completedAnalysisFixture()
        defer { fixture.cleanup() }
        let before = try #require(fixture.store.record(fixture.caseID)?.result)
        let service = ReconstructionService()

        service.start(
            caseID: fixture.caseID,
            store: fixture.store,
            reconstructor: AlwaysFailingReconstructor()
        )
        await waitUntil {
            fixture.store.record(fixture.caseID)?.result?.reconstruction?.status == .failed
        }

        let after = try #require(fixture.store.record(fixture.caseID)?.result)
        #expect(after.dhc == before.dhc)
        #expect(after.ac == before.ac)
        #expect(after.reconstruction == .failed("offline"))
    }

    @Test func analysisOpensDHCAndACBeforeBackgroundReconstructionFinishes() async throws {
        let fixture = try await capturedCaseFixture()
        defer { fixture.cleanup() }
        let gate = ReconstructionGate()
        let service = ReconstructionService()
        let pipeline = AnalysisPipeline(
            engine: MockEngine(stageDelay: .zero),
            reconstructor: DelayedSuccessfulReconstructor(gate: gate),
            reconstructionService: service
        )

        await pipeline.run(caseID: fixture.caseID, store: fixture.store)

        let immediate = try #require(fixture.store.record(fixture.caseID)?.result)
        #expect(pipeline.state == .finished)
        #expect(immediate.dhc.reliableCount >= 0)
        #expect(immediate.ac.score >= 0)
        if case .processing = ReconstructionAvailability.resolve(immediate.reconstruction) {
            // The result is available while Smartee is still waiting.
        } else {
            Issue.record("Reconstruction should continue in the background.")
        }

        await gate.open()
        await waitUntil {
            fixture.store.record(fixture.caseID)?.result?.reconstruction?.status == .complete
        }
        #expect(fixture.store.record(fixture.caseID)?.result?.reconstruction?.status == .complete)
    }
}

@MainActor
private func completedAnalysisFixture() async throws -> ReconstructionFlowFixture {
    let fixture = try await capturedCaseFixture()
    let pipeline = AnalysisPipeline(engine: MockEngine(stageDelay: .zero))
    await pipeline.run(caseID: fixture.caseID, store: fixture.store)
    return fixture
}

@MainActor
private func capturedCaseFixture() async throws -> ReconstructionFlowFixture {
    let indexURL = FileManager.default.temporaryDirectory
        .appendingPathComponent("malokit-reconstruction-flow-\(UUID().uuidString).json")
    let store = CaseStore(fileURL: indexURL)
    let record = try store.createCase(label: "Reconstruction flow")
    let image = UIGraphicsImageRenderer(size: CGSize(width: 30, height: 20)).image { context in
        UIColor.white.setFill()
        context.fill(CGRect(x: 0, y: 0, width: 30, height: 20))
    }
    for view in ToothView.allCases {
        try store.attach(image, to: record.id, view: view)
    }
    return ReconstructionFlowFixture(store: store, caseID: record.id, indexURL: indexURL)
}

private struct ReconstructionFlowFixture {
    let store: CaseStore
    let caseID: UUID
    let indexURL: URL

    @MainActor
    func cleanup() {
        ImageStore.deleteFolder(for: caseID)
        try? FileManager.default.removeItem(at: indexURL)
    }
}

private struct AlwaysFailingReconstructor: ReconstructionClient {
    let name = "Failure fixture"

    func reconstruct(caseID: UUID, record: CaseRecord) async throws -> ReconstructionRecord {
        throw SmarteeReconstructionError(message: "offline")
    }
}

private struct SuccessfulReconstructor: ReconstructionClient {
    let name = "Success fixture"

    func reconstruct(caseID: UUID, record: CaseRecord) async throws -> ReconstructionRecord {
        completeReconstruction()
    }
}

private struct DelayedSuccessfulReconstructor: ReconstructionClient {
    let name = "Delayed success fixture"
    let gate: ReconstructionGate

    func reconstruct(caseID: UUID, record: CaseRecord) async throws -> ReconstructionRecord {
        await gate.wait()
        return completeReconstruction()
    }
}

private actor ReconstructionGate {
    private var isOpen = false
    private var waiters: [CheckedContinuation<Void, Never>] = []

    func wait() async {
        guard !isOpen else { return }
        await withCheckedContinuation { continuation in
            waiters.append(continuation)
        }
    }

    func open() {
        isOpen = true
        waiters.forEach { $0.resume() }
        waiters.removeAll()
    }
}

@MainActor
private func waitUntil(_ condition: @escaping @MainActor () -> Bool) async {
    for _ in 0..<100 {
        if condition() { return }
        try? await Task.sleep(nanoseconds: 10_000_000)
    }
}

private func completeReconstruction() -> ReconstructionRecord {
    ReconstructionRecord(
        status: .complete,
        upperOBJFilename: "reconstruction/upper.obj",
        lowerOBJFilename: "reconstruction/lower.obj",
        upperTextureFilename: "reconstruction/upper.png",
        lowerTextureFilename: "reconstruction/lower.png",
        serverModelID: "pc10-lidar",
        captureTag: "fixture",
        errorMessage: nil
    )
}
