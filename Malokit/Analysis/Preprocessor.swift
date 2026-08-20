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


    /// Crops the captured photo down to the guide frame the person framed the
    /// shot in.
    ///
    /// Two reasons this matters. The obvious one: the guide promises "this is
    /// what I am capturing", and a photo that ignores it breaks that promise.
    /// The quieter one: every pixel of cheek, retractor and room outside the
    /// mouth is material for a false mask. The export brief records a patient
    /// whose overjet read 9.33 because a fragment outside the mouth was picked
    /// as the canine anchor. A tighter frame removes that material.
    ///
    /// A margin is kept because the guide is an aiming aid, not a precise
    /// boundary, and cropping is irreversible. Losing a molar to an
    /// over-tight crop would be worse than carrying a little extra background.
    static func crop(
        _ image: UIImage,
        guideRect: CGRect,
        previewSize: CGSize,
        margin: CGFloat = 0.07
    ) -> UIImage {
        guard
            let cgImage = image.cgImage,
            previewSize.width > 0, previewSize.height > 0,
            guideRect.width > 0, guideRect.height > 0
        else { return image }

        let imageWidth = CGFloat(cgImage.width)
        let imageHeight = CGFloat(cgImage.height)

        // The preview uses aspect fill, so it shows a centred crop of the
        // sensor. Undo that to find where the guide sits in the full photo.
        let scale = max(previewSize.width / imageWidth, previewSize.height / imageHeight)
        let visibleWidth = previewSize.width / scale
        let visibleHeight = previewSize.height / scale
        let visibleOriginX = (imageWidth - visibleWidth) / 2
        let visibleOriginY = (imageHeight - visibleHeight) / 2

        var rect = CGRect(
            x: visibleOriginX + guideRect.minX / scale,
            y: visibleOriginY + guideRect.minY / scale,
            width: guideRect.width / scale,
            height: guideRect.height / scale
        )

        rect = rect.insetBy(dx: -rect.width * margin, dy: -rect.height * margin)
        rect = rect.intersection(CGRect(x: 0, y: 0, width: imageWidth, height: imageHeight))

        guard rect.width > 32, rect.height > 32, let cropped = cgImage.cropping(to: rect) else {
            return image
        }
        return UIImage(cgImage: cropped, scale: 1, orientation: .up)
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
