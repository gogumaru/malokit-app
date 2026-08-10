import SwiftUI

/// The framing guide drawn over the live preview. Its aspect follows the view
/// being shot, so an occlusal frame is portrait and a buccal frame is
/// landscape. The midline tick only appears where midline actually matters.
struct GuideOverlay: View {
    let view: ToothView
    var isReady: Bool

    var body: some View {
        GeometryReader { geo in
            let frame = guideRect(in: geo.size)

            ZStack {
                Color.black.opacity(0.45)
                    .mask {
                        Rectangle()
                            .overlay {
                                RoundedRectangle(cornerRadius: 14, style: .continuous)
                                    .frame(width: frame.width, height: frame.height)
                                    .position(x: frame.midX, y: frame.midY)
                                    .blendMode(.destinationOut)
                            }
                            .compositingGroup()
                    }
                    .allowsHitTesting(false)

                RoundedRectangle(cornerRadius: 14, style: .continuous)
                    .stroke(isReady ? Theme.accent : .white.opacity(0.65),
                            style: StrokeStyle(lineWidth: 2, dash: isReady ? [] : [7, 6]))
                    .frame(width: frame.width, height: frame.height)
                    .position(x: frame.midX, y: frame.midY)
                    .animation(.easeInOut(duration: 0.2), value: isReady)

                if view == .front {
                    // Midline reference. Angle's classification and the AC
                    // score both fail quietly if the midline is off frame.
                    Path { path in
                        path.move(to: CGPoint(x: frame.midX, y: frame.minY + 10))
                        path.addLine(to: CGPoint(x: frame.midX, y: frame.minY + 34))
                        path.move(to: CGPoint(x: frame.midX, y: frame.maxY - 34))
                        path.addLine(to: CGPoint(x: frame.midX, y: frame.maxY - 10))
                    }
                    .stroke(.white.opacity(0.8), lineWidth: 1.5)
                }

                if view == .right || view == .left {
                    // Molar zone marker, on the side the retractor is pulled.
                    let x = view == .right ? frame.minX + frame.width * 0.24
                                           : frame.maxX - frame.width * 0.24
                    Circle()
                        .stroke(.white.opacity(0.7), style: StrokeStyle(lineWidth: 1.5, dash: [4, 4]))
                        .frame(width: frame.width * 0.28)
                        .position(x: x, y: frame.midY)
                }
            }
        }
    }

    private func guideRect(in size: CGSize) -> CGRect {
        let maxWidth = size.width * 0.9
        let maxHeight = size.height * 0.68
        var width = maxWidth
        var height = width / view.guideAspect
        if height > maxHeight {
            height = maxHeight
            width = height * view.guideAspect
        }
        return CGRect(
            x: (size.width - width) / 2,
            y: (size.height - height) / 2,
            width: width,
            height: height
        )
    }
}
