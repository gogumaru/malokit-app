//
//  WorldLiDARPointProjector.swift
//  TeethLidar
//
//  Pure scene-depth back-projection into ARKit world coordinates.
//

import Foundation
import simd

struct WorldLiDARFrameSnapshot: Sendable {
    let depthValues: [Float]
    let confidenceValues: [UInt8]?
    let width: Int
    let height: Int
    let cameraImageWidth: Int
    let cameraImageHeight: Int
    let intrinsics: simd_float3x3
    let cameraTransform: simd_float4x4
    let timestamp: TimeInterval
}

struct WorldLiDARPoint: Equatable, Sendable {
    let sourceIndex: Int
    let position: SIMD3<Float>
    let confidence: UInt8
}

enum WorldLiDARPointProjector {
    static func project(
        snapshot: WorldLiDARFrameSnapshot,
        sampleStride: Int = 2
    ) -> [WorldLiDARPoint] {
        guard snapshot.width > 0,
              snapshot.height > 0,
              snapshot.cameraImageWidth > 0,
              snapshot.cameraImageHeight > 0,
              snapshot.depthValues.count >= snapshot.width * snapshot.height,
              sampleStride > 0 else {
            return []
        }

        let scaleX = Float(snapshot.width) / Float(snapshot.cameraImageWidth)
        let scaleY = Float(snapshot.height) / Float(snapshot.cameraImageHeight)
        let fx = snapshot.intrinsics.columns.0.x * scaleX
        let fy = snapshot.intrinsics.columns.1.y * scaleY
        let cx = snapshot.intrinsics.columns.2.x * scaleX
        let cy = snapshot.intrinsics.columns.2.y * scaleY
        guard fx.isFinite, fy.isFinite, fx > 0, fy > 0 else { return [] }

        var result: [WorldLiDARPoint] = []
        result.reserveCapacity(
            snapshot.width * snapshot.height / (sampleStride * sampleStride)
        )

        for row in Swift.stride(from: 0, to: snapshot.height, by: sampleStride) {
            for column in Swift.stride(from: 0, to: snapshot.width, by: sampleStride) {
                let index = row * snapshot.width + column
                let depth = snapshot.depthValues[index]
                let confidence = snapshot.confidenceValues.flatMap {
                    index < $0.count ? $0[index] : nil
                } ?? 2
                guard depth.isFinite,
                      depth >= 0.05,
                      depth <= 2.0,
                      confidence >= 1 else {
                    continue
                }

                let imageX = (Float(column) - cx) * depth / fx
                let imageY = (Float(row) - cy) * depth / fy
                let cameraPoint = SIMD4<Float>(imageX, -imageY, -depth, 1)
                let worldPoint = snapshot.cameraTransform * cameraPoint
                result.append(WorldLiDARPoint(
                    sourceIndex: index,
                    position: SIMD3<Float>(worldPoint.x, worldPoint.y, worldPoint.z),
                    confidence: confidence
                ))
            }
        }

        return result
    }

    /// The world-space position of the depth grid's centre pixel — i.e.
    /// wherever the camera was actually pointed, at its real measured
    /// distance. Falls back to the nearest valid pixel within a small
    /// neighbourhood if the exact centre sample is missing/invalid, since
    /// intraoral depth grids can have small per-frame holes.
    static func centerWorldPoint(snapshot: WorldLiDARFrameSnapshot) -> SIMD3<Float>? {
        guard snapshot.width > 0,
              snapshot.height > 0,
              snapshot.cameraImageWidth > 0,
              snapshot.cameraImageHeight > 0,
              snapshot.depthValues.count >= snapshot.width * snapshot.height else {
            return nil
        }

        let scaleX = Float(snapshot.width) / Float(snapshot.cameraImageWidth)
        let scaleY = Float(snapshot.height) / Float(snapshot.cameraImageHeight)
        let fx = snapshot.intrinsics.columns.0.x * scaleX
        let fy = snapshot.intrinsics.columns.1.y * scaleY
        let cx = snapshot.intrinsics.columns.2.x * scaleX
        let cy = snapshot.intrinsics.columns.2.y * scaleY
        guard fx.isFinite, fy.isFinite, fx > 0, fy > 0 else { return nil }

        let centerColumn = snapshot.width / 2
        let centerRow = snapshot.height / 2
        let searchRadius = max(snapshot.width, snapshot.height) / 8

        for radius in stride(from: 0, through: searchRadius, by: 1) {
            for rowOffset in -radius...radius {
                for columnOffset in -radius...radius {
                    guard max(abs(rowOffset), abs(columnOffset)) == radius else { continue }
                    let row = centerRow + rowOffset
                    let column = centerColumn + columnOffset
                    guard row >= 0, row < snapshot.height, column >= 0, column < snapshot.width else {
                        continue
                    }
                    let index = row * snapshot.width + column
                    let depth = snapshot.depthValues[index]
                    let confidence = snapshot.confidenceValues.flatMap {
                        index < $0.count ? $0[index] : nil
                    } ?? 2
                    guard depth.isFinite, depth >= 0.05, depth <= 2.0, confidence >= 1 else {
                        continue
                    }
                    let imageX = (Float(column) - cx) * depth / fx
                    let imageY = (Float(row) - cy) * depth / fy
                    let cameraPoint = SIMD4<Float>(imageX, -imageY, -depth, 1)
                    let worldPoint = snapshot.cameraTransform * cameraPoint
                    return SIMD3<Float>(worldPoint.x, worldPoint.y, worldPoint.z)
                }
            }
        }
        return nil
    }
}
