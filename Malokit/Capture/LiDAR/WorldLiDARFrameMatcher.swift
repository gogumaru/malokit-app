//
//  WorldLiDARFrameMatcher.swift
//  TeethLidar
//
//  Strict RGB/depth timestamp pairing for high-resolution AR captures.
//

import Foundation

enum WorldLiDARFrameMatcher {
    static func closest(
        to timestamp: TimeInterval,
        frames: [WorldLiDARFrameSnapshot],
        maximumDelta: TimeInterval = 0.100
    ) -> WorldLiDARFrameSnapshot? {
        let candidate = frames.min {
            abs($0.timestamp - timestamp) < abs($1.timestamp - timestamp)
        }
        guard let candidate,
              abs(candidate.timestamp - timestamp) <= maximumDelta else {
            return nil
        }
        return candidate
    }
}
