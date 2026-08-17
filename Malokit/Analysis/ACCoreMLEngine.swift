import UIKit

/// Scores the aesthetic component with the trained Core ML model, on top of
/// whichever engine supplies DHC and Angle. DHC and AC are genuinely
/// separate pipelines — DHC comes from a server (`RemoteEngine`) or the
/// mock, AC always runs on-device here — so this engine wraps a `fallback`
/// for DHC and Angle rather than assuming one specific source, and the real
/// Core ML score runs regardless of which fallback is in use.
///
/// This is the "single swap point" `AnalysisPipeline` calls out in its own
/// comment: once another component has a real model, wrap it the same way
/// rather than writing a second full `AnalysisEngine`.
struct ACCoreMLEngine: AnalysisEngine {
    let name: String

    private let fallback: AnalysisEngine
    private let regressor: ACGraderRegressor?

    init(fallback: AnalysisEngine = MockEngine()) {
        self.fallback = fallback
        self.name = "Malokit v1 (AC: Core ML, DHC: \(fallback.name))"
        regressor = try? ACGraderRegressor()
    }

    /// The DHC source always finishes before the on-device AC score. The
    /// pipeline owns 3D reconstruction and report persistence afterward.
    var stages: [AnalysisStage] {
        fallback.stages.filter { stage in
            stage != .ac && stage != .model3D && stage != .report
        } + [.ac]
    }

    func analyze(
        _ input: AnalysisInput,
        onStage: @escaping @MainActor (AnalysisStage) -> Void
    ) async throws -> AnalysisResult {
        var result = try await fallback.analyze(input, onStage: onStage)
        result.engineName = name

        // No model in the bundle, or no front photo: keep the fallback's AC
        // score rather than failing the whole report, so DHC and Angle stay
        // usable even before the model ships.
        onStage(.ac)

        guard let regressor, let frontImage = input.images[.front] else { return result }

        do {
            let prediction = try regressor.predict(image: frontImage)
            if prediction.isScorable {
                result.ac = ACResult(
                    score: prediction.grade,
                    confidence: prediction.confidencePM1,
                    nearestReference: prediction.grade,
                    isScorable: true,
                    rejectionReason: nil
                )
            } else {
                result.ac = ACResult(
                    score: result.ac.score,
                    confidence: 0,
                    nearestReference: result.ac.nearestReference,
                    isScorable: false,
                    rejectionReason: prediction.rejectionReason
                )
            }
        } catch {
            // Model failed at inference time: keep the fallback's AC score
            // and let the rest of the report through.
        }

        return result
    }
}
