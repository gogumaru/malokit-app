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
                    verdict(result)
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

    // MARK: - Sections

    private func verdict(_ result: AnalysisResult) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Eyebrow(text: "IOTN verdict")
            Text(result.verdict.rawValue)
                .font(.system(size: 34, weight: .bold, design: .rounded))
                .foregroundStyle(Theme.severity(result.verdict))
            Text(reason(result))
                .font(.subheadline)
                .foregroundStyle(Theme.inkSoft)
        }
        .card(padding: 20)
    }

    private func reason(_ result: AnalysisResult) -> String {
        let dhcPart = "\(result.dhc.decidingComponent.title.lowercased()) reaches \(result.dhc.band.rawValue.lowercased())"
        let acPart = "aesthetic component scores \(result.ac.score) of 10"
        return "Decided by \(dhcPart), and the \(acPart)."
    }

    private func angleCard(_ angle: AngleResult) -> some View {
        HStack(spacing: 16) {
            side("Right", angle.right)
            Divider().frame(height: 42)
            side("Left", angle.left)
            Spacer()
            VStack(alignment: .trailing, spacing: 2) {
                Eyebrow(text: "Angle")
                Text(angle.isBilateral ? "Bilateral" : "Asymmetric")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(Theme.ink)
                Text("\(Int(angle.confidence * 100))% confident")
                    .font(.caption2)
                    .foregroundStyle(Theme.inkSoft)
            }
        }
        .card()
    }

    private func side(_ label: String, _ value: AngleClass) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(label).font(.caption2).foregroundStyle(Theme.inkSoft)
            Text(value.shortLabel)
                .font(.system(.title3, design: .rounded).weight(.bold))
                .foregroundStyle(Theme.ink)
        }
    }

    private func featureCards(_ result: AnalysisResult) -> some View {
        VStack(spacing: 12) {
            featureCard(
                title: "IOTN DHC",
                value: result.dhc.decidingComponent.title,
                detail: result.dhc.decidingFinding?.measurementText ?? "",
                band: result.dhc.band,
                symbol: "ruler"
            ) { path.append(.dhc(caseID)) }

            featureCard(
                title: "IOTN AC",
                value: "\(result.ac.score) of 10",
                detail: result.ac.band.rawValue,
                band: result.ac.band,
                symbol: "photo.stack"
            ) { path.append(.ac(caseID)) }

            featureCard(
                title: "3D view",
                value: result.model3DFilename == nil ? "Preview mesh" : "Reconstructed",
                detail: "Rotate, zoom, measure",
                band: nil,
                symbol: "cube.transparent"
            ) { path.append(.teeth3D(caseID)) }
        }
    }

    private func featureCard(
        title: String,
        value: String,
        detail: String,
        band: SeverityBand?,
        symbol: String,
        action: @escaping () -> Void
    ) -> some View {
        Button(action: action) {
            HStack(spacing: 14) {
                Image(systemName: symbol)
                    .font(.title3)
                    .foregroundStyle(band.map(Theme.severity) ?? Theme.accent)
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
