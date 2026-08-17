import CoreGraphics
import Foundation
import SwiftUI

/// Annotation geometry drawn over a captured photo.
///
/// The pipeline sends coordinates, not a rendered picture. That choice is what
/// makes the annotation interactive rather than decorative: the app knows which
/// polygon is tooth 3, so it can highlight the teeth the crowding rule flagged,
/// let the clinician tap one, and keep everything sharp when zoomed. A finished
/// PNG would be pixels, and none of that would be possible.
///
/// It is also far smaller. Fourteen tooth outlines is a few kilobytes of
/// numbers against hundreds of kilobytes of image.
struct OverlayShape: Codable, Hashable, Identifiable {
    var id: UUID = UUID()
    var kind: Kind
    var role: Role
    /// Normalised to the image, 0 to 1 on both axes, origin top left. Resolution
    /// independent, so the same numbers work on a thumbnail and at full zoom.
    var points: [NormalizedPoint]
    /// Short caption drawn at the shape's centre, for example a tooth index.
    var label: String?
    /// Which reported parameters this shape helps check, using the response
    /// keys verbatim. Empty means always relevant, which is how outlines and
    /// the arch curve stay on screen as context.
    ///
    /// Separate from `role` on purpose: `role` answers "what is this" and picks
    /// the colour, `params` answers "what does this help check" and drives
    /// filtering. One incisor box serves overjet, overbite and anterior
    /// crossbite at once, which no amount of role splitting can express.
    var params: [String]

    enum Kind: String, Codable {
        case polygon
        /// Two points: top left and bottom right.
        case box
        case line
        case point
    }

    /// What the shape means. Colour and stroke follow from this rather than
    /// being sent by the server, so the app can restyle without a server change
    /// and the palette stays consistent with the rest of the UI.
    enum Role: String, Codable, CaseIterable {
        case tooth
        case flagged
        case crossbite
        /// Raw detector output.
        case anchor
        /// The tooth the measurement was actually taken from. Kept apart from
        /// `anchor` because the two can disagree, and when they do, seeing two
        /// colours fail to overlap is the fastest way to spot it. The incisor
        /// is the denominator behind every overjet and overbite figure, so
        /// being unable to pick it out was a real gap.
        case reference
        case measurement
        case archCurve
        case gap
        /// Masks the pipeline discarded: edge slivers and arch-curve outliers.
        /// Off by default, because on a good case they are noise. On a bad one
        /// they are the whole explanation.
        case rejected
        /// Anything this app version does not recognise. Drawn neutrally rather
        /// than dropped, so a newer server can add roles without this app
        /// silently losing shapes or refusing the whole response.
        case unknown

        /// Lenient decoding is the point: an unrecognised string becomes
        /// `.unknown` instead of throwing and taking the entire analysis with it.
        init(from decoder: Decoder) throws {
            let raw = try decoder.singleValueContainer().decode(String.self)
            self = Role(rawValue: raw) ?? .unknown
        }

        var title: String {
            switch self {
            case .tooth:       "Segmentation"
            case .flagged:     "Flagged teeth"
            case .crossbite:   "Crossbite"
            case .anchor:      "Detections"
            case .reference:   "Measured from"
            case .measurement: "Measurements"
            case .archCurve:   "Arch curve"
            case .gap:         "Gaps"
            case .rejected:    "Discarded masks"
            case .unknown:     "Other"
            }
        }

        var tint: Color {
            switch self {
            case .tooth:       Color(hex: 0x2BC4C4)
            case .flagged:     Color(hex: 0xF08A24)
            case .crossbite:   Color(hex: 0x3B7DD8)
            case .anchor:      Color(hex: 0xD94BC4)
            case .reference:   Color(hex: 0x2E9E5B)
            case .measurement: Color(hex: 0xE03B3B)
            case .archCurve:   Color(hex: 0xF2C230)
            case .gap:         Color(hex: 0xE03B3B)
            case .rejected:    Color(hex: 0x9AA5A3)
            case .unknown:     Color(hex: 0x9AA5A3)
            }
        }

        var lineWidth: CGFloat {
            switch self {
            case .tooth, .anchor, .unknown: 1.6
            case .flagged, .crossbite:      2.4
            case .reference:                2.2
            case .rejected:                 1.4
            case .measurement, .gap, .archCurve: 2.0
            }
        }

        /// Discarded and unrecognised shapes are dashed, so they read as
        /// "context" rather than as a finding even before the legend is read.
        var dash: [CGFloat] {
            switch self {
            case .rejected, .unknown: [4, 3]
            default: []
            }
        }

        /// Shown only when the reader asks. Everything else starts visible.
        var isHiddenByDefault: Bool { self == .rejected }
    }

    enum CodingKeys: String, CodingKey {
        case kind, role, points, label, params
    }

    init(
        kind: Kind,
        role: Role,
        points: [NormalizedPoint],
        label: String? = nil,
        params: [String] = []
    ) {
        self.kind = kind
        self.role = role
        self.points = points
        self.label = label
        self.params = params
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        kind = try c.decode(Kind.self, forKey: .kind)
        role = try c.decode(Role.self, forKey: .role)
        points = try c.decode([NormalizedPoint].self, forKey: .points)
        label = try c.decodeIfPresent(String.self, forKey: .label)
        // Absent means "no filtering information", which must behave exactly
        // like today: the shape is always shown. A server that has not shipped
        // params yet keeps working unchanged.
        params = try c.decodeIfPresent([String].self, forKey: .params) ?? []
    }

    /// Whether this shape belongs on screen while `parameter` is being read.
    /// A shape with no params is context and always shows.
    func isRelevant(to parameter: String?) -> Bool {
        guard let parameter, !params.isEmpty else { return true }
        return params.contains(parameter)
    }
}

/// All annotations for one captured view.
///
/// Malformed shapes are skipped instead of failing the response. One bad
/// polygon should cost one polygon, not the patient's whole analysis.
struct ViewOverlay: Codable, Hashable {
    var shapes: [OverlayShape]

    init(shapes: [OverlayShape]) {
        self.shapes = shapes
    }

    private struct Lossy: Decodable {
        let shape: OverlayShape?
        init(from decoder: Decoder) throws {
            shape = try? OverlayShape(from: decoder)
        }
    }

    enum CodingKeys: String, CodingKey { case shapes }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        let lossy = try c.decodeIfPresent([Lossy].self, forKey: .shapes) ?? []
        shapes = lossy.compactMap(\.shape)
    }

    var roles: [OverlayShape.Role] {
        OverlayShape.Role.allCases.filter { role in
            shapes.contains { $0.role == role }
        }
    }

    /// Shapes worth showing while `parameter` is being read.
    func shapes(for parameter: String?) -> [OverlayShape] {
        shapes.filter { $0.isRelevant(to: parameter) }
    }

    /// Whether anything specific to this parameter exists at all.
    ///
    /// A parameter whose result is normal has no shapes of its own: only the
    /// segmentation outlines that serve as context. On screen that is
    /// indistinguishable from annotations having failed to load, so the viewer
    /// needs to say which it is.
    func hasParameterShapes(for parameter: String?) -> Bool {
        shapes(for: parameter).contains { !$0.params.isEmpty }
    }

    /// True when filtering would actually hide something. Drives whether the
    /// "show everything" toggle is offered at all, so it does not appear on
    /// views where it would do nothing.
    func hasFilterableContent(for parameter: String?) -> Bool {
        guard parameter != nil else { return false }
        return shapes.contains { !$0.params.isEmpty }
            && shapes(for: parameter).count < shapes.count
    }

    var isEmpty: Bool { shapes.isEmpty }
}

/// Keyed by the contract's form field names (`frontal`, `lateral_kanan`, ...)
/// so the wire format needs no translation table.
typealias OverlaySet = [String: ViewOverlay]

extension ToothView {
    /// The wire field name for this view, shared with the upload side.
    var wireName: String {
        switch self {
        case .front:      "frontal"
        case .right:      "lateral_kanan"
        case .left:       "lateral_kiri"
        case .maxillary:  "oklusal_atas"
        case .mandibular: "oklusal_bawah"
        }
    }
}

/// A point in image space, 0 to 1 on both axes, origin top left.
///
/// Its own type rather than CGPoint because the wire format is a bare pair
/// `[0.31, 0.62]`, and CGPoint's built-in Codable uses a different shape. Being
/// explicit here also documents that these are fractions, not pixels.
struct NormalizedPoint: Codable, Hashable {
    var x: Double
    var y: Double

    init(_ x: Double, _ y: Double) {
        self.x = x
        self.y = y
    }

    init(from decoder: Decoder) throws {
        var c = try decoder.unkeyedContainer()
        x = try c.decode(Double.self)
        y = try c.decode(Double.self)
    }

    func encode(to encoder: Encoder) throws {
        var c = encoder.unkeyedContainer()
        try c.encode(x)
        try c.encode(y)
    }

    /// Maps into the on-screen rectangle the photo actually occupies.
    func resolved(in rect: CGRect) -> CGPoint {
        CGPoint(x: rect.minX + x * rect.width, y: rect.minY + y * rect.height)
    }
}
