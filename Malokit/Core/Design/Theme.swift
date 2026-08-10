import SwiftUI

/// Palette is built from the clinic, not from a generic app template:
/// pine ink for text, cool clinical grey for the room, dental teal for
/// anything the app is confident about, and a warm alert ramp for severity.
enum Theme {
    static let ink       = Color(hex: 0x10221F)
    static let inkSoft   = Color(hex: 0x5A6B68)
    static let surface   = Color(hex: 0xEDF1F0)
    static let card      = Color.white
    static let hairline  = Color(hex: 0xD3DCDA)

    static let accent    = Color(hex: 0x1B7A6B)
    static let accentDim = Color(hex: 0xE2EFEC)

    /// Severity ramp, shared by DHC and AC so a colour always means the
    /// same thing no matter which screen the clinician is on.
    static let calm      = Color(hex: 0x2E7D5B)
    static let watch     = Color(hex: 0xC08526)
    static let urgent    = Color(hex: 0xB23A34)

    static func severity(_ band: SeverityBand) -> Color {
        switch band {
        case .noNeed, .littleNeed: return calm
        case .borderline:          return watch
        case .definiteNeed:        return urgent
        }
    }
}

/// One shared verdict vocabulary. DHC and AC both collapse into this.
enum SeverityBand: String, Codable, CaseIterable {
    case noNeed        = "No need"
    case littleNeed    = "Little need"
    case borderline    = "Borderline need"
    case definiteNeed  = "Definite need"

    var rank: Int {
        switch self {
        case .noNeed: 0
        case .littleNeed: 1
        case .borderline: 2
        case .definiteNeed: 3
        }
    }
}

extension Color {
    init(hex: UInt32) {
        self.init(
            .sRGB,
            red:   Double((hex >> 16) & 0xFF) / 255,
            green: Double((hex >> 8) & 0xFF) / 255,
            blue:  Double(hex & 0xFF) / 255,
            opacity: 1
        )
    }
}

// MARK: - Reusable chrome

struct CardModifier: ViewModifier {
    var padding: CGFloat = 16
    func body(content: Content) -> some View {
        content
            .padding(padding)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Theme.card, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: 18, style: .continuous)
                    .stroke(Theme.hairline, lineWidth: 1)
            )
    }
}

extension View {
    func card(padding: CGFloat = 16) -> some View {
        modifier(CardModifier(padding: padding))
    }

    /// Screen background used everywhere so pushes do not flash white.
    func screenBackground() -> some View {
        background(Theme.surface.ignoresSafeArea())
    }
}

struct Eyebrow: View {
    let text: String
    var tint: Color = Theme.inkSoft

    var body: some View {
        Text(text.uppercased())
            .font(.caption2.weight(.semibold))
            .tracking(1.2)
            .foregroundStyle(tint)
    }
}
