import SwiftUI

/// The DHC screen reports MOCDO cases, not a 30 grade taxonomy. It shows
/// which components were found, what each one measures, and which one won.
struct DHCDetailView: View {
    let caseID: UUID
    @Environment(CaseStore.self) private var store

    private var dhc: DHCResult? { store.record(caseID)?.result?.dhc }

    var body: some View {
        ScrollView {
            if let dhc {
                VStack(alignment: .leading, spacing: 16) {
                    deciding(dhc)
                    detectedSection(dhc)
                    if !dhc.clearComponents.isEmpty {
                        clearSection(dhc)
                    }
                    ruleNote
                }
                .padding(20)
            } else {
                Text("No dental health component for this case.")
                    .foregroundStyle(Theme.inkSoft)
                    .padding(40)
            }
        }
        .screenBackground()
        .navigationTitle("IOTN DHC")
        .navigationBarTitleDisplayMode(.inline)
    }

    private func deciding(_ dhc: DHCResult) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Eyebrow(text: "Deciding MOCDO case")
            HStack(alignment: .firstTextBaseline, spacing: 10) {
                Text(dhc.decidingComponent.title)
                    .font(.title2.weight(.bold))
                    .foregroundStyle(Theme.ink)
                Text(dhc.decidingComponent.letter)
                    .font(.system(.caption, design: .monospaced).weight(.bold))
                    .foregroundStyle(.white)
                    .padding(.horizontal, 6).padding(.vertical, 2)
                    .background(Theme.severity(dhc.band), in: RoundedRectangle(cornerRadius: 5))
            }

            if let finding = dhc.decidingFinding {
                Text(finding.reading)
                    .font(.subheadline)
                    .foregroundStyle(Theme.inkSoft)

                if let mm = finding.millimetres {
                    SeverityRuler(
                        value: mm,
                        range: 0...12,
                        majorStep: 2,
                        tint: Theme.severity(dhc.band),
                        valueLabel: String(format: "%.1f mm", mm)
                    )
                    .padding(.top, 4)
                }
            }

            Text(dhc.band.rawValue)
                .font(.footnote.weight(.semibold))
                .foregroundStyle(.white)
                .padding(.horizontal, 10).padding(.vertical, 5)
                .background(Theme.severity(dhc.band), in: Capsule())
        }
        .card(padding: 20)
    }

    private func detectedSection(_ dhc: DHCResult) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Eyebrow(text: "Detected, \(dhc.detected.count) of 5 components")
            ForEach(dhc.detected) { finding in
                findingRow(finding, isDeciding: finding.component == dhc.decidingComponent)
            }
        }
    }

    private func findingRow(_ finding: MOCDOFinding, isDeciding: Bool) -> some View {
        HStack(spacing: 12) {
            Image(systemName: finding.component.symbol)
                .font(.subheadline)
                .foregroundStyle(Theme.severity(finding.band))
                .frame(width: 34, height: 34)
                .background(Theme.accentDim, in: RoundedRectangle(cornerRadius: 10, style: .continuous))

            VStack(alignment: .leading, spacing: 2) {
                HStack(spacing: 6) {
                    Text(finding.component.title)
                        .font(.subheadline.weight(.semibold))
                        .foregroundStyle(Theme.ink)
                    if isDeciding {
                        Text("decides")
                            .font(.system(size: 9, weight: .bold))
                            .foregroundStyle(.white)
                            .padding(.horizontal, 5).padding(.vertical, 1.5)
                            .background(Theme.ink, in: Capsule())
                    }
                }
                Text(finding.reading).font(.caption).foregroundStyle(Theme.inkSoft)
                Text("Rule: \(finding.component.thresholdNote)")
                    .font(.caption2)
                    .foregroundStyle(Theme.inkSoft.opacity(0.75))
            }

            Spacer()

            VStack(alignment: .trailing, spacing: 2) {
                Text(finding.measurementText)
                    .font(.system(.subheadline, design: .rounded).weight(.bold))
                    .monospacedDigit()
                    .foregroundStyle(Theme.severity(finding.band))
                Text("\(Int(finding.confidence * 100))%")
                    .font(.caption2)
                    .foregroundStyle(Theme.inkSoft)
            }
        }
        .card(padding: 12)
    }

    private func clearSection(_ dhc: DHCResult) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Eyebrow(text: "Checked and clear")
            ForEach(dhc.clearComponents) { component in
                HStack(spacing: 10) {
                    Image(systemName: "checkmark")
                        .font(.caption.weight(.bold))
                        .foregroundStyle(Theme.calm)
                    Text(component.title).font(.subheadline).foregroundStyle(Theme.ink)
                    Spacer()
                    Text(component.sourceViews.map(\.title).joined(separator: ", "))
                        .font(.caption2)
                        .foregroundStyle(Theme.inkSoft)
                }
                .padding(.vertical, 2)
            }
        }
        .card()
    }

    private var ruleNote: some View {
        Text("MOCDO takes one component only, the most severe. A mild finding on another component does not add to the score.")
            .font(.footnote)
            .foregroundStyle(Theme.inkSoft)
    }
}
