import Foundation
import Observation
import UIKit

/// Persistence is a single JSON file plus one image folder per case.
///
/// SwiftData was considered and rejected on purpose: the result schema will
/// keep changing while the DHC, AC and 3D models are still being trained, and
/// a JSON snapshot tolerates that churn without a migration step. Swap this
/// class for a SwiftData ModelContainer once the schema settles.
@Observable
final class CaseStore {
    private(set) var cases: [CaseRecord] = []

    private let fileURL: URL = {
        let base = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
        return base.appendingPathComponent("cases.json")
    }()

    init() { load() }

    // MARK: - Reading

    func record(_ id: UUID) -> CaseRecord? {
        cases.first { $0.id == id }
    }

    var sorted: [CaseRecord] {
        cases.sorted { $0.createdAt > $1.createdAt }
    }

    // MARK: - Writing

    @discardableResult
    func createCase(label: String? = nil) -> CaseRecord {
        let index = cases.count + 1
        let record = CaseRecord(label: label ?? "Case \(String(format: "%03d", index))")
        cases.append(record)
        save()
        return record
    }

    func update(_ record: CaseRecord) {
        guard let index = cases.firstIndex(where: { $0.id == record.id }) else { return }
        cases[index] = record
        save()
    }

    func attach(_ image: UIImage, to caseID: UUID, view: ToothView) {
        guard var record = record(caseID) else { return }
        do {
            let filename = try ImageStore.save(image, caseID: caseID, view: view)
            record.setFilename(filename, for: view)
            record.status = record.isComplete ? .ready : .draft
            update(record)
        } catch {
            assertionFailure("Could not write \(view.rawValue): \(error)")
        }
    }

    func clearImage(_ view: ToothView, in caseID: UUID) {
        guard var record = record(caseID) else { return }
        if let filename = record.filename(for: view) {
            try? FileManager.default.removeItem(
                at: ImageStore.url(caseID: caseID, filename: filename)
            )
        }
        record.setFilename(nil, for: view)
        record.status = .draft
        update(record)
    }

    func attach(_ result: AnalysisResult, to caseID: UUID) {
        guard var record = record(caseID) else { return }
        record.result = result
        record.status = .complete
        update(record)
    }

    func setStatus(_ status: CaseStatus, for caseID: UUID) {
        guard var record = record(caseID) else { return }
        record.status = status
        update(record)
    }

    func delete(_ id: UUID) {
        cases.removeAll { $0.id == id }
        ImageStore.deleteFolder(for: id)
        save()
    }

    /// Removes cases that were started and abandoned without a single photo.
    func pruneEmptyDrafts(keeping keepID: UUID? = nil) {
        let stale = cases.filter {
            $0.id != keepID && $0.status == .draft && $0.imageFilenames.isEmpty
        }
        for record in stale { delete(record.id) }
    }

    // MARK: - Disk

    private func load() {
        guard let data = try? Data(contentsOf: fileURL) else { return }
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        cases = (try? decoder.decode([CaseRecord].self, from: data)) ?? []
    }

    private func save() {
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        guard let data = try? encoder.encode(cases) else { return }
        try? data.write(to: fileURL, options: .atomic)
    }
}
