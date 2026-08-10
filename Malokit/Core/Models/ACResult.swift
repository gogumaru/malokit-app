import Foundation

/// IOTN Aesthetic Component: a 1 to 10 match against the standard
/// photographic reference series, where 1 is the most attractive.
struct ACResult: Codable, Hashable {
    var score: Int
    var confidence: Double
    /// Index 1 to 10 of the closest reference photograph.
    var nearestReference: Int

    var band: SeverityBand {
        switch score {
        case ...2: .noNeed
        case 3...4: .littleNeed
        case 5...7: .borderline
        default: .definiteNeed
        }
    }

    static let referenceCount = 10
}
