import SwiftUI

struct ResultSummaryView: View {
    let caseID: UUID
    @Binding var path: [Route]

    @Environment(CaseStore.self) private var store
    @Environment(ServerSettings.self) private var settings
    @Environment(ReconstructionService.self) private var reconstructionService

    @State private var inspectingAngle: AngleInspection?

    private struct AngleInspection: Identifiable {
        let id = UUID()
        let view: ToothView
        let overlay: ViewOverlay
        let context: String
    }

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
        .sheet(item: $inspectingAngle) { target in
                    OverlaySheet(
                        caseID: caseID,
                        view: target.view,
                        overlay: target.overlay,
                        context: target.context
                    )
                }
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
            angleInspectButton(angle)
        
        }
        .card()
    }
    
    /// Opens the lateral view Angle was read from.
        ///
        /// Angle shares its anchors with overjet, so when molar reads "not
        /// computed" the useful question is whether the detector found the molar at
        /// all. Seeing the boxes answers that; the words cannot.
        @ViewBuilder
        private func angleInspectButton(_ angle: AngleReading) -> some View {
            if let overlays = result?.dhc.overlays {
                // Prefer the side Angle actually reported, fall back to whichever
                // lateral view has annotations.
                let preferred: [ToothView] = angle.side?.lowercased().contains("left") == true
                    ? [.left, .right]
                    : [.right, .left]

                if let match = preferred.compactMap({ view -> (ToothView, ViewOverlay)? in
                    guard let overlay = overlays[view.wireName], !overlay.isEmpty else { return nil }
                    return (view, overlay)
                }).first {
                    Button {
                        inspectingAngle = AngleInspection(
                            view: match.0,
                            overlay: match.1,
                            context: angle.hasAnyValue
                                ? "Angle is read from the canine and molar anchors. Check the boxes are on teeth."
                                : "Angle could not be read. The detections below are what the model did find."
                        )
                    } label: {
                        HStack(spacing: 6) {
                            Image(systemName: "viewfinder")
                            Text("Show on \(match.0.title.lowercased())")
                            Spacer()
                            Image(systemName: "chevron.right").font(.caption2)
                        }
                        .font(.caption.weight(.medium))
                        .foregroundStyle(Theme.accent)
                        .padding(.top, 2)
                    }
                    .buttonStyle(.plain)
                }
            }
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

            featureCard(
                title: "IOTN AC",
                value: result.ac.isScorable ? "\(result.ac.score) of 10" : "Not scored",
                detail: result.ac.isScorable ? result.ac.band.rawValue : (result.ac.rejectionReason ?? "Out of model scope"),
                tint: result.ac.isScorable ? Theme.severity(result.ac.band) : Theme.inkSoft,
                symbol: "photo.stack"
            ) { path.append(.ac(caseID)) }

            featureCard(
                title: "3D view",
                value: reconstructionValue(result),
                detail: reconstructionDetail(result),
                tint: reconstructionTint(result),
                symbol: "cube.transparent"
            ) {
                switch ReconstructionAvailability.resolve(result.reconstruction) {
                case .ready: path.append(.teeth3D(caseID))
                case .processing: break
                case .needsReconstruction, .failed:
                    reconstructionService.start(
                        caseID: caseID,
                        store: store,
                        reconstructor: settings.makeReconstructor()
                    )
                }
            }
        }
    }

    private func reconstructionValue(_ result: AnalysisResult) -> String {
        switch ReconstructionAvailability.resolve(result.reconstruction) {
        case .ready: "Ready to view"
        case .processing: "Building your 3D model"
        case .failed: "3D model unavailable"
        case .needsReconstruction: "3D model not built yet"
        }
    }

    private func reconstructionDetail(_ result: AnalysisResult) -> String {
        switch ReconstructionAvailability.resolve(result.reconstruction) {
        case .ready: "Tap to see your upper and lower teeth in 3D"
        case .processing(let progress):
            "\(progress.label) • Step \(progress.completedSteps + 1) of \(progress.totalSteps) (\(progress.percentComplete)%)"
        case .failed(let message): "Tap to try again — " + message
        case .needsReconstruction: "Tap to build it"
        }
    }

    private func reconstructionTint(_ result: AnalysisResult) -> Color {
        switch ReconstructionAvailability.resolve(result.reconstruction) {
        case .ready, .processing: Theme.accent
        case .needsReconstruction, .failed: Theme.watch
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
