import Foundation

@main struct SavedSetupChecks {
    static func main() throws {
        let root = URL(fileURLWithPath: CommandLine.arguments[1])
        let store = SetupStore(directory: root.appendingPathComponent("private"))
        let setup = SavedSetup(target: "user@fixture.local", targetHome: "/Users/user",
                               workspaces: ["/Users/source/Git"], personalSkills: true,
                               workspaceSkills: false)
        let empty = try store.load()
        precondition(empty == nil)
        try store.save(setup)
        let loaded = try store.load()
        precondition(loaded == setup)
        let file = store.directory.appendingPathComponent("last-setup.json")
        let attrs = try FileManager.default.attributesOfItem(atPath: file.path)
        precondition((attrs[.posixPermissions] as! NSNumber).intValue == 0o600)
        let payload = try JSONSerialization.jsonObject(with: Data(contentsOf: file)) as! [String: Any]
        precondition(Set(payload.keys) == Set(["target", "targetHome", "workspaces", "personalSkills", "workspaceSkills"]))
        var changed = setup
        changed.workspaces.append("/Users/source/Projects")
        try store.save(changed)
        let reloaded = try store.load()
        precondition(reloaded == changed)
        let names = try FileManager.default.contentsOfDirectory(atPath: store.directory.path)
        precondition(names.count == 1)
        try FileManager.default.setAttributes([.posixPermissions: 0o644], ofItemAtPath: file.path)
        do { _ = try store.load(); fatalError("Public setup accepted") } catch {}
        try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: file.path)
        try Data("invalid json".utf8).write(to: file)
        do { _ = try store.load(); fatalError("Corrupt setup accepted") } catch {}
        try FileManager.default.removeItem(at: file)
        let outside = root.appendingPathComponent("untouched")
        try Data("unchanged".utf8).write(to: outside)
        try FileManager.default.createSymbolicLink(at: file, withDestinationURL: outside)
        do { _ = try store.load(); fatalError("Symlink accepted") } catch {}
        try store.save(setup)
        let untouched = try String(contentsOf: outside, encoding: .utf8)
        precondition(untouched == "unchanged")
        let alias = SetupStore(directory: root.appendingPathComponent("alias"))
        try FileManager.default.createSymbolicLink(at: alias.directory, withDestinationURL: store.directory)
        do { try alias.save(setup); fatalError("Directory symlink accepted") } catch {}
        print("Saved setup checks passed")
    }
}
