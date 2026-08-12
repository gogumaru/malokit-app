import SwiftUI

/// Lists the six DHC parameters, each showing its reliability state as plainly
/// as its value. The brief section 8 is emphatic: a not-computed result is
/// normal and frequent, and a guard-flagged result must never look fine. This
/// screen is built so those two states are impossible to miss.
struct DHCDetailView: View {
    let caseID: UUID
    @Environment(CaseStore.self) private var store

    private var dhc: DHCResult? { store.record(caseID)?.result?.dhc }

    @State private var inspecting: InspectTarget?

    /// What the overlay sheet is currently showing. Identifiable so it can
    /// drive a sheet item binding.
    private struct InspectTarget: Identifiable {
        let id = UUID()
        let view: ToothView
        let overlay: ViewOverlay
        let context: String
    }

    var body: some View {
        ScrollView {
            if let dhc {
                VStack(alignment: .leading, spacing: 12) {
                    banner
                    readingRow(.overjet, dhc.overjet)
                    readingRow(.overbite, dhc.overbite)
                    anteriorCrossbiteRow(dhc.anteriorCrossbite)
                    posteriorRow(dhc.posteriorCrossbite)
                    missingRow(dhc.missing)
                    crowdingRow(dhc.crowding)
                    footnote
                }
                .padding(20)
            } else {
                Text("No dental health parameters for this case.")
                    .foregroundStyle(Theme.inkSoft)
                    .padding(40)
            }
        }
        .screenBackground()
        .navigationTitle("DHC parameters")
        .navigationBarTitleDisplayMode(.inline)
        .sheet(item: $inspecting) { target in
            OverlaySheet(
                caseID: caseID,
                view: target.view,
                overlay: target.overlay,
                context: target.context
            )
        }
    }

    private var banner: some View {
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: "info.circle").foregroundStyle(Theme.accent)
            Text("Each parameter stands alone. There is no combined grade. Values marked for review or not computed are normal outcomes, not errors.")
                .font(.caption)
                .foregroundStyle(Theme.inkSoft)
        }
        .card(padding: 12)
    }

    // MARK: - Reliability badge, shared by every row

    private func badge(_ reliability: Reliability) -> some View {
        HStack(spacing: 4) {
            Image(systemName: reliability.symbol)
            Text(reliability.badgeText)
        }
        .font(.caption2.weight(.semibold))
        .foregroundStyle(.white)
        .padding(.horizontal, 8).padding(.vertical, 3)
        .background(reliability.tint, in: Capsule())
    }

    private func rowHeader(_ title: String, symbol: String, reliability: Reliability) -> some View {
        HStack(spacing: 10) {
            Image(systemName: symbol)
                .font(.subheadline)
                .foregroundStyle(reliability.tint)
                .frame(width: 32, height: 32)
                .background(Theme.accentDim, in: RoundedRectangle(cornerRadius: 9, style: .continuous))
            Text(title).font(.subheadline.weight(.semibold)).foregroundStyle(Theme.ink)
            Spacer()
            badge(reliability)
        }
    }

    /// Opens the annotated photo behind a parameter.
    ///
    /// Only rendered when annotations exist for that parameter, so the app never
    /// offers to show workings it does not have. This matters most for the
    /// unreliable and not-computed cases: seeing that the model outlined a
    /// fragment outside the mouth explains a bad number far better than a
    /// warning sentence can.
    @ViewBuilder
    private func inspectButton(_ parameter: DHCParameter, context: String) -> some View {
        if let match = dhc?.overlay(for: parameter) {
            Button {
                inspecting = InspectTarget(
                    view: match.view,
                    overlay: match.overlay,
                    context: context
                )
            } label: {
                HStack(spacing: 6) {
                    Image(systemName: "viewfinder")
                    Text("Show on \(match.view.title.lowercased())")
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

    private func warningLines(_ warnings: [String]) -> some View {
        ForEach(warnings, id: \.self) { warning in
            HStack(alignment: .top, spacing: 6) {
                Image(systemName: "exclamationmark.triangle.fill")
                    .font(.caption2)
                    .foregroundStyle(Theme.watch)
                Text(warning).font(.caption).foregroundStyle(Theme.inkSoft)
            }
        }
    }

    // MARK: - Simple numeric parameter (overjet, overbite, anterior crossbite)

    private func readingRow(_ parameter: DHCParameter, _ reading: Reading) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            rowHeader(parameter.title, symbol: parameter.symbol, reliability: reading.reliability)

            if reading.hasValue {
                HStack(alignment: .firstTextBaseline, spacing: 8) {
                    Text(reading.formatted())
                        .font(.system(.title3, design: .rounded).weight(.bold))
                        .monospacedDigit()
                        .foregroundStyle(reading.reliability.tint)
                    if let label = reading.label {
                        Text(label).font(.caption).foregroundStyle(Theme.inkSoft)
                    }
                    if let side = reading.side {
                        Spacer()
                        Text(side).font(.caption2).foregroundStyle(Theme.inkSoft)
                    }
                }
            } else {
                notComputedBlock(parameter)
            }

            warningLines(reading.warnings)
            inspectButton(parameter, context: contextLine(parameter, reading))
        }
        .card(padding: 14)
    }

    private func contextLine(_ parameter: DHCParameter, _ reading: Reading) -> String {
        switch reading.reliability {
        case .reliable:
            "\(parameter.title): \(reading.formatted()). Check the outlines match the teeth."
        case .unreliable:
            "\(parameter.title) was flagged. Check whether the model outlined the right teeth."
        case .notComputed:
            "\(parameter.title) could not be computed. The detections below are what the model did find."
        }
    }

    /// The honest empty state. Points at the photos most likely responsible
    /// rather than showing a blank or a zero.
    private func notComputedBlock(_ parameter: DHCParameter) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text("No value could be computed from the photos.")
                .font(.caption)
                .foregroundStyle(Theme.inkSoft)
            Text("Reads from: \(parameter.sourceViews.map(\.title).joined(separator: ", "))")
                .font(.caption2)
                .foregroundStyle(Theme.inkSoft.opacity(0.8))
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(10)
        .background(Theme.surface, in: RoundedRectangle(cornerRadius: 10, style: .continuous))
    }

    // MARK: - Anterior crossbite

    /// Presented as presence, not as a number.
    ///
    /// The server derives this from the sign of overjet, so its `value` is the
    /// same figure already shown in the overjet row. Repeating it would make a
    /// clinician hunt for a difference that does not exist, so the number is
    /// demoted to a caption and the state is what leads.
    private func anteriorCrossbiteRow(_ reading: Reading) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            rowHeader("Anterior crossbite",
                      symbol: DHCParameter.crossbiteAnterior.symbol,
                      reliability: reading.reliability)

            if reading.hasValue {
                let isPresent = (reading.value ?? 0) < 0
                HStack(spacing: 8) {
                    Image(systemName: isPresent ? "exclamationmark.circle.fill" : "checkmark.circle")
                        .foregroundStyle(isPresent ? Theme.watch : Theme.calm)
                    Text(isPresent ? "Present" : "Not present")
                        .font(.subheadline.weight(.semibold))
                        .foregroundStyle(Theme.ink)
                    Spacer()
                }
                Text("Derived from the sign of overjet (\(reading.formatted())), not measured separately.")
                    .font(.caption2)
                    .foregroundStyle(Theme.inkSoft)
            } else {
                notComputedBlock(.crossbiteAnterior)
            }

            warningLines(reading.warnings)
            inspectButton(.crossbiteAnterior,
                          context: "Derived from overjet, measured on the lateral views.")
        }
        .card(padding: 14)
    }

    // MARK: - Posterior crossbite

    private func posteriorRow(_ crossbite: CrossbitePosterior) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            rowHeader("Posterior crossbite",
                      symbol: DHCParameter.crossbitePosterior.symbol,
                      reliability: crossbite.reliability)

            if crossbite.isPresent {
                Text(crossbite.label ?? "Flagged")
                    .font(.caption).foregroundStyle(Theme.ink)
                ForEach(crossbite.flagged) { flag in
                    Text("\(flag.side) side, position \(flag.position) . ratio \(String(format: "%.2f", flag.ratio))")
                        .font(.caption2)
                        .foregroundStyle(Theme.inkSoft)
                }
            } else {
                Text("None flagged.").font(.caption).foregroundStyle(Theme.inkSoft)
            }

            inspectButton(.crossbitePosterior,
                          context: "Posterior crossbite is read from the frontal view.")
        }
        .card(padding: 14)
    }

    // MARK: - Missing, two sources side by side

    private func missingRow(_ missing: MissingReading) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 10) {
                Image(systemName: DHCParameter.missing.symbol)
                    .font(.subheadline)
                    .foregroundStyle(missing.reliability.tint)
                    .frame(width: 32, height: 32)
                    .background(Theme.accentDim, in: RoundedRectangle(cornerRadius: 9, style: .continuous))
                Text("Missing teeth").font(.subheadline.weight(.semibold)).foregroundStyle(Theme.ink)
                Spacer()
                badge(missing.reliability)
            }

            HStack(spacing: 16) {
                sourceCount("Occlusal", missing.occlusalGaps, primary: true)
                Divider().frame(height: 34)
                sourceCount("Frontal", missing.frontalGaps, primary: false)
                Spacer()
            }

            if missing.disagreement {
                HStack(spacing: 6) {
                    Image(systemName: "exclamationmark.triangle.fill")
                        .font(.caption2).foregroundStyle(Theme.watch)
                    Text("Sources disagree. Occlusal is more trusted, but the gap needs a manual check.")
                        .font(.caption).foregroundStyle(Theme.inkSoft)
                }
            }
            warningLines(missing.warnings)
            inspectButton(.missing, context: "Gaps found on the occlusal view.")
        }
        .card(padding: 14)
    }

    private func sourceCount(_ label: String, _ count: Int?, primary: Bool) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            HStack(spacing: 4) {
                Text(label).font(.caption2).foregroundStyle(Theme.inkSoft)
                if primary {
                    Text("primary")
                        .font(.system(size: 8, weight: .bold))
                        .foregroundStyle(.white)
                        .padding(.horizontal, 4).padding(.vertical, 1)
                        .background(Theme.accent, in: Capsule())
                }
            }
            Text(count.map { "\($0) gap\($0 == 1 ? "" : "s")" } ?? "—")
                .font(.system(.subheadline, design: .rounded).weight(.bold))
                .foregroundStyle(Theme.ink)
        }
    }

    // MARK: - Crowding, per arch

    private func crowdingRow(_ crowding: CrowdingReading) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Crowding").font(.subheadline.weight(.semibold)).foregroundStyle(Theme.ink)
            if let upper = crowding.upper { archBlock("Upper arch", upper, view: .maxillary) }
            if let lower = crowding.lower { archBlock("Lower arch", lower, view: .mandibular) }
            if crowding.upper == nil && crowding.lower == nil {
                Text("Not computed.").font(.caption).foregroundStyle(Theme.inkSoft)
            }
        }
        .card(padding: 14)
    }

    private func archBlock(_ label: String, _ arch: CrowdingArch, view: ToothView) -> some View {
        VStack(alignment: .leading, spacing: 5) {
            HStack {
                Text(label).font(.caption.weight(.semibold)).foregroundStyle(Theme.ink)
                Spacer()
                badge(arch.reliability)
            }
            HStack(spacing: 8) {
                Text(arch.sum.map { String(format: "%.2f", $0) } ?? "—")
                    .font(.system(.subheadline, design: .rounded).weight(.bold))
                    .monospacedDigit()
                    .foregroundStyle(arch.reliability.tint)
                if let l = arch.label {
                    Text(l).font(.caption).foregroundStyle(Theme.inkSoft)
                }
            }
            if !arch.flaggedTeeth.isEmpty {
                Text("Flagged teeth: \(arch.flaggedTeeth.map(String.init).joined(separator: ", "))")
                    .font(.caption2).foregroundStyle(Theme.inkSoft)
            }
            warningLines(arch.warnings)

            if let overlay = dhc?.overlays?[view.wireName], !overlay.isEmpty {
                Button {
                    inspecting = InspectTarget(
                        view: view,
                        overlay: overlay,
                        context: "Flagged teeth are highlighted. The yellow line is the fitted arch curve."
                    )
                } label: {
                    HStack(spacing: 6) {
                        Image(systemName: "viewfinder")
                        Text("Show flagged teeth")
                        Spacer()
                        Image(systemName: "chevron.right").font(.caption2)
                    }
                    .font(.caption.weight(.medium))
                    .foregroundStyle(Theme.accent)
                }
                .buttonStyle(.plain)
            }
        }
        .padding(10)
        .background(Theme.surface, in: RoundedRectangle(cornerRadius: 10, style: .continuous))
    }

    private var footnote: some View {
        Text("Thresholds are calibrated on a small sample and are not clinical standards. Crowding is measured on the anterior segment only.")
            .font(.footnote)
            .foregroundStyle(Theme.inkSoft)
    }
}
