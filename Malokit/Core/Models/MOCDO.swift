import Foundation

/// IOTN Dental Health Component, reduced to what this app actually reports:
/// which MOCDO components were found, what they measure, and which one wins.
///
/// MOCDO = Missing, Overjet, Crossbite, Displacement, Overbite.
/// The rule is "take one, the most severe".
enum MOCDOComponent: String, Codable, CaseIterable, Identifiable {
    case missing
    case overjet
    case crossbite
    case displacement
    case overbite

    var id: String { rawValue }

    var title: String {
        switch self {
        case .missing:      "Missing teeth"
        case .overjet:      "Overjet"
        case .crossbite:    "Crossbite"
        case .displacement: "Displacement"
        case .overbite:     "Overbite / open bite"
        }
    }

    var letter: String {
        switch self {
        case .missing: "M"
        case .overjet: "O"
        case .crossbite: "C"
        case .displacement: "D"
        case .overbite: "O"
        }
    }

    var symbol: String {
        switch self {
        case .missing:      "rectangle.dashed"
        case .overjet:      "arrow.left.and.right"
        case .crossbite:    "arrow.triangle.swap"
        case .displacement: "arrow.up.and.down.righttriangle.up.righttriangle.down"
        case .overbite:     "arrow.down.to.line"
        }
    }

    /// The measurement thresholds this project agreed on, shown to the user
    /// verbatim so the number on screen can always be traced to a rule.
    var thresholdNote: String {
        switch self {
        case .missing:      "Hypodontia requiring space closure or prosthetic replacement"
        case .overjet:      "3.5 to 6 mm, and greater than 9 mm"
        case .crossbite:    "1 to 2 mm discrepancy between RCP and ICP"
        case .displacement: "1 to 4 mm contact point displacement"
        case .overbite:     "1 to 2 mm, and 3.5 to 4 mm"
        }
    }

    /// Which captured views the detector reads for this component.
    var sourceViews: [ToothView] {
        switch self {
        case .missing:      [.maxillary, .mandibular, .front]
        case .overjet:      [.right, .left]
        case .crossbite:    [.maxillary, .mandibular]
        case .displacement: [.maxillary, .mandibular]
        case .overbite:     [.right, .left]
        }
    }
}

/// One detected finding. `millimetres` is nil for components that are
/// counted rather than measured, such as missing teeth.
struct MOCDOFinding: Codable, Identifiable, Hashable {
    var id: UUID = UUID()
    var component: MOCDOComponent
    var millimetres: Double?
    /// Short human reading, for example "9.5 mm" or "2 teeth, upper left".
    var reading: String
    /// The severity this single finding implies on its own.
    var band: SeverityBand
    /// Model confidence, 0 to 1.
    var confidence: Double

    var measurementText: String {
        guard let mm = millimetres else { return reading }
        return String(format: "%.1f mm", mm)
    }
}

/// The DHC output. Deliberately not the full 30 grade taxonomy: this app
/// reports the MOCDO case that decided the outcome and its severity band.
struct DHCResult: Codable, Hashable {
    var findings: [MOCDOFinding]
    var decidingComponent: MOCDOComponent
    var band: SeverityBand

    var decidingFinding: MOCDOFinding? {
        findings.first { $0.component == decidingComponent }
    }

    var detected: [MOCDOFinding] {
        findings.sorted { $0.band.rank > $1.band.rank }
    }

    /// Components the detector looked for and did not find.
    var clearComponents: [MOCDOComponent] {
        MOCDOComponent.allCases.filter { component in
            !findings.contains { $0.component == component }
        }
    }

    /// "Take one, the most severe."
    static func decide(from findings: [MOCDOFinding]) -> DHCResult {
        let worst = findings.max { lhs, rhs in
            if lhs.band.rank != rhs.band.rank { return lhs.band.rank < rhs.band.rank }
            return (lhs.millimetres ?? 0) < (rhs.millimetres ?? 0)
        }
        return DHCResult(
            findings: findings,
            decidingComponent: worst?.component ?? .displacement,
            band: worst?.band ?? .noNeed
        )
    }
}
