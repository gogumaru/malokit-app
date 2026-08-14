import SwiftUI

/// One annotated view: the photo plus its shapes.
struct OverlayTarget: Identifiable, Hashable {
    let id = UUID()
    let view: ToothView
    let overlay: ViewOverlay
}

/// Full screen annotation viewer, opened from a DHC parameter row.
///
/// Layers are switchable because a single picture with everything drawn at once
/// is unreadable on a phone, and because the useful question changes: checking a
/// crowding number means looking at flagged teeth and the arch curve, checking
/// an overjet means looking at the anchor boxes that produced it.
struct OverlaySheet: View {
    let caseID: UUID
    /// One entry per annotated view. More than one gets a picker, because some
    /// parameters are genuinely read from several photos at once.
    let targets: [OverlayTarget]
    /// What the reader came to check, shown above the photo.
    let context: String
    /// Response key of the parameter being inspected, used to filter shapes.
    /// Nil means show everything, which is what the Angle card did before
    /// filtering existed.
    let parameter: String?

    @Environment(\.dismiss) private var dismiss
    @State private var visibleRoles: Set<OverlayShape.Role> = []
    @State private var selected: OverlayShape?
    @State private var index: Int = 0
    @State private var showEverything = false

    init(caseID: UUID, targets: [OverlayTarget], context: String, parameter: String? = nil) {
        self.caseID = caseID
        self.targets = targets
        self.context = context
        self.parameter = parameter
    }

    /// Single view convenience.
    init(caseID: UUID, view: ToothView, overlay: ViewOverlay, context: String, parameter: String? = nil) {
        self.init(
            caseID: caseID,
            targets: [OverlayTarget(view: view, overlay: overlay)],
            context: context,
            parameter: parameter
        )
    }

    /// The overlay actually drawn: filtered to the parameter unless the reader
    /// asked for everything.
    private var visibleOverlay: ViewOverlay {
        showEverything
            ? overlay
            : ViewOverlay(shapes: overlay.shapes(for: parameter))
    }

    private var canShowMore: Bool {
        overlay.hasFilterableContent(for: parameter)
    }

    private var current: OverlayTarget? {
        guard targets.indices.contains(index) else { return targets.first }
        return targets[index]
    }

    private var view: ToothView { current?.view ?? .front }
    private var overlay: ViewOverlay { current?.overlay ?? ViewOverlay(shapes: []) }

    private var image: UIImage? { ImageStore.load(caseID: caseID, view: view) }

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                if let image {
                    OverlayCanvas(
                        image: image,
                        overlay: visibleOverlay,
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
        .onChange(of: index) { _, _ in
            selected = nil
            visibleRoles = Set(visibleOverlay.roles.filter { !$0.isHiddenByDefault })
        }
        .onChange(of: showEverything) { _, _ in
            selected = nil
            visibleRoles = Set(visibleOverlay.roles.filter { !$0.isHiddenByDefault })
        }
        .onAppear {
            // Everything on by default except discarded masks, which are noise
            // on a good case and only wanted when a reader is asking why a
            // number went wrong.
            visibleRoles = Set(visibleOverlay.roles.filter { !$0.isHiddenByDefault })
        }
    }

    private var controls: some View {
        VStack(alignment: .leading, spacing: 10) {
            if targets.count > 1 {
                Picker("View", selection: $index) {
                    ForEach(Array(targets.enumerated()), id: \.offset) { offset, target in
                        Text(target.view.title).tag(offset)
                    }
                }
                .pickerStyle(.segmented)
            }

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
                    ForEach(visibleOverlay.roles, id: \.self) { role in
                        layerChip(role)
                    }
                }
                .padding(.vertical, 2)
            }

            // Nothing highlighted is a result, not a malfunction. Say so.
            if parameter != nil, !showEverything, !visibleOverlay.hasParameterShapes(for: parameter) {
                HStack(alignment: .top, spacing: 6) {
                    Image(systemName: "checkmark.circle")
                    Text("Nothing was flagged for this parameter. The outlines show what the model segmented.")
                }
                .font(.caption)
                .foregroundStyle(Theme.calm)
            }

            // Filtering has to be visible. A screen that quietly shows a subset
            // invites the reader to assume that is everything there is.
            if canShowMore {
                Toggle(isOn: $showEverything) {
                    Text(showEverything
                         ? "Showing every annotation"
                         : "Showing only what this parameter uses")
                        .font(.caption)
                        .foregroundStyle(Theme.inkSoft)
                }
                .toggleStyle(.switch)
                .tint(Theme.accent)
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
