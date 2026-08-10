import UIKit

/// The stages the person watches on the analysing screen. Keeping them
/// explicit means a failure can be attributed to one model rather than to
/// "analysis failed".
enum AnalysisStage: String, CaseIterable, Identifiable {
    case preprocess
    case angle
    case dhc
    case ac
    case model3D
    case report

    var id: String { rawValue }

    var title: String {
        switch self {
        case .preprocess: "Preparing photos"
        case .angle:      "Angle's classification"
        case .dhc:        "MOCDO detection"
        case .ac:         "Aesthetic component"
        case .model3D:    "3D reconstruction"
        case .report:     "Writing the report"
        }
    }

    var detail: String {
        switch self {
        case .preprocess: "Resize and normalise, no mirroring"
        case .angle:      "Molar relation on each side"
        case .dhc:        "Missing, overjet, crossbite, displacement, overbite"
        case .ac:         "Match against the 10 reference photographs"
        case .model3D:    "Arch mesh from the five views"
        case .report:     "Combine both components into one verdict"
        }
    }
}

struct AnalysisInput {
    let caseID: UUID
    let images: [ToothView: UIImage]

    var isComplete: Bool {
        ToothView.allCases.allSatisfy { images[$0] != nil }
    }
}

enum AnalysisError: LocalizedError {
    case incompleteInput([ToothView])
    case engineFailed(stage: AnalysisStage, reason: String)

    var errorDescription: String? {
        switch self {
        case .incompleteInput(let missing):
            "Missing \(missing.map(\.title).joined(separator: ", ")). All five views are required."
        case .engineFailed(let stage, let reason):
            "\(stage.title) failed: \(reason)"
        }
    }
}

/// Everything that produces results implements this. The UI never learns
/// whether the numbers came from a mock, a server, or an on device model.
protocol AnalysisEngine {
    var name: String { get }
    func analyze(
        _ input: AnalysisInput,
        onStage: @escaping @MainActor (AnalysisStage) -> Void
    ) async throws -> AnalysisResult
}
