//
//  WorldLiDARVoxelAccumulator.swift
//  TeethLidar
//
//  Bounded 2 mm world-space deduplication for the live LiDAR cloud.
//

import Foundation
import simd

private struct WorldLiDARVoxelKey: Hashable {
    let x: Int
    let y: Int
    let z: Int
}

struct WorldLiDARVoxelAccumulator {
    let voxelSize: Float
    let maximumCount: Int

    private var voxels: [WorldLiDARVoxelKey: WorldLiDARPoint] = [:]
    private var voxelOrder: [WorldLiDARVoxelKey] = []
    private var nextEvictionIndex = 0

    init(voxelSize: Float = 0.002, maximumCount: Int = 50_000) {
        self.voxelSize = voxelSize
        self.maximumCount = maximumCount
    }

    var points: [WorldLiDARPoint] {
        Array(voxels.values)
    }

    var count: Int {
        voxels.count
    }

    mutating func insert(_ points: [WorldLiDARPoint]) {
        guard voxelSize > 0, maximumCount > 0 else { return }

        for point in points {
            let key = WorldLiDARVoxelKey(
                x: Int(floor(point.position.x / voxelSize)),
                y: Int(floor(point.position.y / voxelSize)),
                z: Int(floor(point.position.z / voxelSize))
            )
            if voxels[key] != nil {
                voxels[key] = point
            } else if voxels.count < maximumCount {
                voxels[key] = point
                voxelOrder.append(key)
            } else {
                let evictedKey = voxelOrder[nextEvictionIndex]
                voxels.removeValue(forKey: evictedKey)
                voxels[key] = point
                voxelOrder[nextEvictionIndex] = key
                nextEvictionIndex = (nextEvictionIndex + 1) % maximumCount
            }
        }
    }

    mutating func reset() {
        voxels.removeAll(keepingCapacity: true)
        voxelOrder.removeAll(keepingCapacity: true)
        nextEvictionIndex = 0
    }
}
