import UIKit

/// Returns a worked example shaped exactly like the section 2 JSON contract, so
/// the whole app can be driven end to end before the FastAPI server exists.
///
/// The example is chosen to exercise every reliability state the real pipeline
/// will produce: a reliable value, an unreliable value with a warning, a
/// not-computed value, an Angle disagreement, and a Missing disagreement.
/// If the UI handles this mock cleanly, it will handle the real thing.
///
/// Swap for RemoteEngine by changing one line in AnalysisPipeline.
struct MockEngine: AnalysisEngine {
    let name = "Mock v2"

    var stageDelay: Duration = .milliseconds(650)
    var stages: [AnalysisStage] { [.preprocess, .angle, .dhc] }

    func analyze(
        _ input: AnalysisInput,
        onStage: @escaping @MainActor (AnalysisStage) -> Void
    ) async throws -> AnalysisResult {
        guard input.isComplete else {
            throw AnalysisError.incompleteInput(
                ToothView.captureOrder.filter { input.images[$0] == nil }
            )
        }

        for stage in stages {
            onStage(stage)
            try await Task.sleep(for: stageDelay)
        }

        let dhc = DHCResult(
            // Reliable finding: a clear excess overjet from the clean side.
            overjet: Reading(
                value: 0.62,
                label: "Possible excess overjet",
                side: "right",
                reliability: .reliable
            ),
            // Unreliable: both sides flagged, so the number is shown but marked.
            overbite: Reading(
                value: 0.71,
                label: "Possible deep bite",
                side: "right",
                reliability: .unreliable,
                warnings: ["Both sides flagged, value may be unstable"]
            ),
            // Anterior crossbite mirrors overjet: a positive overjet means no
            // anterior crossbite. Null here would wrongly read as "could not
            // check" rather than "checked, none found".
            anteriorCrossbite: Reading(
                value: 0.62,
                label: "no anterior crossbite",
                side: "right",
                reliability: .reliable
            ),
            posteriorCrossbite: CrossbitePosterior(
                label: "Possible posterior crossbite",
                flagged: [CrossbiteFlag(side: "left", position: 1, ratio: 0.10)],
                reliability: .reliable
            ),
            // Not computed: canine anchor missing on the lateral views, the
            // single most common failure per brief 8.1.
            missing: MissingReading(
                occlusalGaps: 0,
                frontalGaps: 1,
                disagreement: true,
                reliability: .unreliable,
                warnings: ["Occlusal and frontal disagree, manual review advised"]
            ),
            crowding: CrowdingReading(
                upper: CrowdingArch(
                    sum: 1.16,
                    label: "Possible crowding",
                    flaggedTeeth: [3, 4],
                    reliability: .reliable,
                    warnings: []
                ),
                lower: CrowdingArch(
                    sum: 1.40,
                    label: "Possible crowding",
                    flaggedTeeth: [5, 6],
                    reliability: .unreliable,
                    warnings: ["Lower arch threshold not yet validated"]
                )
            )
        )

        // Angle: canine suggests Class III, molar could not be measured. Not a
        // disagreement because only one of the two produced a value.
        let angle = AngleReading(
            side: "left",
            molar: Reading(value: nil, reliability: .notComputed),
            canine: Reading(value: -0.61, label: "Resembles Class III", reliability: .reliable),
            disagreement: false
        )

        return AnalysisResult(
            angle: angle,
            dhc: dhc,
            ac: ACResult(score: 6, confidence: 0.74, nearestReference: 6),
            model3DFilename: nil,
            narrative: Self.sampleNarrative,
            generatedAt: .now,
            engineName: name
        )
    }

    static let sampleNarrative = """
    This is a research aid and every result must be reviewed manually. The \
    pipeline does not produce a combined IOTN grade.

    Overjet reads as a possible excess on the right side and is reliable. \
    Overbite is flagged on both sides, so its value is shown but marked for \
    review. Anterior crossbite could not be computed. On Angle, the canine \
    resembles Class III while the molar could not be measured.

    Missing teeth disagree between the occlusal and frontal views, which needs \
    a manual check.
    """
}
