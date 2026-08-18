import CoreVideo
import CoreMedia
import UIKit

/// A single reading of how usable a frame is. Sharpness is the variance of a
/// Laplacian response on the luma channel, brightness is mean luma 0 to 1.
struct QualityReading: Equatable {
    var sharpness: Double
    var brightness: Double

    enum Issue: String, Identifiable {
        case blurry, dark, bright
        var id: String { rawValue }

        var hint: String {
            switch self {
            case .blurry: "Hold steadier and let the camera focus"
            case .dark:   "Add light or move the mirror out of the shadow"
            case .bright: "Back off the flash, the enamel is blowing out"
            }
        }
    }

    var issues: [Issue] {
        var found: [Issue] = []
        if sharpness < QualityThresholds.minSharpness { found.append(.blurry) }
        if brightness < QualityThresholds.minBrightness { found.append(.dark) }
        if brightness > QualityThresholds.maxBrightness { found.append(.bright) }
        return found
    }

    var isAcceptable: Bool { issues.isEmpty }

    var summary: String { issues.first?.hint ?? "Good to shoot" }
}

/// Tune these on a real device with real intraoral photos. The defaults are a
/// starting point, not a calibration.
enum QualityThresholds {
    static let minSharpness: Double = 55
    static let minBrightness: Double = 0.22
    static let maxBrightness: Double = 0.88
}

enum QualityChecker {

    /// Live path. Reads the luma plane directly so nothing is converted or
    /// copied while the preview is running.
    static func evaluate(sampleBuffer: CMSampleBuffer) -> QualityReading? {
        guard let pixelBuffer = CMSampleBufferGetImageBuffer(sampleBuffer) else { return nil }
        return evaluate(pixelBuffer: pixelBuffer)
    }

    /// ARKit path. It uses the same luma-plane thresholds as AVCapture so
    /// moving to a persistent AR preview does not change Malokit's feedback.
    static func evaluate(pixelBuffer: CVPixelBuffer) -> QualityReading? {
        CVPixelBufferLockBaseAddress(pixelBuffer, .readOnly)
        defer { CVPixelBufferUnlockBaseAddress(pixelBuffer, .readOnly) }

        guard let base = CVPixelBufferGetBaseAddressOfPlane(pixelBuffer, 0) else { return nil }
        let width = CVPixelBufferGetWidthOfPlane(pixelBuffer, 0)
        let height = CVPixelBufferGetHeightOfPlane(pixelBuffer, 0)
        let rowBytes = CVPixelBufferGetBytesPerRowOfPlane(pixelBuffer, 0)

        return analyze(
            base.assumingMemoryBound(to: UInt8.self),
            width: width, height: height, rowBytes: rowBytes
        )
    }

    /// Still path. Used on stored photos, including ones imported from the
    /// library rather than shot in the app.
    static func evaluate(image: UIImage) -> QualityReading? {
        guard let cgImage = image.cgImage else { return nil }

        let targetWidth = 320
        let scale = min(1, Double(targetWidth) / Double(cgImage.width))
        let width = max(8, Int(Double(cgImage.width) * scale))
        let height = max(8, Int(Double(cgImage.height) * scale))
        let rowBytes = width

        var buffer = [UInt8](repeating: 0, count: rowBytes * height)
        guard let context = CGContext(
            data: &buffer,
            width: width, height: height,
            bitsPerComponent: 8, bytesPerRow: rowBytes,
            space: CGColorSpaceCreateDeviceGray(),
            bitmapInfo: CGImageAlphaInfo.none.rawValue
        ) else { return nil }

        context.draw(cgImage, in: CGRect(x: 0, y: 0, width: width, height: height))

        return buffer.withUnsafeBufferPointer { pointer -> QualityReading? in
            guard let base = pointer.baseAddress else { return nil }
            return analyze(base, width: width, height: height, rowBytes: rowBytes)
        }
    }

    // MARK: - Core

    private static func analyze(
        _ bytes: UnsafePointer<UInt8>,
        width: Int, height: Int, rowBytes: Int
    ) -> QualityReading {
        let step = max(1, min(width, height) / 240)
        var lumaSum = 0.0
        var lapSum = 0.0
        var lapSquareSum = 0.0
        var count = 0.0

        var y = step
        while y < height - step {
            var x = step
            while x < width - step {
                let centre = Double(bytes[y * rowBytes + x])
                let up     = Double(bytes[(y - step) * rowBytes + x])
                let down   = Double(bytes[(y + step) * rowBytes + x])
                let left   = Double(bytes[y * rowBytes + (x - step)])
                let right  = Double(bytes[y * rowBytes + (x + step)])

                let laplacian = 4 * centre - up - down - left - right
                lumaSum += centre
                lapSum += laplacian
                lapSquareSum += laplacian * laplacian
                count += 1
                x += step
            }
            y += step
        }

        guard count > 0 else { return QualityReading(sharpness: 0, brightness: 0) }
        let mean = lapSum / count
        let variance = max(0, lapSquareSum / count - mean * mean)
        return QualityReading(sharpness: variance, brightness: lumaSum / count / 255)
    }
}
