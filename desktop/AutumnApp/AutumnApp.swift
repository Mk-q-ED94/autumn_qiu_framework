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
    @StateObject private var conversations: ConversationStore
    @StateObject private var projects: ProjectStore

    init() {
        let settings = AppSettings()
        let localServer = LocalServerManager()
        let conversations = ConversationStore()
        let projects = ProjectStore()

        _settings = StateObject(wrappedValue: settings)
        _localServer = StateObject(wrappedValue: localServer)
        _conversations = StateObject(wrappedValue: conversations)
        _projects = StateObject(wrappedValue: projects)

        #if os(macOS)
        AutumnAppDelegate.settings = settings
        AutumnAppDelegate.localServer = localServer
        #endif
    }

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(settings)
                .environmentObject(localServer)
                .environmentObject(conversations)
                .environmentObject(projects)
                .tint(Color.accentColor)
        }
        #if os(macOS)
        .windowResizability(.contentSize)
        .commands {
            AppCommands()
        }
        #endif
    }
}
