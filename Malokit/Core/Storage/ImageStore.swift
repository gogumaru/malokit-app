import UIKit

struct ImageCaseReplacement {
    let filename: String?
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

struct CaseFolderRemoval {
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

    static func replace(_ image: UIImage, caseID: UUID, view: ToothView) throws -> ImageCaseReplacement {
        let filename = "\(view.rawValue).jpg"
        guard let data = image.jpegData(compressionQuality: 0.92) else {
            throw StoreError.encodingFailed
        }
        let destination = url(caseID: caseID, filename: filename)
        let parent = destination.deletingLastPathComponent()
        let staging = parent.appendingPathComponent(".\(view.rawValue)-photo-staging-\(UUID().uuidString)")
        let backup = FileManager.default.fileExists(atPath: destination.path)
            ? parent.appendingPathComponent(".\(view.rawValue)-photo-backup-\(UUID().uuidString)")
            : nil
        try data.write(to: staging, options: .atomic)
        do {
            if let backup { try FileManager.default.moveItem(at: destination, to: backup) }
            try FileManager.default.moveItem(at: staging, to: destination)
        } catch {
            try? FileManager.default.removeItem(at: staging)
            if let backup, FileManager.default.fileExists(atPath: backup.path) {
                try? FileManager.default.moveItem(at: backup, to: destination)
            }
            throw error
        }
        return ImageCaseReplacement(filename: filename, destination: destination, backup: backup)
    }

    static func stageRemoval(caseID: UUID, view: ToothView) throws -> ImageCaseReplacement {
        let filename = "\(view.rawValue).jpg"
        let destination = url(caseID: caseID, filename: filename)
        guard FileManager.default.fileExists(atPath: destination.path) else {
            return ImageCaseReplacement(filename: nil, destination: destination, backup: nil)
        }
        let backup = destination.deletingLastPathComponent()
            .appendingPathComponent(".\(view.rawValue)-photo-backup-\(UUID().uuidString)")
        try FileManager.default.moveItem(at: destination, to: backup)
        return ImageCaseReplacement(filename: nil, destination: destination, backup: backup)
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

    static func stageFolderRemoval(for caseID: UUID) throws -> CaseFolderRemoval {
        let destination = root.appendingPathComponent(caseID.uuidString, isDirectory: true)
        guard FileManager.default.fileExists(atPath: destination.path) else {
            return CaseFolderRemoval(destination: destination, backup: nil)
        }
        let backup = root.appendingPathComponent(
            ".\(caseID.uuidString)-case-backup-\(UUID().uuidString)",
            isDirectory: true
        )
        try FileManager.default.moveItem(at: destination, to: backup)
        return CaseFolderRemoval(destination: destination, backup: backup)
    }

    enum StoreError: Error { case encodingFailed }
}
