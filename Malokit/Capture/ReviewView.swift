import SwiftUI

/// The gate before analysis. Every view gets a quality badge here, because a
/// blurred occlusal photo silently degrades crowding and crossbite detection
/// and nothing downstream will tell you that happened.
struct ReviewView: View {
    let caseID: UUID
    @Binding var path: [Route]

    @Environment(CaseStore.self) private var store
    @State private var readings: [ToothView: QualityReading] = [:]
    @State private var validations: [ToothView: ViewValidation] = [:]
    @State private var isRenaming = false

    /// `nil` when the model is missing from the bundle or fails to load —
    /// the view-match badge is simply omitted in that case, same fail-open
    /// spirit as `CaptureFlowView`.
    private let validator = try? ViewValidatorRegressor()

    private var record: CaseRecord? { store.record(caseID) }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                header

                ForEach(ToothView.allCases) { view in
                    row(for: view)
                }

                Text("Nothing is mirrored or flipped. Left and right decide Angle's classification, so the app keeps the frames exactly as shot.")
                    .font(.footnote)
                    .foregroundStyle(Theme.inkSoft)
                    .padding(.top, 4)
            }
            .padding(20)
        }
        .screenBackground()
        .navigationTitle("Review photos")
        .navigationBarTitleDisplayMode(.inline)
        .safeAreaInset(edge: .bottom) { runBar }
        .task { await measureAll() }
        .caseNamePrompt(
            isPresented: $isRenaming,
            currentName: record?.label ?? ""
        ) { newName in
            store.rename(caseID, to: newName)
        }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 4) {
            Button {
                isRenaming = true
            } label: {
                HStack(spacing: 5) {
                    Text(record?.label ?? "Case")
                        .font(.caption2.weight(.semibold))
                        .tracking(1.2)
                    Image(systemName: "pencil").font(.caption2)
                }
                .foregroundStyle(Theme.accent)
            }
            .buttonStyle(.plain)

            Text("\(record?.capturedViews.count ?? 0) of 5 captured")
                .font(.title2.weight(.semibold))
                .foregroundStyle(Theme.ink)
        }
    }

    private func row(for view: ToothView) -> some View {
        let filename = record?.filename(for: view)
        let image = filename.flatMap { ImageStore.load(caseID: caseID, filename: $0) }
        let reading = readings[view]
        let validation = validations[view]

        return HStack(spacing: 14) {
            Group {
                if let image {
                    Image(uiImage: image)
                        .resizable()
                        .scaledToFill()
                } else {
                    RoundedRectangle(cornerRadius: 12)
                        .fill(Theme.surface)
                        .overlay {
                            Image(systemName: view.symbol).foregroundStyle(Theme.inkSoft)
                        }
                }
            }
            .frame(width: 86, height: 66)
            .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))

            VStack(alignment: .leading, spacing: 3) {
                Text(view.title).font(.subheadline.weight(.semibold)).foregroundStyle(Theme.ink)

                if image == nil {
                    Text("Not captured").font(.caption).foregroundStyle(Theme.urgent)
                } else if let validation, !validation.isValid {
                    HStack(spacing: 5) {
                        Circle().fill(Theme.urgent).frame(width: 7, height: 7)
                        Text(mismatchSummary(validation))
                            .font(.caption)
                            .foregroundStyle(Theme.inkSoft)
                    }
                } else if let reading {
                    HStack(spacing: 5) {
                        Circle()
                            .fill(reading.isAcceptable ? Theme.calm : Theme.watch)
                            .frame(width: 7, height: 7)
                        Text(reading.isAcceptable ? "Usable" : reading.summary)
                            .font(.caption)
                            .foregroundStyle(Theme.inkSoft)
                    }
                } else {
                    Text("Checking").font(.caption).foregroundStyle(Theme.inkSoft)
                }

                Text(view.feeds).font(.caption2).foregroundStyle(Theme.inkSoft.opacity(0.8))
            }

            Spacer()

            Button(image == nil ? "Shoot" : "Retake") {
                if image != nil { store.clearImage(view, in: caseID) }
                readings[view] = nil
                validations[view] = nil
                path.append(.capture(caseID))
            }
            .font(.footnote.weight(.semibold))
            .buttonStyle(.bordered)
            .tint(Theme.accent)
        }
        .card(padding: 12)
    }

    /// Short badge text for a failed view-match, distinct from the sharpness/
    /// brightness wording `QualityReading.summary` already covers.
    private func mismatchSummary(_ validation: ViewValidation) -> String {
        guard let detected = validation.detectedView else {
            return "Not a valid intraoral photo"
        }
        return validation.matchesExpected ? "Unclear shot" : "Looks like \(detected.title)"
    }

    private var runBar: some View {
        VStack(spacing: 8) {
            Button {
                path.append(.analyzing(caseID))
            } label: {
                Text("Run analysis")
                    .font(.headline)
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 14)
            }
            .buttonStyle(.borderedProminent)
            .tint(Theme.accent)
            .disabled(!(record?.isComplete ?? false))

            if let missing = record?.missingViews, !missing.isEmpty {
                Text("Still needed: \(missing.map(\.title).joined(separator: ", "))")
                    .font(.caption)
                    .foregroundStyle(Theme.inkSoft)
            }
        }
        .padding(.horizontal, 20)
        .padding(.vertical, 12)
        .background(.ultraThinMaterial)
    }

    private func measureAll() async {
        guard let record else { return }
        for view in ToothView.allCases {
            guard
                let filename = record.filename(for: view),
                let image = ImageStore.load(caseID: caseID, filename: filename)
            else { continue }

            if let reading = QualityChecker.evaluate(image: image) {
                readings[view] = reading
            }
            if let validator, let validation = try? validator.validate(image: image, expected: view) {
                validations[view] = validation
            }
        }
    }
}
