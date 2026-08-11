import Foundation

/// The six DHC parameters the pipeline reports. Deliberately NOT collapsed into
/// a single IOTN grade: the export brief section 8.7 states no combined grading
/// exists yet, and inventing one in the app would misrepresent the pipeline.
///
/// Each parameter stands alone, each carries its own reliability, and the
/// summary of the whole case is "what was found and what could not be checked",
/// never a single confident number.
enum DHCParameter: String, Codable, CaseIterable, Identifiable {
    case overjet
    case overbite
    case crossbiteAnterior
    case crossbitePosterior
    case missing
    case crowding

    var id: String { rawValue }

    var title: String {
        switch self {
        case .overjet:            "Overjet"
        case .overbite:           "Overbite"
        case .crossbiteAnterior:  "Anterior crossbite"
        case .crossbitePosterior: "Posterior crossbite"
        case .missing:            "Missing teeth"
        case .crowding:           "Crowding"
        }
    }

    var symbol: String {
        switch self {
        case .overjet:            "arrow.left.and.right"
        case .overbite:           "arrow.down.to.line"
        case .crossbiteAnterior:  "arrow.triangle.swap"
        case .crossbitePosterior: "arrow.triangle.swap"
        case .missing:            "rectangle.dashed"
        case .crowding:           "arrow.left.and.right.square"
        }
    }

    /// Which captured views the pipeline reads for this parameter, from the
    /// section 1 table. Shown so a not-computed result can point at the photo
    /// most likely responsible.
    var sourceViews: [ToothView] {
        switch self {
        case .overjet, .overbite, .crossbiteAnterior: [.right, .left]
        case .crossbitePosterior:                     [.front]
        case .missing:                                [.maxillary, .mandibular, .front]
        case .crowding:                               [.maxillary, .mandibular]
        }
    }
}

/// Angle's classification, reported per side, and with molar and canine kept
/// SEPARATE as the brief section 2 rule 3 requires. When both are present but
/// disagree, `disagreement` is set and the app must show "needs manual review"
/// rather than forcing one conclusion.
struct AngleReading: Codable, Hashable {
    var side: String?
    var molar: Reading
    var canine: Reading
    var disagreement: Bool

    /// True only when at least one of molar or canine produced a value.
    var hasAnyValue: Bool { molar.hasValue || canine.hasValue }
}

/// Missing teeth reported from two sources side by side, per brief rule 4.
/// Occlusal is the primary source, frontal is a cross-check. A count mismatch
/// sets `disagreement` and asks for manual review rather than silently
/// preferring one.
struct MissingReading: Codable, Hashable {
    var occlusalGaps: Int?
    var frontalGaps: Int?
    var disagreement: Bool
    var reliability: Reliability
    var warnings: [String]

    var primaryCount: Int? { occlusalGaps ?? frontalGaps }
}

/// Crowding is per arch and can name specific teeth, so it is not a single
/// Reading. Each arch has its own sum, label, and flagged tooth positions.
struct CrowdingArch: Codable, Hashable {
    var sum: Double?
    var label: String?
    var flaggedTeeth: [Int]
    var reliability: Reliability
    var warnings: [String]
}

struct CrowdingReading: Codable, Hashable {
    var upper: CrowdingArch?
    var lower: CrowdingArch?
}

/// Posterior crossbite names the flagged positions rather than a single value.
struct CrossbiteFlag: Codable, Hashable, Identifiable {
    var id: UUID = UUID()
    var side: String
    var position: Int
    var ratio: Double

    enum CodingKeys: String, CodingKey { case side, position = "posisi", ratio }
}

struct CrossbitePosterior: Codable, Hashable {
    var label: String?
    var flagged: [CrossbiteFlag]
    var reliability: Reliability

    var isPresent: Bool { !flagged.isEmpty }
}

/// The full DHC output. Every field is optional or carries its own reliability,
/// so a partial result (the common case, per section 8.1) is a first-class
/// outcome, not a degraded one.
struct DHCResult: Codable, Hashable {
    var overjet: Reading
    var overbite: Reading
    var anteriorCrossbite: Reading
    var posteriorCrossbite: CrossbitePosterior
    var missing: MissingReading
    var crowding: CrowdingReading

    /// How many of the six parameters produced a trustworthy value. Drives the
    /// honest one-line summary on the result screen.
    var reliableCount: Int {
        var n = 0
        if overjet.reliability.isTrustworthy { n += 1 }
        if overbite.reliability.isTrustworthy { n += 1 }
        if anteriorCrossbite.reliability.isTrustworthy { n += 1 }
        if posteriorCrossbite.reliability.isTrustworthy { n += 1 }
        if missing.reliability.isTrustworthy { n += 1 }
        let crowdingOK = (crowding.upper?.reliability.isTrustworthy ?? false)
            || (crowding.lower?.reliability.isTrustworthy ?? false)
        if crowdingOK { n += 1 }
        return n
    }

    /// Parameters that could not be computed at all. Surfaced prominently so a
    /// missing overjet reads as "the photo did not allow it", not as "normal".
    var notComputedParameters: [DHCParameter] {
        var out: [DHCParameter] = []
        if overjet.reliability == .notComputed { out.append(.overjet) }
        if overbite.reliability == .notComputed { out.append(.overbite) }
        if missing.reliability == .notComputed { out.append(.missing) }
        return out
    }

    var hasAnyWarning: Bool {
        !overjet.warnings.isEmpty || !overbite.warnings.isEmpty
            || !missing.warnings.isEmpty
            || overjet.reliability == .unreliable
            || overbite.reliability == .unreliable
    }
}
