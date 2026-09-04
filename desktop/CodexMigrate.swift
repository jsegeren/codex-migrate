import SwiftUI
import AppKit
import CryptoKit

// The desktop shell owns setup and its child process. The existing engine owns
// all migration safety decisions; user input is never interpolated into a shell.
@MainActor final class MigrationModel: ObservableObject {
    static let shared = MigrationModel()
    @Published var target = ""
    @Published var targetHome = ""
    @Published var identity = ""
    @Published var workspaces: [String] = []
    @Published var personalSkills = true
    @Published var workspaceSkills = false
    @Published var enableChanges = false
    @Published var output = "Choose the destination and inspect before enabling changes."
    @Published var running = false
    @Published var operation: String?
    @Published var stopRequested = false
    @Published var dashboardURL: URL?
    @Published var failure: String?
    private var process: Process?
    private var stateDirectory: URL?
    private var buffer = Data()
    private let home = FileManager.default.homeDirectoryForCurrentUser
    private var setupStore: SetupStore {
        SetupStore(directory: home.appendingPathComponent("Library/Application Support/Codex Migrate"))
    }

    init() { restoreSetup() }

    func restoreSetup() {
        guard !running else { return }
        do {
            guard let setup = try setupStore.load() else { return }
            target = setup.target
            targetHome = setup.targetHome
            workspaces = setup.workspaces
            personalSkills = setup.personalSkills
            workspaceSkills = setup.workspaceSkills
            identity = ""
            enableChanges = false
            output = "Restored the last launched setup. Review destination and folders before continuing. Changes remain disabled. If you used a custom SSH key, select it again."
        } catch {
            failure = "Saved setup could not be read safely. Enter the destination and folders again. Existing migration staging has not been changed."
        }
    }

    func chooseFolders() {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.allowsMultipleSelection = true
        panel.directoryURL = home
        if panel.runModal() == .OK {
            workspaces = Array(Set(workspaces + panel.urls.map(\.path))).sorted()
        }
    }

    func suggestFolders() {
        let candidates = ["Git", "Projects", "Developer"].map { home.appendingPathComponent($0) }
        workspaces = Array(Set(workspaces + candidates.filter {
            var isDirectory: ObjCBool = false
            return FileManager.default.fileExists(atPath: $0.path, isDirectory: &isDirectory) && isDirectory.boolValue
        }.map(\.path))).sorted()
        output = "Suggested existing Git/Projects/Developer folders. This is not an exhaustive repository scan. Review these roots; remove anything you do not want transferred."
    }

    func chooseIdentity() {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = false
        panel.showsHiddenFiles = true
        panel.directoryURL = home.appendingPathComponent(".ssh")
        if panel.runModal() == .OK { identity = panel.url?.path ?? "" }
    }

    func arguments(command: String, apply: Bool) throws -> [String] {
        let destination = target.trimmingCharacters(in: .whitespacesAndNewlines)
        let destinationHome = targetHome.trimmingCharacters(in: .whitespacesAndNewlines)
        guard destination.contains("@"), destinationHome.hasPrefix("/Users/") else {
            throw SetupError.message("Enter user@host and the new Mac's exact /Users/username home directory.")
        }
        let configuration = [destination, destinationHome] + workspaces.sorted()
        let digest = SHA256.hash(data: try JSONEncoder().encode(configuration))
        let key = digest.map { String(format: "%02x", $0) }.joined()
        let state = home.appendingPathComponent(".local/state/codex-migrate-desktop/" + key)
        stateDirectory = state
        var args = [command, "--target", destination, "--target-home", destinationHome,
                    "--state-dir", state.path]
        for path in workspaces { args += ["--workspace", path] }
        if !identity.isEmpty { args += ["--identity-file", identity] }
        if apply { args.append("--apply") }
        if command == "serve" { args += ["--port", "0", "--no-open"] }
        if command == "export" {
            guard personalSkills || workspaceSkills else {
                throw SetupError.message("Select at least one skills component.")
            }
            if personalSkills { args += ["--component", "personal-skills"] }
            if workspaceSkills { args += ["--component", "workspace-skills"] }
        }
        return args
    }

    func launch(_ command: String, apply: Bool = false) {
        guard !running else { return }
        if apply && command == "export" {
            let alert = NSAlert()
            alert.messageText = "Apply the selected skill export?"
            alert.informativeText = "This backs up and replaces matching skills on \(target). Other skills and conversations are left untouched. Inspect the export plan first."
            alert.addButton(withTitle: "Export skills")
            alert.addButton(withTitle: "Cancel")
            guard alert.runModal() == .alertFirstButtonReturn else { return }
        }
        do {
            guard let resources = Bundle.main.resourceURL else { throw SetupError.message("App resources are missing.") }
            let binary = resources.appendingPathComponent("engine/codex-migrate-engine")
            guard FileManager.default.isExecutableFile(atPath: binary.path) else {
                throw SetupError.message("Bundled migration engine is missing. Reinstall the app.")
            }
            let child = Process()
            child.executableURL = binary
            child.arguments = try arguments(command: command, apply: apply)
            try setupStore.save(SavedSetup(target: target.trimmingCharacters(in: .whitespacesAndNewlines),
                                          targetHome: targetHome.trimmingCharacters(in: .whitespacesAndNewlines),
                                          workspaces: workspaces, personalSkills: personalSkills,
                                          workspaceSkills: workspaceSkills))
            child.currentDirectoryURL = home
            // Keep SSH agent support, but do not forward Python loader overrides.
            child.environment = ProcessInfo.processInfo.environment.filter {
                !$0.key.hasPrefix("PYTHON") && !$0.key.hasPrefix("DYLD_")
            }
            let pipe = Pipe()
            child.standardOutput = pipe
            child.standardError = pipe
            child.standardInput = FileHandle.nullDevice
            buffer = Data()
            dashboardURL = nil
            output = command == "serve" ? "Starting a private local dashboard…" : "Inspecting…"
            if command == "export" && apply { output = "Preparing the selected skills export…" }
            pipe.fileHandleForReading.readabilityHandler = { handle in
                let chunk = handle.availableData
                if chunk.isEmpty { handle.readabilityHandler = nil; return }
                DispatchQueue.main.async { self.consume(chunk) }
            }
            child.terminationHandler = { child in
                pipe.fileHandleForReading.readabilityHandler = nil
                let remaining = pipe.fileHandleForReading.readDataToEndOfFile()
                DispatchQueue.main.async {
                    self.consume(remaining)
                    self.consume(Data([10]))
                    self.running = false
                    self.dashboardURL = nil
                    self.process = nil
                    self.operation = nil
                    self.stopRequested = false
                    self.output += child.terminationStatus == 130 ? "\nOperation stopped." : "\nProcess finished (exit \(child.terminationStatus))."
                    if child.terminationStatus != 0 && child.terminationStatus != 130 && child.terminationReason == .exit {
                        self.failure = "The operation did not complete. Review the output below. No success is being claimed."
                    }
                }
            }
            try child.run()
            process = child
            operation = command
            stopRequested = false
            running = true
        } catch { failure = error.localizedDescription }
    }

    private func consume(_ data: Data) {
        buffer.append(data)
        while let newline = buffer.firstIndex(of: 10) {
            let line = String(decoding: buffer.prefix(upTo: newline), as: UTF8.self)
            buffer.removeSubrange(...newline)
            let prefix = "Codex Migrate dashboard: "
            if line.hasPrefix(prefix) {
                guard let url = URL(string: String(line.dropFirst(prefix.count))),
                      url.scheme == "http", url.host == "127.0.0.1", url.port != nil,
                      url.fragment?.hasPrefix("token=") == true else {
                    failure = "The engine returned an invalid local dashboard address."
                    continue
                }
                dashboardURL = url
                output += "\nDashboard ready. Keep this app open while using its controls."
                NSWorkspace.shared.open(url)
            } else if !line.isEmpty {
                output += "\n" + line
                output = String(output.suffix(32_000))
            }
        }
        if buffer.count > 32_000 { buffer = Data(buffer.suffix(32_000)) }
    }

    func stopDashboard() {
        guard dashboardURL != nil, let child = process, child.isRunning else { return }
        // Never offer shutdown while the engine is installing, inspecting, or
        // holding a paused transfer. Use its own safe-stop control first.
        guard let state = stateDirectory,
              let data = try? Data(contentsOf: state.appendingPathComponent("state.json")),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let status = json["status"] as? String,
              ["idle", "ready", "ready_to_finalize", "waiting", "cancelled", "failed", "interrupted", "complete"].contains(status) else {
            failure = "An operation is active, paused, or its state is unknown. Use Stop safely in the dashboard, or wait for installation to finish."
            return
        }
        child.terminate()
    }

    func stopOperation() {
        guard operation == "inspect" || operation == "export",
              let child = process, child.isRunning, !stopRequested else { return }
        stopRequested = true
        output += "\nStop requested. If backup/replacement has begun, it will finish before stopping. Keep both Macs connected."
        child.interrupt()
    }

    func openGuide(_ name: String) {
        guard let url = Bundle.main.resourceURL?.appendingPathComponent(name),
              FileManager.default.fileExists(atPath: url.path) else {
            failure = "The bundled guide is missing. Reinstall the app or use the online documentation."
            return
        }
        NSWorkspace.shared.open(url)
    }
}

enum SetupError: LocalizedError {
    case message(String)
    var errorDescription: String? { if case let .message(text) = self { return text }; return nil }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        if MigrationModel.shared.running {
            let alert = NSAlert()
            alert.messageText = "The migration engine is still open"
            alert.informativeText = MigrationModel.shared.operation == "serve"
                ? "Use Stop safely in the dashboard, then Close dashboard here before quitting. During installation, wait for verification to finish."
                : "Use Stop operation in the setup window. If backup/replacement has begun, wait for it to finish before quitting."
            alert.runModal()
            return .terminateCancel
        }
        return .terminateNow
    }
}

@main struct CodexMigrateApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) var delegate
    @StateObject private var model = MigrationModel.shared
    var body: some Scene {
        WindowGroup("Codex Migrate") {
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    Text("Keep the work. Change the Mac.").font(.largeTitle.bold())
                    Text("Run this app on the old Mac. Data moves directly over SSH; we do not receive your workspace.")
                    GroupBox("1 · Prepare the new Mac") {
                        VStack(alignment: .leading, spacing: 8) {
                            Text("Install Codex, open it, and sign in once. Enable Remote Login in System Settings → General → Sharing. Allow access to your user account.")
                            Text("Set up SSH key login and verify the new Mac's host fingerprint before using the app. Connections fail closed if authentication or host verification is missing.")
                            Link("Connection and permission guide", destination: URL(string: "https://github.com/jsegeren/codex-migrate/blob/main/docs/desktop-setup.md")!)
                            Button("Read setup guide offline") { model.openGuide("Read me.md") }
                        }.padding(8).frame(maxWidth: .infinity, alignment: .leading)
                    }
                    GroupBox("2 · Destination and scope") {
                        VStack(alignment: .leading, spacing: 12) {
                            TextField("SSH destination (new-user@new-mac.local)", text: $model.target)
                            TextField("Destination home (/Users/new-user)", text: $model.targetHome)
                            Button("Restore last launched setup") { model.restoreSetup() }
                            Text("Your last launched destination and folder selection are saved privately on this Mac. Changes are always disabled after reopening. SSH key selections are not saved.")
                            HStack {
                                TextField("SSH key file (optional; existing SSH configuration is used)", text: $model.identity)
                                Button("Choose key…") { model.chooseIdentity() }
                            }
                            Text("Selected workspace folders include .git, uncommitted files, and any secrets stored inside them. Review before transferring.")
                            HStack {
                                Button("Add folders…") { model.chooseFolders() }
                                Button("Suggest common folders") { model.suggestFolders() }
                            }
                            ForEach(model.workspaces, id: \.self) { path in
                                HStack { Text(path).textSelection(.enabled); Spacer(); Button("Remove") { model.workspaces.removeAll { $0 == path } }.accessibilityLabel("Remove workspace \(path)") }
                            }
                            if model.workspaces.isEmpty { Text("No workspace folders selected. A full migration will copy Codex state only.").foregroundStyle(.secondary) }
                        }.padding(8).textFieldStyle(.roundedBorder)
                    }.disabled(model.running)
                    GroupBox("3 · Inspect, then transfer") {
                        VStack(alignment: .leading, spacing: 12) {
                            Toggle("Enable changes on the destination (off by default)", isOn: $model.enableChanges)
                            Text("A verified destination backup is mandatory. Insufficient space or a failed backup check blocks replacement; there is no skip-backup option. Keep the old Mac intact: a same-disk backup does not protect against disk failure.")
                            Text("The dashboard never starts a transfer automatically. Inspect first, then choose Start transfer. Finalization requires both Codex apps closed and an explicit backup-and-replace confirmation.")
                            HStack {
                                Button("Inspect both Macs") { model.launch("inspect") }
                                Button("Open migration dashboard") { model.launch("serve", apply: model.enableChanges) }
                            }
                            Divider()
                            Text("Only need to restore skills?").bold()
                            Toggle("Personal skills", isOn: $model.personalSkills)
                            Toggle("Workspace skills in selected folders", isOn: $model.workspaceSkills)
                            HStack {
                                Button("Plan skill export") { model.launch("export") }
                                Button("Apply skill export…") { model.launch("export", apply: true) }.disabled(!model.enableChanges)
                            }
                        }.padding(8)
                    }.disabled(model.running)
                    if let url = model.dashboardURL {
                        HStack {
                            Button("Show dashboard") { NSWorkspace.shared.open(url) }
                            Button("Close dashboard") { model.stopDashboard() }
                            Text("Keep this app open during migration.").foregroundStyle(.secondary)
                        }
                    }
                    if model.running { ProgressView("Migration engine is open") }
                    if model.running && model.operation != "serve" {
                        Button(model.stopRequested ? "Waiting for safe stop…" : "Stop operation") { model.stopOperation() }
                            .disabled(model.stopRequested)
                    }
                    Text(model.output).font(.system(size: 14, design: .monospaced)).textSelection(.enabled)
                        .frame(maxWidth: .infinity, alignment: .leading).padding().background(.quaternary).cornerRadius(10)
                    Text("Support is best-effort. We aim to respond within a few business days, depending on availability and complexity. No fix or resolution deadline is guaranteed. Keep an independent backup.").foregroundStyle(.secondary)
                    Link("Support and recovery guide", destination: URL(string: "https://github.com/jsegeren/codex-migrate/blob/main/docs/desktop-setup.md")!)
                    HStack {
                        Button("Read recovery guide offline") { model.openGuide("recovery.md") }
                        Button("Read security guide offline") { model.openGuide("security-model.md") }
                    }
                    Text("Unofficial. Not affiliated with or endorsed by OpenAI.").foregroundStyle(.secondary)
                }.padding(28).font(.system(size: 15)).frame(minWidth: 650, maxWidth: 1000)
            }.frame(minWidth: 710, minHeight: 680)
            .alert("Please review", isPresented: Binding(get: { model.failure != nil }, set: { if !$0 { model.failure = nil } })) {
                Button("OK") { model.failure = nil }
            } message: { Text(model.failure ?? "") }
        }
    }
}
