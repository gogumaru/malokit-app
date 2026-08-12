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
        case anchor
        case measurement
        case archCurve
        case gap

        var title: String {
            switch self {
            case .tooth:       "Segmentation"
            case .flagged:     "Flagged teeth"
            case .anchor:      "Detections"
            case .measurement: "Measurements"
            case .archCurve:   "Arch curve"
            case .gap:         "Gaps"
            }
        }

        var tint: Color {
            switch self {
            case .tooth:       Color(hex: 0x2BC4C4)
            case .flagged:     Color(hex: 0xF08A24)
            case .anchor:      Color(hex: 0xD94BC4)
            case .measurement: Color(hex: 0xE03B3B)
            case .archCurve:   Color(hex: 0xF2C230)
            case .gap:         Color(hex: 0xE03B3B)
            }
        }

        var lineWidth: CGFloat {
            switch self {
            case .tooth, .anchor: 1.6
            case .flagged:        2.4
            case .measurement, .gap, .archCurve: 2.0
            }
        }
    }

    enum CodingKeys: String, CodingKey {
        case kind, role, points, label
    }
}

/// All annotations for one captured view.
struct ViewOverlay: Codable, Hashable {
    var shapes: [OverlayShape]

    var roles: [OverlayShape.Role] {
        OverlayShape.Role.allCases.filter { role in
            shapes.contains { $0.role == role }
        }
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
