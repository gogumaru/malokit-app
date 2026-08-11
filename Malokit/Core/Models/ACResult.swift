import Foundation

/// IOTN Aesthetic Component: a 1 to 10 match against the standard
/// photographic reference series, where 1 is the most attractive.
struct ACResult: Codable, Hashable {
    var score: Int
    var confidence: Double
    /// Index 1 to 10 of the closest reference photograph.
    var nearestReference: Int
    /// False when the Core ML model rejected the photo as out of
    /// distribution (not a frontal intraoral photo). `score` and
    /// `confidence` are not meaningful in that case.
    var isScorable: Bool = true
    /// Why the photo was rejected, shown to the user in place of a score.
    var rejectionReason: String? = nil

    var band: SeverityBand {
        switch score {
        case ...1: .noNeed
        case 2...3: .littleNeed
        case 4...6: .borderline
        default: .definiteNeed
        }
    }

    static let referenceCount = 10
}
