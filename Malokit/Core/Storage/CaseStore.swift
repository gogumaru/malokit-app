import Foundation
import Observation
import UIKit

enum CaseStoreError: LocalizedError {
    case captureViewMismatch(captured: ToothView, destination: ToothView)
    case missingAnalysisResult

    var errorDescription: String? {
        switch self {
        case .captureViewMismatch(let captured, let destination):
            "The \(captured.title) capture cannot be saved as \(destination.title). Please retake it."
        case .missingAnalysisResult:
            "Run DHC and AC before saving a 3D reconstruction."
        }
    }
}

/// Persistence is a single JSON file plus one image folder per case.
///
/// SwiftData was considered and rejected on purpose: the result schema will
/// keep changing while the DHC, AC and 3D models are still being trained, and
/// a JSON snapshot tolerates that churn without a migration step. Swap this
/// class for a SwiftData ModelContainer once the schema settles.
@Observable
final class CaseStore {
    private(set) var cases: [CaseRecord] = []

    private let fileURL: URL
    private let writer: (Data, URL) throws -> Void

    init(
        fileURL: URL? = nil,
        writer: @escaping (Data, URL) throws -> Void = { data, url in
            try data.write(to: url, options: .atomic)
        }
    ) {
        let base = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
        self.fileURL = fileURL ?? base.appendingPathComponent("cases.json")
        self.writer = writer
        load()
    }

    // MARK: - Reading

    func record(_ id: UUID) -> CaseRecord? {
        cases.first { $0.id == id }
    }

    var sorted: [CaseRecord] {
        cases.sorted { $0.createdAt > $1.createdAt }
    }

    // MARK: - Writing

    @discardableResult
    func createCase(label: String? = nil) throws -> CaseRecord {
        let index = cases.count + 1
        let record = CaseRecord(label: label ?? "Case \(String(format: "%03d", index))")
        cases.append(record)
        do {
            try save()
        } catch {
            cases.removeAll { $0.id == record.id }
            throw error
        }
        return record
    }

    func update(_ record: CaseRecord) throws {
        try persist(record)
    }

    func attach(_ image: UIImage, to caseID: UUID, view: ToothView) throws {
        guard var record = record(caseID) else { return }
        let imageReplacement = try ImageStore.replace(image, caseID: caseID, view: view)
        var lidarRemoval: LiDARCaseRemoval?
        do {
            lidarRemoval = try LiDARCaseStore.stageRemoval(caseID: caseID, view: view)
            record.setFilename(imageReplacement.filename, for: view)
            record.setLiDARRecord(nil, for: view)
            record.status = record.isComplete ? .ready : .draft
            try persist(record)
            imageReplacement.commit()
            lidarRemoval?.commit()
        } catch {
            lidarRemoval?.rollback()
            imageReplacement.rollback()
            throw error
        }
    }

    /// Saves the Malokit JPEG and the independent lossless/depth bundle as
    /// one logical replacement for a view.
    func attach(_ capture: CapturedPhoto, to caseID: UUID, view: ToothView) throws {
        guard var record = record(caseID) else { return }
        guard capture.type.toothView == view else {
            throw CaseStoreError.captureViewMismatch(
                captured: capture.type.toothView,
                destination: view
            )
        }
        let replacement = try LiDARCaseStore.save(capture, caseID: caseID, view: view)
        var imageReplacement: ImageCaseReplacement?
        do {
            imageReplacement = try ImageStore.replace(capture.image, caseID: caseID, view: view)
            record.setFilename(imageReplacement?.filename, for: view)
            record.setLiDARRecord(replacement.record, for: view)
            record.status = record.isComplete ? .ready : .draft
            try persist(record)
            imageReplacement?.commit()
            replacement.commit()
        } catch {
            imageReplacement?.rollback()
            replacement.rollback()
            throw error
        }
    }

    func clearImage(_ view: ToothView, in caseID: UUID) throws {
        guard var record = record(caseID) else { return }
        let imageRemoval = try ImageStore.stageRemoval(caseID: caseID, view: view)
        var lidarRemoval: LiDARCaseRemoval?
        do {
            lidarRemoval = try LiDARCaseStore.stageRemoval(caseID: caseID, view: view)
            record.setFilename(nil, for: view)
            record.setLiDARRecord(nil, for: view)
            record.status = .draft
            try persist(record)
            imageRemoval.commit()
            lidarRemoval?.commit()
        } catch {
            lidarRemoval?.rollback()
            imageRemoval.rollback()
            throw error
        }
    }

    func attach(_ result: AnalysisResult, to caseID: UUID) throws {
        guard var record = record(caseID) else { return }
        record.result = result
        record.status = .complete
        try persist(record)
    }

    /// Replaces only the reconstruction portion of an existing analysis so a
    /// Smartee retry never discards completed DHC or AC results.
    func attach(_ reconstruction: ReconstructionRecord, to caseID: UUID) throws {
        guard var record = record(caseID) else { return }
        guard var result = record.result else {
            throw CaseStoreError.missingAnalysisResult
        }
        result.reconstruction = reconstruction
        result.model3DFilename = reconstruction.status == .complete
            ? reconstruction.upperOBJFilename
            : nil
        record.result = result
        record.status = .complete
        try persist(record)
    }

    /// Renames a case. Blank input is ignored rather than wiping the label,
    /// so a mis-tap in the rename field cannot leave a case with no name.
    func rename(_ id: UUID, to label: String) throws {
        guard var record = record(id) else { return }
        let trimmed = label.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        record.label = trimmed
        try persist(record)
    }

    func setStatus(_ status: CaseStatus, for caseID: UUID) throws {
        guard var record = record(caseID) else { return }
        record.status = status
        try persist(record)
    }

    func delete(_ id: UUID) throws {
        guard cases.contains(where: { $0.id == id }) else { return }
        let previousCases = cases
        let folderRemoval = try ImageStore.stageFolderRemoval(for: id)
        cases.removeAll { $0.id == id }
        do {
            try save()
            folderRemoval.commit()
        } catch {
            cases = previousCases
            folderRemoval.rollback()
            throw error
        }
    }

    /// Removes cases that were started and abandoned without a single photo.
    func pruneEmptyDrafts(keeping keepID: UUID? = nil) throws {
        let stale = cases.filter {
            $0.id != keepID && $0.status == .draft && $0.imageFilenames.isEmpty
        }
        for record in stale { try delete(record.id) }
    }

    // MARK: - Disk

    private func load() {
        guard let data = try? Data(contentsOf: fileURL) else { return }
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        cases = (try? decoder.decode([CaseRecord].self, from: data)) ?? []
    }

    private func persist(_ record: CaseRecord) throws {
        guard let index = cases.firstIndex(where: { $0.id == record.id }) else { return }
        let previous = cases[index]
        cases[index] = record
        do {
            try save()
        } catch {
            cases[index] = previous
            throw error
        }
    }

    private func save() throws {
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        let data = try encoder.encode(cases)
        try writer(data, fileURL)
    }
}
