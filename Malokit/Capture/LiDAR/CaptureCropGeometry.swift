//
//  CaptureCropGeometry.swift
//  TeethLidar
//
//  Pure geometry shared by the synchronized camera preview guide and the
//  saved landscape 3:2 RGB crop.
//

import CoreGraphics
import Foundation

struct RGBCropMetadata: Codable, Equatable {
    let originalWidth: Int
    let originalHeight: Int
    let x: Int
    let y: Int
    let width: Int
    let height: Int
    let targetAspectRatio: Double
}

enum CaptureCropError: LocalizedError {
    case invalidDimensions
    case imageBufferUnavailable
    case cropFailed

    var errorDescription: String? {
        switch self {
        case .invalidDimensions:
            return "The camera returned invalid image or preview dimensions. Please retake the photo."
        case .imageBufferUnavailable:
            return "The captured RGB pixel buffer is unavailable. Please retake the photo."
        case .cropFailed:
            return "The captured image could not be cropped to landscape 3:2. Please retake the photo."
        }
    }
}

enum CaptureCropGeometry {
    static let guideFraction = 0.86
    static let targetAspectRatio = 3.0 / 2.0

    static func guideRect(previewWidth: Double, previewHeight: Double) -> CGRect {
        guard previewWidth > 0, previewHeight > 0 else { return .zero }

        let width = min(
            previewWidth * guideFraction,
            previewHeight * guideFraction * targetAspectRatio
        )
        let height = width / targetAspectRatio
        return CGRect(
            x: (previewWidth - width) / 2.0,
            y: (previewHeight - height) / 2.0,
            width: width,
            height: height
        )
    }

    static func landscapeThreeByTwo(
        originalWidth: Int,
        originalHeight: Int,
        previewWidth: Double,
        previewHeight: Double
    ) throws -> RGBCropMetadata {
        guard originalWidth > 0, originalHeight > 0 else {
            throw CaptureCropError.invalidDimensions
        }

        let sourceWidth = Double(originalWidth)
        let sourceHeight = Double(originalHeight)
        let cropWidth: Int

        if previewWidth > 0, previewHeight > 0 {
            let fillScale = max(previewWidth / sourceWidth, previewHeight / sourceHeight)
            let guide = guideRect(previewWidth: previewWidth, previewHeight: previewHeight)
            cropWidth = exactThreeByTwoWidth(notExceeding: guide.width / fillScale)
        } else {
            cropWidth = exactThreeByTwoWidth(
                notExceeding: min(sourceWidth, sourceHeight * targetAspectRatio)
            )
        }

        let cropHeight = cropWidth * 2 / 3
        guard cropWidth > 0, cropHeight > 0,
              cropWidth <= originalWidth, cropHeight <= originalHeight else {
            throw CaptureCropError.invalidDimensions
        }

        let x = Int(((sourceWidth - Double(cropWidth)) / 2.0).rounded())
        let y = Int(((sourceHeight - Double(cropHeight)) / 2.0).rounded())

        return RGBCropMetadata(
            originalWidth: originalWidth,
            originalHeight: originalHeight,
            x: x,
            y: y,
            width: cropWidth,
            height: cropHeight,
            targetAspectRatio: targetAspectRatio
        )
    }

    /// Projects a crop selected on a high-resolution reference frame onto a
    /// live AR frame with its own pixel dimensions. The two ARKit sources use
    /// different resolutions, so reusing reference-frame pixel coordinates
    /// would crop a different part of the live image.
    static func reproject(
        _ reference: RGBCropMetadata,
        ontoSourceWidth originalWidth: Int,
        height originalHeight: Int
    ) throws -> RGBCropMetadata {
        guard reference.originalWidth > 0,
              reference.originalHeight > 0,
              reference.width > 0,
              reference.height > 0,
              originalWidth > 0,
              originalHeight > 0 else {
            throw CaptureCropError.invalidDimensions
        }

        let maximumWidth = exactThreeByTwoWidth(
            notExceeding: min(Double(originalWidth), Double(originalHeight) * targetAspectRatio)
        )
        let desiredWidth = exactThreeByTwoWidth(
            notExceeding: Double(reference.width) / Double(reference.originalWidth) * Double(originalWidth)
        )
        let cropWidth = min(desiredWidth, maximumWidth)
        let cropHeight = cropWidth * 2 / 3
        guard cropWidth > 0, cropHeight > 0 else {
            throw CaptureCropError.invalidDimensions
        }

        let referenceCenterX = Double(reference.x) + Double(reference.width) / 2.0
        let referenceCenterY = Double(reference.y) + Double(reference.height) / 2.0
        let targetCenterX = referenceCenterX / Double(reference.originalWidth) * Double(originalWidth)
        let targetCenterY = referenceCenterY / Double(reference.originalHeight) * Double(originalHeight)
        let x = min(
            max(0, Int((targetCenterX - Double(cropWidth) / 2.0).rounded())),
            originalWidth - cropWidth
        )
        let y = min(
            max(0, Int((targetCenterY - Double(cropHeight) / 2.0).rounded())),
            originalHeight - cropHeight
        )
        return RGBCropMetadata(
            originalWidth: originalWidth,
            originalHeight: originalHeight,
            x: x,
            y: y,
            width: cropWidth,
            height: cropHeight,
            targetAspectRatio: targetAspectRatio
        )
    }

    private static func exactThreeByTwoWidth(notExceeding width: Double) -> Int {
        max(0, Int(width.rounded(.down)) / 3 * 3)
    }
}

#if canImport(UIKit)
import UIKit

extension UIImage {
    func cropped(using crop: RGBCropMetadata) throws -> UIImage {
        guard let cgImage else { throw CaptureCropError.imageBufferUnavailable }
        let rect = CGRect(x: crop.x, y: crop.y, width: crop.width, height: crop.height)
        guard let result = cgImage.cropping(to: rect) else {
            throw CaptureCropError.cropFailed
        }
        return UIImage(cgImage: result, scale: scale, orientation: .up)
    }
}
#endif
