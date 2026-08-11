import SwiftUI

struct ACDetailView: View {
    let caseID: UUID
    @Environment(CaseStore.self) private var store

    private var ac: ACResult? { store.record(caseID)?.result?.ac }

    var body: some View {
        ScrollView {
            if let ac {
                VStack(alignment: .leading, spacing: 16) {
                    if ac.isScorable {
                        scoreCard(ac)
                        frontPhoto
                        //referenceStrip(ac)
                        note
                    } else {
                        rejectionCard(ac)
                        frontPhoto
                    }
                }
                .padding(20)
            } else {
                Text("This case has no results yet.")
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

            Text(severityDescription(ac.score))
                .font(.footnote)
                .foregroundStyle(Theme.inkSoft)
        }
        .card(padding: 20)
    }

    /// Plain-language read of the grade, next to the numeric score and band
    /// so the clinician doesn't have to memorise what each number means.
    private func severityDescription(_ grade: Int) -> String {
        switch grade {
        case 1:  "Excellent alignment, no treatment needed."
        case 2:  "Near ideal, no treatment needed."
        case 3:  "Minor deviation, slight treatment need."
        case 4:  "Mild malocclusion, minor treatment need."
        case 5:  "Moderate malocclusion, moderate treatment need."
        case 6:  "Noticeable malocclusion, treatment advisable."
        case 7:  "Obvious malocclusion, treatment recommended."
        case 8:  "Severely affected dental appearance, treatment highly recommended."
        case 9:  "Severe malocclusion, treatment strongly needed."
        case 10: "Worst case, treatment urgently needed."
        default: ""
        }
    }

    /// Shown instead of the score card when the model rejects the photo as
    /// out of distribution, for example a non-intraoral or unusable frame.
    private func rejectionCard(_ ac: ACResult) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Eyebrow(text: "Aesthetic component")
            HStack(spacing: 8) {
                Image(systemName: "exclamationmark.triangle.fill")
                    .foregroundStyle(Theme.watch)
                Text("Photo not scored")
                    .font(.headline)
                    .foregroundStyle(Theme.ink)
            }
            Text(ac.rejectionReason ?? "Photo is out of the model's scope.")
                .font(.subheadline)
                .foregroundStyle(Theme.inkSoft)
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

//    private func referenceStrip(_ ac: ACResult) -> some View {
//        VStack(alignment: .leading, spacing: 10) {
//            Eyebrow(text: "Reference series")
//            Text("The score is the closest match in the standard 10 photograph series, where 1 is the most attractive alignment.")
//                .font(.caption)
//                .foregroundStyle(Theme.inkSoft)
//
//            ScrollView(.horizontal, showsIndicators: false) {
//                HStack(spacing: 8) {
//                    ForEach(1...ACResult.referenceCount, id: \.self) { index in
//                        referenceCell(index: index, matched: index == ac.nearestReference)
//                    }
//                }
//                .padding(.vertical, 4)
//            }
//        }
//        .card()
//    }

//    private func referenceCell(index: Int, matched: Bool) -> some View {
//        VStack(spacing: 6) {
//            RoundedRectangle(cornerRadius: 10, style: .continuous)
//                .fill(matched ? Theme.accentDim : Theme.surface)
//                .frame(width: 58, height: 46)
//                .overlay {
//                    // Reference photographs are licensed material and are not
//                    // bundled. Drop them into Assets as ac-1 ... ac-10 and this
//                    // placeholder resolves to the real image.
//                    if let image = UIImage(named: "ac-\(index)") {
//                        Image(uiImage: image).resizable().scaledToFill()
//                    } else {
//                        Image(systemName: "mouth")
//                            .foregroundStyle(Theme.inkSoft.opacity(0.5))
//                    }
//                }
//                .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
//                .overlay {
//                    RoundedRectangle(cornerRadius: 10, style: .continuous)
//                        .stroke(matched ? Theme.accent : Theme.hairline, lineWidth: matched ? 2 : 1)
//                }
//            Text("\(index)")
//                .font(.caption2.weight(matched ? .bold : .regular))
//                .foregroundStyle(matched ? Theme.accent : Theme.inkSoft)
//        }
//    }

    private var note: some View {
        Text("The aesthetic component is scored on the front view alone. It is a perception scale, so it can disagree with the dental health component, and either one reaching definite need is enough to escalate the case.")
            .font(.footnote)
            .foregroundStyle(Theme.inkSoft)
    }
}
