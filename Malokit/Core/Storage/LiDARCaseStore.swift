import Foundation
import UIKit

enum LiDARCaseStoreError: LocalizedError {
    case missingRGB
    case incompleteFigure8
    case missingDepth

    var errorDescription: String? {
        switch self {
        case .missingRGB: "The lossless LiDAR reference image could not be encoded."
        case .incompleteFigure8: "The Figure-8 capture is missing one or more K0–K6 positions."
        case .missingDepth: "The LiDAR capture does not contain synchronized depth."
        }
    }
}

struct LiDARCaseReplacement {
    let record: LiDARViewRecord
    fileprivate let destination: URL
    fileprivate let backup: URL?

    func commit() {
        if let backup { try? FileManager.default.removeItem(at: backup) }
    }

    func rollback() {
        if FileManager.default.fileExists(atPath: destination.path) {
            try? FileManager.default.removeItem(at: destination)
        }
        if let backup, FileManager.default.fileExists(atPath: backup.path) {
            try? FileManager.default.moveItem(at: backup, to: destination)
        }
    }
}

struct LiDARCaseRemoval {
    fileprivate let destination: URL
    fileprivate let backup: URL?

    func commit() {
        if let backup { try? FileManager.default.removeItem(at: backup) }
    }

    func rollback() {
        if let backup, FileManager.default.fileExists(atPath: backup.path) {
            try? FileManager.default.moveItem(at: backup, to: destination)
        }
    }
}

/// Owns raw LiDAR artifacts beneath the existing case folder. The case JSON
/// contains only a small relative-path index, never binary camera data.
enum LiDARCaseStore {
    static func directory(caseID: UUID, view: ToothView) -> URL {
        ImageStore.folder(for: caseID)
            .appendingPathComponent("lidar", isDirectory: true)
            .appendingPathComponent(view.rawValue, isDirectory: true)
    }

    static func save(
        _ capture: CapturedPhoto,
        caseID: UUID,
        view: ToothView
    ) throws -> LiDARCaseReplacement {
        let destination = directory(caseID: caseID, view: view)
        let parent = destination.deletingLastPathComponent()
        try FileManager.default.createDirectory(at: parent, withIntermediateDirectories: true)
        let staging = parent.appendingPathComponent(
            ".\(view.rawValue)-staging-\(UUID().uuidString)",
            isDirectory: true
        )
        defer {
            if FileManager.default.fileExists(atPath: staging.path) {
                try? FileManager.default.removeItem(at: staging)
            }
        }

        let record: LiDARViewRecord

        if let bundle = capture.figure8Capture {
            guard view.requiresFigure8, bundle.isComplete else {
                throw LiDARCaseStoreError.incompleteFigure8
            }
            try Figure8CaptureStore.write(bundle, to: staging)
            record = LiDARViewRecord(
                kind: .figure8,
                relativeDirectory: "lidar/\(view.rawValue)",
                keyframeCount: Figure8KeyframeID.allCases.count
            )
        } else {
            guard let lidar = capture.lidarCapture else {
                throw LiDARCaseStoreError.missingDepth
            }
            guard let rgb = capture.image.pngData() else {
                throw LiDARCaseStoreError.missingRGB
            }
            try FileManager.default.createDirectory(at: staging, withIntermediateDirectories: true)
            try rgb.write(to: staging.appendingPathComponent("reference.rgb.png"), options: .atomic)
            try lidar.depthFloat32.write(
                to: staging.appendingPathComponent("reference.depth.f32"),
                options: .atomic
            )
            try lidar.confidenceUInt8.write(
                to: staging.appendingPathComponent("reference.confidence.u8"),
                options: .atomic
            )
            try JSONEncoder().encode(lidar.metadata).write(
                to: staging.appendingPathComponent("reference.metadata.json"),
                options: .atomic
            )
            record = LiDARViewRecord(
                kind: .diagnosticDepth,
                relativeDirectory: "lidar/\(view.rawValue)",
                keyframeCount: 1
            )
        }

        let backup = FileManager.default.fileExists(atPath: destination.path)
            ? parent.appendingPathComponent(".\(view.rawValue)-backup-\(UUID().uuidString)")
            : nil
        do {
            if let backup { try FileManager.default.moveItem(at: destination, to: backup) }
            try FileManager.default.moveItem(at: staging, to: destination)
        } catch {
            if let backup, FileManager.default.fileExists(atPath: backup.path) {
                try? FileManager.default.moveItem(at: backup, to: destination)
            }
            throw error
        }
        return LiDARCaseReplacement(record: record, destination: destination, backup: backup)
    }

    static func clear(caseID: UUID, view: ToothView) {
        let destination = directory(caseID: caseID, view: view)
        if FileManager.default.fileExists(atPath: destination.path) {
            try? FileManager.default.removeItem(at: destination)
        }
    }

    static func stageRemoval(caseID: UUID, view: ToothView) throws -> LiDARCaseRemoval {
        let destination = directory(caseID: caseID, view: view)
        guard FileManager.default.fileExists(atPath: destination.path) else {
            return LiDARCaseRemoval(destination: destination, backup: nil)
        }
        let backup = destination.deletingLastPathComponent()
            .appendingPathComponent(".\(view.rawValue)-backup-\(UUID().uuidString)")
        try FileManager.default.moveItem(at: destination, to: backup)
        return LiDARCaseRemoval(destination: destination, backup: backup)
    }

    static func url(caseID: UUID, record: LiDARViewRecord, filename: String) -> URL {
        ImageStore.folder(for: caseID)
            .appendingPathComponent(record.relativeDirectory, isDirectory: true)
            .appendingPathComponent(filename)
    }

    static func figure8(caseID: UUID, record: LiDARViewRecord) throws -> Figure8CaptureBundle? {
        guard record.kind == .figure8 else { return nil }
        let directory = ImageStore.folder(for: caseID)
            .appendingPathComponent(record.relativeDirectory, isDirectory: true)
        return try Figure8CaptureStore.load(from: directory)
    }
}
