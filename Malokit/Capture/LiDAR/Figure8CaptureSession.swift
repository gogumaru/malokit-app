//
//  Figure8CaptureSession.swift
//  TeethLidar
//
//  Pure Figure-8 capture decisions based on ARKit pose samples.
//

import Foundation
import simd

struct Figure8CaptureSession {
    private let configuration: Figure8SweepConfiguration
    private var referenceTransform: simd_float4x4?
    private var selectedArtifacts: [Figure8KeyframeID: Figure8KeyframeArtifact] = [:]

    private(set) var coverage: Figure8CoverageGate
    private(set) var selector = Figure8KeyframeSelector()
    private(set) var guidanceMode: Figure8GuidanceMode?

    init(configuration: Figure8SweepConfiguration) {
        self.configuration = configuration
        self.coverage = Figure8CoverageGate(configuration: configuration)
    }

    mutating func begin(
        k0: Figure8KeyframeArtifact,
        referenceTransform: simd_float4x4
    ) -> Figure8Acceptance {
        reset()
        guard k0.isDirectView else {
            coverage.begin(directView: false, referenceTransform: referenceTransform)
            return Figure8Acceptance(
                accepted: false,
                state: coverage.state,
                rejectionReason: "mirror_view"
            )
        }

        self.referenceTransform = referenceTransform
        coverage.begin(directView: true, referenceTransform: referenceTransform)
        let acceptance = Figure8Acceptance(accepted: true, state: .idle, rejectionReason: nil)
        retain(k0, with: acceptance)
        return acceptance
    }

    mutating func accept(
        sample: Figure8FrameSample,
        candidate: Figure8KeyframeArtifact
    ) -> Figure8Acceptance {
        guard referenceTransform != nil else {
            return Figure8Acceptance(
                accepted: false,
                state: .idle,
                rejectionReason: "sweep_not_started"
            )
        }
        switch coverage.guidance(for: sample).poseIssue {
        case .trackingLimited:
            guidanceMode = .arkitRecovery
            return pausedAcceptance()
        case .referenceDistanceExceeded:
            guidanceMode = .referenceDistanceRecovery
            return pausedAcceptance()
        case .sweepNotStarted:
            guidanceMode = .arkitRecovery
            return pausedAcceptance()
        case .notAimedAtTeeth:
            guidanceMode = .aimAtTeeth
            return pausedAcceptance()
        case nil:
            break
        }
        guidanceMode = nil

        let acceptance = coverage.accept(sample: sample)
        guard acceptance.accepted else { return acceptance }
        guard candidate.isDirectView else {
            reset()
            return Figure8Acceptance(
                accepted: false,
                state: .idle,
                rejectionReason: "mirror_keyframe"
            )
        }
        guard candidate.id.expectedCoverageState == acceptance.state else {
            reset()
            return Figure8Acceptance(
                accepted: false,
                state: .idle,
                rejectionReason: "keyframe_state_mismatch"
            )
        }

        retain(candidate, with: acceptance)
        return acceptance
    }

    mutating func reset() {
        referenceTransform = nil
        selectedArtifacts = [:]
        selector = Figure8KeyframeSelector()
        coverage = Figure8CoverageGate(configuration: configuration)
        guidanceMode = nil
    }

    var completedBundle: Figure8CaptureBundle? {
        guard coverage.state == .complete,
              Figure8KeyframeID.allCases.allSatisfy({ selectedArtifacts[$0] != nil }) else {
            return nil
        }
        return try? Figure8CaptureBundle(keyframes: Array(selectedArtifacts.values))
    }

    private mutating func retain(
        _ artifact: Figure8KeyframeArtifact,
        with acceptance: Figure8Acceptance
    ) {
        let candidate = Figure8KeyframeCandidate(
            id: artifact.id,
            isDirectView: artifact.isDirectView,
            coverageAcceptance: acceptance,
            depthCoverage: artifact.depthCoverage,
            blurScore: artifact.blurScore,
            poseSeparation: artifact.poseSeparation
        )
        let previous = selector.selected[artifact.id]
        selector.consider(candidate: candidate)
        guard let selected = selector.selected[artifact.id],
              !sameCandidate(previous, selected) else {
            return
        }
        selectedArtifacts[artifact.id] = artifact
    }

    private func pausedAcceptance() -> Figure8Acceptance {
        Figure8Acceptance(
            accepted: false,
            state: coverage.state,
            rejectionReason: nil
        )
    }

    private func sameCandidate(
        _ lhs: Figure8KeyframeCandidate?,
        _ rhs: Figure8KeyframeCandidate
    ) -> Bool {
        guard let lhs else { return false }
        return lhs.id == rhs.id
            && lhs.isDirectView == rhs.isDirectView
            && lhs.coverageAcceptance == rhs.coverageAcceptance
            && lhs.depthCoverage == rhs.depthCoverage
            && lhs.blurScore == rhs.blurScore
            && lhs.poseSeparation == rhs.poseSeparation
    }
}
