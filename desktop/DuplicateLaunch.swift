import Foundation

enum DuplicateLaunch {
    static func sameCopyIsRunning(ownURL: URL, ownPID: Int32,
                                  candidates: [(pid: Int32, bundleURL: URL?)]) -> Bool {
        let ownPath = ownURL.standardizedFileURL.path
        return candidates.contains { candidate in
            candidate.pid != ownPID && candidate.bundleURL?.standardizedFileURL.path == ownPath
        }
    }
}
