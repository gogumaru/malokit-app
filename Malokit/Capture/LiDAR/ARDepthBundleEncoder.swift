//
//  ARDepthBundleEncoder.swift
//  TeethLidar
//
//  Encodes one ARKit scene-depth snapshot into the portable raw-depth bundle.
//

import Foundation
import simd

struct EncodedARDepthBundle {
    let depthFloat32: Data
    let confidenceUInt8: Data
    let metadata: LiDARCaptureMetadata
}

enum ARDepthBundleEncodingError: Error {
    case invalidDepthBuffer
}

enum ARDepthBundleEncoder {
    static func encodeAccumulated(
        snapshots: [WorldLiDARFrameSnapshot],
        referenceSnapshot: WorldLiDARFrameSnapshot,
        ssmDepthEligible: Bool,
        exclusionReason: String?,
        rgbCrop: RGBCropMetadata
    ) throws -> EncodedARDepthBundle {
        let width = referenceSnapshot.width
        let height = referenceSnapshot.height
        let pixelCount = width * height
        guard width > 0, height > 0 else {
            throw ARDepthBundleEncodingError.invalidDepthBuffer
        }

        // 1. Initialize a dense depth buffer with infinity
        var denseDepth = [Float](repeating: .infinity, count: pixelCount)
        var denseConfidence = [UInt8](repeating: 0, count: pixelCount)
        
        let referenceCameraTransformInverse = referenceSnapshot.cameraTransform.inverse
        
        // 2. Accumulate points from all snapshots
        for snapshot in snapshots {
            let worldPoints = WorldLiDARPointProjector.project(snapshot: snapshot, sampleStride: 1)
            
            for point in worldPoints {
                // Transform world point into the reference camera's coordinate space
                let worldPos = SIMD4<Float>(point.position.x, point.position.y, point.position.z, 1.0)
                let cameraPos = referenceCameraTransformInverse * worldPos
                
                // Depth is the negative Z axis in ARKit camera space
                let depth = -cameraPos.z
                guard depth > 0.05, depth < 2.0 else { continue }
                
                // Project onto the 2D image plane using reference intrinsics
                let scaleX = Float(width) / Float(referenceSnapshot.cameraImageWidth)
                let scaleY = Float(height) / Float(referenceSnapshot.cameraImageHeight)
                let fx = referenceSnapshot.intrinsics.columns.0.x * scaleX
                let fy = referenceSnapshot.intrinsics.columns.1.y * scaleY
                let cx = referenceSnapshot.intrinsics.columns.2.x * scaleX
                let cy = referenceSnapshot.intrinsics.columns.2.y * scaleY
                
                let imageX = (cameraPos.x * fx / depth) + cx
                let imageY = (-cameraPos.y * fy / depth) + cy // Y is flipped in image space
                
                let col = Int(round(imageX))
                let row = Int(round(imageY))
                
                // If within bounds, keep the closest depth
                if col >= 0, col < width, row >= 0, row < height {
                    let index = row * width + col
                    if depth < denseDepth[index] {
                        denseDepth[index] = depth
                        denseConfidence[index] = point.confidence
                    }
                }
            }
        }
        
        // 3. Create a synthetic fused snapshot to pass to the standard encoder
        // For pixels that received no points, we set depth to 0 (invalid)
        for i in 0..<pixelCount {
            if denseDepth[i] == .infinity {
                denseDepth[i] = 0
            }
        }
        
        let fusedSnapshot = WorldLiDARFrameSnapshot(
            depthValues: denseDepth,
            confidenceValues: denseConfidence,
            width: width,
            height: height,
            cameraImageWidth: referenceSnapshot.cameraImageWidth,
            cameraImageHeight: referenceSnapshot.cameraImageHeight,
            intrinsics: referenceSnapshot.intrinsics,
            cameraTransform: referenceSnapshot.cameraTransform,
            timestamp: referenceSnapshot.timestamp
        )
        
        return try encode(
            snapshot: fusedSnapshot,
            rgbTimestamp: referenceSnapshot.timestamp,
            ssmDepthEligible: ssmDepthEligible,
            exclusionReason: exclusionReason,
            rgbCrop: rgbCrop
        )
    }

    static func encode(
        snapshot: WorldLiDARFrameSnapshot,
        rgbTimestamp: TimeInterval,
        ssmDepthEligible: Bool,
        exclusionReason: String?,
        rgbCrop: RGBCropMetadata
    ) throws -> EncodedARDepthBundle {
        let pixelCount = snapshot.width * snapshot.height
        guard snapshot.width > 0,
              snapshot.height > 0,
              snapshot.depthValues.count >= pixelCount else {
            throw ARDepthBundleEncodingError.invalidDepthBuffer
        }

        var packed = Data(capacity: pixelCount * MemoryLayout<Float32>.size)
        var confidenceBytes = Data(capacity: pixelCount)
        var validDepths: [Float] = []
        var mediumCount = 0
        var highCount = 0

        for index in 0..<pixelCount {
            let value = snapshot.depthValues[index]
            var bits = value.bitPattern.littleEndian
            withUnsafeBytes(of: &bits) { packed.append(contentsOf: $0) }

            let sourceConfidence = snapshot.confidenceValues.flatMap {
                index < $0.count ? $0[index] : nil
            } ?? 0
            confidenceBytes.append(sourceConfidence)
            let confidence = snapshot.confidenceValues == nil ? 2 : sourceConfidence
            if confidence == 1 { mediumCount += 1 }
            if confidence >= 2 { highCount += 1 }
            if value.isFinite,
               value >= 0.05,
               value <= 2.0,
               confidence >= 1 {
                validDepths.append(value)
            }
        }
        validDepths.sort()

        var metadata = LiDARCaptureMetadata(
            schemaVersion: 4,
            depthWidth: snapshot.width,
            depthHeight: snapshot.height,
            bytesPerSample: MemoryLayout<Float32>.size,
            units: "metres",
            intrinsicMatrix: flatten(snapshot.intrinsics),
            intrinsicReferenceWidth: Double(snapshot.cameraImageWidth),
            intrinsicReferenceHeight: Double(snapshot.cameraImageHeight),
            extrinsicMatrix: [],
            accuracy: "absolute",
            quality: highCount > 0 ? "high" : "low",
            isFiltered: false,
            validPixelCount: validDepths.count,
            validFraction: Double(validDepths.count) / Double(pixelCount),
            minimumDepthMetres: validDepths.first,
            medianDepthMetres: validDepths.isEmpty ? nil : validDepths[validDepths.count / 2],
            maximumDepthMetres: validDepths.last,
            ssmDepthEligible: ssmDepthEligible,
            exclusionReason: exclusionReason,
            rgbCrop: rgbCrop,
            cameraTransform: flatten(snapshot.cameraTransform),
            depthTimestampSeconds: snapshot.timestamp,
            rgbTimestampSeconds: rgbTimestamp,
            timestampDeltaSeconds: abs(rgbTimestamp - snapshot.timestamp),
            mediumConfidencePixelCount: mediumCount,
            highConfidencePixelCount: highCount
        )
        metadata.matrixLayout = "column-major"
        metadata.coordinateSystem = "ARKit camera-to-world"

        return EncodedARDepthBundle(
            depthFloat32: packed,
            confidenceUInt8: confidenceBytes,
            metadata: metadata
        )
    }

    private static func flatten(_ matrix: simd_float3x3) -> [Float] {
        (0..<3).flatMap { column in
            (0..<3).map { row in matrix[column][row] }
        }
    }

    private static func flatten(_ matrix: simd_float4x4) -> [Float] {
        (0..<4).flatMap { column in
            (0..<4).map { row in matrix[column][row] }
        }
    }
}
