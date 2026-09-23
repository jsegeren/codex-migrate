import Foundation

enum InstallLocation {
    static func needsMoveToApplications(appURL: URL, homeURL: URL) -> Bool {
        let path = appURL.standardizedFileURL.path
        let downloads = homeURL.appendingPathComponent("Downloads").standardizedFileURL.path
        return path.hasPrefix("/Volumes/") || path.contains("/AppTranslocation/") ||
            path.hasPrefix(downloads + "/")
    }
}
