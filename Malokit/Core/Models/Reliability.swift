import SwiftUI

enum Reliability: String, Codable, Hashable {
    /// A value exists and passed the pipeline guards.
    case reliable
    /// A value exists but a guard flagged it, for example both sides were
    /// problematic or the measurement is clinically implausible.
    case unreliable
    /// No value could be produced, for example the canine anchor was missing
    /// so overjet has nothing to measure from.
    case notComputed

    var badgeText: String {
        switch self {
        case .reliable:    "Reliable"
        case .unreliable:  "Review needed"
        case .notComputed: "Not computed"
        }
    }

    var symbol: String {
        switch self {
        case .reliable:    "checkmark.seal.fill"
        case .unreliable:  "exclamationmark.triangle.fill"
        case .notComputed: "questionmark.circle"
        }
    }

    var tint: Color {
        switch self {
        case .reliable:    Theme.calm
        case .unreliable:  Theme.watch
        case .notComputed: Theme.inkSoft
        }
    }

    var isTrustworthy: Bool { self == .reliable }
}

struct Reading: Codable, Hashable {
    var value: Double?
    /// Human label from the pipeline, for example "possible excess overjet".
    var label: String?
    /// Which side the reported value came from, when relevant.
    var side: String?
    var reliability: Reliability
    var warnings: [String]

    init(
        value: Double?,
        label: String? = nil,
        side: String? = nil,
        reliability: Reliability,
        warnings: [String] = []
    ) {
        self.value = value
        self.label = label
        self.side = side
        self.reliability = reliability
        self.warnings = warnings
    }

    // The JSON uses `reliable: Bool` and a possibly-null `value`. Map that pair
    // onto the three-state enum on the way in, so the rest of the app only ever
    // sees Reliability, never a raw bool that could be misread.
    enum CodingKeys: String, CodingKey {
        case value, label, side, reliable, warnings
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        value = try c.decodeIfPresent(Double.self, forKey: .value)
        label = try c.decodeIfPresent(String.self, forKey: .label)
        side = try c.decodeIfPresent(String.self, forKey: .side)
        warnings = try c.decodeIfPresent([String].self, forKey: .warnings) ?? []

        let reliable = try c.decodeIfPresent(Bool.self, forKey: .reliable) ?? false
        if value == nil {
            reliability = .notComputed
        } else {
            reliability = reliable ? .reliable : .unreliable
        }
    }

    func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encodeIfPresent(value, forKey: .value)
        try c.encodeIfPresent(label, forKey: .label)
        try c.encodeIfPresent(side, forKey: .side)
        try c.encode(reliability == .reliable, forKey: .reliable)
        try c.encode(warnings, forKey: .warnings)
    }

    var hasValue: Bool { value != nil }

    /// Formatted number, or a dash when there is nothing to show.
    func formatted(_ fractionDigits: Int = 2) -> String {
        guard let value else { return "—" }
        return String(format: "%.\(fractionDigits)f", value)
    }
}
