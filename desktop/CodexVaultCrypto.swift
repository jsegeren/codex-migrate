import CryptoKit
import Darwin
import Foundation
import Security

private let keychainService = "com.segeren.codex-vault"
private let formatVersion = 1

private struct Chunk: Codable {
    let id: String
    let size: Int
}

private struct StoredFile: Codable {
    let sha256: String
    let size: Int
    let chunks: [Chunk]
}

private struct ManifestFile: Codable {
    let collection: String
    let path: String
    let size: Int
    let mtime_ns: Int64
    let sha256: String
    let chunks: [Chunk]
}

private struct Manifest: Codable {
    let format: String
    let version: Int
    let snapshot_id: String
    let created_at: String
    let files: [ManifestFile]
}

private struct Verification: Codable {
    let snapshot_id: String
    let files: Int
    let chunks: Int
    let bytes: Int
}

private struct KeyResult: Codable {
    let key_id: String
    let recovery_key: String?
    let imported: Bool?
    let deleted: Bool?
}

private struct SealResult: Codable {
    let bytes: Int
    let sealed: Bool
}

private enum VaultError: Error, CustomStringConvertible {
    case message(String)

    var description: String {
        switch self {
        case .message(let text): return text
        }
    }
}

private func fail(_ text: String) -> Never {
    FileHandle.standardError.write(Data(("Codex Vault crypto: " + text + "\n").utf8))
    exit(70)
}

private func base64URL(_ data: Data) -> String {
    data.base64EncodedString()
        .replacingOccurrences(of: "+", with: "-")
        .replacingOccurrences(of: "/", with: "_")
        .replacingOccurrences(of: "=", with: "")
}

private func decodeBase64URL(_ text: String) throws -> Data {
    var encoded = text.replacingOccurrences(of: "-", with: "+")
        .replacingOccurrences(of: "_", with: "/")
    encoded += String(repeating: "=", count: (4 - encoded.count % 4) % 4)
    guard let result = Data(base64Encoded: encoded) else {
        throw VaultError.message("the recovery key is invalid")
    }
    return result
}

private func hex<D: Sequence>(_ data: D) -> String where D.Element == UInt8 {
    data.map { String(format: "%02x", $0) }.joined()
}

private func canonicalKeyID(_ value: String) throws -> String {
    guard let identifier = UUID(uuidString: value) else {
        throw VaultError.message("the key identifier is invalid")
    }
    return identifier.uuidString.lowercased()
}

private func keyQuery(_ keyID: String) -> [CFString: Any] {
    [
        kSecClass: kSecClassGenericPassword,
        kSecAttrService: keychainService,
        kSecAttrAccount: keyID,
    ]
}

private func storeKey(_ data: Data, keyID: String) throws {
    guard data.count == 32 else {
        throw VaultError.message("the encryption key has an invalid size")
    }
    var query = keyQuery(keyID)
    query[kSecValueData] = data
    query[kSecAttrAccessible] = kSecAttrAccessibleWhenUnlockedThisDeviceOnly
    let status = SecItemAdd(query as CFDictionary, nil)
    guard status == errSecSuccess else {
        if status == errSecDuplicateItem {
            throw VaultError.message("that key identifier already exists in Keychain")
        }
        throw VaultError.message("the encryption key could not be saved in Keychain")
    }
}

private func loadKey(_ keyID: String) throws -> SymmetricKey {
    var query = keyQuery(keyID)
    query[kSecReturnData] = true
    query[kSecMatchLimit] = kSecMatchLimitOne
    var item: CFTypeRef?
    let status = SecItemCopyMatching(query as CFDictionary, &item)
    guard status == errSecSuccess, let data = item as? Data, data.count == 32 else {
        throw VaultError.message("the encryption key is unavailable; import its recovery key on this Mac")
    }
    return SymmetricKey(data: data)
}

private func deleteKey(_ keyID: String) throws {
    let status = SecItemDelete(keyQuery(keyID) as CFDictionary)
    guard status == errSecSuccess || status == errSecItemNotFound else {
        throw VaultError.message("the encryption key could not be removed from Keychain")
    }
}

private func rawKey(_ key: SymmetricKey) -> Data {
    key.withUnsafeBytes { Data($0) }
}

private func encryptionKey(_ master: SymmetricKey) -> SymmetricKey {
    HKDF<SHA256>.deriveKey(
        inputKeyMaterial: master,
        salt: Data("codex-vault-v1".utf8),
        info: Data("authenticated-encryption".utf8),
        outputByteCount: 32
    )
}

private func identifierKey(_ master: SymmetricKey) -> SymmetricKey {
    HKDF<SHA256>.deriveKey(
        inputKeyMaterial: master,
        salt: Data("codex-vault-v1".utf8),
        info: Data("private-object-identifiers".utf8),
        outputByteCount: 32
    )
}

private func objectID(_ plaintext: Data, key: SymmetricKey) -> String {
    hex(HMAC<SHA256>.authenticationCode(for: plaintext, using: key))
}

private func chunkAAD(id: String, size: Int) -> Data {
    Data("codex-vault:chunk:v1:\(id):\(size)".utf8)
}

private func sealed(_ plaintext: Data, key: SymmetricKey, aad: Data) throws -> Data {
    let box = try AES.GCM.seal(plaintext, using: key, authenticating: aad)
    guard let combined = box.combined else {
        throw VaultError.message("authenticated encryption did not produce a combined payload")
    }
    return combined
}

private func opened(_ ciphertext: Data, key: SymmetricKey, aad: Data) throws -> Data {
    let box = try AES.GCM.SealedBox(combined: ciphertext)
    return try AES.GCM.open(box, using: key, authenticating: aad)
}

private func safeRegularFile(_ url: URL, maxBytes: Int) throws -> Data {
    let descriptor = open(url.path, O_RDONLY | O_NOFOLLOW | O_NONBLOCK)
    guard descriptor >= 0 else {
        throw VaultError.message("an encrypted Vault object is not a regular file")
    }
    let handle = FileHandle(fileDescriptor: descriptor, closeOnDealloc: true)
    var information = stat()
    guard fstat(descriptor, &information) == 0, (information.st_mode & S_IFMT) == S_IFREG,
          information.st_size >= 0, information.st_size <= maxBytes else {
        try? handle.close()
        throw VaultError.message("an encrypted Vault object has an invalid type or size")
    }
    return try handle.readToEnd() ?? Data()
}

private func objectURL(root: URL, id: String) throws -> URL {
    guard id.range(of: "^[0-9a-f]{64}$", options: .regularExpression) != nil else {
        throw VaultError.message("a Vault object identifier is invalid")
    }
    return root.appendingPathComponent(String(id.prefix(2)), isDirectory: true)
        .appendingPathComponent(String(id.dropFirst(2)) + ".cvchunk", isDirectory: false)
}

private func writeNew(_ data: Data, to destination: URL) throws {
    let manager = FileManager.default
    let parent = destination.deletingLastPathComponent()
    if !manager.fileExists(atPath: parent.path) {
        try manager.createDirectory(at: parent, withIntermediateDirectories: false,
                                    attributes: [.posixPermissions: 0o700])
    }
    let parentValues = try parent.resourceValues(forKeys: [.isDirectoryKey, .isSymbolicLinkKey])
    guard parentValues.isDirectory == true, parentValues.isSymbolicLink != true else {
        throw VaultError.message("an encrypted Vault object folder is unsafe")
    }
    if manager.fileExists(atPath: destination.path) {
        throw VaultError.message("refusing to replace an existing Vault object")
    }
    let temporary = destination.deletingLastPathComponent()
        .appendingPathComponent("." + UUID().uuidString + ".tmp")
    do {
        try data.write(to: temporary, options: [.withoutOverwriting])
        try manager.setAttributes([.posixPermissions: 0o600], ofItemAtPath: temporary.path)
        try manager.moveItem(at: temporary, to: destination)
    } catch {
        try? manager.removeItem(at: temporary)
        throw error
    }
}

private func storeChunk(_ plaintext: Data, root: URL,
                        encryption: SymmetricKey, identifiers: SymmetricKey) throws -> Chunk {
    let id = objectID(plaintext, key: identifiers)
    let destination = try objectURL(root: root, id: id)
    let aad = chunkAAD(id: id, size: plaintext.count)
    if FileManager.default.fileExists(atPath: destination.path) {
        let existing = try safeRegularFile(destination, maxBytes: plaintext.count + 64)
        let restored = try opened(existing, key: encryption, aad: aad)
        guard restored == plaintext else {
            throw VaultError.message("an existing encrypted object failed content verification")
        }
    } else {
        let ciphertext = try sealed(plaintext, key: encryption, aad: aad)
        try writeNew(ciphertext, to: destination)
        let restored = try opened(safeRegularFile(destination, maxBytes: plaintext.count + 64),
                                  key: encryption, aad: aad)
        guard restored == plaintext else {
            throw VaultError.message("a newly written encrypted object failed verification")
        }
    }
    return Chunk(id: id, size: plaintext.count)
}

private func JSON<T: Encodable>(_ value: T) throws -> Data {
    let encoder = JSONEncoder()
    encoder.outputFormatting = [.sortedKeys]
    return try encoder.encode(value)
}

private func printJSON<T: Encodable>(_ value: T) throws {
    FileHandle.standardOutput.write(try JSON(value))
    FileHandle.standardOutput.write(Data("\n".utf8))
}

private func argument(_ name: String, in arguments: [String]) throws -> String {
    guard let index = arguments.firstIndex(of: name), index + 1 < arguments.count else {
        throw VaultError.message("missing required argument \(name)")
    }
    return arguments[index + 1]
}

private func createKeyCommand() throws {
    let keyID = UUID().uuidString.lowercased()
    let key = SymmetricKey(size: .bits256)
    let material = rawKey(key)
    try storeKey(material, keyID: keyID)
    try printJSON(KeyResult(key_id: keyID,
                            recovery_key: "CV1-" + base64URL(material),
                            imported: nil, deleted: nil))
}

private func importKeyCommand(_ arguments: [String]) throws {
    let keyID = try canonicalKeyID(argument("--key-id", in: arguments))
    guard let input = String(data: FileHandle.standardInput.readDataToEndOfFile(), encoding: .utf8) else {
        throw VaultError.message("the recovery key could not be read")
    }
    let trimmed = input.trimmingCharacters(in: .whitespacesAndNewlines)
    guard trimmed.hasPrefix("CV1-") else {
        throw VaultError.message("the recovery key is invalid")
    }
    try storeKey(try decodeBase64URL(String(trimmed.dropFirst(4))), keyID: keyID)
    try printJSON(KeyResult(key_id: keyID, recovery_key: nil,
                            imported: true, deleted: nil))
}

private func exportKeyCommand(_ arguments: [String]) throws {
    let keyID = try canonicalKeyID(argument("--key-id", in: arguments))
    let key = try loadKey(keyID)
    try printJSON(KeyResult(key_id: keyID,
                            recovery_key: "CV1-" + base64URL(rawKey(key)),
                            imported: nil, deleted: nil))
}

private func deleteKeyCommand(_ arguments: [String]) throws {
    let keyID = try canonicalKeyID(argument("--key-id", in: arguments))
    try deleteKey(keyID)
    try printJSON(KeyResult(key_id: keyID, recovery_key: nil,
                            imported: nil, deleted: true))
}

private func storeChunksCommand(_ arguments: [String]) throws {
    let keyID = try canonicalKeyID(argument("--key-id", in: arguments))
    let root = URL(fileURLWithPath: try argument("--object-dir", in: arguments), isDirectory: true)
    let chunkSizeText = try argument("--chunk-size", in: arguments)
    guard let chunkSize = Int(chunkSizeText), chunkSize >= 64 * 1024,
          chunkSize <= 64 * 1024 * 1024 else {
        throw VaultError.message("the chunk size is outside the supported range")
    }
    let master = try loadKey(keyID)
    let encryption = encryptionKey(master)
    let identifiers = identifierKey(master)
    var digest = SHA256()
    var chunks: [Chunk] = []
    var total = 0
    while true {
        let data = try FileHandle.standardInput.read(upToCount: chunkSize) ?? Data()
        if data.isEmpty { break }
        digest.update(data: data)
        total += data.count
        chunks.append(try storeChunk(data, root: root, encryption: encryption,
                                     identifiers: identifiers))
    }
    try printJSON(StoredFile(sha256: hex(digest.finalize()), size: total, chunks: chunks))
}

private func sealManifestCommand(_ arguments: [String]) throws {
    let keyID = try canonicalKeyID(argument("--key-id", in: arguments))
    let output = URL(fileURLWithPath: try argument("--output", in: arguments))
    let snapshotID = try argument("--snapshot-id", in: arguments)
    guard UUID(uuidString: snapshotID) != nil else {
        throw VaultError.message("the snapshot identifier is invalid")
    }
    let plaintext = FileHandle.standardInput.readDataToEndOfFile()
    guard !plaintext.isEmpty, plaintext.count <= 128 * 1024 * 1024 else {
        throw VaultError.message("the snapshot manifest has an invalid size")
    }
    let aad = Data("codex-vault:manifest:v1:\(snapshotID.lowercased())".utf8)
    let ciphertext = try sealed(plaintext, key: encryptionKey(loadKey(keyID)), aad: aad)
    try writeNew(ciphertext, to: output)
    let restored = try opened(safeRegularFile(output, maxBytes: plaintext.count + 64),
                              key: encryptionKey(loadKey(keyID)), aad: aad)
    guard restored == plaintext else {
        throw VaultError.message("the encrypted manifest failed verification")
    }
    try printJSON(SealResult(bytes: plaintext.count, sealed: true))
}

private func verifyCommand(_ arguments: [String]) throws {
    let keyID = try canonicalKeyID(argument("--key-id", in: arguments))
    let root = URL(fileURLWithPath: try argument("--object-dir", in: arguments), isDirectory: true)
    let manifestURL = URL(fileURLWithPath: try argument("--manifest", in: arguments))
    let snapshotID = try argument("--snapshot-id", in: arguments).lowercased()
    guard UUID(uuidString: snapshotID) != nil else {
        throw VaultError.message("the snapshot identifier is invalid")
    }
    let master = try loadKey(keyID)
    let encryption = encryptionKey(master)
    let identifiers = identifierKey(master)
    let aad = Data("codex-vault:manifest:v1:\(snapshotID)".utf8)
    let manifestData = try opened(safeRegularFile(manifestURL, maxBytes: 128 * 1024 * 1024 + 64),
                                  key: encryption, aad: aad)
    let manifest = try JSONDecoder().decode(Manifest.self, from: manifestData)
    guard manifest.format == "codex-vault-snapshot", manifest.version == formatVersion,
          manifest.snapshot_id.lowercased() == snapshotID else {
        throw VaultError.message("the decrypted manifest has an unsupported identity or format")
    }
    var totalBytes = 0
    var totalChunks = 0
    for file in manifest.files {
        var digest = SHA256()
        var fileBytes = 0
        for chunk in file.chunks {
            guard chunk.size >= 0, chunk.size <= 64 * 1024 * 1024 else {
                throw VaultError.message("an encrypted chunk has an invalid plaintext size")
            }
            let url = try objectURL(root: root, id: chunk.id)
            let plaintext = try opened(try safeRegularFile(url, maxBytes: chunk.size + 64), key: encryption,
                                       aad: chunkAAD(id: chunk.id, size: chunk.size))
            guard plaintext.count == chunk.size,
                  objectID(plaintext, key: identifiers) == chunk.id else {
                throw VaultError.message("an encrypted chunk failed identity verification")
            }
            digest.update(data: plaintext)
            fileBytes += plaintext.count
            totalChunks += 1
        }
        guard fileBytes == file.size, hex(digest.finalize()) == file.sha256 else {
            throw VaultError.message("a restored transcript failed file verification")
        }
        totalBytes += fileBytes
    }
    try printJSON(Verification(snapshot_id: snapshotID, files: manifest.files.count,
                               chunks: totalChunks, bytes: totalBytes))
}

private func run() throws {
    let arguments = Array(CommandLine.arguments.dropFirst())
    guard let command = arguments.first else {
        throw VaultError.message("a command is required")
    }
    switch command {
    case "create-key": try createKeyCommand()
    case "import-key": try importKeyCommand(arguments)
    case "export-key": try exportKeyCommand(arguments)
    case "delete-key": try deleteKeyCommand(arguments)
    case "store-chunks": try storeChunksCommand(arguments)
    case "seal-manifest": try sealManifestCommand(arguments)
    case "verify": try verifyCommand(arguments)
    default: throw VaultError.message("the requested command is not supported")
    }
}

@main
private struct CodexVaultCrypto {
    static func main() {
        do {
            try run()
        } catch let error as VaultError {
            fail(error.description)
        } catch {
            fail("the authenticated operation failed; no snapshot was published")
        }
    }
}
