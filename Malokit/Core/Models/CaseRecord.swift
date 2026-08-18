import Foundation

enum CaseStatus: String, Codable {
    case draft
    case ready
    case analyzing
    case complete
    case failed
}

enum LiDARCaptureKind: String, Codable, Hashable {
    case diagnosticDepth
    case figure8
}

/// Lightweight JSON index for artifacts stored beneath the case folder.
struct LiDARViewRecord: Codable, Hashable {
    var kind: LiDARCaptureKind
    var relativeDirectory: String
    var keyframeCount: Int
}

enum ReconstructionStatus: String, Codable, Hashable {
    case processing
    case complete
    case failed
}

/// Honest client-visible milestones for Smartee's synchronous reconstruction
/// request. Everything from `queued` onwards is a stage the server reports
/// through `/progress/<tag>`; nothing here is invented or timer-driven, so the
/// label only moves when the pipeline actually moves.
enum ReconstructionProgress: String, Codable, Hashable, CaseIterable {
    case preparing
    case uploading
    case queued
    case segmenting
    case stage0
    case stage1
    case gridSearch
    case stage23
    case saving

    /// Stage ids as `server.py` spells them. Progress never runs backwards, so
    /// an ordering is all the client needs to fold a poll into its state.
    static func serverStage(_ id: String) -> Self? {
        Self(rawValue: id).flatMap { $0.isServerStage ? $0 : nil }
    }

    private var isServerStage: Bool {
        switch self {
        case .preparing, .uploading, .saving: false
        default: true
        }
    }

    var completedSteps: Int {
        Self.allCases.firstIndex(of: self) ?? 0
    }

    var totalSteps: Int { Self.allCases.count }

    var percentComplete: Int { completedSteps * 100 / totalSteps }

    /// Cases stored by an older build (`reconstructing`) must not take the
    /// whole saved DHC and AC result down with them when they fail to decode.
    init(from decoder: Decoder) throws {
        let raw = try decoder.singleValueContainer().decode(String.self)
        self = Self(rawValue: raw) ?? .queued
    }

    var label: String {
        switch self {
        case .preparing:  "Preparing your photos and scan"
        case .uploading:  "Uploading your photos and scan"
        case .queued:     "Upload received, waiting to start"
        case .segmenting: "Finding the tooth edges in your photos"
        case .stage0:     "Matching a 3D model to your photos"
        case .stage1:     "Working out the size of your teeth"
        case .gridSearch: "Finding the best overall fit"
        case .stage23:    "Fine-tuning each tooth"
        case .saving:     "Saving your 3D model"
        }
    }
}

struct ReconstructionRecord: Codable, Hashable {
    var status: ReconstructionStatus
    var upperOBJFilename: String?
    var lowerOBJFilename: String?
    var upperTextureFilename: String?
    var lowerTextureFilename: String?
    var serverModelID: String?
    var captureTag: String?
    var errorMessage: String?
    var progress: ReconstructionProgress? = nil

    static func processing(_ progress: ReconstructionProgress) -> Self {
        Self(
            status: .processing,
            upperOBJFilename: nil,
            lowerOBJFilename: nil,
            upperTextureFilename: nil,
            lowerTextureFilename: nil,
            serverModelID: nil,
            captureTag: nil,
            errorMessage: nil,
            progress: progress
        )
    }

    static func failed(_ message: String) -> Self {
        Self(
            status: .failed,
            upperOBJFilename: nil,
            lowerOBJFilename: nil,
            upperTextureFilename: nil,
            lowerTextureFilename: nil,
            serverModelID: nil,
            captureTag: nil,
            errorMessage: message,
            progress: nil
        )
    }
}

/// Everything the pipeline produced for one patient, in one value type.
struct AnalysisResult: Codable, Hashable {
    var angle: AngleReading
    var dhc: DHCResult
    var ac: ACResult
    /// Filename of the reconstructed mesh inside the case folder, if any.
    var model3DFilename: String?
    /// Non-fatal Smartee output. A failed record can coexist with successful
    /// DHC and on-device AC results.
    var reconstruction: ReconstructionRecord? = nil
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
        if !dhc.notComputedParameters.isEmpty || !ac.isScorable {
            return .partialResult
        }
        let anyFinding = dhc.posteriorCrossbite.isPresent
            || (dhc.crowding.upper?.flaggedTeeth.isEmpty == false)
            || (dhc.crowding.lower?.flaggedTeeth.isEmpty == false)
            || (dhc.overjet.label?.isEmpty == false)
            || ac.band != .noNeed
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
    /// Missing from legacy cases.json files; decoding defaults to an empty map.
    var lidarViewRecords: [String: LiDARViewRecord] = [:]
    var result: AnalysisResult?

    func filename(for view: ToothView) -> String? {
        imageFilenames[view.rawValue]
    }

    mutating func setFilename(_ name: String?, for view: ToothView) {
        if let name {
            imageFilenames[view.rawValue] = name
        } else {
            imageFilenames.removeValue(forKey: view.rawValue)
        }
    }

    func lidarRecord(for view: ToothView) -> LiDARViewRecord? {
        lidarViewRecords[view.rawValue]
    }

    mutating func setLiDARRecord(_ value: LiDARViewRecord?, for view: ToothView) {
        if let value {
            lidarViewRecords[view.rawValue] = value
        } else {
            lidarViewRecords.removeValue(forKey: view.rawValue)
        }
    }

    var capturedViews: [ToothView] {
        ToothView.captureOrder.filter { imageFilenames[$0.rawValue] != nil }
    }

    var missingViews: [ToothView] {
        ToothView.captureOrder.filter { imageFilenames[$0.rawValue] == nil }
    }

    var isComplete: Bool { missingViews.isEmpty }

    var nextViewToCapture: ToothView? { missingViews.first }
}

extension CaseRecord {
    private enum CodingKeys: String, CodingKey {
        case id, label, createdAt, status, imageFilenames, lidarViewRecords, result
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        id = try container.decodeIfPresent(UUID.self, forKey: .id) ?? UUID()
        label = try container.decode(String.self, forKey: .label)
        createdAt = try container.decodeIfPresent(Date.self, forKey: .createdAt) ?? .now
        status = try container.decodeIfPresent(CaseStatus.self, forKey: .status) ?? .draft
        imageFilenames = try container.decodeIfPresent([String: String].self, forKey: .imageFilenames) ?? [:]
        lidarViewRecords = try container.decodeIfPresent(
            [String: LiDARViewRecord].self,
            forKey: .lidarViewRecords
        ) ?? [:]
        result = try container.decodeIfPresent(AnalysisResult.self, forKey: .result)
    }
}
