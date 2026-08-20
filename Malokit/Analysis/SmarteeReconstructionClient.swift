import Foundation
import UIKit

protocol ReconstructionClient {
    var name: String { get }
    func reconstruct(caseID: UUID, record: CaseRecord) async throws -> ReconstructionRecord
    func reconstruct(
        caseID: UUID,
        record: CaseRecord,
        reportProgress: @escaping @MainActor (ReconstructionProgress) -> Void
    ) async throws -> ReconstructionRecord
}

extension ReconstructionClient {
    func reconstruct(
        caseID: UUID,
        record: CaseRecord,
        reportProgress: @escaping @MainActor (ReconstructionProgress) -> Void
    ) async throws -> ReconstructionRecord {
        reportProgress(.queued)
        return try await reconstruct(caseID: caseID, record: record)
    }
}

struct SmarteeReconstructionError: LocalizedError {
    let message: String
    var errorDescription: String? { message }
}

struct SmarteeUpload {
    let request: URLRequest
    let body: Data
}

struct SmarteeReconstructionClient: ReconstructionClient {
    let settings: ServerSettings
    var name: String { "Smartee" }

    func reconstruct(caseID: UUID, record: CaseRecord) async throws -> ReconstructionRecord {
        try await reconstruct(caseID: caseID, record: record, reportProgress: { _ in })
    }

    func reconstruct(
        caseID: UUID,
        record: CaseRecord,
        reportProgress: @escaping @MainActor (ReconstructionProgress) -> Void
    ) async throws -> ReconstructionRecord {
        reportProgress(.uploading)
        let requestTag = Self.makeRequestTag()
        let upload = try makeUpload(caseID: caseID, record: record, requestTag: requestTag)
        reportProgress(.queued)

        // Reconstruction is one long synchronous POST, so the only way to say
        // anything truthful about the wait is to ask the server which stage it
        // is on while the upload request is still open.
        let poller = Task {
            await pollStages(tag: requestTag, reportProgress: reportProgress)
        }
        defer { poller.cancel() }

        let (data, response) = try await URLSession.shared.upload(
            for: upload.request,
            from: upload.body
        )
        guard let http = response as? HTTPURLResponse else {
            throw SmarteeReconstructionError(message: "The 3D model server did not respond.")
        }
        guard http.statusCode == 200 else {
            let serverMessage = (try? JSONDecoder().decode(SmarteeErrorResponse.self, from: data).error)
            throw SmarteeReconstructionError(
                message: serverMessage ?? "The 3D model server reported an error (status \(http.statusCode))."
            )
        }

        let responseBody = try JSONDecoder().decode(SmarteeResponse.self, from: data)
        let model = responseBody.models?.first(where: { $0.id == "pc10-lidar" })
            ?? responseBody.models?.first
        guard let upperOBJ = model?.upperObj ?? responseBody.upperObj,
              let lowerOBJ = model?.lowerObj ?? responseBody.lowerObj else {
            throw SmarteeReconstructionError(message: "The 3D model server did not return an upper and lower arch.")
        }

        reportProgress(.saving)
        return try ReconstructionStore.save(
            caseID: caseID,
            upperOBJ: upperOBJ,
            lowerOBJ: lowerOBJ,
            upperTexture: (model?.upperTexture ?? responseBody.upperTexture).flatMap {
                Data(base64Encoded: $0)
            },
            lowerTexture: (model?.lowerTexture ?? responseBody.lowerTexture).flatMap {
                Data(base64Encoded: $0)
            },
            serverModelID: model?.id ?? "single-model",
            captureTag: responseBody.lidarCaptureTag
        )
    }

    /// Tags name files on the server, which only accepts `[A-Za-z0-9-]`.
    static func makeRequestTag() -> String {
        String(UUID().uuidString.replacingOccurrences(of: "-", with: "").prefix(12)).lowercased()
    }

    /// Folds `/progress/<tag>` polls into reported progress until the upload
    /// finishes and cancels this task. Failures are silent on purpose: a
    /// missed poll must never disturb a reconstruction that is still running.
    private func pollStages(
        tag: String,
        reportProgress: @escaping @MainActor (ReconstructionProgress) -> Void
    ) async {
        guard let url = settings.reconstructionURL(path: "/progress/\(tag)") else { return }
        var reported = ReconstructionProgress.queued
        while !Task.isCancelled {
            try? await Task.sleep(nanoseconds: 5 * NSEC_PER_SEC)
            guard !Task.isCancelled else { return }

            var request = URLRequest(url: url)
            request.timeoutInterval = 8
            guard let (data, _) = try? await URLSession.shared.data(for: request),
                  let stage = try? JSONDecoder().decode(SmarteeProgressResponse.self, from: data).stage,
                  let progress = ReconstructionProgress.serverStage(stage),
                  progress.completedSteps > reported.completedSteps else {
                continue
            }
            reported = progress
            await reportProgress(progress)
        }
    }

    func makeUpload(
        caseID: UUID,
        record: CaseRecord,
        requestTag: String = SmarteeReconstructionClient.makeRequestTag(),
        boundary: String = "Malokit-Smartee-\(UUID().uuidString)"
    ) throws -> SmarteeUpload {
        guard let endpoint = settings.reconstructionURL(path: "/reconstruct") else {
            throw SmarteeReconstructionError(message: "The 3D model server address is not valid.")
        }
        guard record.isComplete else {
            throw SmarteeReconstructionError(message: "All five photos are needed to build the 3D model.")
        }

        var builder = SmarteeMultipartBuilder(boundary: boundary)
        builder.addField(name: "modelMode", value: "baseline-only")
        builder.addField(name: "requestTag", value: requestTag)

        for view in ToothView.captureOrder {
            let field = view.smarteeFieldName
            let artifacts = try loadArtifacts(caseID: caseID, record: record, view: view)
            builder.addFile(
                name: field,
                filename: "\(field).png",
                mimeType: "image/png",
                data: artifacts.rgbPNG
            )

            if let depth = artifacts.depthFloat32,
               let metadata = artifacts.depthMetadata {
                builder.addFile(
                    name: "\(field)Depth",
                    filename: "\(field).depth.f32",
                    mimeType: "application/octet-stream",
                    data: depth
                )
                builder.addFile(
                    name: "\(field)DepthMetadata",
                    filename: "\(field).depth.json",
                    mimeType: "application/json",
                    data: metadata
                )
            }

            if let bundle = artifacts.figure8 {
                try append(bundle: bundle, field: field, to: &builder)
            }
        }

        var request = URLRequest(url: endpoint)
        request.httpMethod = "POST"
        request.setValue(builder.contentType, forHTTPHeaderField: "Content-Type")
        request.timeoutInterval = 2 * 60 * 60

        return SmarteeUpload(request: request, body: builder.finalize())
    }

    static func checkHealth(settings: ServerSettings) async -> HealthReport {
        guard let url = settings.reconstructionURL(path: "/health") else {
            return HealthReport(ok: false, message: "The 3D model server address is not valid.")
        }
        var request = URLRequest(url: url)
        request.timeoutInterval = 8
        do {
            let (data, response) = try await URLSession.shared.data(for: request)
            guard let http = response as? HTTPURLResponse, http.statusCode == 200 else {
                return HealthReport(ok: false, message: "The 3D model server is not responding normally.")
            }
            let payload = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
            let status = payload?["status"] as? String ?? "ready"
            return HealthReport(ok: true, message: "Reachable. \(status.capitalized).")
        } catch {
            return HealthReport(ok: false, message: "Not reachable. \(error.localizedDescription)")
        }
    }

    private func loadArtifacts(
        caseID: UUID,
        record: CaseRecord,
        view: ToothView
    ) throws -> LoadedSmarteeArtifacts {
        guard let filename = record.filename(for: view),
              let fallbackImage = ImageStore.load(caseID: caseID, filename: filename),
              let fallbackPNG = fallbackImage.pngData() else {
            throw SmarteeReconstructionError(message: "Could not read the \(view.title) photo.")
        }
        guard let lidarRecord = record.lidarRecord(for: view) else {
            return LoadedSmarteeArtifacts(
                rgbPNG: fallbackPNG,
                depthFloat32: nil,
                depthMetadata: nil,
                figure8: nil
            )
        }

        switch lidarRecord.kind {
        case .figure8:
            guard let bundle = try LiDARCaseStore.figure8(caseID: caseID, record: lidarRecord),
                  bundle.isComplete,
                  let k0 = bundle.keyframes[.k0] else {
                throw SmarteeReconstructionError(
                    message: "The \(view.title) scan is incomplete, so the 3D model was not built."
                )
            }
            return LoadedSmarteeArtifacts(
                rgbPNG: k0.rgbPNG,
                depthFloat32: k0.depthFloat32,
                depthMetadata: try JSONEncoder().encode(k0.metadata),
                figure8: bundle
            )
        case .diagnosticDepth:
            let rgb = try Data(contentsOf: LiDARCaseStore.url(
                caseID: caseID,
                record: lidarRecord,
                filename: "reference.rgb.png"
            ))
            let depth = try Data(contentsOf: LiDARCaseStore.url(
                caseID: caseID,
                record: lidarRecord,
                filename: "reference.depth.f32"
            ))
            let metadata = try Data(contentsOf: LiDARCaseStore.url(
                caseID: caseID,
                record: lidarRecord,
                filename: "reference.metadata.json"
            ))
            return LoadedSmarteeArtifacts(
                rgbPNG: rgb,
                depthFloat32: depth,
                depthMetadata: metadata,
                figure8: nil
            )
        }
    }

    private func append(
        bundle: Figure8CaptureBundle,
        field: String,
        to builder: inout SmarteeMultipartBuilder
    ) throws {
        guard bundle.isComplete else {
            throw SmarteeReconstructionError(message: "The \(field) scan is incomplete.")
        }
        let entries = try Figure8KeyframeID.allCases.map { id -> Figure8UploadManifest.Entry in
            guard let artifact = bundle.keyframes[id] else {
                throw SmarteeReconstructionError(message: "The \(field) scan is missing part of its sweep.")
            }
            return .init(
                id: id.wireName,
                depthCoverage: artifact.depthCoverage,
                blurScore: artifact.blurScore,
                poseSeparation: artifact.poseSeparation
            )
        }
        builder.addFile(
            name: "\(field)Figure8Manifest",
            filename: "\(field).figure8.json",
            mimeType: "application/json",
            data: try JSONEncoder().encode(Figure8UploadManifest(schemaVersion: 1, keyframes: entries))
        )
        for id in Figure8KeyframeID.allCases {
            guard let artifact = bundle.keyframes[id] else { continue }
            let prefix = "\(field)Figure8\(id.wireName)"
            builder.addFile(name: "\(prefix)RGB", filename: "\(id.wireName).rgb.png", mimeType: "image/png", data: artifact.rgbPNG)
            builder.addFile(name: "\(prefix)Depth", filename: "\(id.wireName).depth.f32", mimeType: "application/octet-stream", data: artifact.depthFloat32)
            builder.addFile(name: "\(prefix)Confidence", filename: "\(id.wireName).confidence.u8", mimeType: "application/octet-stream", data: artifact.confidenceUInt8)
            builder.addFile(name: "\(prefix)Metadata", filename: "\(id.wireName).metadata.json", mimeType: "application/json", data: try JSONEncoder().encode(artifact.metadata))
        }
    }
}

private struct LoadedSmarteeArtifacts {
    let rgbPNG: Data
    let depthFloat32: Data?
    let depthMetadata: Data?
    let figure8: Figure8CaptureBundle?
}

private struct SmarteeResponse: Decodable {
    let upperObj: String?
    let lowerObj: String?
    let upperTexture: String?
    let lowerTexture: String?
    let models: [SmarteeModel]?
    let lidarCaptureTag: String?
}

private struct SmarteeModel: Decodable {
    let id: String
    let upperObj: String
    let lowerObj: String
    let upperTexture: String?
    let lowerTexture: String?
}

private struct SmarteeErrorResponse: Decodable { let error: String? }

private struct SmarteeProgressResponse: Decodable { let stage: String? }

private struct Figure8UploadManifest: Encodable {
    struct Entry: Encodable {
        let id: String
        let depthCoverage: Float
        let blurScore: Float
        let poseSeparation: Float
    }
    let schemaVersion: Int
    let keyframes: [Entry]
}

struct SmarteeMultipartBuilder {
    private let boundary: String
    private(set) var body = Data()
    var contentType: String { "multipart/form-data; boundary=\(boundary)" }

    init(boundary: String) { self.boundary = boundary }

    mutating func addField(name: String, value: String) {
        append("--\(boundary)\r\n")
        append("Content-Disposition: form-data; name=\"\(name)\"\r\n\r\n")
        append("\(value)\r\n")
    }

    mutating func addFile(name: String, filename: String, mimeType: String, data: Data) {
        append("--\(boundary)\r\n")
        append("Content-Disposition: form-data; name=\"\(name)\"; filename=\"\(filename)\"\r\n")
        append("Content-Type: \(mimeType)\r\n\r\n")
        body.append(data)
        append("\r\n")
    }

    mutating func finalize() -> Data {
        append("--\(boundary)--\r\n")
        return body
    }

    private mutating func append(_ text: String) {
        body.append(text.data(using: .utf8)!)
    }
}
