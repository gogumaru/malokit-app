//
//  Figure8Keyframes.swift
//  TeethLidar
//
//  Pure candidate ranking for ordered Figure-8 keyframes.
//

import Foundation

enum Figure8KeyframeID: String, Codable, CaseIterable {
    case k0
    case k1
    case k2
    case k3
    case k4
    case k5
    case k6

    var wireName: String {
        rawValue.uppercased()
    }

    var expectedCoverageState: Figure8State {
        switch self {
        case .k0: return .idle
        case .k1: return .leftUpper
        case .k2: return .leftLower
        case .k3: return .centreCrossing
        case .k4: return .rightUpper
        case .k5: return .rightLower
        case .k6: return .complete
        }
    }
}

struct Figure8KeyframeCandidate {
    let id: Figure8KeyframeID
    let isDirectView: Bool
    let coverageAcceptance: Figure8Acceptance
    let depthCoverage: Float
    let blurScore: Float
    let poseSeparation: Float

    var isEligible: Bool {
        isDirectView
            && coverageAcceptance.accepted
            && coverageAcceptance.state == id.expectedCoverageState
            && depthCoverage.isFinite
            && blurScore.isFinite
            && poseSeparation.isFinite
    }
}

struct Figure8KeyframeSelector {
    private(set) var selected: [Figure8KeyframeID: Figure8KeyframeCandidate] = [:]

    mutating func consider(candidate: Figure8KeyframeCandidate) {
        guard candidate.isEligible else { return }
        guard let current = selected[candidate.id] else {
            selected[candidate.id] = candidate
            return
        }
        if ranksHigher(candidate, than: current) {
            selected[candidate.id] = candidate
        }
    }

    private func ranksHigher(
        _ candidate: Figure8KeyframeCandidate,
        than current: Figure8KeyframeCandidate
    ) -> Bool {
        if candidate.depthCoverage != current.depthCoverage {
            return candidate.depthCoverage > current.depthCoverage
        }
        if candidate.blurScore != current.blurScore {
            return candidate.blurScore > current.blurScore
        }
        return candidate.poseSeparation > current.poseSeparation
    }
}
