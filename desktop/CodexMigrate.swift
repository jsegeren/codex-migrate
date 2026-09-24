import AppKit
import Sparkle

// The Mac app owns only the local helper's lifetime. All setup, migration,
// progress and recovery decisions belong to the browser.
@main final class AppDelegate: NSObject, NSApplicationDelegate, NSMenuDelegate, SPUUpdaterDelegate {
    private var item: NSStatusItem!
    private var process: Process?
    private var dashboardURL: URL?
    private var buffer = Data()
    private var quitting = false
    private var idleInstallTimer: Timer?
    private var idleProbeInFlight = false
    private var idleInstallHandler: (() -> Void)?
    private var idleInstallShutdownPending = false
    private var idleInstallShutdownConfirmed = false
    private var updateScheduledForQuit = false
    private var updateArchiveReady = false
    private var updateTargetBuild: Int?
    private var quitRequiresUpdateGuard = false
    private var quitShutdownConfirmed = false
    private var updateShutdownAuthorized = false
    private var automaticChecksItem: NSMenuItem!
    private var automaticInstallItem: NSMenuItem!
    private lazy var updaterController = SPUStandardUpdaterController(
        startingUpdater: true, updaterDelegate: self, userDriverDelegate: nil)

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
                                ("Check for Updates…", #selector(checkForUpdates)),
                                ("Link Purchase for Updates…", #selector(linkPurchase)),
                                ("Quit Codex Migrate", #selector(quit))] {
            let entry = NSMenuItem(title: title, action: action, keyEquivalent: "")
            entry.target = self
            menu.addItem(entry)
        }
        automaticChecksItem = NSMenuItem(title: "Check for updates automatically", action: #selector(toggleAutomaticChecks), keyEquivalent: "")
        automaticChecksItem.target = self
        menu.insertItem(automaticChecksItem, at: 2)
        automaticInstallItem = NSMenuItem(title: "Install updates automatically when idle", action: #selector(toggleAutomaticInstall), keyEquivalent: "")
        automaticInstallItem.target = self
        menu.insertItem(automaticInstallItem, at: 3)
        menu.delegate = self
        item.menu = menu
        if InstallLocation.needsMoveToApplications(
            appURL: Bundle.main.bundleURL,
            homeURL: FileManager.default.homeDirectoryForCurrentUser
        ) {
            showFailure("Quit this copy, move Codex Migrate.app into Applications, then open it there. In-app updates may not install from Downloads, a disk image, or a translocated app. Your Codex data has not changed.",
                        title: "Move Codex Migrate to Applications")
            NSApplication.shared.terminate(nil)
            return
        }
        _ = updaterController
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

    func applicationWillTerminate(_ notification: Notification) {
        idleInstallTimer?.invalidate()
    }

    @objc private func checkForUpdates() {
        guard UpdateEntitlement.savedToken() != nil else {
            linkPurchase(); return
        }
        updaterController.checkForUpdates(nil)
    }

    func menuWillOpen(_ menu: NSMenu) {
        let linked = UpdateEntitlement.savedToken() != nil
        automaticChecksItem.isEnabled = linked && !idleInstallShutdownPending
        automaticInstallItem.isEnabled = linked && !idleInstallShutdownPending
        automaticChecksItem.state = updaterController.updater.automaticallyChecksForUpdates ? .on : .off
        automaticInstallItem.state = updaterController.updater.automaticallyDownloadsUpdates ? .on : .off
    }

    @objc private func toggleAutomaticChecks() {
        guard !idleInstallShutdownPending, UpdateEntitlement.savedToken() != nil else { return }
        let updater = updaterController.updater
        updater.automaticallyChecksForUpdates = !updater.automaticallyChecksForUpdates
        if !updater.automaticallyChecksForUpdates {
            updater.automaticallyDownloadsUpdates = false
            idleInstallTimer?.invalidate()
            idleInstallTimer = nil
            idleInstallHandler = nil
        }
    }

    @objc private func toggleAutomaticInstall() {
        guard !idleInstallShutdownPending, UpdateEntitlement.savedToken() != nil else { return }
        let updater = updaterController.updater
        let enabling = !updater.automaticallyDownloadsUpdates
        if enabling { updater.automaticallyChecksForUpdates = true }
        updater.automaticallyDownloadsUpdates = enabling
        if !enabling {
            idleInstallTimer?.invalidate()
            idleInstallTimer = nil
            idleInstallHandler = nil
            updater.resetUpdateCycle()
        }
    }

    @objc private func linkPurchase() {
        let alert = NSAlert()
        alert.messageText = "Link your purchase for updates"
        alert.informativeText = "Paste the private link from your purchase email once. It is stored only in this Mac’s Keychain and checked against your purchase before an update is downloaded."
        let field = NSSecureTextField(frame: NSRect(x: 0, y: 0, width: 420, height: 26))
        field.placeholderString = "Private purchase link"
        alert.accessoryView = field
        alert.addButton(withTitle: "Link Purchase")
        alert.addButton(withTitle: "Cancel")
        guard alert.runModal() == .alertFirstButtonReturn else { return }
        guard let token = UpdateEntitlement.token(from: field.stringValue) else {
            showFailure("Paste the complete private link from your Codex Migrate purchase email.", title: "Invalid purchase link")
            return
        }
        UpdateEntitlement.verify(token) { valid in
            guard valid else {
                self.showFailure("We could not verify this purchase right now. Check the link or email joshua@segeren.com; do not purchase again.", title: "Purchase not verified")
                return
            }
            DispatchQueue.global(qos: .userInitiated).async {
                let saved = UpdateEntitlement.save(token)
                DispatchQueue.main.async {
                    guard saved else {
                        self.showFailure("macOS could not save update access in Keychain. Your purchase is unchanged.", title: "Could not link purchase")
                        return
                    }
                    self.updaterController.updater.automaticallyChecksForUpdates = true
                    self.updaterController.checkForUpdates(nil)
                }
            }
        }
    }

    func updater(_ updater: SPUUpdater, willDownloadUpdate item: SUAppcastItem, with request: NSMutableURLRequest) {
        updateTargetBuild = Int(item.versionString)
        updateArchiveReady = false
        guard request.url?.scheme == "https", request.url?.host == "migrate.segeren.com",
              request.url?.path == "/api/update-archive", let token = UpdateEntitlement.savedToken() else { return }
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
    }

    func updater(_ updater: SPUUpdater, didDownloadUpdate item: SUAppcastItem) {
        updateTargetBuild = Int(item.versionString)
        updateArchiveReady = true
    }

    func updater(_ updater: SPUUpdater, failedToDownloadUpdate item: SUAppcastItem, error: Error) {
        updateArchiveReady = false
    }

    func userDidCancelDownload(_ updater: SPUUpdater) {
        updateArchiveReady = false
    }

    func updater(_ updater: SPUUpdater, willInstallUpdate item: SUAppcastItem) {
        updateTargetBuild = Int(item.versionString)
        updateArchiveReady = true
    }

    func updater(_ updater: SPUUpdater, willInstallUpdateOnQuit item: SUAppcastItem,
                 immediateInstallationBlock install: @escaping () -> Void) -> Bool {
        updateScheduledForQuit = true
        updateTargetBuild = Int(item.versionString)
        updateArchiveReady = true
        // Take control of the staged update so Sparkle can install and relaunch
        // after the helper confirms that no migration or Vault job is active.
        guard updater.automaticallyDownloadsUpdates, UpdateEntitlement.savedToken() != nil else { return false }
        idleInstallHandler = install
        idleInstallTimer?.invalidate()
        idleInstallTimer = Timer.scheduledTimer(withTimeInterval: 60, repeats: true) { [weak self] _ in
            self?.attemptAutomaticInstallWhenIdle()
        }
        // Let Sparkle finish scheduling the install-on-quit before a fast
        // loopback response can initiate application termination.
        DispatchQueue.main.asyncAfter(deadline: .now() + 5) { [weak self] in
            self?.attemptAutomaticInstallWhenIdle()
        }
        return true
    }

    private func attemptAutomaticInstallWhenIdle() {
        guard !quitting, !idleProbeInFlight, !idleInstallShutdownPending,
              idleInstallHandler != nil else { return }
        guard updaterController.updater.automaticallyDownloadsUpdates,
              UpdateEntitlement.savedToken() != nil else {
            idleInstallTimer?.invalidate()
            idleInstallTimer = nil
            return
        }
        guard let child = process else { startHelper(); return }
        guard child.isRunning, let request = helperRequest("/api/update-idle", method: "GET") else { return }
        idleProbeInFlight = true
        URLSession.shared.dataTask(with: request) { _, response, _ in
            DispatchQueue.main.async {
                self.idleProbeInFlight = false
                guard !self.quitting, self.updaterController.updater.automaticallyDownloadsUpdates,
                      self.idleInstallHandler != nil else { return }
                if (response as? HTTPURLResponse)?.statusCode == 200 {
                    self.shutdownHelperForIdleInstall()
                }
            }
        }.resume()
    }

    private func shutdownHelperForIdleInstall() {
        guard !idleInstallShutdownPending, process?.isRunning == true,
              let request = helperRequest("/api/update-shutdown", method: "POST", targetBuild: updateTargetBuild) else { return }
        // This POST rechecks idleness under the helper's action lock. A job
        // started after the GET wins and leaves the app and helper running.
        idleInstallShutdownPending = true
        URLSession.shared.dataTask(with: request) { _, response, _ in
            DispatchQueue.main.async {
                guard self.idleInstallShutdownPending else { return }
                guard (response as? HTTPURLResponse)?.statusCode == 200 else {
                    self.idleInstallShutdownPending = false
                    if self.process == nil { self.startHelper() }
                    return
                }
                self.idleInstallShutdownConfirmed = true
                self.installAfterHelperExit()
            }
        }.resume()
    }

    private func installAfterHelperExit() {
        guard idleInstallShutdownPending, idleInstallShutdownConfirmed,
              process == nil, let install = idleInstallHandler else { return }
        idleInstallShutdownPending = false
        idleInstallShutdownConfirmed = false
        idleInstallHandler = nil
        idleInstallTimer?.invalidate()
        idleInstallTimer = nil
        updateShutdownAuthorized = true
        install() // Sparkle owns signature verification, replacement and relaunch.
    }

    private func startHelper() {
        guard process == nil else { return }
        // Reopen/menu events can arrive while the first-launch alert is up.
        // No helper may run from a path Sparkle cannot replace safely.
        guard !InstallLocation.needsMoveToApplications(
            appURL: Bundle.main.bundleURL,
            homeURL: FileManager.default.homeDirectoryForCurrentUser
        ) else { return }
        guard let resources = Bundle.main.resourceURL else {
            showFailure("The app is missing its resources. Reinstall Codex Migrate.")
            return
        }
        let child = Process()
        child.executableURL = resources.appendingPathComponent("engine/codex-migrate-engine")
        var arguments = ["launch", "--port", "0", "--no-open"]
        if let installedBuild = Int(Bundle.main.object(forInfoDictionaryKey: "CFBundleVersion") as? String ?? "") {
            arguments += ["--resume-after-update-build", String(installedBuild)]
        }
        child.arguments = arguments
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
                if self.idleInstallShutdownPending {
                    self.installAfterHelperExit()
                } else if self.quitting {
                    // An early helper exit is not proof that the update guard
                    // was committed. Wait for the shutdown HTTP 200 before
                    // allowing Sparkle to replace the bundle.
                    if !self.quitRequiresUpdateGuard || self.quitShutdownConfirmed {
                        NSApplication.shared.terminate(nil)
                    }
                } else if child.terminationStatus == 0 || child.terminationStatus == 130 {
                    if (self.updateScheduledForQuit || self.updateArchiveReady) &&
                        !self.updateShutdownAuthorized && !self.quitShutdownConfirmed {
                        // The helper can exit before the network reply. Do
                        // not let its exit status stand in for a Vault guard.
                        self.startHelper()
                    } else {
                        NSApplication.shared.terminate(nil)
                    }
                } else if child.terminationStatus == 75 {
                    let peers = NSRunningApplication.runningApplications(
                        withBundleIdentifier: Bundle.main.bundleIdentifier ?? ""
                    ).map { (pid: $0.processIdentifier, bundleURL: $0.bundleURL) }
                    if DuplicateLaunch.sameCopyIsRunning(
                        ownURL: Bundle.main.bundleURL,
                        ownPID: ProcessInfo.processInfo.processIdentifier,
                        candidates: peers
                    ) {
                        // Sparkle can reopen the installed bundle twice. The copy
                        // that lost the helper lock should exit without alarming
                        // the buyer; the healthy copy remains open.
                        NSApplication.shared.terminate(nil)
                    } else {
                        self.showFailure("Continue in the existing browser tab. To switch copies, finish or stop the current operation safely, then choose Quit Codex Migrate from its menu-bar icon and reopen this copy. This copy hasn’t changed your migration data.", title: "Codex Migrate is already running")
                    }
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
        // A check or incomplete download cannot replace the bundle. A staged
        // archive can, even if Sparkle's session flag changes during quit.
        let updatePending = updateScheduledForQuit || updateArchiveReady
        guard let child = process, child.isRunning else {
            if (updatePending || updateArchiveReady ||
                (quitting && quitRequiresUpdateGuard)) &&
                !updateShutdownAuthorized &&
                !(quitting && quitRequiresUpdateGuard && quitShutdownConfirmed) {
                // A crashed/missing helper cannot prove the cross-process
                // Vault guard. Reopen it and refuse this install attempt.
                if process == nil { startHelper() }
                return .terminateCancel
            }
            return .terminateNow
        }
        guard !quitting else { return .terminateCancel }
        let endpoint = updatePending ? "/api/update-shutdown" : "/api/shutdown"
        guard let request = helperRequest(endpoint, method: "POST", targetBuild: updateTargetBuild) else { return .terminateCancel }
        quitting = true
        quitRequiresUpdateGuard = updatePending
        quitShutdownConfirmed = false
        URLSession.shared.dataTask(with: request) { _, response, _ in
            DispatchQueue.main.async {
                guard self.quitting else { return }
                guard (response as? HTTPURLResponse)?.statusCode == 200 else {
                    self.quitting = false
                    self.quitRequiresUpdateGuard = false
                    self.quitShutdownConfirmed = false
                    self.openMigration()
                    return
                }
                self.quitShutdownConfirmed = true
                // The helper may have exited before its response reached us.
                // In that case the termination handler could not request the
                // fresh quit, so do it here after the guard is confirmed.
                if self.process?.isRunning != true {
                    NSApplication.shared.terminate(nil)
                }
            }
        }.resume()
        return .terminateCancel
    }

    private func helperRequest(_ path: String, method: String, targetBuild: Int? = nil) -> URLRequest? {
        guard let url = dashboardURL,
              let token = URLComponents(string: "http://localhost/?" + (url.fragment ?? ""))?.queryItems?.first(where: { $0.name == "token" })?.value,
              var endpoint = URLComponents(url: url, resolvingAgainstBaseURL: false) else { return nil }
        endpoint.path = path
        endpoint.query = nil
        endpoint.fragment = nil
        guard let requestURL = endpoint.url else { return nil }
        var request = URLRequest(url: requestURL)
        request.httpMethod = method
        request.setValue(token, forHTTPHeaderField: "X-Codex-Migrate-Token")
        request.timeoutInterval = 5
        if method == "POST" {
            request.httpBody = Data("{}".utf8)
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        }
        if path == "/api/update-shutdown" {
            guard let targetBuild, targetBuild > 0 else { return nil }
            request.setValue(String(targetBuild), forHTTPHeaderField: "X-Codex-Migrate-Target-Build")
        }
        return request
    }

    private func showFailure(_ message: String, title: String = "Codex Migrate couldn’t open") {
        let alert = NSAlert()
        alert.messageText = title
        alert.informativeText = message
        alert.addButton(withTitle: "OK")
        alert.runModal()
    }
}
