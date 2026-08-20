import Observation
import UIKit

/// Owns one run of the analysis and the progress the user watches.
@MainActor
@Observable
final class AnalysisPipeline {

    enum State: Equatable {
        case idle
        case running(AnalysisStage)
        case finished
        case failed(String)
    }

    var state: State = .idle
    var completedStages: Set<AnalysisStage> = []
    var failedStages: Set<AnalysisStage> = []

    /// Injected by the caller from ServerSettings, so switching between the
    /// mock and the real server is a setting rather than a code change.
    private let engine: AnalysisEngine
    private let reconstructor: (any ReconstructionClient)?
    private let reconstructionService: ReconstructionService?

    init(
        engine: AnalysisEngine? = nil,
        reconstructor: (any ReconstructionClient)? = nil,
        reconstructionService: ReconstructionService? = nil
    ) {
        self.engine = engine ?? ACCoreMLEngine()
        self.reconstructor = reconstructor
        self.reconstructionService = reconstructionService
    }

    var engineName: String { engine.name }
    var stages: [AnalysisStage] {
        let analysisStages = engine.stages.filter {
            $0 != .model3D && $0 != .report
        }
        return analysisStages + [.report]
    }

    func run(caseID: UUID, store: CaseStore) async {
        guard let record = store.record(caseID) else {
            state = .failed("This case no longer exists.")
            return
        }

        state = .running(.preprocess)
        completedStages = []
        failedStages = []
        do {
            try store.setStatus(.analyzing, for: caseID)
        } catch {
            state = .failed("Could not save analysis status. \(error.localizedDescription)")
            return
        }

        var images: [ToothView: UIImage] = [:]
        for view in ToothView.captureOrder {
            if let filename = record.filename(for: view),
               let image = ImageStore.load(caseID: caseID, filename: filename) {
                images[view] = image
            }
        }

        let input = AnalysisInput(caseID: caseID, images: images)

        do {
            var result = try await engine.analyze(input) { @MainActor stage in
                self.completeCurrentStage()
                self.state = .running(stage)
            }
            if reconstructor != nil {
                result.reconstruction = .processing(.preparing)
            }
            completeCurrentStage()
            state = .running(.report)
            try store.attach(result, to: caseID)
            completedStages.insert(.report)
            state = .finished
            if let reconstructor, let reconstructionService {
                reconstructionService.start(
                    caseID: caseID,
                    store: store,
                    reconstructor: reconstructor
                )
            }
        } catch {
            try? store.setStatus(.failed, for: caseID)
            state = .failed(error.localizedDescription)
        }
    }

    private func completeCurrentStage() {
        guard case .running(let stage) = state, !failedStages.contains(stage) else { return }
        completedStages.insert(stage)
    }
}
