import Foundation

@main struct DuplicateLaunchChecks {
    static func main() {
        let installed = URL(fileURLWithPath: "/Applications/Codex Migrate.app")
        let other = URL(fileURLWithPath: "/Users/buyer/Downloads/Codex Migrate.app")
        precondition(DuplicateLaunch.sameCopyIsRunning(ownURL: installed, ownPID: 12,
            candidates: [(pid: 13, bundleURL: installed)]))
        precondition(!DuplicateLaunch.sameCopyIsRunning(ownURL: installed, ownPID: 12,
            candidates: [(pid: 12, bundleURL: installed)]))
        precondition(!DuplicateLaunch.sameCopyIsRunning(ownURL: installed, ownPID: 12,
            candidates: [(pid: 13, bundleURL: other), (pid: 14, bundleURL: nil)]))
        print("Duplicate launch checks passed")
    }
}
