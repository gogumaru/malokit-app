import UIKit

/// Talks to the DHC pipeline server described in API_CONTRACT.md.
///
/// The five photos are posted as multipart form fields whose NAMES carry the
/// view identity. The server is explicitly told which photo is which and never
/// re-guesses from image content, which is the trap the export brief warns
/// about: a mirrored or mislabelled occlusal view silently corrupts every
/// downstream measurement.
struct RemoteEngine: AnalysisEngine {
    let settings: ServerSettings

    var name: String { "DHC server" }

    /// The server computes DHC and Angle only. It does not produce an aesthetic
    /// component or a 3D mesh, so those stages are not advertised to the user
    /// as if something were running.
    var stages: [AnalysisStage] { [.preprocess, .angle, .dhc] }

    /// Form field name for each view, per the contract. Explicit, never derived.
    static let fieldNames: [ToothView: String] = [
        .front:       "frontal",
        .right:       "lateral_kanan",
        .left:        "lateral_kiri",
        .maxillary:   "oklusal_atas",
        .mandibular:  "oklusal_bawah"
    ]

    func analyze(
        _ input: AnalysisInput,
        onStage: @escaping @MainActor (AnalysisStage) -> Void
    ) async throws -> AnalysisResult {
        guard input.isComplete else {
            throw AnalysisError.incompleteInput(
                ToothView.captureOrder.filter { input.images[$0] == nil }
            )
        }
        guard let endpoint = settings.url(path: "/v1/analyze") else {
            throw AnalysisError.engineFailed(stage: .preprocess, reason: "Server address is not valid.")
        }

        // Build the upload.
        onStage(.preprocess)
        var builder = MultipartBuilder()
        for view in ToothView.captureOrder {
            guard let field = Self.fieldNames[view] else { continue }
            guard let data = jpegData(for: view, in: input) else {
                throw AnalysisError.engineFailed(
                    stage: .preprocess,
                    reason: "Could not read the \(view.title) photo."
                )
            }
            builder.addFile(name: field, filename: "\(field).jpg", mimeType: "image/jpeg", data: data)
        }
        builder.addField(name: "patient_id", value: input.caseID.uuidString)

        var request = URLRequest(url: endpoint)
        request.httpMethod = "POST"
        request.setValue(builder.contentType, forHTTPHeaderField: "Content-Type")
        if !settings.apiKey.isEmpty {
            request.setValue(settings.apiKey, forHTTPHeaderField: "X-API-Key")
        }
        request.httpBody = builder.finalize()
        request.timeoutInterval = 60

        // Send. The server reports no sub-progress, so the request itself is
        // shown as the DHC stage rather than faking finer granularity.
        onStage(.angle)
        onStage(.dhc)

        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await URLSession.shared.data(for: request)
        } catch {
            throw AnalysisError.engineFailed(
                stage: .dhc,
                reason: "Could not reach the server. \(error.localizedDescription)"
            )
        }

        guard let http = response as? HTTPURLResponse else {
            throw AnalysisError.engineFailed(stage: .dhc, reason: "Unexpected response from server.")
        }

        guard http.statusCode == 200 else {
            throw AnalysisError.engineFailed(
                stage: .dhc,
                reason: ServerError.describe(data: data, statusCode: http.statusCode)
            )
        }

        let decoder = JSONDecoder()
        let payload: AnalyzeResponse
        do {
            payload = try decoder.decode(AnalyzeResponse.self, from: data)
        } catch {
            throw AnalysisError.engineFailed(
                stage: .report,
                reason: "The server replied in an unexpected shape. \(error.localizedDescription)"
            )
        }

        return AnalysisResult(
            angle: payload.angle,
            dhc: payload.dhc,
            ac: ACResult(
                score: 0,
                confidence: 0,
                nearestReference: 0,
                isScorable: false,
                rejectionReason: "This engine does not produce an aesthetic component score."
            ),
            model3DFilename: nil,       // separate pipeline, not this server
            narrative: nil,             // report LLM not wired yet
            generatedAt: .now,
            engineName: payload.engineVersion ?? "DHC server"
        )
    }

    /// Reads the stored JPEG bytes straight off disk.
    ///
    /// The file is already upright, already resized, and already JPEG, so
    /// re-encoding the in-memory UIImage would be a second lossy generation for
    /// no gain. Those artifacts land on tooth edges, which is exactly what the
    /// segmentation model measures. Falls back to encoding only if the file is
    /// somehow unreadable.
    ///
    /// The server also accepts PNG, WebP and HEIC, but the app always stores
    /// JPEG, so that is what goes over the wire.
    private func jpegData(for view: ToothView, in input: AnalysisInput) -> Data? {
        let url = ImageStore.url(caseID: input.caseID, filename: "\(view.rawValue).jpg")
        if let data = try? Data(contentsOf: url), !data.isEmpty {
            return data
        }
        return input.images[view]?.jpegData(compressionQuality: 0.9)
    }

    /// Quick reachability check for the settings screen.
    ///
    /// The server reports which model weights are missing, which is the
    /// difference between "the server is up but cannot actually analyse
    /// anything" and "the server is ready". Surfacing that here means a
    /// misconfigured server is caught in Settings rather than halfway through
    /// a patient's analysis.
    static func checkHealth(settings: ServerSettings) async -> HealthReport {
        guard let url = settings.url(path: "/v1/health") else {
            return HealthReport(ok: false, message: "Server address is not valid.")
        }
        var request = URLRequest(url: url)
        request.timeoutInterval = 8
        if !settings.apiKey.isEmpty {
            request.setValue(settings.apiKey, forHTTPHeaderField: "X-API-Key")
        }

        do {
            let (data, response) = try await URLSession.shared.data(for: request)
            guard let http = response as? HTTPURLResponse else {
                return HealthReport(ok: false, message: "Unexpected response.")
            }
            guard http.statusCode == 200 else {
                return HealthReport(ok: false, message: "Server replied \(http.statusCode).")
            }

            let health = try? JSONDecoder().decode(HealthResponse.self, from: data)
            let missing = health?.missingModels ?? []

            if health?.stub == true {
                return HealthReport(
                    ok: true,
                    message: "Reachable, running in stub mode. Responses are a fixed example, not real measurements."
                )
            }
            if !missing.isEmpty {
                return HealthReport(
                    ok: false,
                    message: "Reachable, but \(missing.count) model weight\(missing.count == 1 ? "" : "s") missing: \(missing.joined(separator: ", ")). Analysis will fail."
                )
            }
            return HealthReport(ok: true, message: "Reachable. \(health?.status ?? "Ready") ")
        } catch {
            return HealthReport(ok: false, message: "Not reachable. \(error.localizedDescription)")
        }
    }
}

// MARK: - Wire types

/// Mirrors the top level of the contract response. Kept separate from the
/// domain model so a server-side rename shows up as a decode error here rather
/// than as a silently empty screen.
private struct AnalyzeResponse: Decodable {
    let engineVersion: String?
    let angle: AngleReading
    let dhc: DHCResult

    enum CodingKeys: String, CodingKey {
        case engineVersion = "engine_version"
        case angle
        // DHC parameters live at the top level of the response, not nested,
        // so they are lifted into DHCResult here.
        case overjet, overbite, missing, crowding, overlays
        case anteriorCrossbite = "anterior_crossbite"
        case posteriorCrossbite = "crossbite_posterior"
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        engineVersion = try c.decodeIfPresent(String.self, forKey: .engineVersion)
        angle = try c.decode(AngleReading.self, forKey: .angle)
        var built = DHCResult(
                    overjet: try c.decode(Reading.self, forKey: .overjet),
                    overbite: try c.decode(Reading.self, forKey: .overbite),
                    anteriorCrossbite: try c.decode(Reading.self, forKey: .anteriorCrossbite),
                    posteriorCrossbite: try c.decode(CrossbitePosterior.self, forKey: .posteriorCrossbite),
                    missing: try c.decode(MissingReading.self, forKey: .missing),
                    crowding: try c.decode(CrowdingReading.self, forKey: .crowding)
        )
        built.overlays = try c.decodeIfPresent(OverlaySet.self, forKey: .overlays)
        dhc = built
    }
}

struct HealthReport {
    let ok: Bool
    let message: String
}

/// Shape of GET /v1/health. The exact field names were not pinned down in the
/// contract, so every key is optional and a decode miss degrades to a plain
/// "reachable" rather than to a false alarm.
private struct HealthResponse: Decodable {
    let status: String?
    let stub: Bool?
    let missingModels: [String]?

    enum CodingKeys: String, CodingKey {
        case status, stub
        case missingModels = "missing_models"
    }
}

/// The contract's error bodies for 400 and 500.
private struct ServerError: Decodable {
    let error: String?
    let message: String?
    let missing: [String]?

    static func describe(data: Data, statusCode: Int) -> String {
        guard let body = try? JSONDecoder().decode(ServerError.self, from: data) else {
            return "Server replied \(statusCode)."
        }
        if let missing = body.missing, !missing.isEmpty {
            return "Server is missing photos: \(missing.joined(separator: ", "))."
        }
        return body.message ?? body.error ?? "Server replied \(statusCode)."
    }
}

// MARK: - Multipart

struct MultipartBuilder {
    private let boundary = "Boundary-\(UUID().uuidString)"
    private var body = Data()

    var contentType: String { "multipart/form-data; boundary=\(boundary)" }

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

    private mutating func append(_ string: String) {
        if let data = string.data(using: .utf8) { body.append(data) }
    }
}
