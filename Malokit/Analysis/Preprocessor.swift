import UIKit

enum Preprocessor {

    /// Long edge the app stores. Big enough for millimetre level measurement,
    /// small enough to keep a five photo case under a few megabytes.
    static let storedLongEdge: CGFloat = 1600

    /// Redraws the image with its orientation baked in, so every later step
    /// works on plain top left origin pixels.
    static func upright(_ image: UIImage) -> UIImage {
        guard image.imageOrientation != .up else { return image }
        let format = UIGraphicsImageRendererFormat.default()
        format.scale = image.scale
        return UIGraphicsImageRenderer(size: image.size, format: format).image { _ in
            image.draw(in: CGRect(origin: .zero, size: image.size))
        }
    }

    /// Resize only. Do not add a horizontal flip here, now or later.
    ///
    /// Angle's classification is scored per side and the app labels the right
    /// and left buccal views by which side the retractor was on. A mirrored
    /// frame turns a Class II right into a Class II left and nothing
    /// downstream can detect that it happened. Rotation and brightness
    /// normalisation are safe, horizontal flip is not.
    static func prepare(_ image: UIImage) -> UIImage {
        let upright = upright(image)
        let longEdge = max(upright.size.width, upright.size.height)
        guard longEdge > storedLongEdge else { return upright }

        let scale = storedLongEdge / longEdge
        let target = CGSize(
            width: (upright.size.width * scale).rounded(),
            height: (upright.size.height * scale).rounded()
        )
        let format = UIGraphicsImageRendererFormat.default()
        format.scale = 1
        return UIGraphicsImageRenderer(size: target, format: format).image { _ in
            upright.draw(in: CGRect(origin: .zero, size: target))
        }
    }

    /// Square centre crop plus resize, the shape most classifier backbones
    /// expect. Used by the CoreML engine later.
    static func squarePatch(_ image: UIImage, side: CGFloat) -> UIImage {
        let source = upright(image)
        guard let cgImage = source.cgImage else { return source }

        let edge = min(cgImage.width, cgImage.height)
        let cropRect = CGRect(
            x: (cgImage.width - edge) / 2,
            y: (cgImage.height - edge) / 2,
            width: edge,
            height: edge
        )
        guard let cropped = cgImage.cropping(to: cropRect) else { return source }

        let format = UIGraphicsImageRendererFormat.default()
        format.scale = 1
        let target = CGSize(width: side, height: side)
        return UIGraphicsImageRenderer(size: target, format: format).image { _ in
            UIImage(cgImage: cropped).draw(in: CGRect(origin: .zero, size: target))
        }
    }
}
