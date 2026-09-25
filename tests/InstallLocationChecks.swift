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

        let manager = FileManager.default
        let fixture = manager.temporaryDirectory.appendingPathComponent("install-location-\(UUID().uuidString)")
        defer { try? manager.removeItem(at: fixture) }
        let fixtureHome = fixture.appendingPathComponent("Home")
        let fixtureDownloads = fixtureHome.appendingPathComponent("Downloads")
        let fixtureApplications = fixtureHome.appendingPathComponent("Applications")
        try! manager.createDirectory(at: fixtureDownloads.appendingPathComponent("Codex Migrate.app"),
                                     withIntermediateDirectories: true)
        try! manager.createDirectory(at: fixtureApplications, withIntermediateDirectories: true)
        let appAlias = fixtureApplications.appendingPathComponent("Codex Migrate.app")
        try! manager.createSymbolicLink(at: appAlias,
                                        withDestinationURL: fixtureDownloads.appendingPathComponent("Codex Migrate.app"))
        precondition(InstallLocation.needsMoveToApplications(appURL: appAlias, homeURL: fixtureHome))
        try! manager.removeItem(at: appAlias)
        precondition(!InstallLocation.needsMoveToApplications(appURL: appAlias, homeURL: fixtureHome))

        let directoryAlias = fixtureHome.appendingPathComponent("Applications Alias")
        try! manager.createSymbolicLink(at: directoryAlias, withDestinationURL: fixtureDownloads)
        precondition(InstallLocation.needsMoveToApplications(
            appURL: directoryAlias.appendingPathComponent("Codex Migrate.app"), homeURL: fixtureHome))
        print("Install location checks passed")
    }
}
