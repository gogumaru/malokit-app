//
//  Figure8Coverage.swift
//  TeethLidar
//
//  Pure ordered coverage gate for a direct-view Figure-8 capture.
//

import Foundation
import simd

enum Figure8State: String, Codable, CaseIterable {
    case idle
    case leftUpper
    case leftLower
    case centreCrossing
    case rightUpper
    case rightLower
    case returnCentre
    case complete
    case rejected
}

struct Figure8SweepConfiguration: Equatable {
    let leftRightThresholdMetres: Float
    let verticalSeparationMetres: Float
    let maximumZDeviationMetres: Float
    let targetRadiusMetres: Float
    /// Consecutive in-radius candidate samples required to advance out of a
    /// boundary-extreme lobe (see `Figure8CoverageGate.isBoundaryExtremeState`)
    /// — the sweep's horizontal extremes, nearest a neighbouring direct field
    /// — so the operator lingers long enough for boundary teeth to be tracked
    /// confidently from both fields. Candidate samples arrive at most every
    /// `sweepCandidateInterval` (0.20s), so 5 samples is roughly one second.
    let boundaryDwellSampleCount: Int
    /// Max angle (radians) between the camera's forward axis and the
    /// direction to the teeth anchor before a candidate is rejected as "not
    /// aimed at the teeth" — stops an in-radius XY position from counting as
    /// reached while the phone is pointed away from the teeth-anchored AR
    /// reticle. ~18°; tune if it feels too strict/loose in practice.
    let maxAimDeviationRadians: Float

    static let developmentDefault = Figure8SweepConfiguration(
        leftRightThresholdMetres: 0.010,
        verticalSeparationMetres: 0.008,
        maximumZDeviationMetres: 0.015,
        targetRadiusMetres: 0.003,
        boundaryDwellSampleCount: 5,
        maxAimDeviationRadians: 0.314159
    )
}

struct Figure8FrameSample {
    let cameraTransform: simd_float4x4
    let trackingIsNormal: Bool
    /// World transform of the fixed teeth-anchor landmark (see
    /// `WorldLiDARCaptureController.sweepTeethAnchorWorldTransform`), used to
    /// check the camera is actually pointed at the teeth. `nil` (e.g. in
    /// tests, or before the anchor is computed) skips the aim check.
    let teethAnchorWorldTransform: simd_float4x4?

    init(
        cameraTransform: simd_float4x4,
        trackingIsNormal: Bool,
        teethAnchorWorldTransform: simd_float4x4? = nil
    ) {
        self.cameraTransform = cameraTransform
        self.trackingIsNormal = trackingIsNormal
        self.teethAnchorWorldTransform = teethAnchorWorldTransform
    }
}

struct Figure8Acceptance: Equatable {
    let accepted: Bool
    let state: Figure8State
    let rejectionReason: String?
}

enum Figure8PoseIssue: Equatable {
    case trackingLimited
    case referenceDistanceExceeded
    case sweepNotStarted
    case notAimedAtTeeth
}

struct Figure8MovementTarget: Equatable {
    let normalizedPosition: SIMD2<Float>
    let instruction: String
    let positionMetres: SIMD2<Float>

    init(
        normalizedPosition: SIMD2<Float>,
        instruction: String,
        positionMetres: SIMD2<Float> = .zero
    ) {
        self.normalizedPosition = normalizedPosition
        self.instruction = instruction
        self.positionMetres = positionMetres
    }
}

/// Screen presentation orientation, kept independent from UIKit so the
/// Figure-8 guidance can be tested outside the iOS app target.
enum Figure8ScreenOrientation: Equatable {
    case portrait
    case portraitUpsideDown
    case landscapeLeft
    case landscapeRight
}

/// Converts ARKit's landscape-left camera axes into the coordinates a person
/// sees on the active phone screen. Coverage itself stays in ARKit's stable
/// reference space.
enum Figure8ScreenCoordinates {
    static func map(
        _ cameraCoordinates: SIMD2<Float>,
        for orientation: Figure8ScreenOrientation
    ) -> SIMD2<Float> {
        switch orientation {
        case .landscapeRight:
            return cameraCoordinates
        case .portrait:
            return SIMD2<Float>(cameraCoordinates.y, -cameraCoordinates.x)
        case .landscapeLeft:
            return -cameraCoordinates
        case .portraitUpsideDown:
            return SIMD2<Float>(-cameraCoordinates.y, cameraCoordinates.x)
        }
    }

    static func target(
        from target: Figure8MovementTarget,
        orientation: Figure8ScreenOrientation
    ) -> Figure8MovementTarget {
        let position = map(target.normalizedPosition, for: orientation)
        return Figure8MovementTarget(
            normalizedPosition: position,
            instruction: instruction(for: position),
            positionMetres: map(target.positionMetres, for: orientation)
        )
    }

    private static func instruction(for position: SIMD2<Float>) -> String {
        let horizontal = abs(position.x) > 0.2
        let vertical = abs(position.y) > 0.2
        switch (horizontal, vertical, position.x >= 0, position.y >= 0) {
        case (true, true, false, true): return "Move phone left and up"
        case (true, true, true, true): return "Move phone right and up"
        case (true, true, false, false): return "Move phone left and down"
        case (true, true, true, false): return "Move phone right and down"
        case (true, false, false, _): return "Move phone left"
        case (true, false, true, _): return "Move phone right"
        case (false, true, _, true): return "Move phone up"
        case (false, true, _, false): return "Move phone down"
        case (false, false, _, _): return "Move phone to centre"
        }
    }
}

enum SweepMovementDirection: Equatable {
    case up
    case down
    case left
    case right
    case upLeft
    case upRight
    case downLeft
    case downRight
    case holdStill

    static func from(current: SIMD2<Float>, target: SIMD2<Float>?) -> Self {
        guard let target else { return .holdStill }
        let delta = target - current
        let horizontal = abs(delta.x) > 0.2
        let vertical = abs(delta.y) > 0.2
        switch (horizontal, vertical, delta.x >= 0, delta.y >= 0) {
        case (true, true, false, true): return .upLeft
        case (true, true, true, true): return .upRight
        case (true, true, false, false): return .downLeft
        case (true, true, true, false): return .downRight
        case (true, false, false, _): return .left
        case (true, false, true, _): return .right
        case (false, true, _, true): return .up
        case (false, true, _, false): return .down
        case (false, false, _, _): return .holdStill
        }
    }

    var systemImageName: String {
        switch self {
        case .up: return "arrow.up"
        case .down: return "arrow.down"
        case .left: return "arrow.left"
        case .right: return "arrow.right"
        case .upLeft: return "arrow.up.left"
        case .upRight: return "arrow.up.right"
        case .downLeft: return "arrow.down.left"
        case .downRight: return "arrow.down.right"
        case .holdStill: return "hand.raised.fill"
        }
    }

    var instruction: String {
        switch self {
        case .up: return "Move phone up"
        case .down: return "Move phone down"
        case .left: return "Move phone left"
        case .right: return "Move phone right"
        case .upLeft: return "Move phone left and up"
        case .upRight: return "Move phone right and up"
        case .downLeft: return "Move phone left and down"
        case .downRight: return "Move phone right and down"
        case .holdStill: return "Hold the phone still"
        }
    }
}

/// A small, corner-docked 2D directional aid — complements the AR-anchored
/// 3D reticle for cases where it's out of frame or hard to read at a glance.
struct SweepPositionGuide: Equatable {
    static let displayRadiusMetres: Float = 0.015

    let cursorPosition: SIMD2<Float>
    let targetPosition: SIMD2<Float>
    let isInsideTarget: Bool

    static func from(
        phonePositionMetres: SIMD2<Float>,
        targetPositionMetres: SIMD2<Float>,
        targetRadiusMetres: Float
    ) -> Self {
        return Self(
            cursorPosition: normalized(phonePositionMetres),
            targetPosition: normalized(targetPositionMetres),
            isInsideTarget: simd_length(phonePositionMetres - targetPositionMetres)
                <= targetRadiusMetres
        )
    }

    private static func normalized(_ positionMetres: SIMD2<Float>) -> SIMD2<Float> {
        let normalized = positionMetres / displayRadiusMetres
        return SIMD2<Float>(
            max(-1, min(1, normalized.x)),
            max(-1, min(1, normalized.y))
        )
    }
}

struct Figure8PoseGuidance: Equatable {
    let normalizedPosition: SIMD2<Float>
    let positionMetres: SIMD2<Float>
    let target: Figure8MovementTarget?
    let poseIssue: Figure8PoseIssue?
}

enum Figure8GuidanceMode: Equatable {
    case arkitRecovery
    case referenceDistanceRecovery
    case aimAtTeeth

    var message: String {
        switch self {
        case .arkitRecovery:
            return "Hold phone still until ARKit tracking recovers"
        case .referenceDistanceRecovery:
            return "Return to the original distance"
        case .aimAtTeeth:
            return "Point the phone at the teeth marker"
        }
    }
}

struct Figure8SweepGuidance: Equatable {
    let mode: Figure8GuidanceMode?
    let normalizedPosition: SIMD2<Float>
    let screenPositionMetres: SIMD2<Float>
    let target: Figure8MovementTarget?
    let targetRadiusMetres: Float?
    let targetReached: Bool
    let instruction: String
}

struct Figure8CoverageGate {
    let configuration: Figure8SweepConfiguration
    private(set) var state: Figure8State = .idle
    private var referenceFromWorld: simd_float4x4?
    /// Consecutive in-radius samples accumulated at a boundary-extreme target
    /// (see `isBoundaryExtremeState`), reset whenever the phone leaves the
    /// ring before the dwell requirement is met.
    private var boundaryDwellCount: Int = 0

    init(configuration: Figure8SweepConfiguration) {
        self.configuration = configuration
    }

    var targetRadiusMetres: Float {
        configuration.targetRadiusMetres
    }

    mutating func begin(directView: Bool, referenceTransform: simd_float4x4) {
        guard directView else {
            state = .rejected
            referenceFromWorld = nil
            return
        }
        state = .idle
        referenceFromWorld = referenceTransform.inverse
    }

    var nextTarget: Figure8MovementTarget? {
        guard let position = nextTargetPosition else { return nil }
        return Figure8MovementTarget(
            normalizedPosition: SIMD2<Float>(
                position.x / configuration.leftRightThresholdMetres,
                position.y / (configuration.verticalSeparationMetres / 2)
            ),
            instruction: instruction(for: state),
            positionMetres: position
        )
    }

    func guidance(for sample: Figure8FrameSample) -> Figure8PoseGuidance {
        guard let referenceFromWorld else {
            return Figure8PoseGuidance(
                normalizedPosition: .zero,
                positionMetres: .zero,
                target: nil,
                poseIssue: .sweepNotStarted
            )
        }

        let localPosition = (referenceFromWorld * sample.cameraTransform).columns.3
        let normalizedPosition = SIMD2<Float>(
            localPosition.x / configuration.leftRightThresholdMetres,
            localPosition.y / (configuration.verticalSeparationMetres / 2)
        )
        let poseIssue: Figure8PoseIssue?
        if !sample.trackingIsNormal {
            poseIssue = .trackingLimited
        } else if abs(localPosition.z) > configuration.maximumZDeviationMetres {
            poseIssue = .referenceDistanceExceeded
        } else if !isAimedAtTeeth(sample: sample) {
            poseIssue = .notAimedAtTeeth
        } else {
            poseIssue = nil
        }
        return Figure8PoseGuidance(
            normalizedPosition: normalizedPosition,
            positionMetres: SIMD2<Float>(localPosition.x, localPosition.y),
            target: nextTarget,
            poseIssue: poseIssue
        )
    }

    mutating func accept(sample: Figure8FrameSample) -> Figure8Acceptance {
        guard state != .rejected else {
            return rejection("mirror_or_ineligible_view")
        }
        guard state != .complete else {
            return rejection("sweep_already_complete")
        }
        guard let referenceFromWorld else {
            return rejection("sweep_not_started")
        }
        guard sample.trackingIsNormal else {
            return rejection("limited_tracking")
        }
        let localTransform = referenceFromWorld * sample.cameraTransform
        let localPosition = localTransform.columns.3
        guard abs(localPosition.z) <= configuration.maximumZDeviationMetres else {
            return rejection("reference_distance_exceeded")
        }
        guard isAimedAtTeeth(sample: sample) else {
            return rejection("not_aimed_at_teeth")
        }

        guard let target = nextTargetPosition,
              simd_length(SIMD2<Float>(localPosition.x, localPosition.y) - target)
                <= configuration.targetRadiusMetres else {
            boundaryDwellCount = 0
            return Figure8Acceptance(accepted: false, state: state, rejectionReason: nil)
        }

        if isBoundaryExtremeState(state) {
            boundaryDwellCount += 1
            guard boundaryDwellCount >= configuration.boundaryDwellSampleCount else {
                return Figure8Acceptance(accepted: false, state: state, rejectionReason: nil)
            }
        }

        boundaryDwellCount = 0
        advance()
        return Figure8Acceptance(accepted: true, state: state, rejectionReason: nil)
    }

    /// True for the four lobe-approach states whose `nextTargetPosition` sits
    /// at the sweep's horizontal extreme (`|x| == leftRightThresholdMetres`),
    /// closest to a neighbouring direct field. Holding here — rather than
    /// advancing the instant the ring is entered — gives boundary teeth a
    /// chance to be tracked confidently from two fields, which M6 requires.
    private func isBoundaryExtremeState(_ state: Figure8State) -> Bool {
        switch state {
        case .idle, .leftUpper, .centreCrossing, .rightUpper: return true
        case .leftLower, .rightLower, .returnCentre, .complete, .rejected: return false
        }
    }

    private mutating func advance() {
        switch state {
        case .idle: state = .leftUpper
        case .leftUpper: state = .leftLower
        case .leftLower: state = .centreCrossing
        case .centreCrossing: state = .rightUpper
        case .rightUpper: state = .rightLower
        case .rightLower: state = .complete
        case .returnCentre, .complete, .rejected:
            break
        }
    }

    private var nextTargetPosition: SIMD2<Float>? {
        let side = configuration.leftRightThresholdMetres
        let vertical = configuration.verticalSeparationMetres / 2
        switch state {
        case .idle: return SIMD2<Float>(-side, vertical)
        case .leftUpper: return SIMD2<Float>(-side, -vertical)
        case .leftLower: return .zero
        case .centreCrossing: return SIMD2<Float>(side, vertical)
        case .rightUpper: return SIMD2<Float>(side, -vertical)
        case .rightLower: return .zero
        case .returnCentre, .complete, .rejected: return nil
        }
    }

    private func instruction(for state: Figure8State) -> String {
        switch state {
        case .idle: return "Move phone left and up, then hold steady"
        case .leftUpper: return "Move phone left and down, then hold steady"
        case .leftLower: return "Move phone to centre"
        case .centreCrossing: return "Move phone right and up, then hold steady"
        case .rightUpper: return "Move phone right and down, then hold steady"
        case .rightLower: return "Return phone to centre"
        case .returnCentre, .complete, .rejected: return ""
        }
    }

    private func rejection(_ reason: String) -> Figure8Acceptance {
        Figure8Acceptance(accepted: false, state: state, rejectionReason: reason)
    }

    /// True when no teeth anchor is known yet, or when the camera's forward
    /// axis points at the anchor within `maxAimDeviationRadians` — the
    /// pure-math equivalent of "the on-screen crosshair overlaps the
    /// teeth-anchored AR reticle", so an in-radius XY position doesn't get
    /// accepted while the phone is pointed away from the teeth.
    private func isAimedAtTeeth(sample: Figure8FrameSample) -> Bool {
        guard let anchorTransform = sample.teethAnchorWorldTransform else { return true }
        let cameraPosition = sample.cameraTransform.columns.3
        let anchorPosition = anchorTransform.columns.3
        let toAnchor = SIMD3<Float>(
            anchorPosition.x - cameraPosition.x,
            anchorPosition.y - cameraPosition.y,
            anchorPosition.z - cameraPosition.z
        )
        guard simd_length(toAnchor) > 1e-5 else { return true }
        // ARKit cameras look down their local -Z axis.
        let forward = -SIMD3<Float>(
            sample.cameraTransform.columns.2.x,
            sample.cameraTransform.columns.2.y,
            sample.cameraTransform.columns.2.z
        )
        let cosAngle = simd_dot(simd_normalize(toAnchor), simd_normalize(forward))
        return acos(max(-1, min(1, cosAngle))) <= configuration.maxAimDeviationRadians
    }
}
