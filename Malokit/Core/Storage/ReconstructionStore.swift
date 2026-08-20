import Foundation

enum ReconstructionStore {
    static func save(
        caseID: UUID,
        upperOBJ: String,
        lowerOBJ: String,
        upperTexture: Data?,
        lowerTexture: Data?,
        serverModelID: String,
        captureTag: String?
    ) throws -> ReconstructionRecord {
        let directory = ImageStore.folder(for: caseID)
            .appendingPathComponent("reconstruction", isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)

        let upperOBJName = "reconstruction/upper.obj"
        let lowerOBJName = "reconstruction/lower.obj"
        try Data(upperOBJ.utf8).write(
            to: ImageStore.folder(for: caseID).appendingPathComponent(upperOBJName),
            options: .atomic
        )
        try Data(lowerOBJ.utf8).write(
            to: ImageStore.folder(for: caseID).appendingPathComponent(lowerOBJName),
            options: .atomic
        )

        var upperTextureName: String?
        if let upperTexture {
            upperTextureName = "reconstruction/upper.png"
            try upperTexture.write(
                to: ImageStore.folder(for: caseID).appendingPathComponent(upperTextureName!),
                options: .atomic
            )
        }
        var lowerTextureName: String?
        if let lowerTexture {
            lowerTextureName = "reconstruction/lower.png"
            try lowerTexture.write(
                to: ImageStore.folder(for: caseID).appendingPathComponent(lowerTextureName!),
                options: .atomic
            )
        }

        return ReconstructionRecord(
            status: .complete,
            upperOBJFilename: upperOBJName,
            lowerOBJFilename: lowerOBJName,
            upperTextureFilename: upperTextureName,
            lowerTextureFilename: lowerTextureName,
            serverModelID: serverModelID,
            captureTag: captureTag,
            errorMessage: nil
        )
    }
}
