import SwiftUI

/// Full screen annotation viewer, opened from a DHC parameter row.
///
/// Layers are switchable because a single picture with everything drawn at once
/// is unreadable on a phone, and because the useful question changes: checking a
/// crowding number means looking at flagged teeth and the arch curve, checking
/// an overjet means looking at the anchor boxes that produced it.
struct OverlaySheet: View {
    let caseID: UUID
    let view: ToothView
    let overlay: ViewOverlay
    /// What the reader came to check, shown above the photo.
    let context: String

    @Environment(\.dismiss) private var dismiss
    @State private var visibleRoles: Set<OverlayShape.Role> = []
    @State private var selected: OverlayShape?

    private var image: UIImage? { ImageStore.load(caseID: caseID, view: view) }

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                if let image {
                    OverlayCanvas(
                        image: image,
                        overlay: overlay,
                        visibleRoles: visibleRoles,
                        selected: $selected
                    )
                    .background(Color.black)
                } else {
                    ContentUnavailableView(
                        "Photo missing",
                        systemImage: "photo",
                        description: Text("The \(view.title) photo is no longer on this device.")
                    )
                }

                controls
            }
            .navigationTitle(view.title)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Done") { dismiss() }
                }
            }
        }
        .onAppear {
            // Everything on by default, so nothing is hidden without the reader
            // choosing to hide it.
            visibleRoles = Set(overlay.roles)
        }
    }

    private var controls: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(context)
                .font(.caption)
                .foregroundStyle(Theme.inkSoft)
                .frame(maxWidth: .infinity, alignment: .leading)

            if let selected {
                HStack(spacing: 8) {
                    Circle().fill(selected.role.tint).frame(width: 8, height: 8)
                    Text(selected.label.map { "\(selected.role.title) \($0)" } ?? selected.role.title)
                        .font(.footnote.weight(.semibold))
                        .foregroundStyle(Theme.ink)
                    Spacer()
                    Button("Clear") { self.selected = nil }
                        .font(.caption)
                }
                .padding(10)
                .background(Theme.surface, in: RoundedRectangle(cornerRadius: 10, style: .continuous))
            }

            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 8) {
                    ForEach(overlay.roles, id: \.self) { role in
                        layerChip(role)
                    }
                }
                .padding(.vertical, 2)
            }

            Text("Pinch to zoom, tap a shape to identify it. Outlines come from the model, not from a clinician.")
                .font(.caption2)
                .foregroundStyle(Theme.inkSoft)
        }
        .padding(16)
        .background(Theme.card)
    }

    private func layerChip(_ role: OverlayShape.Role) -> some View {
        let isOn = visibleRoles.contains(role)
        return Button {
            if isOn { visibleRoles.remove(role) } else { visibleRoles.insert(role) }
        } label: {
            HStack(spacing: 6) {
                Circle()
                    .fill(isOn ? role.tint : Color.clear)
                    .overlay(Circle().stroke(role.tint, lineWidth: 1.5))
                    .frame(width: 9, height: 9)
                Text(role.title)
                    .font(.caption.weight(.medium))
            }
            .foregroundStyle(isOn ? Theme.ink : Theme.inkSoft)
            .padding(.horizontal, 10)
            .padding(.vertical, 7)
            .background(
                Capsule().fill(isOn ? Theme.accentDim : Theme.surface)
            )
        }
        .buttonStyle(.plain)
    }
}
