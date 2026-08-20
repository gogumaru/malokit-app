import AVFoundation
import Foundation
import UIKit

enum IntraoralPhotoType: String, CaseIterable {
    case front
    case leftLateral = "left_lateral"
    case rightLateral = "right_lateral"
    case maxillary
    case mandibular

    var isMirrorView: Bool { self == .maxillary }

    var toothView: ToothView {
        switch self {
        case .front: .front
        case .leftLateral: .left
        case .rightLateral: .right
        case .maxillary: .maxillary
        case .mandibular: .mandibular
        }
    }
}

extension ToothView {
    var lidarPhotoType: IntraoralPhotoType {
        switch self {
        case .front: .front
        case .right: .rightLateral
        case .left: .leftLateral
        case .maxillary: .maxillary
        case .mandibular: .mandibular
        }
    }
}

struct LiDARCaptureData {
    let depthFloat32: Data
    let confidenceUInt8: Data
    let metadata: LiDARCaptureMetadata

    init(
        depthFloat32: Data,
        confidenceUInt8: Data = Data(),
        metadata: LiDARCaptureMetadata
    ) {
        self.depthFloat32 = depthFloat32
        self.confidenceUInt8 = confidenceUInt8
        self.metadata = metadata
    }
}

struct CapturedPhoto {
    let image: UIImage
    let timestamp: Date
    let type: IntraoralPhotoType
    let depthData: AVDepthData?
    let lidarCapture: LiDARCaptureData?
    let figure8Capture: Figure8CaptureBundle?

    init(
        image: UIImage,
        timestamp: Date,
        type: IntraoralPhotoType,
        depthData: AVDepthData?,
        lidarCapture: LiDARCaptureData? = nil,
        figure8Capture: Figure8CaptureBundle? = nil
    ) {
        self.image = image
        self.timestamp = timestamp
        self.type = type
        self.depthData = depthData
        self.lidarCapture = lidarCapture
        self.figure8Capture = figure8Capture
    }
}

enum LiDARCaptureError: LocalizedError {
    case cameraPermissionDenied
    case lidarUnavailable
    case depthMissing
    case depthNotSynchronized
    case photoCaptureFailed(String)

    var errorDescription: String? {
        switch self {
        case .cameraPermissionDenied:
            "Camera access is required for LiDAR capture."
        case .lidarUnavailable:
            "This device does not provide ARKit scene depth."
        case .depthMissing:
            "No LiDAR depth frame is available yet. Hold still and try again."
        case .depthNotSynchronized:
            "A synchronized depth frame was not available. Please retake the photo."
        case .photoCaptureFailed(let reason):
            reason
        }
    }
}
