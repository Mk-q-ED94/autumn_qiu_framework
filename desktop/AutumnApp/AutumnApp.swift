import SwiftUI
#if os(macOS)
import AppKit
#endif

@main
struct QcoworkApp: App {
    #if os(macOS)
    @NSApplicationDelegateAdaptor(QcoworkAppDelegate.self) private var appDelegate
    #endif

    @StateObject private var settings: AppSettings
    @StateObject private var localServer: LocalServerManager
    @StateObject private var ollamaManager: OllamaManager
    @StateObject private var conversations: ConversationStore
    @StateObject private var projects: ProjectStore

    init() {
        let settings = AppSettings()
        let localServer = LocalServerManager()
        let ollamaManager = OllamaManager()
        let conversations = ConversationStore()
        let projects = ProjectStore()

        _settings = StateObject(wrappedValue: settings)
        _localServer = StateObject(wrappedValue: localServer)
        _ollamaManager = StateObject(wrappedValue: ollamaManager)
        _conversations = StateObject(wrappedValue: conversations)
        _projects = StateObject(wrappedValue: projects)

        #if os(macOS)
        QcoworkAppDelegate.settings = settings
        QcoworkAppDelegate.localServer = localServer
        QcoworkAppDelegate.ollamaManager = ollamaManager
        #endif
    }

    var body: some Scene {
        WindowGroup("Qcowork", id: "workspace") {
            ContentView()
                .environmentObject(settings)
                .environmentObject(localServer)
                .environmentObject(ollamaManager)
                .environmentObject(conversations)
                .environmentObject(projects)
                .tint(Qcowork.colors.flame)
        }
        #if os(macOS)
        .windowResizability(.contentSize)
        .commands {
            AppCommands()
        }
        #endif

        #if os(macOS)
        Settings {
            SettingsView()
                .environmentObject(settings)
                .environmentObject(localServer)
                .environmentObject(ollamaManager)
                .tint(Qcowork.colors.flame)
                .frame(minWidth: 760, minHeight: 620)
        }
        #endif
    }
}
