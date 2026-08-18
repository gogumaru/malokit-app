import Foundation
import Observation

enum ReconstructionAvailability: Equatable {
    case ready
    case processing(ReconstructionProgress)
    case needsReconstruction
    case failed(String)

    static func resolve(_ reconstruction: ReconstructionRecord?) -> Self {
        guard let reconstruction else { return .needsReconstruction }
        switch reconstruction.status {
        case .processing:
            return .processing(reconstruction.progress ?? .preparing)
        case .complete:
            return .ready
        case .failed:
            return .failed(
                reconstruction.errorMessage ?? "Building the 3D model failed."
            )
        }
    }
}

/// Lives at app scope, so reconstruction continues after the analysing screen
/// has opened the DHC and AC results.
@Observable
final class ReconstructionService {
    private var activeCaseIDs: Set<UUID> = []

    func start(
        caseID: UUID,
        store: CaseStore,
        reconstructor: any ReconstructionClient
    ) {
        guard !activeCaseIDs.contains(caseID) else { return }
        guard let record = store.record(caseID) else {
            return
        }
        guard record.result != nil else {
            return
        }

        do {
            try store.attach(.processing(.preparing), to: caseID)
        } catch {
            return
        }

        activeCaseIDs.insert(caseID)
        Task { [weak self] in
            await self?.run(caseID: caseID, store: store, reconstructor: reconstructor)
        }
    }

    private func run(
        caseID: UUID,
        store: CaseStore,
        reconstructor: any ReconstructionClient
    ) async {
        defer { activeCaseIDs.remove(caseID) }
        guard let record = store.record(caseID) else { return }

        do {
            let reconstruction = try await reconstructor.reconstruct(
                caseID: caseID,
                record: record,
                reportProgress: { [weak self] progress in
                    self?.persist(.processing(progress), for: caseID, store: store)
                }
            )
            try store.attach(reconstruction, to: caseID)
        } catch {
            try? store.attach(.failed(error.localizedDescription), to: caseID)
        }
    }

    private func persist(
        _ reconstruction: ReconstructionRecord,
        for caseID: UUID,
        store: CaseStore
    ) {
        try? store.attach(reconstruction, to: caseID)
    }
}
