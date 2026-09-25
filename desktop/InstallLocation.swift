import Foundation

enum InstallLocation {
    static func needsMoveToApplications(appURL: URL, homeURL: URL) -> Bool {
        let path = appURL.standardizedFileURL.path
        let resolvedPath = appURL.resolvingSymlinksInPath().standardizedFileURL.path
        let downloads = homeURL.appendingPathComponent("Downloads").standardizedFileURL.path
        let resolvedDownloads = homeURL.appendingPathComponent("Downloads")
            .resolvingSymlinksInPath().standardizedFileURL.path
        return [path, resolvedPath].contains { candidate in
            candidate.hasPrefix("/Volumes/") || candidate.contains("/AppTranslocation/") ||
                candidate.hasPrefix(downloads + "/") || candidate.hasPrefix(resolvedDownloads + "/")
        }
    }
}
