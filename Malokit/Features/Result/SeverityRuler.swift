import SwiftUI

/// The signature element of the app.
///
/// Every number in this workflow comes off a millimetre ruler held against a
/// model, so scores are drawn as a ruler rather than as a progress bar. The
/// same component carries DHC bands and the AC 1 to 10 scale, which is what
/// makes the two halves of the IOTN feel like one instrument.
struct SeverityRuler: View {
    let value: Double
    let range: ClosedRange<Double>
    let majorStep: Double
    let tint: Color
    var valueLabel: String
    var minorPerMajor: Int = 2

    private var fraction: CGFloat {
        let span = range.upperBound - range.lowerBound
        guard span > 0 else { return 0 }
        return CGFloat((min(max(value, range.lowerBound), range.upperBound) - range.lowerBound) / span)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            GeometryReader { geo in
                let width = geo.size.width
                let x = width * fraction

                ZStack(alignment: .topLeading) {
                    ticks(width: width)

                    // Machined marker: a stem down onto the scale, a chip above.
                    VStack(spacing: 0) {
                        Text(valueLabel)
                            .font(.system(.caption, design: .rounded).weight(.bold))
                            .monospacedDigit()
                            .foregroundStyle(.white)
                            .padding(.horizontal, 8)
                            .padding(.vertical, 3)
                            .background(tint, in: RoundedRectangle(cornerRadius: 6, style: .continuous))
                        Rectangle()
                            .fill(tint)
                            .frame(width: 2, height: 20)
                    }
                    .offset(x: clampedOffset(x, width: width), y: 0)
                }
            }
            .frame(height: 46)

            HStack {
                Text(label(range.lowerBound))
                Spacer()
                Text(label(range.upperBound))
            }
            .font(.caption2)
            .monospacedDigit()
            .foregroundStyle(Theme.inkSoft)
        }
    }

    private func clampedOffset(_ x: CGFloat, width: CGFloat) -> CGFloat {
        let chipHalf: CGFloat = 20
        return min(max(x - chipHalf, -4), width - chipHalf * 2 + 4)
    }

    private func ticks(width: CGFloat) -> some View {
        let span = range.upperBound - range.lowerBound
        let majorCount = Int((span / majorStep).rounded())
        let totalTicks = majorCount * minorPerMajor

        return ZStack(alignment: .bottomLeading) {
            Rectangle()
                .fill(Theme.hairline)
                .frame(height: 1)
                .offset(y: -1)

            ForEach(0...totalTicks, id: \.self) { index in
                let isMajor = index % minorPerMajor == 0
                let x = width * CGFloat(index) / CGFloat(totalTicks)
                Rectangle()
                    .fill(isMajor ? Theme.inkSoft : Theme.hairline)
                    .frame(width: isMajor ? 1.5 : 1, height: isMajor ? 12 : 7)
                    .offset(x: x - 0.75, y: 0)
            }
        }
        .frame(height: 46, alignment: .bottom)
    }

    private func label(_ value: Double) -> String {
        value == value.rounded() ? String(Int(value)) : String(format: "%.1f", value)
    }
}

#Preview {
    VStack(spacing: 32) {
        SeverityRuler(value: 8, range: 1...10, majorStep: 1, tint: Theme.urgent, valueLabel: "8")
        SeverityRuler(value: 9.5, range: 0...12, majorStep: 2, tint: Theme.urgent, valueLabel: "9.5 mm")
    }
    .padding(30)
    .background(Theme.surface)
}
