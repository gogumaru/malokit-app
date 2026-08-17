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

    /// The key this parameter uses in the server response, reused verbatim as
    /// the `params` value so no translation table exists on either side.
    var responseKey: String {
        switch self {
        case .overjet:            "overjet"
        case .overbite:           "overbite"
        case .crossbiteAnterior:  "anterior_crossbite"
        case .crossbitePosterior: "crossbite_posterior"
        case .missing:            "missing"
        case .crowding:           "crowding"
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

    init(
        occlusalGaps: Int?,
        frontalGaps: Int?,
        disagreement: Bool,
        reliability: Reliability,
        warnings: [String] = []
    ) {
        self.occlusalGaps = occlusalGaps
        self.frontalGaps = frontalGaps
        self.disagreement = disagreement
        self.reliability = reliability
        self.warnings = warnings
    }

    enum CodingKeys: String, CodingKey {
        case occlusalGaps = "occlusal_gaps"
        case frontalGaps = "frontal_gaps"
        case disagreement, reliable, warnings
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        occlusalGaps = try c.decodeIfPresent(Int.self, forKey: .occlusalGaps)
        frontalGaps = try c.decodeIfPresent(Int.self, forKey: .frontalGaps)
        disagreement = try c.decodeIfPresent(Bool.self, forKey: .disagreement) ?? false
        warnings = try c.decodeIfPresent([String].self, forKey: .warnings) ?? []

        let reliable = try c.decodeIfPresent(Bool.self, forKey: .reliable) ?? false
        if occlusalGaps == nil && frontalGaps == nil {
            reliability = .notComputed
        } else {
            reliability = reliable ? .reliable : .unreliable
        }
    }

    func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encodeIfPresent(occlusalGaps, forKey: .occlusalGaps)
        try c.encodeIfPresent(frontalGaps, forKey: .frontalGaps)
        try c.encode(disagreement, forKey: .disagreement)
        try c.encode(reliability == .reliable, forKey: .reliable)
        try c.encode(warnings, forKey: .warnings)
    }
}

/// Crowding is per arch and can name specific teeth, so it is not a single
/// Reading. Each arch has its own sum, label, and flagged tooth positions.
struct CrowdingArch: Codable, Hashable {
    var sum: Double?
    var label: String?
    var flaggedTeeth: [Int]
    var reliability: Reliability
    var warnings: [String]

    init(
        sum: Double?,
        label: String?,
        flaggedTeeth: [Int] = [],
        reliability: Reliability,
        warnings: [String] = []
    ) {
        self.sum = sum
        self.label = label
        self.flaggedTeeth = flaggedTeeth
        self.reliability = reliability
        self.warnings = warnings
    }

    enum CodingKeys: String, CodingKey {
        case sum, label, warnings, reliable
        case flaggedTeeth = "flagged_teeth"
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        sum = try c.decodeIfPresent(Double.self, forKey: .sum)
        label = try c.decodeIfPresent(String.self, forKey: .label)
        flaggedTeeth = try c.decodeIfPresent([Int].self, forKey: .flaggedTeeth) ?? []
        warnings = try c.decodeIfPresent([String].self, forKey: .warnings) ?? []

        let reliable = try c.decodeIfPresent(Bool.self, forKey: .reliable) ?? false
        reliability = sum == nil ? .notComputed : (reliable ? .reliable : .unreliable)
    }

    func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encodeIfPresent(sum, forKey: .sum)
        try c.encodeIfPresent(label, forKey: .label)
        try c.encode(flaggedTeeth, forKey: .flaggedTeeth)
        try c.encode(reliability == .reliable, forKey: .reliable)
        try c.encode(warnings, forKey: .warnings)
    }
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

    init(label: String?, flagged: [CrossbiteFlag] = [], reliability: Reliability) {
        self.label = label
        self.flagged = flagged
        self.reliability = reliability
    }

    enum CodingKeys: String, CodingKey {
        case label, flagged, reliable
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        label = try c.decodeIfPresent(String.self, forKey: .label)
        flagged = try c.decodeIfPresent([CrossbiteFlag].self, forKey: .flagged) ?? []
        let reliable = try c.decodeIfPresent(Bool.self, forKey: .reliable) ?? false
        reliability = reliable ? .reliable : .unreliable
    }

    func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encodeIfPresent(label, forKey: .label)
        try c.encode(flagged, forKey: .flagged)
        try c.encode(reliability == .reliable, forKey: .reliable)
    }
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

    /// Annotation geometry per view, keyed by the wire field names.
    ///
    /// Optional so cases stored before overlays existed still decode, and so a
    /// server that has not implemented them yet simply omits the key.
    var overlays: OverlaySet?

    enum CodingKeys: String, CodingKey {
        case overjet, overbite, missing, crowding, overlays
        case anteriorCrossbite = "anterior_crossbite"
        case posteriorCrossbite = "crossbite_posterior"
    }

    /// Every annotated view a parameter is read from, in source order.
    ///
    /// Returns all of them rather than the first. Missing teeth is reported
    /// from the occlusal and frontal views together, and the whole point of
    /// the `disagreement` flag is that those two can differ. Showing one view
    /// would hide exactly the case the flag exists for. Overjet and overbite
    /// benefit the same way, since either lateral can be the clean one.
    func overlayTargets(for parameter: DHCParameter) -> [(view: ToothView, overlay: ViewOverlay)] {
        guard let overlays else { return [] }
        return parameter.sourceViews.compactMap { view in
            guard let overlay = overlays[view.wireName], !overlay.isEmpty else { return nil }
            return (view, overlay)
        }
    }

    /// Convenience for callers that only need one view.
    func overlay(for parameter: DHCParameter) -> (view: ToothView, overlay: ViewOverlay)? {
        overlayTargets(for: parameter).first
    }

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
