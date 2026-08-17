//
//  Figure8CaptureBundle.swift
//  TeethLidar
//
//  Independent raw artifacts retained for one direct-view Figure-8 sweep.
//

import Foundation

enum Figure8CaptureBundleError: Error {
    case duplicateKeyframe(Figure8KeyframeID)
    case nonDirectKeyframe(Figure8KeyframeID)
}

struct Figure8KeyframeArtifact {
    let id: Figure8KeyframeID
    let rgbPNG: Data
    let depthFloat32: Data
    let metadata: LiDARCaptureMetadata
    let confidenceUInt8: Data
    let depthCoverage: Float
    let blurScore: Float
    let poseSeparation: Float
    let isDirectView: Bool
}

struct Figure8CaptureBundle {
    let keyframes: [Figure8KeyframeID: Figure8KeyframeArtifact]

    init(keyframes: [Figure8KeyframeArtifact]) throws {
        var byID: [Figure8KeyframeID: Figure8KeyframeArtifact] = [:]
        for keyframe in keyframes {
            guard keyframe.isDirectView else {
                throw Figure8CaptureBundleError.nonDirectKeyframe(keyframe.id)
            }
            guard byID[keyframe.id] == nil else {
                throw Figure8CaptureBundleError.duplicateKeyframe(keyframe.id)
            }
            byID[keyframe.id] = keyframe
        }
        self.keyframes = byID
    }

    var isComplete: Bool {
        Figure8KeyframeID.allCases.allSatisfy { keyframes[$0] != nil }
    }
}
