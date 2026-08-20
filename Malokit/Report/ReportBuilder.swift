import SceneKit
import SwiftUI
import UIKit

/// Builds a one-file PDF summary of a case: Angle, DHC, AC, and 3D status,
/// in that order because that is the order the result screen presents them.
///
/// Written directly against UIGraphicsPDFRenderer rather than a templating
/// library, because the layout is a handful of labelled sections and does not
/// need one.
///
/// AC is always present in `AnalysisResult` (per the current model), so the
/// report never has to say "AC missing" — only "not scored", using the same
/// `isScorable` / `rejectionReason` the result screen already reads. 3D goes
/// through `ReconstructionAvailability.resolve(_:)` directly rather than
/// re-deriving its branches, so the report can never disagree with what the
/// result screen shows for the same case.
///
/// DHC and Angle parameters that have overlay geometry get a small annotated
/// thumbnail alongside their reading, drawn with the same shape geometry,
/// colours, and dash pattern as `OverlayCanvas`, so a printed page shows the
/// same evidence the interactive viewer does. AC has no such geometry — the
/// on-device model outputs one score for the whole photo, not per-tooth
/// detections — so its section includes the scored photo plain, unannotated.
enum ReportBuilder {

    private static let pageSize = CGSize(width: 595.2, height: 841.8) // A4 @ 72dpi
    private static let margin: CGFloat = 42

    static func generate(
        caseID: UUID,
        record: CaseRecord,
        reconstructionSnapshots: ReconstructionSnapshots = ReconstructionSnapshots()
    ) -> URL? {
        guard let result = record.result else { return nil }

        let format = UIGraphicsPDFRendererFormat()
        format.documentInfo = [
            kCGPDFContextCreator as String: "Malokit",
            kCGPDFContextTitle as String: record.label
        ]
        let renderer = UIGraphicsPDFRenderer(
            bounds: CGRect(origin: .zero, size: pageSize),
            format: format
        )

        let safeName = record.label
            .components(separatedBy: CharacterSet.alphanumerics.inverted)
            .filter { !$0.isEmpty }
            .joined(separator: "_")
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("\(safeName.isEmpty ? "case" : safeName)_report.pdf")

        do {
            try renderer.writePDF(to: url) { context in
                let page = ReportPage(context: context, size: pageSize, margin: margin)
                page.begin()

                drawHeader(page, record: record, result: result)
                drawDisclaimer(page)
                drawPhotos(page, caseID: caseID, record: record)
                drawAngle(page, caseID: caseID, angle: result.angle, dhc: result.dhc)
                drawDHC(page, caseID: caseID, dhc: result.dhc)
                drawAC(page, caseID: caseID, ac: result.ac)
                draw3D(page, result: result, snapshots: reconstructionSnapshots)
                drawNarrative(page, result: result)
                drawFooter(page, result: result)
            }
            return url
        } catch {
            return nil
        }
    }

    // MARK: - Sections

    private static func drawHeader(_ page: ReportPage, record: CaseRecord, result: AnalysisResult) {
        page.text("Malokit — Case Report", font: F.h1, spacingAfter: 2)
        page.text(record.label, font: F.h2, color: .inkSoft, spacingAfter: 2)
        let dateText = record.createdAt.formatted(date: .abbreviated, time: .shortened)
        page.text("Captured \(dateText) · \(result.summary.rawValue)", font: F.small, color: .inkSoft, spacingAfter: 10)
    }

    private static func drawDisclaimer(_ page: ReportPage) {
        page.text(
            "Research aid, not a diagnosis. Values are calibrated on a small sample and do not " +
            "produce a combined IOTN grade. Confirm every finding against the photographs.",
            font: F.small,
            color: .inkSoft,
            spacingAfter: 12
        )
        page.rule()
    }

    private static func drawPhotos(_ page: ReportPage, caseID: UUID, record: CaseRecord) {
        let views = record.capturedViews
        guard !views.isEmpty else { return }

        page.text("Captured views", font: F.h2, spacingAfter: 6)

        let thumbSize: CGFloat = 78
        let gap: CGFloat = 10
        let perRow = max(1, Int((page.contentWidth + gap) / (thumbSize + gap)))
        let rows = Int(ceil(Double(views.count) / Double(perRow)))
        let rowHeight = thumbSize + 14 // image + label

        page.ensure(CGFloat(rows) * (rowHeight + gap))
        let rowsTop = page.y

        for (index, view) in views.enumerated() {
            let row = index / perRow
            let col = index % perRow
            let x = page.margin + CGFloat(col) * (thumbSize + gap)
            let y = rowsTop + CGFloat(row) * (rowHeight + gap)
            let rect = CGRect(x: x, y: y, width: thumbSize, height: thumbSize)

            if let image = ImageStore.load(caseID: caseID, view: view) {
                _ = drawAspectFit(image, in: rect)
                let border = UIBezierPath(rect: rect)
                UIColor.hairline.setStroke()
                border.lineWidth = 0.5
                border.stroke()
            }

            (view.title as NSString).draw(
                at: CGPoint(x: x, y: y + thumbSize + 2),
                withAttributes: [.font: F.small, .foregroundColor: UIColor.inkSoft]
            )
        }

        page.y = rowsTop + CGFloat(rows) * (rowHeight + gap)
        page.rule()
    }

    private static func drawAngle(_ page: ReportPage, caseID: UUID, angle: AngleReading, dhc: DHCResult) {
        let sideSuffix = angle.side.map { " — \($0) side" } ?? ""
        page.text("Angle classification\(sideSuffix)", font: F.h2, spacingAfter: 6)
        drawReadingLine(page, label: "Molar", reading: angle.molar)
        drawReadingLine(page, label: "Canine", reading: angle.canine)
        if angle.disagreement {
            page.text(
                "Molar and canine disagree. Manual review advised.",
                font: F.small, color: .watch, spacingAfter: 8
            )
        }

        if let overlays = dhc.overlays {
            let preferredViews: [ToothView] = angle.side?.lowercased().contains("left") == true
                ? [.left, .right] : [.right, .left]
            let target = preferredViews.compactMap { view -> (ToothView, ViewOverlay)? in
                guard let overlay = overlays[view.wireName], !overlay.isEmpty else { return nil }
                return (view, overlay)
            }.first
            if let target {
                drawParameterThumbnails(page, caseID: caseID, targets: [target], paramKey: "angle")
            }
        }

        page.rule()
    }

    private static func drawReadingLine(_ page: ReportPage, label: String, reading: Reading) {
        let valueText = reading.hasValue ? (reading.label ?? reading.formatted()) : "Not computed"
        page.text("\(label): \(valueText)", font: F.body, color: tint(for: reading.reliability), spacingAfter: 3)
        for warning in reading.warnings {
            page.text("· \(warning)", font: F.small, color: .inkSoft, x: 12, spacingAfter: 2)
        }
    }

    private static func drawDHC(_ page: ReportPage, caseID: UUID, dhc: DHCResult) {
        page.text("DHC parameters — \(dhc.reliableCount) of 6 reliable", font: F.h2, spacingAfter: 6)

        drawReadingRow(page, title: "Overjet", reading: dhc.overjet)
        drawParameterThumbnails(
            page, caseID: caseID,
            targets: dhc.overlayTargets(for: .overjet),
            paramKey: DHCParameter.overjet.responseKey
        )

        drawReadingRow(page, title: "Overbite", reading: dhc.overbite)
        drawParameterThumbnails(
            page, caseID: caseID,
            targets: dhc.overlayTargets(for: .overbite),
            paramKey: DHCParameter.overbite.responseKey
        )

        drawAnteriorCrossbiteRow(page, reading: dhc.anteriorCrossbite)
        drawParameterThumbnails(
            page, caseID: caseID,
            targets: dhc.overlayTargets(for: .crossbiteAnterior),
            paramKey: DHCParameter.crossbiteAnterior.responseKey
        )

        drawPosteriorCrossbiteRow(page, crossbite: dhc.posteriorCrossbite)
        if dhc.posteriorCrossbite.isPresent {
            drawParameterThumbnails(
                page, caseID: caseID,
                targets: dhc.overlayTargets(for: .crossbitePosterior),
                paramKey: DHCParameter.crossbitePosterior.responseKey
            )
        }

        drawMissingRow(page, missing: dhc.missing)
        drawParameterThumbnails(
            page, caseID: caseID,
            targets: dhc.overlayTargets(for: .missing),
            paramKey: DHCParameter.missing.responseKey
        )

        drawCrowdingRow(page, crowding: dhc.crowding)
        drawParameterThumbnails(
            page, caseID: caseID,
            targets: dhc.overlayTargets(for: .crowding),
            paramKey: DHCParameter.crowding.responseKey
        )

        page.rule()
    }

    private static func drawReadingRow(_ page: ReportPage, title: String, reading: Reading) {
        let valueText = reading.hasValue
            ? reading.formatted() + (reading.label.map { " — \($0)" } ?? "")
            : "Not computed"
        page.text("\(title): \(valueText)", font: F.bodyBold, color: tint(for: reading.reliability), spacingAfter: 2)
        if let side = reading.side {
            page.text("Source: \(side) side", font: F.small, color: .inkSoft, x: 12, spacingAfter: 2)
        }
        for warning in reading.warnings {
            page.text("· \(warning)", font: F.small, color: .inkSoft, x: 12, spacingAfter: 2)
        }
        page.space(2)
    }

    private static func drawAnteriorCrossbiteRow(_ page: ReportPage, reading: Reading) {
        guard reading.hasValue else {
            page.text("Anterior crossbite: Not computed", font: F.bodyBold, color: .inkSoft, spacingAfter: 6)
            return
        }
        let present = (reading.value ?? 0) < 0
        page.text(
            "Anterior crossbite: \(present ? "Present" : "Not present")",
            font: F.bodyBold, color: tint(for: reading.reliability), spacingAfter: 2
        )
        if let side = reading.side {
            page.text("Source: \(side) side", font: F.small, color: .inkSoft, x: 12, spacingAfter: 6)
        } else {
            page.space(4)
        }
    }

    private static func drawPosteriorCrossbiteRow(_ page: ReportPage, crossbite: CrossbitePosterior) {
        guard crossbite.isPresent else {
            page.text("Posterior crossbite: None flagged", font: F.bodyBold, color: .inkSoft, spacingAfter: 6)
            return
        }
        page.text(
            "Posterior crossbite: \(crossbite.label ?? "Flagged")",
            font: F.bodyBold, color: tint(for: crossbite.reliability), spacingAfter: 2
        )
        for flag in crossbite.flagged {
            page.text("· \(flag.side) side, position \(flag.position)", font: F.small, color: .inkSoft, x: 12, spacingAfter: 2)
        }
        page.space(4)
    }

    private static func drawMissingRow(_ page: ReportPage, missing: MissingReading) {
        let occlusal = missing.occlusalGaps.map(String.init) ?? "—"
        let frontal = missing.frontalGaps.map(String.init) ?? "—"
        let disagreementNote = missing.disagreement ? " (sources disagree)" : ""
        page.text(
            "Missing teeth: occlusal \(occlusal), frontal \(frontal)\(disagreementNote)",
            font: F.bodyBold, color: tint(for: missing.reliability), spacingAfter: 2
        )
        for warning in missing.warnings {
            page.text("· \(warning)", font: F.small, color: .inkSoft, x: 12, spacingAfter: 2)
        }
        page.space(4)
    }

    private static func drawCrowdingRow(_ page: ReportPage, crowding: CrowdingReading) {
        if let upper = crowding.upper {
            let sum = upper.sum.map { String(format: "%.2f", $0) } ?? "—"
            page.text(
                "Crowding, upper arch: \(sum)" + (upper.label.map { " — \($0)" } ?? ""),
                font: F.body, color: tint(for: upper.reliability), spacingAfter: 2
            )
            if !upper.flaggedTeeth.isEmpty {
                page.text(
                    "· Flagged teeth: \(upper.flaggedTeeth.map(String.init).joined(separator: ", "))",
                    font: F.small, color: .inkSoft, x: 12, spacingAfter: 2
                )
            }
        }
        if let lower = crowding.lower {
            let sum = lower.sum.map { String(format: "%.2f", $0) } ?? "—"
            page.text(
                "Crowding, lower arch: \(sum)" + (lower.label.map { " — \($0)" } ?? ""),
                font: F.body, color: tint(for: lower.reliability), spacingAfter: 2
            )
            if !lower.flaggedTeeth.isEmpty {
                page.text(
                    "· Flagged teeth: \(lower.flaggedTeeth.map(String.init).joined(separator: ", "))",
                    font: F.small, color: .inkSoft, x: 12, spacingAfter: 6
                )
            }
        }
    }

    private static func drawAC(_ page: ReportPage, caseID: UUID, ac: ACResult) {
        page.text("IOTN AC", font: F.h2, spacingAfter: 6)
        if ac.isScorable {
            page.text(
                "Score: \(ac.score) of 10 — \(ac.band.rawValue)",
                font: F.bodyBold, color: tint(for: ac.band), spacingAfter: 2
            )
            page.text("Confidence \(Int(ac.confidence * 100))%", font: F.small, color: .inkSoft, spacingAfter: 8)
        } else {
            page.text(
                "Not scored: \(ac.rejectionReason ?? "not available for this case")",
                font: F.body, color: .watch, spacingAfter: 10
            )
        }

        if let frontImage = ImageStore.load(caseID: caseID, view: .front) {
            let size: CGFloat = 130
            page.ensure(size + 16)
            let rect = CGRect(x: page.margin, y: page.y, width: size, height: size)
            _ = drawAspectFit(frontImage, in: rect)
            let border = UIBezierPath(rect: rect)
            UIColor.hairline.setStroke()
            border.lineWidth = 0.5
            border.stroke()
            ("Scored from this photo" as NSString).draw(
                at: CGPoint(x: page.margin, y: page.y + size + 2),
                withAttributes: [.font: F.small, .foregroundColor: UIColor.inkSoft]
            )
            page.y += size + 16
        }

        page.rule()
    }

    private static func draw3D(_ page: ReportPage, result: AnalysisResult, snapshots: ReconstructionSnapshots) {
        page.text("3D reconstruction", font: F.h2, spacingAfter: 6)

        switch ReconstructionAvailability.resolve(result.reconstruction) {
        case .ready:
            page.text(
                "A reconstructed mesh is attached to this case. The views below are a fixed " +
                "camera angle; open the app to rotate, zoom, and measure it interactively.",
                font: F.body, color: .inkSoft, spacingAfter: 8
            )
            drawReconstructionSnapshots(page, snapshots: snapshots)
        case .processing(let progress):
            page.text(
                "Still being built: \(progress.label) — step \(progress.completedSteps + 1) of " +
                "\(progress.totalSteps) (\(progress.percentComplete)%). Reopen this case later to check on it.",
                font: F.body, color: .watch, spacingAfter: 10
            )
        case .needsReconstruction:
            page.text(
                "Not built yet for this case. Open the app and tap 3D view to start reconstruction.",
                font: F.body, color: .inkSoft, spacingAfter: 10
            )
        case .failed(let message):
            page.text(
                "Reconstruction failed: \(message). The saved DHC and AC results are unaffected.",
                font: F.body, color: .urgent, spacingAfter: 10
            )
        }
        page.rule()
    }

    /// Three thumbnails from the snapshot pass: both arches, upper only,
    /// lower only. Omitted individually if rendering that one failed, and
    /// the whole block is skipped if none rendered — a case can still be
    /// "ready" per status while a render happens to come back empty, and
    /// the report should not show three blank boxes for that.
    private static func drawReconstructionSnapshots(_ page: ReportPage, snapshots: ReconstructionSnapshots) {
        let items: [(label: String, image: UIImage)] = [
            ("Front", snapshots.front),
            ("Upper arch", snapshots.upper),
            ("Lower arch", snapshots.lower)
        ].compactMap { label, image in image.map { (label, $0) } }
        guard !items.isEmpty else { return }

        let thumbSize: CGFloat = 130
        let gap: CGFloat = 10
        let rowHeight = thumbSize + 14
        page.ensure(rowHeight + 6)
        let rowTop = page.y

        for (index, item) in items.enumerated() {
            let x = page.margin + CGFloat(index) * (thumbSize + gap)
            let rect = CGRect(x: x, y: rowTop, width: thumbSize, height: thumbSize)
            _ = drawAspectFit(item.image, in: rect)
            let border = UIBezierPath(rect: rect)
            UIColor.hairline.setStroke()
            border.lineWidth = 0.5
            border.stroke()
            (item.label as NSString).draw(
                at: CGPoint(x: x, y: rowTop + thumbSize + 2),
                withAttributes: [.font: F.small, .foregroundColor: UIColor.inkSoft]
            )
        }
        page.y = rowTop + rowHeight + 6
    }

    private static func drawNarrative(_ page: ReportPage, result: AnalysisResult) {
        guard let narrative = result.narrative, !narrative.isEmpty else { return }
        page.text("Report notes", font: F.h2, spacingAfter: 6)
        page.text(narrative, font: F.body, color: .black, spacingAfter: 10)
        page.rule()
    }

    private static func drawFooter(_ page: ReportPage, result: AnalysisResult) {
        page.text(
            "\(result.engineName) · generated \(result.generatedAt.formatted(date: .abbreviated, time: .shortened))",
            font: F.small, color: .inkSoft
        )
    }

    // MARK: - Overlay thumbnails

    private static func drawParameterThumbnails(
        _ page: ReportPage,
        caseID: UUID,
        targets: [(view: ToothView, overlay: ViewOverlay)],
        paramKey: String,
        thumbSize: CGFloat = 130
    ) {
        let relevant: [(view: ToothView, shapes: [OverlayShape])] = targets.compactMap { target in
            let shapes = target.overlay.shapes(for: paramKey)
            guard shapes.contains(where: { !$0.params.isEmpty }) else { return nil }
            return (target.view, shapes)
        }
        guard !relevant.isEmpty else { return }

        let gap: CGFloat = 10
        let rowHeight = thumbSize + 14
        page.ensure(rowHeight + 6)
        let rowTop = page.y

        for (index, item) in relevant.enumerated() {
            let x = page.margin + CGFloat(index) * (thumbSize + gap)
            let rect = CGRect(x: x, y: rowTop, width: thumbSize, height: thumbSize)

            guard let image = ImageStore.load(caseID: caseID, view: item.view) else { continue }
            let drawnRect = drawAspectFit(image, in: rect)
            drawShapes(item.shapes, in: drawnRect)

            let border = UIBezierPath(rect: rect)
            UIColor.hairline.setStroke()
            border.lineWidth = 0.5
            border.stroke()

            (item.view.title as NSString).draw(
                at: CGPoint(x: x, y: rowTop + thumbSize + 2),
                withAttributes: [.font: F.small, .foregroundColor: UIColor.inkSoft]
            )
        }

        page.y = rowTop + rowHeight + 6
    }

    private static func drawShapes(_ shapes: [OverlayShape], in rect: CGRect) {
        for shape in shapes {
            let points = shape.points.map { $0.resolved(in: rect) }
            guard !points.isEmpty else { continue }

            let tint = UIColor(shape.role.tint)
            let path = UIBezierPath()

            switch shape.kind {
            case .polygon:
                path.move(to: points[0])
                for point in points.dropFirst() { path.addLine(to: point) }
                path.close()
            case .box:
                guard points.count >= 2 else { continue }
                let boxRect = CGRect(
                    x: min(points[0].x, points[1].x),
                    y: min(points[0].y, points[1].y),
                    width: abs(points[1].x - points[0].x),
                    height: abs(points[1].y - points[0].y)
                )
                path.append(UIBezierPath(rect: boxRect))
            case .line:
                path.move(to: points[0])
                for point in points.dropFirst() { path.addLine(to: point) }
            case .point:
                let p = points[0]
                path.append(UIBezierPath(ovalIn: CGRect(x: p.x - 3, y: p.y - 3, width: 6, height: 6)))
            }

            tint.setStroke()
            path.lineWidth = shape.role.lineWidth
            let dash = shape.role.dash
            if dash.isEmpty {
                path.setLineDash(nil, count: 0, phase: 0)
            } else {
                path.setLineDash(dash, count: dash.count, phase: 0)
            }
            path.stroke()

            if let label = shape.label {
                drawShapeLabel(label, at: centroid(points), tint: tint)
            }
        }
    }

    private static func drawShapeLabel(_ label: String, at centre: CGPoint, tint: UIColor) {
        let attributes: [NSAttributedString.Key: Any] = [
            .font: UIFont.systemFont(ofSize: 7, weight: .bold),
            .foregroundColor: UIColor.white
        ]
        let textSize = (label as NSString).size(withAttributes: attributes)
        let pad: CGFloat = 2
        let background = CGRect(
            x: centre.x - textSize.width / 2 - pad,
            y: centre.y - textSize.height / 2 - pad,
            width: textSize.width + pad * 2,
            height: textSize.height + pad * 2
        )
        tint.withAlphaComponent(0.9).setFill()
        UIBezierPath(roundedRect: background, cornerRadius: 3).fill()
        (label as NSString).draw(
            at: CGPoint(x: centre.x - textSize.width / 2, y: centre.y - textSize.height / 2),
            withAttributes: attributes
        )
    }

    private static func centroid(_ points: [CGPoint]) -> CGPoint {
        guard !points.isEmpty else { return .zero }
        let sum = points.reduce(CGPoint.zero) { CGPoint(x: $0.x + $1.x, y: $0.y + $1.y) }
        return CGPoint(x: sum.x / CGFloat(points.count), y: sum.y / CGFloat(points.count))
    }

    // MARK: - Layout helpers

    @discardableResult
    private static func drawAspectFit(_ image: UIImage, in rect: CGRect) -> CGRect {
        let imageAspect = image.size.width / max(image.size.height, 1)
        let rectAspect = rect.width / rect.height
        var drawRect = rect
        if imageAspect > rectAspect {
            let height = rect.width / imageAspect
            drawRect = CGRect(x: rect.minX, y: rect.minY + (rect.height - height) / 2, width: rect.width, height: height)
        } else {
            let width = rect.height * imageAspect
            drawRect = CGRect(x: rect.minX + (rect.width - width) / 2, y: rect.minY, width: width, height: rect.height)
        }
        image.draw(in: drawRect)
        return drawRect
    }

    private static func tint(for reliability: Reliability) -> UIColor {
        switch reliability {
        case .reliable:    return .calm
        case .unreliable:  return .watch
        case .notComputed: return .inkSoft
        }
    }

    private static func tint(for band: SeverityBand) -> UIColor {
        switch band {
        case .noNeed, .littleNeed: return .calm
        case .borderline:          return .watch
        case .definiteNeed:        return .urgent
        }
    }
}

// MARK: - Fonts

private enum F {
    static let h1 = UIFont.systemFont(ofSize: 20, weight: .bold)
    static let h2 = UIFont.systemFont(ofSize: 14, weight: .semibold)
    static let body = UIFont.systemFont(ofSize: 10, weight: .regular)
    static let bodyBold = UIFont.systemFont(ofSize: 10, weight: .semibold)
    static let small = UIFont.systemFont(ofSize: 8.5, weight: .regular)
}

// MARK: - Colours

private extension UIColor {
    convenience init(hex: UInt32) {
        self.init(
            red: CGFloat((hex >> 16) & 0xFF) / 255,
            green: CGFloat((hex >> 8) & 0xFF) / 255,
            blue: CGFloat(hex & 0xFF) / 255,
            alpha: 1
        )
    }

    static let inkSoft  = UIColor(hex: 0x5A6B68)
    static let hairline = UIColor(hex: 0xD3DCDA)
    static let calm     = UIColor(hex: 0x2E7D5B)
    static let watch    = UIColor(hex: 0xC08526)
    static let urgent   = UIColor(hex: 0xB23A34)
}

// MARK: - Page cursor

private final class ReportPage {
    let context: UIGraphicsPDFRendererContext
    let size: CGSize
    let margin: CGFloat

    fileprivate(set) var y: CGFloat = 0

    init(context: UIGraphicsPDFRendererContext, size: CGSize, margin: CGFloat) {
        self.context = context
        self.size = size
        self.margin = margin
    }

    var contentWidth: CGFloat { size.width - margin * 2 }
    private var bottomLimit: CGFloat { size.height - margin }

    func begin() {
        context.beginPage()
        y = margin
    }

    func ensure(_ height: CGFloat) {
        if y + height > bottomLimit {
            context.beginPage()
            y = margin
        }
    }

    func space(_ height: CGFloat) { y += height }

    func rule(color: UIColor = .hairline) {
        ensure(14)
        let path = UIBezierPath()
        path.move(to: CGPoint(x: margin, y: y))
        path.addLine(to: CGPoint(x: size.width - margin, y: y))
        color.setStroke()
        path.lineWidth = 0.75
        path.stroke()
        y += 14
    }

    @discardableResult
    func text(
        _ string: String,
        font: UIFont,
        color: UIColor = .black,
        x offsetX: CGFloat = 0,
        width: CGFloat? = nil,
        spacingAfter: CGFloat = 4
    ) -> CGFloat {
        guard !string.isEmpty else { return 0 }
        let attributes: [NSAttributedString.Key: Any] = [.font: font, .foregroundColor: color]
        let boundingWidth = width ?? (contentWidth - offsetX)
        let bounds = (string as NSString).boundingRect(
            with: CGSize(width: boundingWidth, height: .greatestFiniteMagnitude),
            options: [.usesLineFragmentOrigin, .usesFontLeading],
            attributes: attributes,
            context: nil
        )
        let height = ceil(bounds.height)
        ensure(height + spacingAfter)
        (string as NSString).draw(
            in: CGRect(x: margin + offsetX, y: y, width: boundingWidth, height: height),
            withAttributes: attributes
        )
        y += height + spacingAfter
        return height
    }
}

// MARK: - 3D snapshots

extension ReportBuilder {

    struct ReconstructionSnapshots {
        var front: UIImage? = nil
        var upper: UIImage? = nil
        var lower: UIImage? = nil
    }

    /// Renders three fixed-angle snapshots of the saved reconstruction — both
    /// arches, upper only, lower only — using `SCNRenderer.snapshot`, which is
    /// built for generating a still image without a view ever being attached
    /// to the screen. `SCNView`'s own snapshot can come back blank when called
    /// outside its normal attach-and-display flow, which this sidesteps
    /// entirely.
    ///
    /// Camera field of view, distance, and vertical offset match
    /// `Teeth3DView`'s `fitCamera` exactly — the same
    /// `ReconstructionSceneBounds.cameraDistance` call, the same 45° field of
    /// view, the same `dimension * 0.18` vertical lift — so this is the same
    /// framing the interactive viewer settles on, not a new calculation.
    ///
    /// Returns all-nil snapshots, never throws, when there is nothing to
    /// render: a report must still be generatable for a case whose 3D model
    /// is missing, still processing, or failed.
    static func renderReconstructionSnapshots(
        caseID: UUID,
        reconstruction: ReconstructionRecord?
    ) async -> ReconstructionSnapshots {
        guard let reconstruction, reconstruction.status == .complete else {
            return ReconstructionSnapshots()
        }
        do {
            let assets = try await MainActor.run {
                try ReconstructionAssetURLs(caseID: caseID, reconstruction: reconstruction)
            }
            let loaded = try await ReconstructionSceneLoader.load(assets)
            return await MainActor.run { renderSnapshots(from: loaded) }
        } catch {
            return ReconstructionSnapshots()
        }
    }

    @MainActor
    private static func renderSnapshots(from loaded: LoadedReconstructionScene) -> ReconstructionSnapshots {
        // Clinical, not patient: patient material requires both textures
        // (LoadedReconstructionScene force-unwraps them for that branch), and
        // clinical is the legible, always-available choice for a printed page
        // regardless of whether this case has texture data.
        loaded.apply(.clinical)

        let renderSize = CGSize(width: 480, height: 480)
        let cameraNode = SCNNode()
        cameraNode.name = "reportSnapshotCamera"
        cameraNode.camera = SCNCamera()
        cameraNode.camera?.fieldOfView = 45
        cameraNode.camera?.zNear = 0.1

        let distance = loaded.bounds.cameraDistance(
            verticalFieldOfView: 45,
            viewportAspectRatio: Float(renderSize.width / renderSize.height)
        )
        cameraNode.camera?.zFar = Double(max(distance * 10, 500))
        let dimension = loaded.bounds.maximumDimension
        cameraNode.position = SCNVector3(0, dimension * 0.18, distance)
        cameraNode.look(at: SCNVector3Zero)

        loaded.scene.rootNode.addChildNode(cameraNode)
        defer { cameraNode.removeFromParentNode() }

        let renderer = SCNRenderer(device: nil, options: nil)
        renderer.scene = loaded.scene
        renderer.pointOfView = cameraNode
        // The scene supplies its own directional lights (installLighting in
        // ReconstructionSceneLoader); a default light on top would flatten
        // exactly the shading those were tuned to produce.
        renderer.autoenablesDefaultLighting = false

        func shot(upper: Bool, lower: Bool) -> UIImage {
            loaded.setVisibility(upper: upper, lower: lower)
            return renderer.snapshot(atTime: 0, with: renderSize, antialiasingMode: .multisampling4X)
        }

        // Bounds are fixed from both arches regardless of visibility
        // (isHidden does not shrink modelRoot.boundingBox), so the same
        // camera position is correct and stable across all three shots —
        // matching how the live viewer only re-fits on scene load or aspect
        // change, never on a visibility toggle.
        let front = shot(upper: true, lower: true)
        let upperOnly = shot(upper: true, lower: false)
        let lowerOnly = shot(upper: false, lower: true)

        return ReconstructionSnapshots(front: front, upper: upperOnly, lower: lowerOnly)
    }
}
