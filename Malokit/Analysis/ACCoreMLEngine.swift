import UIKit

/// Scores the aesthetic component with the trained Core ML model, on top of
/// whichever engine supplies DHC and Angle. DHC and AC are genuinely
/// separate pipelines — DHC comes from a server (`RemoteEngine`) or the
/// mock, AC always runs on-device here — so this engine wraps a `fallback`
/// for DHC/Angle/3D rather than assuming one specific source, and the real
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

    /// Whatever stages the DHC source runs, plus `.ac`: this engine always
    /// attempts a real on-device score no matter where DHC came from.
    var stages: [AnalysisStage] {
        var included = Set(fallback.stages)
        included.insert(.ac)
        return AnalysisStage.allCases.filter { included.contains($0) }
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
        guard let regressor, let frontImage = input.images[.front] else { return result }

        await onStage(.ac)

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
