import SwiftUI

struct AnalyzingView: View {
    let caseID: UUID
    @Binding var path: [Route]

    @Environment(CaseStore.self) private var store
    @State private var pipeline = AnalysisPipeline()

    var body: some View {
        VStack(alignment: .leading, spacing: 20) {
            VStack(alignment: .leading, spacing: 4) {
                Eyebrow(text: "Engine \(pipeline.engineName)")
                Text(headline)
                    .font(.title2.weight(.semibold))
                    .foregroundStyle(Theme.ink)
            }

            VStack(spacing: 0) {
                ForEach(Array(AnalysisStage.allCases.enumerated()), id: \.element.id) { index, stage in
                    stageRow(stage)
                    if index < AnalysisStage.allCases.count - 1 {
                        Divider().padding(.leading, 42)
                    }
                }
            }
            .card(padding: 0)

            if case .failed(let message) = pipeline.state {
                VStack(alignment: .leading, spacing: 10) {
                    Text(message).font(.footnote).foregroundStyle(Theme.urgent)
                    Button("Try again") {
                        Task { await pipeline.run(caseID: caseID, store: store) }
                    }
                    .buttonStyle(.bordered)
                    .tint(Theme.accent)
                }
                .card()
            }

            Spacer()
        }
        .padding(20)
        .screenBackground()
        .navigationTitle("Analysing")
        .navigationBarTitleDisplayMode(.inline)
        .navigationBarBackButtonHidden(pipeline.state != .idle && !isFailed)
        .task { await pipeline.run(caseID: caseID, store: store) }
        .onChange(of: pipeline.state) { _, state in
            if state == .finished {
                path = [.result(caseID)]
            }
        }
    }

    private var isFailed: Bool {
        if case .failed = pipeline.state { return true }
        return false
    }

    private var headline: String {
        switch pipeline.state {
        case .failed: "Analysis stopped"
        case .finished: "Done"
        default: "Reading five views"
        }
    }

    private func stageRow(_ stage: AnalysisStage) -> some View {
        let isDone = pipeline.completedStages.contains(stage)
        let isActive = pipeline.state == .running(stage)

        return HStack(spacing: 12) {
            ZStack {
                if isDone {
                    Image(systemName: "checkmark.circle.fill")
                        .foregroundStyle(Theme.accent)
                } else if isActive {
                    ProgressView().controlSize(.small)
                } else {
                    Circle().stroke(Theme.hairline, lineWidth: 1.5).frame(width: 16, height: 16)
                }
            }
            .frame(width: 22)

            VStack(alignment: .leading, spacing: 2) {
                Text(stage.title)
                    .font(.subheadline.weight(isActive ? .semibold : .regular))
                    .foregroundStyle(isDone || isActive ? Theme.ink : Theme.inkSoft)
                Text(stage.detail)
                    .font(.caption2)
                    .foregroundStyle(Theme.inkSoft)
            }
            Spacer()
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 12)
    }
}
