import SwiftUI

/// Draws overlay geometry on top of a photo, with pinch zoom, pan, and tap to
/// select a shape.
///
/// The photo is laid out with aspect fit, so the drawing rectangle is computed
/// rather than assumed. Getting this wrong is the classic overlay bug: outlines
/// that sit a few percent off the teeth and quietly mislead.
struct OverlayCanvas: View {
    let image: UIImage
    let overlay: ViewOverlay
    /// Roles the viewer currently wants drawn.
    let visibleRoles: Set<OverlayShape.Role>
    @Binding var selected: OverlayShape?

    @State private var zoom: CGFloat = 1
    @State private var pinchZoom: CGFloat = 1
    @State private var offset: CGSize = .zero
    @State private var dragOffset: CGSize = .zero

    private var shapes: [OverlayShape] {
        overlay.shapes.filter { visibleRoles.contains($0.role) }
    }

    var body: some View {
        GeometryReader { geo in
            let rect = imageRect(in: geo.size)

            ZStack(alignment: .topLeading) {
                Image(uiImage: image)
                    .resizable()
                    .scaledToFit()
                    .frame(width: geo.size.width, height: geo.size.height)

                Canvas { context, _ in
                    for shape in shapes {
                        draw(shape, in: &context, rect: rect)
                    }
                }
                .allowsHitTesting(false)
            }
            .scaleEffect(zoom * pinchZoom)
            .offset(x: offset.width + dragOffset.width, y: offset.height + dragOffset.height)
            .contentShape(Rectangle())
            .gesture(
                SimultaneousGesture(
                    MagnificationGesture()
                        .onChanged { pinchZoom = $0 }
                        .onEnded { _ in
                            zoom = min(max(zoom * pinchZoom, 1), 6)
                            pinchZoom = 1
                            if zoom == 1 { withAnimation { offset = .zero } }
                        },
                    DragGesture()
                        .onChanged { if zoom > 1 { dragOffset = $0.translation } }
                        .onEnded { _ in
                            offset.width += dragOffset.width
                            offset.height += dragOffset.height
                            dragOffset = .zero
                        }
                )
            )
            .onTapGesture { location in
                selected = hitTest(location, rect: rect)
            }
            .clipped()
        }
    }

    // MARK: - Drawing

    private func draw(_ shape: OverlayShape, in context: inout GraphicsContext, rect: CGRect) {
        let points = shape.points.map { $0.resolved(in: rect) }
        guard !points.isEmpty else { return }

        let isSelected = shape.id == selected?.id
        let tint = shape.role.tint
        let width = shape.role.lineWidth / max(zoom * pinchZoom, 1) * (isSelected ? 2 : 1)

        var path = Path()
        switch shape.kind {
        case .polygon:
            path.addLines(points)
            path.closeSubpath()
        case .box:
            guard points.count >= 2 else { return }
            path.addRect(CGRect(
                x: min(points[0].x, points[1].x),
                y: min(points[0].y, points[1].y),
                width: abs(points[1].x - points[0].x),
                height: abs(points[1].y - points[0].y)
            ))
        case .line:
            path.addLines(points)
        case .point:
            path.addEllipse(in: CGRect(
                x: points[0].x - 3, y: points[0].y - 3, width: 6, height: 6
            ))
        }

        if isSelected {
            context.fill(path, with: .color(tint.opacity(0.28)))
        }
        context.stroke(path, with: .color(tint), lineWidth: width)

        if let label = shape.label {
            let centre = centroid(points)
            let text = Text(label)
                .font(.system(size: 11 / max(zoom * pinchZoom, 1), weight: .bold))
                .foregroundStyle(.white)
            let resolved = context.resolve(text)
            let size = resolved.measure(in: CGSize(width: 60, height: 30))
            let pad: CGFloat = 3 / max(zoom * pinchZoom, 1)
            let bg = CGRect(
                x: centre.x - size.width / 2 - pad,
                y: centre.y - size.height / 2 - pad,
                width: size.width + pad * 2,
                height: size.height + pad * 2
            )
            context.fill(Path(roundedRect: bg, cornerRadius: 3), with: .color(tint.opacity(0.9)))
            context.draw(resolved, at: centre, anchor: .center)
        }
    }

    // MARK: - Geometry

    /// Where the photo actually sits inside the view after aspect fit.
    private func imageRect(in size: CGSize) -> CGRect {
        let imageAspect = image.size.width / max(image.size.height, 1)
        let viewAspect = size.width / max(size.height, 1)

        if imageAspect > viewAspect {
            let height = size.width / imageAspect
            return CGRect(x: 0, y: (size.height - height) / 2, width: size.width, height: height)
        } else {
            let width = size.height * imageAspect
            return CGRect(x: (size.width - width) / 2, y: 0, width: width, height: size.height)
        }
    }

    private func centroid(_ points: [CGPoint]) -> CGPoint {
        guard !points.isEmpty else { return .zero }
        let sum = points.reduce(CGPoint.zero) { CGPoint(x: $0.x + $1.x, y: $0.y + $1.y) }
        return CGPoint(x: sum.x / CGFloat(points.count), y: sum.y / CGFloat(points.count))
    }

    /// Smallest matching shape wins, so a tooth inside a bounding box is
    /// selectable rather than swallowed by the larger shape behind it.
    private func hitTest(_ location: CGPoint, rect: CGRect) -> OverlayShape? {
        let candidates = shapes.filter { shape in
            let points = shape.points.map { $0.resolved(in: rect) }
            switch shape.kind {
            case .polygon: return contains(points, location)
            case .box:
                guard points.count >= 2 else { return false }
                return CGRect(
                    x: min(points[0].x, points[1].x),
                    y: min(points[0].y, points[1].y),
                    width: abs(points[1].x - points[0].x),
                    height: abs(points[1].y - points[0].y)
                ).contains(location)
            case .line, .point:
                return points.contains { hypot($0.x - location.x, $0.y - location.y) < 16 }
            }
        }
        return candidates.min { area($0, rect) < area($1, rect) }
    }

    private func area(_ shape: OverlayShape, _ rect: CGRect) -> CGFloat {
        let points = shape.points.map { $0.resolved(in: rect) }
        guard points.count > 2 else { return .greatestFiniteMagnitude }
        var total: CGFloat = 0
        for i in 0..<points.count {
            let a = points[i], b = points[(i + 1) % points.count]
            total += a.x * b.y - b.x * a.y
        }
        return abs(total) / 2
    }

    /// Ray casting point in polygon.
    private func contains(_ polygon: [CGPoint], _ point: CGPoint) -> Bool {
        guard polygon.count > 2 else { return false }
        var inside = false
        var j = polygon.count - 1
        for i in 0..<polygon.count {
            let a = polygon[i], b = polygon[j]
            if (a.y > point.y) != (b.y > point.y),
               point.x < (b.x - a.x) * (point.y - a.y) / (b.y - a.y) + a.x {
                inside.toggle()
            }
            j = i
        }
        return inside
    }
}
