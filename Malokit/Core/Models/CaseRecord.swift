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
    var angle: AngleResult
    var dhc: DHCResult
    var ac: ACResult
    /// Filename of the reconstructed mesh inside the case folder, if any.
    var model3DFilename: String?
    /// Narrative paragraph. Written by the report LLM in the real pipeline.
    var narrative: String?
    var generatedAt: Date
    var engineName: String

    /// The single verdict shown at the top of the summary. Either component
    /// reaching definite need is enough to escalate the whole case.
    var verdict: SeverityBand {
        dhc.band.rank >= ac.band.rank ? dhc.band : ac.band
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
