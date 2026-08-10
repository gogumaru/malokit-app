import Foundation

enum AngleClass: String, Codable, CaseIterable, Hashable {
    case classI       = "Class I"
    case classIIdiv1  = "Class II division 1"
    case classIIdiv2  = "Class II division 2"
    case classIII     = "Class III"

    var shortLabel: String {
        switch self {
        case .classI: "I"
        case .classIIdiv1: "II div 1"
        case .classIIdiv2: "II div 2"
        case .classIII: "III"
        }
    }
}

/// Angle's classification is scored per side, so the app never collapses it
/// into a single value before the clinician has seen both.
struct AngleResult: Codable, Hashable {
    var right: AngleClass
    var left: AngleClass
    var confidence: Double

    var isBilateral: Bool { right == left }

    var summary: String {
        isBilateral
            ? "\(right.rawValue) (bilateral)"
            : "Right \(right.shortLabel), left \(left.shortLabel)"
    }
}
