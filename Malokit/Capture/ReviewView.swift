import SwiftUI

/// The gate before analysis. Every view gets a quality badge here, because a
/// blurred occlusal photo silently degrades crowding and crossbite detection
/// and nothing downstream will tell you that happened.
struct ReviewView: View {
    let caseID: UUID
    @Binding var path: [Route]

    @Environment(CaseStore.self) private var store
    @State private var readings: [ToothView: QualityReading] = [:]
    @State private var storageError: String?
    @State private var isRenaming = false

    private var record: CaseRecord? { store.record(caseID) }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                header

                ForEach(ToothView.captureOrder) { view in
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
            do { try store.rename(caseID, to: newName) }
            catch { storageError = error.localizedDescription }
        }
        .alert("Could not update this case", isPresented: .init(
            get: { storageError != nil },
            set: { if !$0 { storageError = nil } }
        )) {
            Button("OK", role: .cancel) {}
        } message: {
            Text(storageError ?? "Unknown storage error")
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
                do {
                    if image != nil { try store.clearImage(view, in: caseID) }
                    readings[view] = nil
                    path.append(.capture(caseID))
                } catch {
                    storageError = error.localizedDescription
                }
            }
            .font(.footnote.weight(.semibold))
            .buttonStyle(.bordered)
            .tint(Theme.accent)
        }
        .card(padding: 12)
    }

    private var runBar: some View {
        VStack(spacing: 8) {
            Button {
                startAnalysis()
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

    private func startAnalysis() {
        path.append(.analyzing(caseID))
    }

    private func measureAll() async {
        guard let record else { return }
        for view in ToothView.captureOrder {
            guard
                let filename = record.filename(for: view),
                let image = ImageStore.load(caseID: caseID, filename: filename),
                let reading = QualityChecker.evaluate(image: image)
            else { continue }
            readings[view] = reading
        }
    }
}
