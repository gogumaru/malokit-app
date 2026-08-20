import SwiftUI

/// Legal and attribution content for the models this app calls.
///
/// The wording here is fixed by license and attribution requirements — AGPL-3.0
/// copyleft on the DHC pipeline in particular — and must be reproduced exactly,
/// never paraphrased or shortened, when this screen changes.
struct AboutMalokitView: View {
    @Environment(\.dismiss) private var dismiss

    private struct AboutSection: Identifiable {
        let id = UUID()
        let title: String
        let body: String
    }

    private let sections: [AboutSection] = [
        AboutSection(
            title: "Dental Health Component (DHC) & Angle Classification",
            body: "Detects missing teeth, overjet, overbite, crossbite, displacement, and molar/canine relation by sending your photos to a research server. This component is built on YOLOv8 (Ultralytics), both the segmentation and detection variants, licensed under AGPL-3.0, an open-source copyleft license. Pretrained COCO weights were used as a starting point and fine-tuned on Malokit's own case data. Because AGPL-3.0 is copyleft, the fine-tuned weights and the server code running them remain subject to the same AGPL-3.0 terms. Source code for this component is available on request."
        ),
        AboutSection(
            title: "Aesthetic Component (AC), on-device",
            body: "Scores your frontal photo on a 1 to 10 aesthetic scale, running entirely on this device via Core ML. The photo never leaves your phone for this step. Built on ResNet-18 (He et al., 2015), starting from pretrained weights available under permissive open-source terms (BSD-3-Clause or Apache License 2.0), fine-tuned on Malokit's own labeled dataset."
        ),
        AboutSection(
            title: "3D Reconstruction",
            body: "Builds a 3D model of your dental arch from your photos and a short LiDAR scan, processed by a separate research server (Smartee). Tooth-edge segmentation in this pipeline uses RF-DETR (Apache License 2.0), trained on a COCO-format dataset for this task."
        )
    ]

    /// Read from the build, not typed in, so this can never drift out of sync
    /// with what actually shipped.
    private var versionString: String {
        let info = Bundle.main.infoDictionary
        let version = info?["CFBundleShortVersionString"] as? String ?? "—"
        let build = info?["CFBundleVersion"] as? String ?? "—"
        return "Version \(version) (\(build))"
    }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    header
                    ForEach(sections) { section in
                        sectionCard(section)
                    }
                }
                .padding(20)
            }
            .screenBackground()
            .navigationTitle("About")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Done") { dismiss() }
                }
            }
        }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("Malokit")
                .font(.system(size: 28, weight: .bold, design: .rounded))
                .foregroundStyle(Theme.ink)
            Text(versionString)
                .font(.caption)
                .foregroundStyle(Theme.inkSoft)
            Text(
                "Malokit captures five standardized intraoral photos and a brief LiDAR scan, then screens for dental health issues (DHC), aesthetic severity (AC), and reconstructs a 3D model of your dental arch. Every result is a screening aid, reviewed by a licensed dentist, not a final diagnosis."
            )
            .font(.subheadline)
            .foregroundStyle(Theme.ink)
            .padding(.top, 4)
        }
        .card(padding: 20)
    }

    private func sectionCard(_ section: AboutSection) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Eyebrow(text: section.title)
            Text(section.body)
                .font(.footnote)
                .foregroundStyle(Theme.inkSoft)
                .lineSpacing(3)
        }
        .card()
    }
}

#Preview {
    AboutMalokitView()
}
