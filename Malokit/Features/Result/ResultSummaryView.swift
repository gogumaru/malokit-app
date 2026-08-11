import SwiftUI

struct ResultSummaryView: View {
    let caseID: UUID
    @Binding var path: [Route]

    @Environment(CaseStore.self) private var store

    private var record: CaseRecord? { store.record(caseID) }
    private var result: AnalysisResult? { record?.result }

    var body: some View {
        ScrollView {
            if let result {
                VStack(alignment: .leading, spacing: 16) {
                    summaryCard(result)
                    disclaimerCard
                    angleCard(result.angle)
                    featureCards(result)
                    if let narrative = result.narrative {
                        narrativeCard(narrative)
                    }
                    provenance(result)
                }
                .padding(20)
            } else {
                Text("This case has no results yet.")
                    .font(.subheadline)
                    .foregroundStyle(Theme.inkSoft)
                    .padding(40)
            }
        }
        .screenBackground()
        .navigationTitle(record?.label ?? "Result")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            if let narrative = result?.narrative {
                ToolbarItem(placement: .topBarTrailing) {
                    ShareLink(item: narrative) { Image(systemName: "square.and.arrow.up") }
                }
            }
        }
    }

    // MARK: - Summary

    private func summaryCard(_ result: AnalysisResult) -> some View {
        let summary = result.summary
        return VStack(alignment: .leading, spacing: 10) {
            Eyebrow(text: "Case summary")
            Text(summary.rawValue)
                .font(.system(size: 30, weight: .bold, design: .rounded))
                .foregroundStyle(summaryTint(summary))
            Text("\(result.dhc.reliableCount) of 6 parameters reliable. Every result needs manual review.")
                .font(.subheadline)
                .foregroundStyle(Theme.inkSoft)

            if !result.dhc.notComputedParameters.isEmpty {
                Text("Could not compute: \(result.dhc.notComputedParameters.map(\.title).joined(separator: ", "))")
                    .font(.caption)
                    .foregroundStyle(Theme.inkSoft)
                    .padding(.top, 2)
            }
        }
        .card(padding: 20)
    }

    private func summaryTint(_ summary: AnalysisResult.CaseSummary) -> Color {
        switch summary {
        case .reviewNeeded:  Theme.watch
        case .partialResult: Theme.inkSoft
        case .findingsFound: Theme.ink
        case .clear:         Theme.calm
        }
    }

    /// The brief calls this the most important thing in the whole document.
    /// It is not a footnote here, it is a card near the top.
    private var disclaimerCard: some View {
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: "stethoscope")
                .foregroundStyle(Theme.accent)
            Text("A research aid, not a diagnosis. The pipeline is calibrated on a small sample and does not produce a combined IOTN grade. Always confirm against the photos.")
                .font(.caption)
                .foregroundStyle(Theme.inkSoft)
        }
        .card(padding: 12)
    }

    // MARK: - Angle

    private func angleCard(_ angle: AngleReading) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Eyebrow(text: "Angle" + (angle.side.map { " . \($0) side" } ?? ""))
                Spacer()
                if angle.disagreement {
                    reviewChip
                }
            }
            HStack(spacing: 16) {
                anglePart("Molar", angle.molar)
                Divider().frame(height: 40)
                anglePart("Canine", angle.canine)
                Spacer()
            }
            if angle.disagreement {
                Text("Molar and canine disagree, manual review advised.")
                    .font(.caption)
                    .foregroundStyle(Theme.watch)
            }
        }
        .card()
    }

    private func anglePart(_ label: String, _ reading: Reading) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(label).font(.caption2).foregroundStyle(Theme.inkSoft)
            if reading.hasValue {
                Text(reading.label ?? reading.formatted())
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(Theme.ink)
            } else {
                Text("Not computed")
                    .font(.subheadline)
                    .foregroundStyle(Theme.inkSoft)
            }
        }
    }

    private var reviewChip: some View {
        HStack(spacing: 4) {
            Image(systemName: "exclamationmark.triangle.fill")
            Text("Review")
        }
        .font(.caption2.weight(.semibold))
        .foregroundStyle(.white)
        .padding(.horizontal, 8).padding(.vertical, 3)
        .background(Theme.watch, in: Capsule())
    }

    // MARK: - Feature cards

    private func featureCards(_ result: AnalysisResult) -> some View {
        VStack(spacing: 12) {
            featureCard(
                title: "DHC parameters",
                value: "\(result.dhc.reliableCount) of 6 reliable",
                detail: result.dhc.hasAnyWarning ? "Some readings need review" : "Tap to see each parameter",
                tint: result.dhc.hasAnyWarning ? Theme.watch : Theme.accent,
                symbol: "ruler"
            ) { path.append(.dhc(caseID)) }

            if let ac = result.ac {
                featureCard(
                    title: "IOTN AC",
                    value: "\(ac.score) of 10",
                    detail: ac.band.rawValue,
                    tint: Theme.severity(ac.band),
                    symbol: "photo.stack"
                ) { path.append(.ac(caseID)) }
            } else {
                unavailableCard(
                    title: "IOTN AC",
                    detail: "The aesthetic component comes from a separate pipeline that is not connected yet.",
                    symbol: "photo.stack"
                )
            }

            featureCard(
                title: "3D view",
                value: result.model3DFilename == nil ? "Preview mesh" : "Reconstructed",
                detail: "Rotate, zoom, measure",
                tint: Theme.accent,
                symbol: "cube.transparent"
            ) { path.append(.teeth3D(caseID)) }
        }
    }

    private func featureCard(
        title: String,
        value: String,
        detail: String,
        tint: Color,
        symbol: String,
        action: @escaping () -> Void
    ) -> some View {
        Button(action: action) {
            HStack(spacing: 14) {
                Image(systemName: symbol)
                    .font(.title3)
                    .foregroundStyle(tint)
                    .frame(width: 40, height: 40)
                    .background(Theme.accentDim, in: RoundedRectangle(cornerRadius: 12, style: .continuous))

                VStack(alignment: .leading, spacing: 2) {
                    Text(title).font(.caption).foregroundStyle(Theme.inkSoft)
                    Text(value).font(.subheadline.weight(.semibold)).foregroundStyle(Theme.ink)
                    Text(detail).font(.caption2).foregroundStyle(Theme.inkSoft)
                }

                Spacer()
                Image(systemName: "chevron.right")
                    .font(.footnote.weight(.semibold))
                    .foregroundStyle(Theme.hairline)
            }
            .card(padding: 12)
        }
        .buttonStyle(.plain)
    }

    /// Honest placeholder for a feature the connected engine does not produce.
    /// Shown as visibly inert so nobody reads it as a pending result.
    private func unavailableCard(title: String, detail: String, symbol: String) -> some View {
        HStack(spacing: 14) {
            Image(systemName: symbol)
                .font(.title3)
                .foregroundStyle(Theme.inkSoft)
                .frame(width: 40, height: 40)
                .background(Theme.surface, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
            VStack(alignment: .leading, spacing: 2) {
                Text(title).font(.caption).foregroundStyle(Theme.inkSoft)
                Text("Not available").font(.subheadline.weight(.semibold)).foregroundStyle(Theme.inkSoft)
                Text(detail).font(.caption2).foregroundStyle(Theme.inkSoft)
            }
            Spacer()
        }
        .card(padding: 12)
        .opacity(0.7)
    }

    private func narrativeCard(_ text: String) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Eyebrow(text: "Report")
            Text(text)
                .font(.subheadline)
                .foregroundStyle(Theme.ink)
                .lineSpacing(3)
        }
        .card()
    }

    private func provenance(_ result: AnalysisResult) -> some View {
        Text("\(result.engineName) . \(result.generatedAt.formatted(date: .abbreviated, time: .shortened))")
            .font(.caption2)
            .foregroundStyle(Theme.inkSoft)
            .frame(maxWidth: .infinity, alignment: .center)
            .padding(.top, 4)
    }
}
