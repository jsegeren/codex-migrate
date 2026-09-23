import Foundation

@main struct InstallLocationChecks {
    static func main() {
        let home = URL(fileURLWithPath: "/Users/buyer")
        func needsMove(_ path: String) -> Bool {
            InstallLocation.needsMoveToApplications(appURL: URL(fileURLWithPath: path), homeURL: home)
        }
        precondition(needsMove("/Volumes/Codex Migrate/Codex Migrate.app"))
        precondition(needsMove("/Users/buyer/Downloads/Codex Migrate.app"))
        precondition(needsMove("/private/var/folders/test/AppTranslocation/ABC/d/Codex Migrate.app"))
        precondition(!needsMove("/Applications/Codex Migrate.app"))
        precondition(!needsMove("/Users/buyer/Downloads-Archive/Codex Migrate.app"))
        precondition(!needsMove("/Users/buyer/Applications/Codex Migrate.app"))
        print("Install location checks passed")
    }
}
