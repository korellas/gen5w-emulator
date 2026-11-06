import AppKit
import UniformTypeIdentifiers

final class USBApp: NSObject, NSApplicationDelegate {
    private var window: NSWindow!
    private let status = NSTextField(wrappingLabelWithString: "에뮬레이터 확인 중…")
    private let insert = NSButton(title: "삽입", target: nil, action: nil)
    private let eject = NSButton(title: "꺼내기", target: nil, action: nil)
    private let progress = NSProgressIndicator()
    private var busy = false
    private var timer: Timer?

    func applicationDidFinishLaunching(_ notification: Notification) {
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 380, height: 176),
                          styleMask: [.titled, .closable, .miniaturizable],
                          backing: .buffered, defer: false)
        window.title = "Gen5W 가상 USB"
        window.isReleasedWhenClosed = false
        let title = NSTextField(labelWithString: "가상 USB")
        title.font = .boldSystemFont(ofSize: 17)
        status.font = .systemFont(ofSize: 12)
        status.textColor = .secondaryLabelColor
        status.maximumNumberOfLines = 2
        insert.target = self
        insert.action = #selector(chooseZip)
        eject.target = self
        eject.action = #selector(ejectDisk)
        for button in [insert, eject] {
            button.bezelStyle = .rounded
            button.widthAnchor.constraint(equalToConstant: 132).isActive = true
            button.isEnabled = false
        }
        progress.style = .spinning
        progress.controlSize = .small
        progress.isDisplayedWhenStopped = false
        let buttons = NSStackView(views: [insert, eject, progress])
        buttons.spacing = 10
        let stack = NSStackView(views: [title, status, buttons])
        stack.orientation = .vertical
        stack.alignment = .leading
        stack.spacing = 16
        stack.translatesAutoresizingMaskIntoConstraints = false
        window.contentView!.addSubview(stack)
        NSLayoutConstraint.activate([
            stack.leadingAnchor.constraint(equalTo: window.contentView!.leadingAnchor, constant: 24),
            stack.trailingAnchor.constraint(equalTo: window.contentView!.trailingAnchor, constant: -24),
            stack.topAnchor.constraint(equalTo: window.contentView!.topAnchor, constant: 22)
        ])
        window.center()
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        run("status")
        timer = Timer.scheduledTimer(withTimeInterval: 4, repeats: true) { [weak self] _ in
            if self?.busy == false { self?.run("status") }
        }
    }

    @objc private func chooseZip() {
        let panel = NSOpenPanel()
        panel.title = "USB에 넣을 ZIP 선택"
        panel.allowedContentTypes = [.zip]
        panel.allowsMultipleSelection = false
        panel.canChooseDirectories = false
        panel.beginSheetModal(for: window) { [weak self] response in
            if response == .OK, let url = panel.url { self?.run("insert", path: url.path) }
        }
    }

    @objc private func ejectDisk() { run("eject") }

    private func run(_ action: String, path: String? = nil) {
        guard !busy else { return }
        busy = true
        insert.isEnabled = false
        eject.isEnabled = false
        if action != "status" {
            status.stringValue = action == "insert" ? "USB 사본 생성·연결 중…" : "안전하게 꺼내는 중…"
            progress.startAnimation(nil)
        }
        let info = Bundle.main.infoDictionary!
        let python = info["Gen5WPython"] as! String
        let project = info["Gen5WProject"] as! String
        let helper = Bundle.main.resourceURL!.appendingPathComponent("usb_control.py").path
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            let task = Process()
            task.executableURL = URL(fileURLWithPath: python)
            task.arguments = ["-B", helper, "--root", project, action] + (path.map { [$0] } ?? [])
            let output = Pipe()
            let errors = Pipe()
            task.standardOutput = output
            task.standardError = errors
            var result: [String: Any]
            do {
                try task.run()
                let data = output.fileHandleForReading.readDataToEndOfFile()
                task.waitUntilExit()
                result = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
                    ?? ["error": "USB 도우미를 실행하지 못했습니다."]
            } catch { result = ["error": error.localizedDescription] }
            DispatchQueue.main.async {
                guard let self = self else { return }
                self.busy = false
                self.progress.stopAnimation(nil)
                if let error = result["error"] as? String {
                    self.status.stringValue = error
                    if action != "status" {
                        let alert = NSAlert()
                        alert.messageText = "USB 작업을 완료하지 못했습니다"
                        alert.informativeText = error
                        alert.beginSheetModal(for: self.window)
                    }
                    return
                }
                let attached = result["attached"] as? Bool ?? false
                self.insert.isEnabled = !attached && (result["ready"] as? Bool ?? false)
                self.eject.isEnabled = attached
                self.status.stringValue = result["message"] as? String ?? "USB가 연결되지 않았습니다."
            }
        }
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
}

let application = NSApplication.shared
let delegate = USBApp()
application.setActivationPolicy(.regular)
application.delegate = delegate
let menu = NSMenu()
let item = NSMenuItem()
let submenu = NSMenu()
submenu.addItem(withTitle: "종료", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
item.submenu = submenu
menu.addItem(item)
application.mainMenu = menu
application.run()
