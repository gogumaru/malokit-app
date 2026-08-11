import Foundation

enum CaseStatus: String, Codable {
    case draft
    case ready
    case analyzing
    case complete
    case failed
}

/// Everything the pipeline produced for one patient, in one value type.
struct AnalysisResult: Codable, Hashable {
    var angle: AngleReading
    var dhc: DHCResult
    /// Optional on purpose: the DHC server does not produce an aesthetic
    /// component. AC comes from a separate pipeline that does not exist yet,
    /// so a result with DHC but no AC is a normal outcome, not a broken one.
    var ac: ACResult?
    /// Filename of the reconstructed mesh inside the case folder, if any.
    var model3DFilename: String?
    /// Narrative paragraph. Written by the report LLM in the real pipeline.
    var narrative: String?
    var generatedAt: Date
    var engineName: String

    /// How the whole case reads at a glance. There is deliberately no single
    /// IOTN grade here: the pipeline does not produce one yet (brief 8.7), so
    /// the summary is honest about coverage instead of inventing a verdict.
    enum CaseSummary: String {
        case reviewNeeded   = "Review needed"
        case partialResult  = "Partial result"
        case findingsFound  = "Findings to review"
        case clear          = "No findings flagged"
    }

    var summary: CaseSummary {
        if dhc.hasAnyWarning || angle.disagreement || dhc.missing.disagreement {
            return .reviewNeeded
        }
        if !dhc.notComputedParameters.isEmpty {
            return .partialResult
        }
        let anyFinding = dhc.posteriorCrossbite.isPresent
            || (dhc.crowding.upper?.flaggedTeeth.isEmpty == false)
            || (dhc.crowding.lower?.flaggedTeeth.isEmpty == false)
            || (dhc.overjet.label?.isEmpty == false)
        return anyFinding ? .findingsFound : .clear
    }
}

struct CaseRecord: Identifiable, Codable, Hashable {
    var id: UUID = UUID()
    var label: String
    var createdAt: Date = .now
    var status: CaseStatus = .draft
    /// Keyed by ToothView.rawValue so the on-disk JSON stays readable.
    var imageFilenames: [String: String] = [:]
    var result: AnalysisResult?

    func filename(for view: ToothView) -> String? {
        imageFilenames[view.rawValue]
    }

    mutating func setFilename(_ name: String?, for view: ToothView) {
        imageFilenames[view.rawValue] = name
    }

    var capturedViews: [ToothView] {
        ToothView.allCases.filter { imageFilenames[$0.rawValue] != nil }
    }

    var missingViews: [ToothView] {
        ToothView.allCases.filter { imageFilenames[$0.rawValue] == nil }
    }

    var isComplete: Bool { missingViews.isEmpty }

    var nextViewToCapture: ToothView? { missingViews.first }
}
