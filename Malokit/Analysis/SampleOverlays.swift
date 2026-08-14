import Foundation

/// Plausible annotation geometry for the mock, so the overlay UI can be built
/// and reviewed before the server implements it.
///
/// Shapes are generated rather than typed out one point at a time, which keeps
/// this readable and makes it obvious the numbers are synthetic. Replace the
/// whole file once real overlays arrive; nothing else depends on it.
enum SampleOverlays {

    static func make() -> OverlaySet {
        [
            ToothView.right.wireName: lateral(),
            ToothView.left.wireName: lateral(mirrored: true),
            ToothView.front.wireName: frontal(),
            ToothView.maxillary.wireName: occlusal(flagged: [3, 4]),
            ToothView.mandibular.wireName: occlusal(flagged: [5, 6])
        ]
    }

    // MARK: - Lateral: a row of teeth, canine anchors, an overjet line

    private static func lateral(mirrored: Bool = false) -> ViewOverlay {
        var shapes: [OverlayShape] = []

        for index in 0..<8 {
            let t = Double(index) / 7
            let x = 0.12 + t * 0.72
            let width = 0.055 + (1 - abs(t - 0.5) * 2) * 0.018
            let height = 0.20 - abs(t - 0.5) * 0.05
            let cy = 0.50 + sin(t * .pi) * 0.03

            shapes.append(OverlayShape(
                kind: .polygon,
                role: .tooth,
                points: toothPolygon(cx: mirrored ? 1 - x : x, cy: cy, w: width, h: height)
            ))
        }

        // Canine anchors, the detections overjet is measured between.
        let anchorX = mirrored ? 0.72 : 0.28
        shapes.append(OverlayShape(
            kind: .box, role: .anchor,
            points: [NormalizedPoint(anchorX - 0.045, 0.38), NormalizedPoint(anchorX + 0.045, 0.62)],
            label: "canine",
            params: ["angle"]
        ))
        shapes.append(OverlayShape(
            kind: .box, role: .anchor,
            points: [NormalizedPoint(anchorX + 0.05, 0.40), NormalizedPoint(anchorX + 0.13, 0.60)],
            label: "distal",
            params: ["angle"]
        ))
        // The incisor is the denominator behind overjet and overbite. Without
        // it on screen there is no way to see that the wrong tooth was used.
        shapes.append(OverlayShape(
            kind: .box, role: .reference,
            points: [NormalizedPoint(anchorX + 0.14, 0.39), NormalizedPoint(anchorX + 0.21, 0.61)],
            label: "incisor",
            params: ["overjet", "overbite", "anterior_crossbite"]
        ))

        // The measured horizontal distance.
        shapes.append(OverlayShape(
            kind: .line, role: .measurement,
            points: [NormalizedPoint(anchorX, 0.47), NormalizedPoint(anchorX + 0.085, 0.47)],
            label: "0.62",
            params: ["overjet", "overbite", "anterior_crossbite"]
        ))

        return ViewOverlay(shapes: shapes)
    }

    // MARK: - Frontal: teeth, a suspected gap, a crossbite marker

    private static func frontal() -> ViewOverlay {
        var shapes: [OverlayShape] = []

        for index in 0..<10 {
            let t = Double(index) / 9
            let x = 0.16 + t * 0.68
            let height = 0.20 - abs(t - 0.5) * 0.06
            shapes.append(OverlayShape(
                kind: .polygon, role: .tooth,
                points: toothPolygon(cx: x, cy: 0.50, w: 0.055, h: height)
            ))
        }

        shapes.append(OverlayShape(
            kind: .line, role: .gap,
            points: [NormalizedPoint(0.30, 0.40), NormalizedPoint(0.30, 0.60)],
            label: "gap",
            params: ["missing"]
        ))
        shapes.append(OverlayShape(
            kind: .box, role: .flagged,
            points: [NormalizedPoint(0.72, 0.42), NormalizedPoint(0.80, 0.58)],
            label: "crossbite",
            params: ["crossbite_posterior"]
        ))

        return ViewOverlay(shapes: shapes)
    }

    // MARK: - Occlusal: an arch of teeth, the fitted curve, flagged positions

    private static func occlusal(flagged: [Int]) -> ViewOverlay {
        var shapes: [OverlayShape] = []
        var curve: [NormalizedPoint] = []

        let count = 12
        for index in 0..<count {
            let t = Double(index) / Double(count - 1)
            let angle = Double.pi * t
            let cx = 0.5 - cos(angle) * 0.33
            // Y grows downward in image coordinates, so the apex of the arch is
            // subtracted, not added. Adding it flips the arch upside down,
            // which is anatomically backwards for both upper and lower views.
            let cy = 0.78 - sin(angle) * 0.42

            curve.append(NormalizedPoint(cx, cy))

            let position = index + 1
            let isFlagged = flagged.contains(position)
            shapes.append(OverlayShape(
                kind: .polygon,
                role: isFlagged ? .flagged : .tooth,
                points: toothPolygon(cx: cx, cy: cy, w: 0.075, h: 0.085),
                label: isFlagged ? "\(position)" : nil,
                params: isFlagged ? ["crowding"] : []
            ))
        }

        shapes.insert(OverlayShape(
            kind: .line, role: .archCurve, points: curve
        ), at: 0)

        // A discarded sliver near the frame edge, hidden by default. This is
        // the shape that explains an implausible measurement when one appears.
        shapes.append(OverlayShape(
            kind: .polygon, role: .rejected,
            points: toothPolygon(cx: 0.08, cy: 0.20, w: 0.05, h: 0.04),
            label: nil
        ))

        return ViewOverlay(shapes: shapes)
    }

    // MARK: - Helpers

    /// A rounded, slightly irregular hexagon, close enough to a segmented tooth
    /// to judge the UI without pretending to be real model output.
    private static func toothPolygon(cx: Double, cy: Double, w: Double, h: Double) -> [NormalizedPoint] {
        let hw = w / 2, hh = h / 2
        return [
            NormalizedPoint(cx - hw * 0.75, cy - hh),
            NormalizedPoint(cx + hw * 0.75, cy - hh),
            NormalizedPoint(cx + hw, cy - hh * 0.25),
            NormalizedPoint(cx + hw * 0.8, cy + hh),
            NormalizedPoint(cx - hw * 0.8, cy + hh),
            NormalizedPoint(cx - hw, cy - hh * 0.25)
        ]
    }
}
