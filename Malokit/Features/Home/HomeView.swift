import SwiftUI

struct HomeView: View {
    @Binding var path: [Route]
    @Environment(CaseStore.self) private var store

    var body: some View {
        Group {
            if store.cases.isEmpty {
                empty
            } else {
                list
            }
        }
        .screenBackground()
        .navigationTitle("Malokit")
        .toolbar {
            ToolbarItem(placement: .topBarLeading) {
                Button { path.append(.settings) } label: {
                    Image(systemName: "gearshape")
                }
            }
            ToolbarItem(placement: .topBarTrailing) {
                Button(action: startCase) {
                    Label("New analysis", systemImage: "plus")
                }
            }
        }
        .onAppear { store.pruneEmptyDrafts() }
    }

    private var empty: some View {
        VStack(spacing: 14) {
            Image(systemName: "camera.viewfinder")
                .font(.system(size: 44))
                .foregroundStyle(Theme.accent)
            Text("No cases yet")
                .font(.title3.weight(.semibold))
                .foregroundStyle(Theme.ink)
            Text("Shoot five intraoral views and Malokit scores both halves of the IOTN, then reconstructs the arches.")
                .font(.subheadline)
                .multilineTextAlignment(.center)
                .foregroundStyle(Theme.inkSoft)
                .padding(.horizontal, 40)
            Button("Start a case", action: startCase)
                .buttonStyle(.borderedProminent)
                .tint(Theme.accent)
                .padding(.top, 4)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    private var list: some View {
        ScrollView {
            LazyVStack(spacing: 12) {
                ForEach(store.sorted) { record in
                    Button { open(record) } label: { CaseRow(record: record) }
                        .buttonStyle(.plain)
                        .contextMenu {
                            Button("Delete", role: .destructive) { store.delete(record.id) }
                        }
                }
            }
            .padding(20)
        }
    }

    private func startCase() {
        let record = store.createCase()
        path.append(.capture(record.id))
    }

    private func open(_ record: CaseRecord) {
        switch record.status {
        case .complete: path.append(.result(record.id))
        case .ready:    path.append(.review(record.id))
        default:        path.append(record.isComplete ? .review(record.id) : .capture(record.id))
        }
    }
}

private struct CaseRow: View {
    let record: CaseRecord

    var body: some View {
        HStack(spacing: 14) {
            thumbnail

            VStack(alignment: .leading, spacing: 4) {
                Text(record.label)
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(Theme.ink)
                Text(record.createdAt.formatted(date: .abbreviated, time: .shortened))
                    .font(.caption)
                    .foregroundStyle(Theme.inkSoft)
                statusLine
            }

            Spacer()
            Image(systemName: "chevron.right")
                .font(.footnote.weight(.semibold))
                .foregroundStyle(Theme.hairline)
        }
        .card(padding: 12)
    }

    private var thumbnail: some View {
        Group {
            if let image = ImageStore.load(caseID: record.id, view: .front) {
                Image(uiImage: image).resizable().scaledToFill()
            } else {
                Rectangle().fill(Theme.surface).overlay {
                    Image(systemName: "mouth").foregroundStyle(Theme.inkSoft)
                }
            }
        }
        .frame(width: 58, height: 58)
        .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
    }

    @ViewBuilder
    private var statusLine: some View {
        if let result = record.result {
            HStack(spacing: 6) {
                Circle().fill(summaryTint(result.summary)).frame(width: 7, height: 7)
                Text(result.summary.rawValue)
                Text(". \(result.dhc.reliableCount)/6 reliable" + (result.ac.isScorable ? " . AC \(result.ac.score)" : ""))
                    .foregroundStyle(Theme.inkSoft)
            }
            .font(.caption.weight(.medium))
            .foregroundStyle(Theme.ink)
        } else {
            Text("\(record.capturedViews.count) of 5 photos")
                .font(.caption.weight(.medium))
                .foregroundStyle(Theme.accent)
        }
    }

    private func summaryTint(_ summary: AnalysisResult.CaseSummary) -> Color {
        switch summary {
        case .reviewNeeded:  Theme.watch
        case .partialResult: Theme.inkSoft
        case .findingsFound: Theme.ink
        case .clear:         Theme.calm
        }
    }
}
