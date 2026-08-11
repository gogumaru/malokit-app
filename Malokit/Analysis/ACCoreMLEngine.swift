import UIKit

/// Scores the aesthetic component with the trained Core ML model. Angle,
/// DHC and the 3D reconstruction still come from `MockEngine` until those
/// modules are wired in by their owners, so the app stays end to end
/// runnable for the rest of the team while AC alone goes real.
///
/// This is the "single swap point" `AnalysisPipeline` calls out in its own
/// comment: once another component has a real model, wrap it the same way
/// rather than writing a second full `AnalysisEngine`.
struct ACCoreMLEngine: AnalysisEngine {
    let name = "Malokit v1 (AC: Core ML, others: mock)"

    private let fallback = MockEngine()
    private let regressor: ACGraderRegressor?

    init() {
        regressor = try? ACGraderRegressor()
    }

    func analyze(
        _ input: AnalysisInput,
        onStage: @escaping @MainActor (AnalysisStage) -> Void
    ) async throws -> AnalysisResult {
        var result = try await fallback.analyze(input, onStage: onStage)
        result.engineName = name

        // No model in the bundle, or no front photo: keep the mock AC score
        // rather than failing the whole report, so DHC, Angle and 3D stay
        // testable even before the model ships.
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
            // Model failed at inference time: keep the mock AC score and let
            // the rest of the report through.
        }

        return result
    }
}
