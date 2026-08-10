import UIKit

/// Returns the worked example from the pipeline document so the whole app can
/// be driven end to end before a single model is trained.
///
/// Replace with RemoteEngine or CoreMLEngine by changing one line in
/// AnalysisPipeline. Nothing in the UI needs to move.
struct MockEngine: AnalysisEngine {
    let name = "Mock v1"

    /// Seconds spent on each stage, purely so the progress screen behaves
    /// like the real thing during design work.
    var stageDelay: Duration = .milliseconds(650)

    func analyze(
        _ input: AnalysisInput,
        onStage: @escaping @MainActor (AnalysisStage) -> Void
    ) async throws -> AnalysisResult {
        guard input.isComplete else {
            throw AnalysisError.incompleteInput(
                ToothView.allCases.filter { input.images[$0] == nil }
            )
        }

        for stage in AnalysisStage.allCases {
            await onStage(stage)
            try await Task.sleep(for: stageDelay)
        }

        let findings: [MOCDOFinding] = [
            MOCDOFinding(
                component: .overjet,
                millimetres: 9.5,
                reading: "9.5 mm, upper anterior protruded",
                band: .definiteNeed,
                confidence: 0.91
            ),
            MOCDOFinding(
                component: .overbite,
                millimetres: 4.2,
                reading: "Deep bite, 4.2 mm with palatal contact",
                band: .borderline,
                confidence: 0.78
            ),
            MOCDOFinding(
                component: .displacement,
                millimetres: 1.8,
                reading: "Mild crowding, 1.8 mm contact point displacement",
                band: .littleNeed,
                confidence: 0.72
            )
        ]

        return AnalysisResult(
            angle: AngleResult(right: .classIIdiv1, left: .classIIdiv1, confidence: 0.87),
            dhc: DHCResult.decide(from: findings),
            ac: ACResult(score: 8, confidence: 0.83, nearestReference: 8),
            model3DFilename: nil,
            narrative: Self.sampleNarrative,
            generatedAt: .now,
            engineName: name
        )
    }

    static let sampleNarrative = """
    Class II division 1 on both sides, with a 9.5 mm overjet and a deep bite.

    Overjet is the deciding MOCDO component and reaches definite need on its \
    own. The aesthetic component scores 8 out of 10, which lands in the same \
    band, so both halves of the IOTN agree.

    An overjet this size raises the risk of trauma to the upper anterior \
    teeth. Treatment is recommended as a priority rather than as an option.
    """
}
