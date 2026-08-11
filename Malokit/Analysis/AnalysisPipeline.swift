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

    /// Injected by the caller from ServerSettings, so switching between the
    /// mock and the real server is a setting rather than a code change.
    private let engine: AnalysisEngine

    init(engine: AnalysisEngine = ACCoreMLEngine()) {
        self.engine = engine
    }

    var engineName: String { engine.name }
    var stages: [AnalysisStage] { engine.stages }

    func run(caseID: UUID, store: CaseStore) async {
        guard let record = store.record(caseID) else {
            state = .failed("This case no longer exists.")
            return
        }

        state = .running(.preprocess)
        completedStages = []
        store.setStatus(.analyzing, for: caseID)

        var images: [ToothView: UIImage] = [:]
        for view in ToothView.allCases {
            if let filename = record.filename(for: view),
               let image = ImageStore.load(caseID: caseID, filename: filename) {
                images[view] = image
            }
        }

        let input = AnalysisInput(caseID: caseID, images: images)

        do {
            let result = try await engine.analyze(input) { @MainActor stage in
                if case .running(let previous) = self.state {
                    self.completedStages.insert(previous)
                }
                self.state = .running(stage)
            }
            completedStages = Set(AnalysisStage.allCases)
            store.attach(result, to: caseID)
            state = .finished
        } catch {
            store.setStatus(.failed, for: caseID)
            state = .failed(error.localizedDescription)
        }
    }
}
