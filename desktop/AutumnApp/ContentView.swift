import SwiftUI

struct ContentView: View {
    @EnvironmentObject private var settings: AppSettings

    var body: some View {
        TabView {
            NavigationStack {
                ChatView(settings: settings)
            }
            .tabItem {
                Label("聊天", systemImage: "bubble.left.and.bubble.right")
            }

            NavigationStack {
                SettingsView()
            }
            .tabItem {
                Label("设置", systemImage: "gearshape")
            }
        }
        #if os(macOS)
        .frame(minWidth: 520, minHeight: 640)
        #endif
    }
}

#Preview {
    ContentView()
        .environmentObject(AppSettings())
}
