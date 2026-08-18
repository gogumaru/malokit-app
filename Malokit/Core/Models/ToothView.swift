import Foundation

/// The five intraoral views the pipeline requires, in the order the
/// clinician is asked to shoot them.
enum ToothView: String, Codable, CaseIterable, Identifiable, Hashable {
    case front
    case right
    case left
    case maxillary
    case mandibular

    /// The single clinician-facing order used by capture, review, DHC and
    /// Smartee uploads. Do not derive workflow order from enum declaration.
    static let captureOrder: [ToothView] = [
        .front,
        .right,
        .left,
        .maxillary,
        .mandibular
    ]

    var id: String { rawValue }

    var title: String {
        switch self {
        case .front:       "Front"
        case .right:       "Right buccal"
        case .left:        "Left buccal"
        case .maxillary:   "Upper occlusal"
        case .mandibular:  "Lower occlusal"
        }
    }

    /// Shown large during capture. Written as an instruction, not a label.
    var instruction: String {
        switch self {
        case .front:      "Teeth together, retractors wide, midline centred in the frame."
        case .right:      "Turn the retractor to the patient's right. Capture the molar relation."
        case .left:       "Turn the retractor to the patient's left. Capture the molar relation."
        case .maxillary:  "Mirror against the upper arch. Fill the frame with the arch curve."
        case .mandibular: "Aim directly at the lower arch. Keep the tongue out of the frame."
        }
    }

    /// What this view is actually used for downstream. Shown as a caption so
    /// the person shooting knows why a retake matters.
    var feeds: String {
        switch self {
        case .front:      "Angle midline, AC score, overjet check"
        case .right:      "Angle class right, overjet, overbite"
        case .left:       "Angle class left, overjet, overbite"
        case .maxillary:  "Crowding, rotation, crossbite, 3D upper"
        case .mandibular: "Crowding, displacement, crossbite, 3D lower"
        }
    }

    var symbol: String {
        switch self {
        case .front:      "face.smiling"
        case .right:      "arrow.right.circle"
        case .left:       "arrow.left.circle"
        case .maxillary:  "arrow.up.circle"
        case .mandibular: "arrow.down.circle"
        }
    }

    /// Explicit multipart name expected by the Smartee reconstruction server.
    var smarteeFieldName: String {
        switch self {
        case .front: "front"
        case .right: "rightLateral"
        case .left: "leftLateral"
        case .maxillary: "maxillary"
        case .mandibular: "mandibular"
        }
    }

    /// Maxillary is captured through a mirror, so its depth is diagnostic
    /// only. Every direct view records an ordered K0–K6 Figure-8 bundle.
    var requiresFigure8: Bool { self != .maxillary }
    var isMirrorLiDARView: Bool { self == .maxillary }

    /// The live guide and the persisted RGB crop share this exact geometry.
    var guideAspect: CGFloat { 3.0 / 2.0 }

    var step: Int { (ToothView.captureOrder.firstIndex(of: self) ?? 0) + 1 }
}
