import AppKit

// The Mac app owns only the local helper's lifetime. All setup, migration,
// progress and recovery decisions belong to the browser.
@main final class AppDelegate: NSObject, NSApplicationDelegate {
    private var item: NSStatusItem!
    private var process: Process?
    private var dashboardURL: URL?
    private var buffer = Data()
    private var quitting = false

    static func main() {
        let app = NSApplication.shared
        let delegate = AppDelegate()
        app.delegate = delegate
        app.setActivationPolicy(.accessory)
        withExtendedLifetime(delegate) { app.run() }
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        item = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        item.button?.image = NSImage(systemSymbolName: "arrow.right.square", accessibilityDescription: "Codex Migrate")
        let menu = NSMenu()
        for (title, action) in [("Open Codex Migrate", #selector(openMigration)),
                                ("Quit Codex Migrate", #selector(quit))] {
            let entry = NSMenuItem(title: title, action: action, keyEquivalent: "")
            entry.target = self
            menu.addItem(entry)
        }
        item.menu = menu
        startHelper()
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        openMigration()
        return false
    }

    @objc private func openMigration() {
        if let url = dashboardURL { NSWorkspace.shared.open(url) }
        else if process == nil { startHelper() }
    }

    @objc private func quit() { NSApplication.shared.terminate(nil) }

    private func startHelper() {
        guard process == nil else { return }
        guard let resources = Bundle.main.resourceURL else {
            showFailure("The app is missing its resources. Reinstall Codex Migrate.")
            return
        }
        let child = Process()
        child.executableURL = resources.appendingPathComponent("engine/codex-migrate-engine")
        child.arguments = ["launch", "--port", "0", "--no-open"]
        child.currentDirectoryURL = FileManager.default.homeDirectoryForCurrentUser
        child.environment = ProcessInfo.processInfo.environment.filter {
            !$0.key.hasPrefix("PYTHON") && !$0.key.hasPrefix("DYLD_")
        }
        child.standardInput = FileHandle.nullDevice
        let pipe = Pipe()
        child.standardOutput = pipe
        child.standardError = pipe
        buffer = Data()
        pipe.fileHandleForReading.readabilityHandler = { handle in
            let data = handle.availableData
            if data.isEmpty { handle.readabilityHandler = nil; return }
            DispatchQueue.main.async { self.consume(data) }
        }
        child.terminationHandler = { child in
            pipe.fileHandleForReading.readabilityHandler = nil
            DispatchQueue.main.async {
                self.process = nil
                self.dashboardURL = nil
                if self.quitting {
                    NSApplication.shared.reply(toApplicationShouldTerminate: true)
                } else if child.terminationStatus == 0 || child.terminationStatus == 130 {
                    NSApplication.shared.terminate(nil)
                } else {
                    self.showFailure("The local helper stopped. Reopen Codex Migrate to resume. If this keeps happening, email joshua@segeren.com. Your saved migration remains on your Macs.")
                }
            }
        }
        do {
            try child.run()
            process = child
        } catch {
            showFailure("The local helper could not start. Reinstall Codex Migrate or email joshua@segeren.com.")
        }
    }

    private func consume(_ data: Data) {
        buffer.append(data)
        while let newline = buffer.firstIndex(of: 10) {
            let line = String(decoding: buffer.prefix(upTo: newline), as: UTF8.self)
            buffer.removeSubrange(...newline)
            let prefix = "Codex Migrate dashboard: "
            guard line.hasPrefix(prefix) else { continue }
            guard let url = URL(string: String(line.dropFirst(prefix.count))),
                  url.scheme == "http", url.host == "127.0.0.1", url.port != nil,
                  url.user == nil, url.password == nil,
                  url.fragment?.hasPrefix("token=") == true else {
                showFailure("The helper returned an invalid local address. Reinstall Codex Migrate.")
                continue
            }
            dashboardURL = url
            NSWorkspace.shared.open(url)
        }
        if buffer.count > 32_000 { buffer = Data(buffer.suffix(32_000)) }
    }

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        guard let child = process, child.isRunning else { return .terminateNow }
        guard !quitting else { return .terminateCancel }
        guard let url = dashboardURL,
              let token = URLComponents(string: "http://localhost/?" + (url.fragment ?? ""))?.queryItems?.first(where: { $0.name == "token" })?.value,
              var endpoint = URLComponents(url: url, resolvingAgainstBaseURL: false) else {
            return .terminateCancel
        }
        endpoint.path = "/api/shutdown"
        endpoint.fragment = nil
        guard let shutdownURL = endpoint.url else { return .terminateCancel }
        var request = URLRequest(url: shutdownURL)
        request.httpMethod = "POST"
        request.httpBody = Data("{}".utf8)
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue(token, forHTTPHeaderField: "X-Codex-Migrate-Token")
        request.timeoutInterval = 5
        quitting = true
        URLSession.shared.dataTask(with: request) { _, response, _ in
            DispatchQueue.main.async {
                guard self.quitting, self.process != nil else { return }
                guard (response as? HTTPURLResponse)?.statusCode == 200 else {
                    self.quitting = false
                    NSApplication.shared.reply(toApplicationShouldTerminate: false)
                    self.openMigration()
                    return
                }
                // The termination handler completes quitting after the helper
                // closes its server and releases migration locks.
            }
        }.resume()
        return .terminateLater
    }

    private func showFailure(_ message: String) {
        let alert = NSAlert()
        alert.messageText = "Codex Migrate couldn’t open"
        alert.informativeText = message
        alert.addButton(withTitle: "OK")
        alert.runModal()
    }
}
