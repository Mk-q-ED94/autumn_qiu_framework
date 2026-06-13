import SwiftUI
#if os(macOS)
import AppKit
#endif

@main
struct AutumnApp: App {
    #if os(macOS)
    @NSApplicationDelegateAdaptor(AutumnAppDelegate.self) private var appDelegate
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
        AutumnAppDelegate.settings = settings
        AutumnAppDelegate.localServer = localServer
        AutumnAppDelegate.ollamaManager = ollamaManager
        #endif
    }

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(settings)
                .environmentObject(localServer)
                .environmentObject(ollamaManager)
                .environmentObject(conversations)
                .environmentObject(projects)
                .tint(Autumn.colors.flame)
        }
        #if os(macOS)
        .windowResizability(.contentSize)
        .commands {
            AppCommands()
        }
        #endif
    }
}
