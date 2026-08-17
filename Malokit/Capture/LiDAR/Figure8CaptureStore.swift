//
//  Figure8CaptureStore.swift
//  TeethLidar
//
//  Durable, independent Figure-8 keyframe artifacts for checkpoint recovery.
//

import Foundation

enum Figure8CaptureStoreError: Error {
    case invalidManifest(String)
    case unknownKeyframeID(String)
    case invalidArtifact(Figure8KeyframeID, String)
}

enum Figure8CaptureStore {
    private static let manifestFileName = "figure8_manifest.json"

    static func write(_ bundle: Figure8CaptureBundle, to directory: URL) throws {
        try validate(bundle: bundle)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)

        let entries = try Figure8KeyframeID.allCases.compactMap { id -> Figure8CaptureManifestEntry? in
            guard let artifact = bundle.keyframes[id] else { return nil }
            let metadata = try metadata(for: artifact)
            try artifact.rgbPNG.write(to: url(for: id, suffix: "rgb.png", in: directory), options: .atomic)
            try artifact.depthFloat32.write(to: url(for: id, suffix: "depth.f32", in: directory), options: .atomic)
            try artifact.confidenceUInt8.write(to: url(for: id, suffix: "confidence.u8", in: directory), options: .atomic)
            try JSONEncoder().encode(metadata).write(
                to: url(for: id, suffix: "metadata.json", in: directory),
                options: .atomic
            )
            return Figure8CaptureManifestEntry(
                id: id.wireName,
                depthCoverage: artifact.depthCoverage,
                blurScore: artifact.blurScore,
                poseSeparation: artifact.poseSeparation
            )
        }

        let manifest = Figure8CaptureManifest(schemaVersion: 1, keyframes: entries)
        try JSONEncoder().encode(manifest).write(
            to: directory.appendingPathComponent(manifestFileName),
            options: .atomic
        )
    }

    static func load(from directory: URL) throws -> Figure8CaptureBundle? {
        let manifestURL = directory.appendingPathComponent(manifestFileName)
        guard FileManager.default.fileExists(atPath: manifestURL.path) else { return nil }

        let manifest = try JSONDecoder().decode(Figure8CaptureManifest.self, from: Data(contentsOf: manifestURL))
        guard manifest.schemaVersion == 1 else {
            throw Figure8CaptureStoreError.invalidManifest("unsupported schema \(manifest.schemaVersion)")
        }

        var artifacts: [Figure8KeyframeArtifact] = []
        for entry in manifest.keyframes {
            let id = try keyframeID(from: entry.id)
            let metadata = try JSONDecoder().decode(
                LiDARCaptureMetadata.self,
                from: Data(contentsOf: url(for: id, suffix: "metadata.json", in: directory))
            )
            let artifact = Figure8KeyframeArtifact(
                id: id,
                rgbPNG: try Data(contentsOf: url(for: id, suffix: "rgb.png", in: directory)),
                depthFloat32: try Data(contentsOf: url(for: id, suffix: "depth.f32", in: directory)),
                metadata: metadata,
                confidenceUInt8: try Data(contentsOf: url(for: id, suffix: "confidence.u8", in: directory)),
                depthCoverage: entry.depthCoverage,
                blurScore: entry.blurScore,
                poseSeparation: entry.poseSeparation,
                isDirectView: metadata.isDirectView ?? false
            )
            try validate(artifact: artifact)
            guard metadata.figure8KeyframeID == id.wireName else {
                throw Figure8CaptureStoreError.invalidArtifact(id, "metadata keyframe ID does not match filename")
            }
            artifacts.append(artifact)
        }

        return try Figure8CaptureBundle(keyframes: artifacts)
    }

    private static func validate(bundle: Figure8CaptureBundle) throws {
        for artifact in bundle.keyframes.values {
            try validate(artifact: artifact)
        }
    }

    private static func validate(artifact: Figure8KeyframeArtifact) throws {
        guard artifact.isDirectView else {
            throw Figure8CaptureStoreError.invalidArtifact(artifact.id, "mirror keyframes cannot be persisted")
        }
        guard artifact.metadata.schemaVersion == 4 else {
            throw Figure8CaptureStoreError.invalidArtifact(artifact.id, "metadata schema must be 4")
        }
        let width = artifact.metadata.depthWidth
        let height = artifact.metadata.depthHeight
        guard width > 0, height > 0 else {
            throw Figure8CaptureStoreError.invalidArtifact(artifact.id, "depth dimensions must be positive")
        }
        let pixelCount = width * height
        guard artifact.depthFloat32.count == pixelCount * MemoryLayout<Float32>.size else {
            throw Figure8CaptureStoreError.invalidArtifact(artifact.id, "depth byte count does not match dimensions")
        }
        guard artifact.confidenceUInt8.count == pixelCount else {
            throw Figure8CaptureStoreError.invalidArtifact(artifact.id, "confidence byte count does not match dimensions")
        }
        guard !artifact.rgbPNG.isEmpty else {
            throw Figure8CaptureStoreError.invalidArtifact(artifact.id, "RGB PNG cannot be empty")
        }
    }

    private static func metadata(for artifact: Figure8KeyframeArtifact) throws -> LiDARCaptureMetadata {
        var metadata = artifact.metadata
        metadata.figure8KeyframeID = artifact.id.wireName
        metadata.isDirectView = true
        return metadata
    }

    private static func keyframeID(from wireName: String) throws -> Figure8KeyframeID {
        guard let id = Figure8KeyframeID(rawValue: wireName.lowercased()) else {
            throw Figure8CaptureStoreError.unknownKeyframeID(wireName)
        }
        return id
    }

    private static func url(for id: Figure8KeyframeID, suffix: String, in directory: URL) -> URL {
        directory.appendingPathComponent("\(id.wireName).\(suffix)")
    }
}

private struct Figure8CaptureManifest: Codable {
    let schemaVersion: Int
    let keyframes: [Figure8CaptureManifestEntry]
}

private struct Figure8CaptureManifestEntry: Codable {
    let id: String
    let depthCoverage: Float
    let blurScore: Float
    let poseSeparation: Float
}
