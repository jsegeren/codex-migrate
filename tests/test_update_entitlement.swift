import Foundation

@main struct UpdateEntitlementChecks {
    static func main() {
        let token = "cs_live_purchase." + String(repeating: "a", count: 64)
        precondition(UpdateEntitlement.token(from: token) == token)
        precondition(UpdateEntitlement.token(from: "https://migrate.segeren.com/purchase#" + token) == token)
        for value in ["https://evil.example/purchase#" + token,
                      "https://migrate.segeren.com/purchase?token=x#" + token,
                      "https://migrate.segeren.com/other#" + token,
                      "cs_test_purchase." + String(repeating: "a", count: 64),
                      token + "junk"] {
            precondition(UpdateEntitlement.token(from: value) == nil)
        }
    }
}
