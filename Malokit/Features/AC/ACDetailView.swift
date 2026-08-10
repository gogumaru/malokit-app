import SwiftUI

struct ACDetailView: View {
    let caseID: UUID
    @Environment(CaseStore.self) private var store

    private var ac: ACResult? { store.record(caseID)?.result?.ac }

    var body: some View {
        ScrollView {
            if let ac {
                VStack(alignment: .leading, spacing: 16) {
                    scoreCard(ac)
                    frontPhoto
                    referenceStrip(ac)
                    note
                }
                .padding(20)
            } else {
                Text("No aesthetic component for this case.")
                    .foregroundStyle(Theme.inkSoft)
                    .padding(40)
            }
        }
        .screenBackground()
        .navigationTitle("IOTN AC")
        .navigationBarTitleDisplayMode(.inline)
    }

    private func scoreCard(_ ac: ACResult) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Eyebrow(text: "Aesthetic component")
            HStack(alignment: .lastTextBaseline, spacing: 6) {
                Text("\(ac.score)")
                    .font(.system(size: 46, weight: .bold, design: .rounded))
                    .foregroundStyle(Theme.severity(ac.band))
                Text("of 10")
                    .font(.headline)
                    .foregroundStyle(Theme.inkSoft)
            }

            SeverityRuler(
                value: Double(ac.score),
                range: 1...10,
                majorStep: 1,
                tint: Theme.severity(ac.band),
                valueLabel: "\(ac.score)",
                minorPerMajor: 1
            )

            HStack(spacing: 8) {
                Text(ac.band.rawValue)
                    .font(.footnote.weight(.semibold))
                    .foregroundStyle(.white)
                    .padding(.horizontal, 10).padding(.vertical, 5)
                    .background(Theme.severity(ac.band), in: Capsule())
                Text("\(Int(ac.confidence * 100))% confident")
                    .font(.caption)
                    .foregroundStyle(Theme.inkSoft)
            }
        }
        .card(padding: 20)
    }

    @ViewBuilder
    private var frontPhoto: some View {
        if let image = ImageStore.load(caseID: caseID, view: .front) {
            VStack(alignment: .leading, spacing: 8) {
                Eyebrow(text: "Scored from")
                Image(uiImage: image)
                    .resizable()
                    .scaledToFit()
                    .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
            }
            .card()
        }
    }

    private func referenceStrip(_ ac: ACResult) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Eyebrow(text: "Reference series")
            Text("The score is the closest match in the standard 10 photograph series, where 1 is the most attractive alignment.")
                .font(.caption)
                .foregroundStyle(Theme.inkSoft)

            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 8) {
                    ForEach(1...ACResult.referenceCount, id: \.self) { index in
                        referenceCell(index: index, matched: index == ac.nearestReference)
                    }
                }
                .padding(.vertical, 4)
            }
        }
        .card()
    }

    private func referenceCell(index: Int, matched: Bool) -> some View {
        VStack(spacing: 6) {
            RoundedRectangle(cornerRadius: 10, style: .continuous)
                .fill(matched ? Theme.accentDim : Theme.surface)
                .frame(width: 58, height: 46)
                .overlay {
                    // Reference photographs are licensed material and are not
                    // bundled. Drop them into Assets as ac-1 ... ac-10 and this
                    // placeholder resolves to the real image.
                    if let image = UIImage(named: "ac-\(index)") {
                        Image(uiImage: image).resizable().scaledToFill()
                    } else {
                        Image(systemName: "mouth")
                            .foregroundStyle(Theme.inkSoft.opacity(0.5))
                    }
                }
                .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
                .overlay {
                    RoundedRectangle(cornerRadius: 10, style: .continuous)
                        .stroke(matched ? Theme.accent : Theme.hairline, lineWidth: matched ? 2 : 1)
                }
            Text("\(index)")
                .font(.caption2.weight(matched ? .bold : .regular))
                .foregroundStyle(matched ? Theme.accent : Theme.inkSoft)
        }
    }

    private var note: some View {
        Text("The aesthetic component is scored on the front view alone. It is a perception scale, so it can disagree with the dental health component, and either one reaching definite need is enough to escalate the case.")
            .font(.footnote)
            .foregroundStyle(Theme.inkSoft)
    }
}
