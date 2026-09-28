import CryptoKit
import Compression
import Darwin
import Foundation
import LocalAuthentication
import Security

private let keychainService = "com.segeren.codex-vault"
private let hostedDeviceService = "com.segeren.codex-vault-hosted-device"
private let keychainInteractionError = "Vault could not access its key without interactive Keychain approval. No backup was published. Contact support if this persists"
private let formatVersion = 1
private let snapshotFormatVersion = 3

private struct Chunk: Codable {
    let id: String
    let size: Int
    let encoding: String?
}

private struct StoredFile: Codable {
    let sha256: String
    let size: Int
    let chunks: [Chunk]
}

private struct RemoteAwareStoredFile: Codable {
    let sha256: String
    let size: Int
    let chunks: [Chunk]
    let local_ids: [String]
    let remote_ids: [String]
}

private struct KnownObjectIDs: Decodable {
    let version: Int
    let ids: [String]
}

private struct PlannedChunk: Codable {
    let raw_id: String
    let compressed_id: String?
    let size: Int
    let compressed_bytes: Int?
}

private struct PlannedFile: Codable {
    let sha256: String
    let size: Int
    let chunks: [PlannedChunk]
}

private struct ManifestFile: Codable {
    let collection: String
    let path: String
    let size: Int
    let mtime_ns: Int64
    let sha256: String
    let chunks: [Chunk]
    let thread_id: String?
    let identity_state: String?
    let titles: [String]?
    let records: Int?
    let assistant_messages: Int?
    let user_messages: Int?
    let at_risk: Bool?
}

private struct Manifest: Codable {
    let format: String
    let version: Int
    let snapshot_id: String
    let created_at: String
    let files: [ManifestFile]
}

private struct CatalogFile: Codable {
    let collection: String
    let path: String
    let size: Int
    let sha256: String
    let thread_id: String?
    let identity_state: String?
    let titles: [String]
    let records: Int?
    let assistant_messages: Int?
    let user_messages: Int?
    let at_risk: Bool?
}

private struct Catalog: Codable {
    let snapshot_id: String
    let version: Int
    let files: [CatalogFile]
}

private struct Verification: Codable {
    let snapshot_id: String
    let files: Int
    let chunks: Int
    let bytes: Int
}

private struct EncryptedInventory: Codable {
    let snapshot_id: String
    let chunk_ids: [String]
    let chunk_sha256: [String: String]
    let manifest_sha256: String
}

private struct RestoreResult: Codable {
    let snapshot_id: String
    let files: Int
    let bytes: Int
    let output: String
}

private struct KeyResult: Codable {
    let key_id: String
    let recovery_key: String?
    let imported: Bool?
    let deleted: Bool?
}

private struct HostedDeviceResult: Codable {
    let device_id: String
    let token_hash: String
    let token: String?
}

private struct HostedDeviceDeleteResult: Codable {
    let device_id: String
    let deleted: Bool
}

private struct HostedDeviceListResult: Codable {
    let devices: [HostedDeviceResult]
}

private struct LegacyInspection: Codable {
    let key_id: String
    let recovery_key: String?
}

private struct SealResult: Codable {
    let bytes: Int
    let sealed: Bool
}

private struct ManifestFingerprint: Codable {
    let snapshot_id: String
    let plaintext_sha256: String
    let ciphertext_sha256: String
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

private func legacyKeyQuery(_ keyID: String) -> [CFString: Any] {
    // Backup and scheduled runs must fail closed rather than summon a password
    // dialog from a helper process. The app can report the failure explicitly.
    let authentication = LAContext()
    authentication.interactionNotAllowed = true
    return [
        kSecClass: kSecClassGenericPassword,
        kSecAttrService: keychainService,
        kSecAttrAccount: keyID,
        kSecUseAuthenticationContext: authentication,
    ]
}

private func keyQuery(_ keyID: String) -> [CFString: Any] {
    var query = legacyKeyQuery(keyID)
#if !CODEX_VAULT_TEST_LEGACY_KEYCHAIN
    // The accessibility class below has no device-only meaning for a legacy
    // file-based macOS Keychain item. Release builds require a provisioned,
    // signed helper with this exact keychain access group.
    query[kSecUseDataProtectionKeychain] = true
    query[kSecAttrAccessGroup] = "P9J3JK79KQ.com.segeren.codex-migrate.vault-crypto"
#endif
    return query
}

private func hostedDeviceQuery(_ deviceID: String) -> [CFString: Any] {
    var query = legacyKeyQuery(deviceID)
    query[kSecAttrService] = hostedDeviceService
#if !CODEX_VAULT_TEST_LEGACY_KEYCHAIN
    query[kSecUseDataProtectionKeychain] = true
    query[kSecAttrAccessGroup] = "P9J3JK79KQ.com.segeren.codex-migrate.vault-crypto"
#endif
    return query
}

private func hostedDeviceHash(_ token: String) -> String {
    var bytes = Data("codex-vault-hosted-session-v1\0".utf8)
    bytes.append(Data(token.utf8))
    return hex(SHA256.hash(data: bytes))
}

private func hostedDeviceToken(_ deviceID: String) throws -> String {
    var query = hostedDeviceQuery(deviceID)
    query[kSecReturnData] = true
    query[kSecMatchLimit] = kSecMatchLimitOne
    var item: CFTypeRef?
    let status = SecItemCopyMatching(query as CFDictionary, &item)
    if status == errSecInteractionNotAllowed {
        throw VaultError.message("the hosted device credential needs interactive Keychain approval")
    }
    guard status == errSecSuccess, let data = item as? Data,
          let token = String(data: data, encoding: .utf8),
          token.range(of: "^hv1_[A-Za-z0-9_-]{43}$", options: .regularExpression) != nil else {
        throw VaultError.message("the hosted device credential is unavailable")
    }
    return token
}

private func createHostedDeviceCommand() throws {
    let deviceID = UUID().uuidString.lowercased()
    let token = "hv1_" + base64URL(rawKey(SymmetricKey(size: .bits256)))
    var query = hostedDeviceQuery(deviceID)
    query[kSecValueData] = Data(token.utf8)
    query[kSecAttrAccessible] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
    let status = SecItemAdd(query as CFDictionary, nil)
    guard status == errSecSuccess else {
        throw VaultError.message("the hosted device credential could not be saved in Keychain")
    }
    guard try hostedDeviceToken(deviceID) == token else {
        throw VaultError.message("the hosted device credential could not be verified")
    }
    // This output is safe for enrollment requests. The bearer token stays in
    // Keychain and never enters argv, a browser response, or this JSON result.
    try printJSON(HostedDeviceResult(device_id: deviceID,
                                     token_hash: hostedDeviceHash(token),
                                     token: nil))
}

private func readHostedDeviceCommand(_ arguments: [String]) throws {
    let deviceID = try canonicalKeyID(argument("--device-id", in: arguments))
    let token = try hostedDeviceToken(deviceID)
    // A future authenticated native transport may consume this over a private
    // pipe. Never display, log, or send this bearer secret through browser JS.
    try printJSON(HostedDeviceResult(device_id: deviceID,
                                     token_hash: hostedDeviceHash(token),
                                     token: token))
}

private func listHostedDevicesCommand() throws {
    var query = hostedDeviceQuery("unused")
    query.removeValue(forKey: kSecAttrAccount)
    query[kSecReturnAttributes] = true
    query[kSecMatchLimit] = kSecMatchLimitAll
    var item: CFTypeRef?
    let status = SecItemCopyMatching(query as CFDictionary, &item)
    if status == errSecItemNotFound {
        try printJSON(HostedDeviceListResult(devices: []))
        return
    }
    guard status == errSecSuccess, let entries = item as? [[String: Any]] else {
        throw VaultError.message("the hosted device credentials could not be listed")
    }
    let devices = try entries.map { entry -> HostedDeviceResult in
        guard let rawID = entry[kSecAttrAccount as String] as? String else {
            throw VaultError.message("a hosted device credential has an invalid identifier")
        }
        let deviceID = try canonicalKeyID(rawID)
        let token = try hostedDeviceToken(deviceID)
        return HostedDeviceResult(device_id: deviceID,
                                  token_hash: hostedDeviceHash(token), token: nil)
    }.sorted { $0.device_id < $1.device_id }
    try printJSON(HostedDeviceListResult(devices: devices))
}

private func deleteHostedDeviceCommand(_ arguments: [String]) throws {
    let deviceID = try canonicalKeyID(argument("--device-id", in: arguments))
    let status = SecItemDelete(hostedDeviceQuery(deviceID) as CFDictionary)
    guard status == errSecSuccess || status == errSecItemNotFound else {
        throw VaultError.message("the hosted device credential could not be removed")
    }
    try printJSON(HostedDeviceDeleteResult(device_id: deviceID, deleted: true))
}

private func storeKey(_ data: Data, keyID: String) throws {
    guard data.count == 32 else {
        throw VaultError.message("the encryption key has an invalid size")
    }
    var query = keyQuery(keyID)
    query[kSecValueData] = data
    // Daily LaunchAgent backups may run while the screen is locked, but never
    // before the user has unlocked the Mac once after a restart.
    query[kSecAttrAccessible] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
    let status = SecItemAdd(query as CFDictionary, nil)
    guard status == errSecSuccess else {
        if status == errSecInteractionNotAllowed {
            throw VaultError.message(keychainInteractionError)
        }
        if status == errSecDuplicateItem {
            throw VaultError.message("that key identifier already exists in Keychain")
        }
        throw VaultError.message("the encryption key could not be saved in Keychain")
    }
}

private func loadKey(_ keyID: String) throws -> SymmetricKey {
    func read(_ base: [CFString: Any]) -> (OSStatus, Data?) {
        var query = base
        query[kSecReturnData] = true
        query[kSecMatchLimit] = kSecMatchLimitOne
        var item: CFTypeRef?
        let status = SecItemCopyMatching(query as CFDictionary, &item)
        return (status, item as? Data)
    }
    let (status, data) = read(keyQuery(keyID))
    if status == errSecInteractionNotAllowed {
        throw VaultError.message(keychainInteractionError)
    }
#if !CODEX_VAULT_TEST_LEGACY_KEYCHAIN
    // A new bundle identifier cannot silently read the old helper's legacy
    // Keychain ACL, even when both binaries are signed by the same team. Ask
    // the separately signed, same-designated-requirement legacy helper over a
    // private pipe; never put key material in argv, a file, or diagnostics.
    if status == errSecSuccess || status == errSecItemNotFound {
        let legacy = try inspectLegacyKey(keyID)
        if status == errSecSuccess, let data = data, data.count == 32 {
            if let legacy = legacy {
                guard legacy == data else {
                    throw VaultError.message("Vault found conflicting Keychain copies; no backup was published")
                }
                try removeLegacyKey(keyID)
            }
            return SymmetricKey(data: data)
        }
        if status == errSecItemNotFound, let legacy = legacy {
            try storeKey(legacy, keyID: keyID)
            let (newStatus, newData) = read(keyQuery(keyID))
            guard newStatus == errSecSuccess, newData == legacy else {
                throw VaultError.message("Vault could not verify the protected Keychain copy")
            }
            try removeLegacyKey(keyID)
            return SymmetricKey(data: legacy)
        }
    }
#endif
    guard status == errSecSuccess, let data = data, data.count == 32 else {
        throw VaultError.message("the encryption key is unavailable; import its recovery key on this Mac")
    }
    return SymmetricKey(data: data)
}

#if !CODEX_VAULT_TEST_LEGACY_KEYCHAIN
private func legacyHelper() throws -> URL {
    let outerContents = Bundle.main.bundleURL.deletingLastPathComponent()
        .deletingLastPathComponent()
    let helper = outerContents.appendingPathComponent("Resources/CodexVaultCrypto")
    guard FileManager.default.isExecutableFile(atPath: helper.path) else {
        throw VaultError.message("Vault's signed legacy-key helper is missing")
    }
    var code: SecStaticCode?
    var requirement: SecRequirement?
    let expected = "identifier CodexVaultCrypto and anchor apple generic and certificate leaf[subject.OU] = P9J3JK79KQ"
    guard SecStaticCodeCreateWithPath(helper as CFURL, SecCSFlags(rawValue: 0), &code) == errSecSuccess,
          SecRequirementCreateWithString(expected as CFString, SecCSFlags(rawValue: 0),
                                         &requirement) == errSecSuccess,
          let code = code, let requirement = requirement,
          SecStaticCodeCheckValidity(code, SecCSFlags(rawValue: kSecCSStrictValidate),
                                     requirement) == errSecSuccess else {
        throw VaultError.message("Vault's legacy-key helper signature is invalid")
    }
    return helper
}

private func runLegacy(_ arguments: [String]) throws -> Data {
    let process = Process()
    process.executableURL = try legacyHelper()
    process.arguments = arguments
    let output = Pipe()
    process.standardOutput = output
    process.standardError = FileHandle.nullDevice
    do { try process.run() } catch {
        throw VaultError.message("Vault could not start its signed legacy-key helper")
    }
    let deadline = Date().addingTimeInterval(15)
    while process.isRunning && Date() < deadline {
        Thread.sleep(forTimeInterval: 0.05)
    }
    if process.isRunning {
        process.terminate()
        process.waitUntilExit()
        throw VaultError.message("Vault's legacy-key check timed out without changing the backup")
    }
    guard process.terminationStatus == 0 else {
        throw VaultError.message("Vault could not safely inspect its old Keychain entry")
    }
    return output.fileHandleForReading.readDataToEndOfFile()
}

private func inspectLegacyKey(_ keyID: String) throws -> Data? {
    let output = try runLegacy(["inspect-key", "--key-id", keyID])
    guard let result = try? JSONDecoder().decode(LegacyInspection.self, from: output),
          result.key_id == keyID else {
        throw VaultError.message("Vault's legacy-key result was invalid")
    }
    guard let recovery = result.recovery_key else { return nil }
    guard recovery.hasPrefix("CV1-") else {
        throw VaultError.message("Vault's old Keychain entry had an invalid format")
    }
    let material = try decodeBase64URL(String(recovery.dropFirst(4)))
    guard material.count == 32 else {
        throw VaultError.message("Vault's old Keychain entry had an invalid size")
    }
    return material
}

private func removeLegacyKey(_ keyID: String) throws {
    _ = try runLegacy(["delete-key", "--key-id", keyID])
    guard try inspectLegacyKey(keyID) == nil else {
        throw VaultError.message("Vault could not verify removal of its old Keychain copy")
    }
}
#endif

private func deleteKey(_ keyID: String) throws {
#if !CODEX_VAULT_TEST_LEGACY_KEYCHAIN
    if try inspectLegacyKey(keyID) != nil {
        try removeLegacyKey(keyID)
    }
#endif
    let status = SecItemDelete(keyQuery(keyID) as CFDictionary)
    if status == errSecInteractionNotAllowed {
        throw VaultError.message(keychainInteractionError)
    }
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

private func compressedObjectID(_ plaintext: Data, key: SymmetricKey) -> String {
    let compressedIdentifiers = HKDF<SHA256>.deriveKey(
        inputKeyMaterial: key,
        salt: Data("codex-vault-lzfse-v1".utf8),
        info: Data("private-compressed-object-identifiers".utf8),
        outputByteCount: 32
    )
    return objectID(plaintext, key: compressedIdentifiers)
}

private func chunkAAD(id: String, size: Int) -> Data {
    Data("codex-vault:chunk:v1:\(id):\(size)".utf8)
}

private func compressedChunkAAD(id: String, size: Int) -> Data {
    Data("codex-vault:chunk:lzfse:v1:\(id):\(size)".utf8)
}

private func compressChunk(_ plaintext: Data) -> Data? {
    guard plaintext.count >= 1024 else { return nil }
    let capacity = plaintext.count
    var encoded = Data(count: capacity)
    let count = encoded.withUnsafeMutableBytes { destination in
        plaintext.withUnsafeBytes { source in
            compression_encode_buffer(
                destination.bindMemory(to: UInt8.self).baseAddress!, capacity,
                source.bindMemory(to: UInt8.self).baseAddress!, plaintext.count,
                nil, COMPRESSION_LZFSE)
        }
    }
    guard count > 0, count + 64 < plaintext.count else { return nil }
    encoded.removeSubrange(count..<capacity)
    return encoded
}

private func decompressChunk(_ encoded: Data, expectedSize: Int) throws -> Data {
    guard !encoded.isEmpty, expectedSize > 0, expectedSize <= 64 * 1024 * 1024 else {
        throw VaultError.message("an encrypted chunk has an invalid decoded size")
    }
    var decoded = Data(count: expectedSize)
    let count = decoded.withUnsafeMutableBytes { destination in
        encoded.withUnsafeBytes { source in
            compression_decode_buffer(
                destination.bindMemory(to: UInt8.self).baseAddress!, expectedSize,
                source.bindMemory(to: UInt8.self).baseAddress!, encoded.count,
                nil, COMPRESSION_LZFSE)
        }
    }
    guard count == expectedSize else {
        throw VaultError.message("an encrypted chunk could not be decompressed exactly")
    }
    return decoded
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

private func readChunk(_ chunk: Chunk, root: URL,
                       encryption: SymmetricKey, identifiers: SymmetricKey,
                       onCiphertext: ((String, Data) throws -> Void)? = nil) throws -> Data {
    guard chunk.size >= 0, chunk.size <= 64 * 1024 * 1024 else {
        throw VaultError.message("an encrypted chunk has an invalid plaintext size")
    }
    let url = try objectURL(root: root, id: chunk.id)
    let ciphertext = try safeRegularFile(url, maxBytes: chunk.size + 64)
    let plaintext: Data
    let expectedID: String
    switch chunk.encoding {
    case nil:
        plaintext = try opened(ciphertext, key: encryption,
                               aad: chunkAAD(id: chunk.id, size: chunk.size))
        expectedID = objectID(plaintext, key: identifiers)
    case "lzfse":
        let encoded = try opened(ciphertext, key: encryption,
                                 aad: compressedChunkAAD(id: chunk.id, size: chunk.size))
        plaintext = try decompressChunk(encoded, expectedSize: chunk.size)
        expectedID = compressedObjectID(plaintext, key: identifiers)
    default:
        throw VaultError.message("an encrypted chunk uses an unsupported encoding")
    }
    guard plaintext.count == chunk.size, expectedID == chunk.id else {
        throw VaultError.message("an encrypted chunk failed identity verification")
    }
    try onCiphertext?(chunk.id, ciphertext)
    return plaintext
}

private func storeChunk(_ plaintext: Data, root: URL,
                        encryption: SymmetricKey, identifiers: SymmetricKey) throws -> Chunk {
    let rawID = objectID(plaintext, key: identifiers)
    let raw = Chunk(id: rawID, size: plaintext.count, encoding: nil)
    let rawURL = try objectURL(root: root, id: rawID)
    if FileManager.default.fileExists(atPath: rawURL.path) {
        guard try readChunk(raw, root: root, encryption: encryption, identifiers: identifiers)
                == plaintext else {
            throw VaultError.message("an existing encrypted object failed content verification")
        }
        return raw
    }
    let compressed = compressChunk(plaintext)
    let chunk = compressed == nil ? raw : Chunk(
        id: compressedObjectID(plaintext, key: identifiers),
        size: plaintext.count, encoding: "lzfse")
    let destination = try objectURL(root: root, id: chunk.id)
    if FileManager.default.fileExists(atPath: destination.path) {
        guard try readChunk(chunk, root: root, encryption: encryption, identifiers: identifiers)
                == plaintext else {
            throw VaultError.message("an existing encrypted object failed content verification")
        }
    } else {
        let aad = chunk.encoding == nil
            ? chunkAAD(id: chunk.id, size: chunk.size)
            : compressedChunkAAD(id: chunk.id, size: chunk.size)
        try writeNew(try sealed(compressed ?? plaintext, key: encryption, aad: aad),
                     to: destination)
        guard try readChunk(chunk, root: root, encryption: encryption, identifiers: identifiers)
                == plaintext else {
            throw VaultError.message("a newly written encrypted object failed verification")
        }
    }
    return chunk
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
    guard rawKey(try loadKey(keyID)) == material else {
        throw VaultError.message("the new Vault key could not be verified")
    }
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
    let material = try decodeBase64URL(String(trimmed.dropFirst(4)))
    try storeKey(material, keyID: keyID)
    guard rawKey(try loadKey(keyID)) == material else {
        throw VaultError.message("the imported key could not be verified")
    }
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

#if CODEX_VAULT_TEST_LEGACY_KEYCHAIN
private func inspectKeyCommand(_ arguments: [String]) throws {
    let keyID = try canonicalKeyID(argument("--key-id", in: arguments))
    var query = legacyKeyQuery(keyID)
    query[kSecReturnData] = true
    query[kSecMatchLimit] = kSecMatchLimitOne
    var item: CFTypeRef?
    let status = SecItemCopyMatching(query as CFDictionary, &item)
    if status == errSecItemNotFound {
        try printJSON(LegacyInspection(key_id: keyID, recovery_key: nil))
        return
    }
    guard status == errSecSuccess, let data = item as? Data, data.count == 32 else {
        throw VaultError.message("the legacy Keychain entry is not available without approval")
    }
    try printJSON(LegacyInspection(key_id: keyID,
                                   recovery_key: "CV1-" + base64URL(data)))
}
#endif

private func deleteKeyCommand(_ arguments: [String]) throws {
    let keyID = try canonicalKeyID(argument("--key-id", in: arguments))
    try deleteKey(keyID)
    try printJSON(KeyResult(key_id: keyID, recovery_key: nil,
                            imported: nil, deleted: true))
}

private func storeChunksCommand(_ arguments: [String]) throws {
    let keyID = try canonicalKeyID(argument("--key-id", in: arguments))
    let root = URL(fileURLWithPath: try argument("--object-dir", in: arguments), isDirectory: true)
    let chunkSize = try chunkSizeArgument(arguments)
    let master = try loadKey(keyID)
    let encryption = encryptionKey(master)
    let identifiers = identifierKey(master)
    var digest = SHA256()
    var chunks: [Chunk] = []
    var total = 0
    while true {
        let data = try readInputChunk(chunkSize)
        if data.isEmpty { break }
        digest.update(data: data)
        total += data.count
        chunks.append(try storeChunk(data, root: root, encryption: encryption,
                                     identifiers: identifiers))
    }
    try printJSON(StoredFile(sha256: hex(digest.finalize()), size: total, chunks: chunks))
}

private func readInputChunk(_ size: Int) throws -> Data {
    // A pipe can return a short read before EOF. Chunk identity must depend
    // on the source bytes, not on when its producer writes to the pipe.
    var chunk = Data()
    while chunk.count < size {
        let next = try FileHandle.standardInput.read(upToCount: size - chunk.count) ?? Data()
        if next.isEmpty { break }
        chunk.append(next)
    }
    return chunk
}

private func knownObjectIDs(_ path: String) throws -> Set<String> {
    // The service's published-only lookup is expected to be persisted by the
    // caller in a private file. Keyed IDs are not plaintext, but can reveal
    // equality of the customer's chunks and must not be world-readable.
    let descriptor = open(path, O_RDONLY | O_NOFOLLOW | O_NONBLOCK)
    guard descriptor >= 0 else {
        throw VaultError.message("the remote object lookup is unavailable")
    }
    let handle = FileHandle(fileDescriptor: descriptor, closeOnDealloc: true)
    var information = stat()
    guard fstat(descriptor, &information) == 0,
          (information.st_mode & S_IFMT) == S_IFREG,
          information.st_uid == geteuid(), information.st_nlink == 1,
          information.st_mode & 0o077 == 0,
          information.st_size >= 0, information.st_size <= 8 * 1024 * 1024 else {
        throw VaultError.message("the remote object lookup is not a private regular file")
    }
    let data = try handle.readToEnd() ?? Data()
    guard data.count <= 8 * 1024 * 1024 else {
        throw VaultError.message("the remote object lookup is too large")
    }
    guard let lookup = try? JSONDecoder().decode(KnownObjectIDs.self, from: data),
          lookup.version == 1, lookup.ids.count <= 100_000,
          lookup.ids.allSatisfy({ $0.range(of: "^[0-9a-f]{64}$", options: .regularExpression) != nil }),
          Set(lookup.ids).count == lookup.ids.count else {
        throw VaultError.message("the remote object lookup is invalid")
    }
    return Set(lookup.ids)
}

private func storeChunksWithKnownCommand(_ arguments: [String]) throws {
    let keyID = try canonicalKeyID(argument("--key-id", in: arguments))
    let root = URL(fileURLWithPath: try argument("--object-dir", in: arguments), isDirectory: true)
    let chunkSize = try chunkSizeArgument(arguments)
    let known = try knownObjectIDs(argument("--known-ids-file", in: arguments))
    let expectedDigest = try argument("--expected-sha256", in: arguments)
    guard expectedDigest.range(of: "^[0-9a-f]{64}$", options: .regularExpression) != nil,
          let expectedSize = Int(try argument("--expected-size", in: arguments)),
          expectedSize >= 0 else {
        throw VaultError.message("the planned file verification is invalid")
    }
    let master = try loadKey(keyID)
    let encryption = encryptionKey(master)
    let identifiers = identifierKey(master)
    var digest = SHA256()
    var chunks: [Chunk] = []
    var localIDs: [String] = []
    var remoteIDs: [String] = []
    var total = 0
    while true {
        let data = try readInputChunk(chunkSize)
        if data.isEmpty { break }
        digest.update(data: data)
        guard total <= expectedSize, data.count <= expectedSize - total else {
            throw VaultError.message("the conversation changed after chunk planning")
        }
        total += data.count
        let raw = Chunk(id: objectID(data, key: identifiers), size: data.count,
                        encoding: nil)
        let compressedData = compressChunk(data)
        let compressed = compressedData.map { _ in
            Chunk(id: compressedObjectID(data, key: identifiers), size: data.count,
                  encoding: "lzfse")
        }
        let selected: Chunk
        let reusedRemotely: Bool
        // Published ciphertext must win over scratch ciphertext for the same
        // keyed ID. AES-GCM nonces differ across attempts; a local retry copy
        // may be valid plaintext yet conflict with the immutable R2 object.
        if let compressed = compressed, known.contains(compressed.id) {
            selected = compressed
            reusedRemotely = true
        } else if known.contains(raw.id) {
            selected = raw
            reusedRemotely = true
        } else if FileManager.default.fileExists(
                    atPath: try objectURL(root: root, id: raw.id).path) {
            guard try readChunk(raw, root: root, encryption: encryption,
                                identifiers: identifiers) == data else {
                throw VaultError.message("an existing encrypted object failed content verification")
            }
            selected = raw
            reusedRemotely = false
        } else if let compressed = compressed,
                  FileManager.default.fileExists(
                    atPath: try objectURL(root: root, id: compressed.id).path) {
            guard try readChunk(compressed, root: root, encryption: encryption,
                                identifiers: identifiers) == data else {
                throw VaultError.message("an existing encrypted object failed content verification")
            }
            selected = compressed
            reusedRemotely = false
        } else {
            selected = try storeChunk(data, root: root, encryption: encryption,
                                      identifiers: identifiers)
            reusedRemotely = false
        }
        chunks.append(selected)
        if reusedRemotely {
            remoteIDs.append(selected.id)
        } else {
            localIDs.append(selected.id)
        }
    }
    guard total == expectedSize, hex(digest.finalize()) == expectedDigest else {
        throw VaultError.message("the conversation changed after chunk planning")
    }
    try printJSON(RemoteAwareStoredFile(
        sha256: expectedDigest, size: total, chunks: chunks,
        local_ids: localIDs, remote_ids: remoteIDs))
}

private func chunkSizeArgument(_ arguments: [String]) throws -> Int {
    let text = try argument("--chunk-size", in: arguments)
    guard let size = Int(text), size >= 64 * 1024,
          size <= 64 * 1024 * 1024 else {
        throw VaultError.message("the chunk size is outside the supported range")
    }
    return size
}

private func planChunksCommand(_ arguments: [String]) throws {
    // Read-only first pass for a future remote-aware writer. Stable keyed IDs
    // let it check for exact published ciphertext before it encrypts anything.
    // A raw object from an older snapshot may exist even when compression is
    // now preferred, so report both candidates rather than guessing one.
    let keyID = try canonicalKeyID(argument("--key-id", in: arguments))
    let chunkSize = try chunkSizeArgument(arguments)
    let identifiers = identifierKey(try loadKey(keyID))
    var digest = SHA256()
    var chunks: [PlannedChunk] = []
    var total = 0
    while true {
        let data = try readInputChunk(chunkSize)
        if data.isEmpty { break }
        digest.update(data: data)
        total += data.count
        let compressed = compressChunk(data)
        chunks.append(PlannedChunk(
            raw_id: objectID(data, key: identifiers),
            compressed_id: compressed == nil ? nil :
                compressedObjectID(data, key: identifiers),
            size: data.count, compressed_bytes: compressed?.count))
    }
    try printJSON(PlannedFile(sha256: hex(digest.finalize()),
                              size: total, chunks: chunks))
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

private func openedManifest(_ arguments: [String]) throws ->
    (Manifest, SymmetricKey, SymmetricKey, String, String) {
    let keyID = try canonicalKeyID(argument("--key-id", in: arguments))
    let manifestURL = URL(fileURLWithPath: try argument("--manifest", in: arguments))
    let snapshotID = try argument("--snapshot-id", in: arguments).lowercased()
    guard UUID(uuidString: snapshotID) != nil else {
        throw VaultError.message("the snapshot identifier is invalid")
    }
    let master = try loadKey(keyID)
    let encryption = encryptionKey(master)
    let identifiers = identifierKey(master)
    let aad = Data("codex-vault:manifest:v1:\(snapshotID)".utf8)
    let ciphertext = try safeRegularFile(manifestURL, maxBytes: 128 * 1024 * 1024 + 64)
    let manifestData = try opened(ciphertext, key: encryption, aad: aad)
    let manifest = try JSONDecoder().decode(Manifest.self, from: manifestData)
    guard manifest.format == "codex-vault-snapshot",
          (manifest.version >= formatVersion && manifest.version <= snapshotFormatVersion),
          manifest.snapshot_id.lowercased() == snapshotID else {
        throw VaultError.message("the decrypted manifest has an unsupported identity or format")
    }
    return (manifest, encryption, identifiers,
            hex(SHA256.hash(data: ciphertext)), hex(SHA256.hash(data: manifestData)))
}

private func manifestFingerprintCommand(_ arguments: [String]) throws {
    let (manifest, _, _, ciphertextSHA256, plaintextSHA256) = try openedManifest(arguments)
    try printJSON(ManifestFingerprint(snapshot_id: manifest.snapshot_id,
                                      plaintext_sha256: plaintextSHA256,
                                      ciphertext_sha256: ciphertextSHA256))
}

private func validatedSnapshot(_ arguments: [String]) throws ->
    (Manifest, SymmetricKey, SymmetricKey, Verification, [String: String], String) {
    let (manifest, encryption, identifiers, manifestSHA256, _) = try openedManifest(arguments)
    let root = URL(fileURLWithPath: try argument("--object-dir", in: arguments), isDirectory: true)
    let snapshotID = manifest.snapshot_id
    var totalBytes = 0
    var totalChunks = 0
    var seenPaths = Set<String>()
    var chunkSHA256 = [String: String]()
    for file in manifest.files {
        guard ["active", "archived", "paginated"].contains(file.collection),
              !file.path.isEmpty, !file.path.hasPrefix("/"), !file.path.contains("\\"),
              file.path.split(separator: "/", omittingEmptySubsequences: false).allSatisfy({
                  !$0.isEmpty && $0 != "." && $0 != ".."
              }), file.size >= 0,
              file.sha256.range(of: "^[0-9a-f]{64}$", options: .regularExpression) != nil else {
            throw VaultError.message("the decrypted manifest contains an unsafe transcript record")
        }
        if manifest.version >= 2 {
            guard let state = file.identity_state,
                  ["verified", "unverified", "needs_review"].contains(state),
                  let records = file.records, records >= 0,
                  let assistants = file.assistant_messages, assistants >= 0,
                  let users = file.user_messages, users >= 0,
                  let titles = file.titles, titles.count <= 64,
                  titles.allSatisfy({ $0.count <= 500 && !$0.contains("\u{0}") }) else {
                throw VaultError.message("the decrypted manifest contains invalid identity metadata")
            }
            if let id = file.thread_id {
                guard UUID(uuidString: id)?.uuidString.lowercased() == id else {
                    throw VaultError.message("the decrypted manifest contains an invalid thread identity")
                }
            }
            if state == "verified" && file.thread_id == nil {
                throw VaultError.message("the decrypted manifest has an unbound verified identity")
            }
        }
        if file.collection == "paginated" {
            guard manifest.version >= 3, let id = file.thread_id,
                  file.identity_state == "verified", file.path == id + ".jsonl",
                  file.size > 0, file.mtime_ns == 0 else {
                throw VaultError.message("the decrypted manifest has an invalid paginated source")
            }
        }
        let logicalPath = file.collection + "/" + file.path
        guard seenPaths.insert(logicalPath).inserted else {
            throw VaultError.message("the decrypted manifest contains a duplicate transcript path")
        }
        var digest = SHA256()
        var fileBytes = 0
        for chunk in file.chunks {
            if manifest.version == formatVersion && chunk.encoding != nil {
                throw VaultError.message("a version 1 snapshot cannot contain encoded chunks")
            }
            let plaintext = try readChunk(chunk, root: root, encryption: encryption,
                                          identifiers: identifiers, onCiphertext: { id, ciphertext in
                let digest = hex(SHA256.hash(data: ciphertext))
                if let earlier = chunkSHA256[id], earlier != digest {
                    throw VaultError.message("an encrypted chunk changed during verification")
                }
                chunkSHA256[id] = digest
            })
            digest.update(data: plaintext)
            let (nextFileBytes, fileOverflow) = fileBytes.addingReportingOverflow(plaintext.count)
            let (nextChunks, chunkOverflow) = totalChunks.addingReportingOverflow(1)
            guard !fileOverflow, !chunkOverflow, nextFileBytes <= file.size else {
                throw VaultError.message("the decrypted manifest contains invalid byte counts")
            }
            fileBytes = nextFileBytes
            totalChunks = nextChunks
        }
        guard fileBytes == file.size, hex(digest.finalize()) == file.sha256 else {
            throw VaultError.message("a restored transcript failed file verification")
        }
        let (nextTotal, totalOverflow) = totalBytes.addingReportingOverflow(fileBytes)
        guard !totalOverflow else {
            throw VaultError.message("the decrypted manifest contains invalid total bytes")
        }
        totalBytes = nextTotal
    }
    let verification = Verification(snapshot_id: snapshotID, files: manifest.files.count,
                                    chunks: totalChunks, bytes: totalBytes)
    return (manifest, encryption, identifiers, verification, chunkSHA256, manifestSHA256)
}

private func verifyCommand(_ arguments: [String]) throws {
    let (_, _, _, verification, _, _) = try validatedSnapshot(arguments)
    try printJSON(verification)
}

private func encryptedInventoryCommand(_ arguments: [String]) throws {
    // Return only opaque identifiers after full authenticated verification.
    // Paths, titles, message text and key material never enter this output.
    let (manifest, _, _, verification, chunkSHA256, manifestSHA256) = try validatedSnapshot(arguments)
    let identifiers = Set(manifest.files.flatMap { file in file.chunks.map { $0.id } })
    try printJSON(EncryptedInventory(snapshot_id: verification.snapshot_id,
                                     chunk_ids: identifiers.sorted(),
                                     chunk_sha256: chunkSHA256,
                                     manifest_sha256: manifestSHA256))
}

private func catalogCommand(_ arguments: [String]) throws {
    let (manifest, _, _, _, _) = try openedManifest(arguments)
    let files = manifest.files.map { file in
        CatalogFile(collection: file.collection, path: file.path, size: file.size,
                    sha256: file.sha256, thread_id: file.thread_id,
                    identity_state: file.identity_state,
                    titles: file.titles ?? [], records: file.records,
                    assistant_messages: file.assistant_messages,
                    user_messages: file.user_messages, at_risk: file.at_risk)
    }
    try printJSON(Catalog(snapshot_id: manifest.snapshot_id,
                          version: manifest.version, files: files))
}

private func prepareEmptyRestoreRoot(_ path: String) throws -> URL {
    let root = URL(fileURLWithPath: path, isDirectory: true)
    let manager = FileManager.default
    if manager.fileExists(atPath: root.path) {
        let values = try root.resourceValues(forKeys: [.isDirectoryKey, .isSymbolicLinkKey])
        guard values.isDirectory == true, values.isSymbolicLink != true,
              try manager.contentsOfDirectory(atPath: root.path).isEmpty else {
            throw VaultError.message("the restore output must be a new or empty unlinked folder")
        }
    } else {
        try manager.createDirectory(at: root, withIntermediateDirectories: false,
                                    attributes: [.posixPermissions: 0o700])
    }
    return root
}

private func restoreCommand(_ arguments: [String]) throws {
    let (manifest, encryption, identifiers, verification, _, _) = try validatedSnapshot(arguments)
    let output = try prepareEmptyRestoreRoot(argument("--output", in: arguments))
    let manager = FileManager.default
    let objectRoot = URL(fileURLWithPath: try argument("--object-dir", in: arguments),
                         isDirectory: true)
    for file in manifest.files {
        let collection = file.collection == "active" ? "sessions" :
            (file.collection == "archived" ? "archived_sessions" : "paginated_history")
        let target = output.appendingPathComponent(collection, isDirectory: true)
            .appendingPathComponent(file.path, isDirectory: false)
        let parent = target.deletingLastPathComponent()
        try manager.createDirectory(at: parent, withIntermediateDirectories: true,
                                    attributes: [.posixPermissions: 0o700])
        guard !manager.fileExists(atPath: target.path) else {
            throw VaultError.message("restore output already contains a transcript")
        }
        let temporary = parent.appendingPathComponent("." + UUID().uuidString + ".tmp")
        let descriptor = open(temporary.path, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW, 0o600)
        guard descriptor >= 0 else {
            throw VaultError.message("a restored transcript could not be staged safely")
        }
        let handle = FileHandle(fileDescriptor: descriptor, closeOnDealloc: true)
        var digest = SHA256()
        var restoredBytes = 0
        do {
            for chunk in file.chunks {
                let plaintext = try readChunk(chunk, root: objectRoot,
                                              encryption: encryption, identifiers: identifiers)
                try handle.write(contentsOf: plaintext)
                digest.update(data: plaintext)
                restoredBytes += plaintext.count
            }
            guard restoredBytes == file.size, hex(digest.finalize()) == file.sha256 else {
                throw VaultError.message("a staged transcript failed restore verification")
            }
            try handle.synchronize()
            try handle.close()
            try manager.moveItem(at: temporary, to: target)
            if file.mtime_ns >= 0 {
                let date = Date(timeIntervalSince1970: Double(file.mtime_ns) / 1_000_000_000)
                try manager.setAttributes([.modificationDate: date], ofItemAtPath: target.path)
            }
        } catch {
            try? handle.close()
            try? manager.removeItem(at: temporary)
            throw error
        }
    }
    let receipt = RestoreResult(snapshot_id: verification.snapshot_id,
                                files: verification.files,
                                bytes: verification.bytes,
                                output: output.path)
    try writeNew(try JSON(receipt), to: output.appendingPathComponent("restore-receipt.json"))
    try printJSON(receipt)
}

private func run() throws {
    // Legacy file-based Keychain ACL prompts are not reliably suppressed by
    // LAContext.interactionNotAllowed alone. Vault runs unattended, so never
    // allow SecurityAgent to block a backup waiting for a password dialog.
    guard SecKeychainSetUserInteractionAllowed(false) == errSecSuccess else {
        throw VaultError.message(keychainInteractionError)
    }
    let arguments = Array(CommandLine.arguments.dropFirst())
    guard let command = arguments.first else {
        throw VaultError.message("a command is required")
    }
    switch command {
    case "create-key": try createKeyCommand()
    case "import-key": try importKeyCommand(arguments)
    case "export-key": try exportKeyCommand(arguments)
#if CODEX_VAULT_TEST_LEGACY_KEYCHAIN
    case "inspect-key": try inspectKeyCommand(arguments)
#endif
    case "delete-key": try deleteKeyCommand(arguments)
    case "hosted-device-create": try createHostedDeviceCommand()
    case "hosted-device-read": try readHostedDeviceCommand(arguments)
    case "hosted-device-list": try listHostedDevicesCommand()
    case "hosted-device-delete": try deleteHostedDeviceCommand(arguments)
    case "store-chunks": try storeChunksCommand(arguments)
    case "store-chunks-with-known": try storeChunksWithKnownCommand(arguments)
    case "plan-chunks": try planChunksCommand(arguments)
    case "seal-manifest": try sealManifestCommand(arguments)
    case "manifest-fingerprint": try manifestFingerprintCommand(arguments)
    case "verify": try verifyCommand(arguments)
    case "encrypted-inventory": try encryptedInventoryCommand(arguments)
    case "catalog": try catalogCommand(arguments)
    case "restore": try restoreCommand(arguments)
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
