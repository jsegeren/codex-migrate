import Foundation
import LocalAuthentication
import Security

enum UpdateEntitlement {
    private static let service = "com.segeren.codex-migrate.update-entitlement"
    private static let account = "purchase-link"

    static func token(from input: String) -> String? {
        let value = input.trimmingCharacters(in: .whitespacesAndNewlines)
        let candidate: String
        if value.hasPrefix("https://") {
            guard let url = URLComponents(string: value), url.scheme == "https",
                  url.host == "migrate.segeren.com", url.port == nil,
                  url.user == nil, url.password == nil, url.path == "/purchase",
                  url.query == nil, let fragment = url.fragment else { return nil }
            candidate = fragment
        } else {
            candidate = value
        }
        guard candidate.range(of: #"^cs_live_[A-Za-z0-9]+\.[a-f0-9]{64}$"#, options: .regularExpression) != nil,
              candidate.count <= 330 else { return nil }
        return candidate
    }

    static func savedToken() -> String? {
        let context = LAContext()
        context.interactionNotAllowed = true
        let query: [String: Any] = [kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service, kSecAttrAccount as String: account,
            kSecReturnData as String: true, kSecMatchLimit as String: kSecMatchLimitOne,
            // Automatic checks must never block AppKit behind a Keychain dialog.
            kSecUseAuthenticationContext as String: context]
        var result: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &result) == errSecSuccess,
              let data = result as? Data, let value = String(data: data, encoding: .utf8) else { return nil }
        return token(from: value)
    }

    static func save(_ token: String) -> Bool {
        guard let value = self.token(from: token), let data = value.data(using: .utf8) else { return false }
        let lookup: [String: Any] = [kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service, kSecAttrAccount as String: account]
        let update: [String: Any] = [kSecValueData as String: data]
        let status = SecItemUpdate(lookup as CFDictionary, update as CFDictionary)
        if status == errSecSuccess { return true }
        if status != errSecItemNotFound { return false }
        var item = lookup
        item[kSecValueData as String] = data
        item[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        return SecItemAdd(item as CFDictionary, nil) == errSecSuccess
    }

    static func verify(_ token: String, completion: @escaping (Bool) -> Void) {
        guard let url = URL(string: "https://migrate.segeren.com/api/purchase") else {
            completion(false); return
        }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.timeoutInterval = 20
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("https://migrate.segeren.com", forHTTPHeaderField: "Origin")
        request.httpBody = try? JSONSerialization.data(withJSONObject: ["action": "entitlement", "credential": token])
        URLSession.shared.dataTask(with: request) { _, response, _ in
            DispatchQueue.main.async { completion((response as? HTTPURLResponse)?.statusCode == 200) }
        }.resume()
    }
}
