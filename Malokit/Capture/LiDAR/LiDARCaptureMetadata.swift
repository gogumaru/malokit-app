//
//  LiDARCaptureMetadata.swift
//  TeethLidar
//
//  JSON-safe metadata for one raw metric-depth capture. Kept independent of
//  AVFoundation so schema compatibility can be tested on the command line.
//

import Foundation

struct LiDARCaptureMetadata: Codable {
    let schemaVersion: Int
    let depthWidth: Int
    let depthHeight: Int
    let bytesPerSample: Int
    let units: String
    let intrinsicMatrix: [Float]
    let intrinsicReferenceWidth: Double
    let intrinsicReferenceHeight: Double
    let extrinsicMatrix: [Float]
    let accuracy: String
    let quality: String
    let isFiltered: Bool
    let validPixelCount: Int
    let validFraction: Double
    let minimumDepthMetres: Float?
    let medianDepthMetres: Float?
    let maximumDepthMetres: Float?
    let ssmDepthEligible: Bool
    let exclusionReason: String?
    let rgbCrop: RGBCropMetadata?
    let cameraTransform: [Float]?
    let depthTimestampSeconds: Double?
    let rgbTimestampSeconds: Double?
    let timestampDeltaSeconds: Double?
    let mediumConfidencePixelCount: Int?
    let highConfidencePixelCount: Int?
    var matrixLayout: String? = nil
    var coordinateSystem: String? = nil
    var cameraToReferenceTransform: [Float]? = nil
    var figure8KeyframeID: String? = nil
    var figure8State: String? = nil
    var isDirectView: Bool? = nil
    var orientation: String? = nil
    var trackingState: String? = nil
}
