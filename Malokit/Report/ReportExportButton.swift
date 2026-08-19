import SwiftUI

/// Self-contained export control: builds the PDF on tap and hands it to the
/// system share sheet.
///
/// Kept as its own view, rather than folded into ResultSummaryView, so wiring
/// it in anywhere is a single line — `ReportExportButton(caseID: caseID)` —
/// with no shared state to coordinate with whatever else that screen is
/// doing.
struct ReportExportButton: View {
    let caseID: UUID
    @Environment(CaseStore.self) private var store

    @State private var isGenerating = false
    @State private var reportFile: ReportFile?
    @State private var failed = false

    var body: some View {
        Button {
            generate()
        } label: {
            if isGenerating {
                ProgressView().controlSize(.small)
            } else {
                Image(systemName: "square.and.arrow.up")
            }
        }
        .disabled(isGenerating)
        .accessibilityLabel("Export report")
        .sheet(item: $reportFile) { file in
            ShareSheet(items: [file.url])
        }
        .alert("Could not build the report", isPresented: $failed) {
            Button("OK", role: .cancel) {}
        } message: {
            Text("Try again, or check that this case has a completed analysis.")
        }
    }

    private func generate() {
        guard let record = store.record(caseID) else { failed = true; return }
        isGenerating = true
        Task.detached(priority: .userInitiated) {
            // Scene loading is async and touches MainActor-isolated calls
            // (apply, setVisibility), so it runs to completion first. The PDF
            // itself is plain synchronous drawing and takes the finished
            // images as data, the same way it already takes the photos.
            let snapshots = await ReportBuilder.renderReconstructionSnapshots(
                caseID: caseID,
                reconstruction: record.result?.reconstruction
            )
            let url = ReportBuilder.generate(
                caseID: caseID,
                record: record,
                reconstructionSnapshots: snapshots
            )
            await MainActor.run {
                isGenerating = false
                if let url {
                    reportFile = ReportFile(url: url)
                } else {
                    failed = true
                }
            }
        }
    }
}

/// Wraps the generated file URL so it can drive `.sheet(item:)`, which
/// SwiftUI requires to be Identifiable.
private struct ReportFile: Identifiable {
    let url: URL
    var id: String { url.path }
}
