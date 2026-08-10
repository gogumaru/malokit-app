import Foundation

/// The five intraoral views the pipeline requires, in the order the
/// clinician is asked to shoot them.
enum ToothView: String, Codable, CaseIterable, Identifiable, Hashable {
    case front
    case right
    case left
    case maxillary
    case mandibular

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
        case .mandibular: "Mirror against the lower arch. Keep the tongue out of the frame."
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

    /// Aspect of the guide frame drawn over the live preview.
    var guideAspect: CGFloat {
        switch self {
        case .front, .right, .left: 4.0 / 3.0
        case .maxillary, .mandibular: 3.0 / 4.0
        }
    }

    var step: Int { (ToothView.allCases.firstIndex(of: self) ?? 0) + 1 }
}
