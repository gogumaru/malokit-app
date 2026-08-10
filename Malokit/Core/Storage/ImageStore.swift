import UIKit

/// Photographs live on disk, never inside the case JSON. One folder per case
/// keeps deletion trivial and keeps the metadata file small enough to rewrite
/// on every edit without thinking about it.
enum ImageStore {
    static var root: URL {
        let base = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
        let dir = base.appendingPathComponent("Cases", isDirectory: true)
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        return dir
    }

    static func folder(for caseID: UUID) -> URL {
        let dir = root.appendingPathComponent(caseID.uuidString, isDirectory: true)
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        return dir
    }

    static func url(caseID: UUID, filename: String) -> URL {
        folder(for: caseID).appendingPathComponent(filename)
    }

    @discardableResult
    static func save(_ image: UIImage, caseID: UUID, view: ToothView) throws -> String {
        let filename = "\(view.rawValue).jpg"
        guard let data = image.jpegData(compressionQuality: 0.92) else {
            throw StoreError.encodingFailed
        }
        try data.write(to: url(caseID: caseID, filename: filename), options: .atomic)
        return filename
    }

    static func load(caseID: UUID, filename: String) -> UIImage? {
        UIImage(contentsOfFile: url(caseID: caseID, filename: filename).path)
    }

    static func load(caseID: UUID, view: ToothView) -> UIImage? {
        load(caseID: caseID, filename: "\(view.rawValue).jpg")
    }

    static func deleteFolder(for caseID: UUID) {
        try? FileManager.default.removeItem(at: folder(for: caseID))
    }

    enum StoreError: Error { case encodingFailed }
}
