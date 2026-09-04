import Foundation

// Explicit allowlist: no credential contents, dashboard tokens, output, or
// permission to apply changes is persisted. Paths are local/private metadata.
struct SavedSetup: Codable, Equatable {
    var target: String
    var targetHome: String
    var workspaces: [String]
    var personalSkills: Bool
    var workspaceSkills: Bool
}

struct SetupStore {
    let directory: URL
    private var file: URL { directory.appendingPathComponent("last-setup.json") }

    private func validate(_ url: URL, type: FileAttributeType) throws {
        let attributes = try FileManager.default.attributesOfItem(atPath: url.path)
        guard attributes[.type] as? FileAttributeType == type,
              let mode = attributes[.posixPermissions] as? NSNumber,
              mode.intValue & 0o077 == 0,
              let owner = attributes[.ownerAccountID] as? NSNumber,
              owner.uint32Value == getuid() else {
            throw CocoaError(.fileReadNoPermission)
        }
    }

    func load() throws -> SavedSetup? {
        guard FileManager.default.fileExists(atPath: directory.path) else { return nil }
        try validate(directory, type: .typeDirectory)
        guard FileManager.default.fileExists(atPath: file.path) else { return nil }
        try validate(file, type: .typeRegular)
        let attributes = try FileManager.default.attributesOfItem(atPath: file.path)
        guard (attributes[.size] as? NSNumber)?.intValue ?? Int.max <= 65_536 else {
            throw CocoaError(.fileReadTooLarge)
        }
        return try JSONDecoder().decode(SavedSetup.self, from: Data(contentsOf: file))
    }

    func save(_ setup: SavedSetup) throws {
        let manager = FileManager.default
        try manager.createDirectory(at: directory, withIntermediateDirectories: true,
                                    attributes: [.posixPermissions: 0o700])
        try validate(directory, type: .typeDirectory)
        let data = try JSONEncoder().encode(setup)
        guard data.count <= 65_536 else { throw CocoaError(.fileWriteOutOfSpace) }
        // Atomic rename preserves the previous setup until the new copy is
        // fully written. The temporary and final file are owner-only.
        let temporary = directory.appendingPathComponent(UUID().uuidString + ".tmp")
        guard manager.createFile(atPath: temporary.path, contents: nil,
                                 attributes: [.posixPermissions: 0o600]) else {
            throw CocoaError(.fileWriteUnknown)
        }
        defer { try? manager.removeItem(at: temporary) }
        let handle = try FileHandle(forWritingTo: temporary)
        do {
            try handle.write(contentsOf: data)
            try handle.synchronize()
            try handle.close()
        } catch {
            try? handle.close()
            throw error
        }
        guard rename(temporary.path, file.path) == 0 else {
            throw POSIXError(POSIXErrorCode(rawValue: errno) ?? .EIO)
        }
    }
}
