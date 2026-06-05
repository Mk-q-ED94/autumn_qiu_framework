import SwiftUI

/// Global notification names that menu commands use to talk to the active scene.
extension Notification.Name {
    static let autumnNewConversation = Notification.Name("autumn.newConversation")
    static let autumnClearConversation = Notification.Name("autumn.clearConversation")
    static let autumnEndSession = Notification.Name("autumn.endSession")
    static let autumnFocusComposer = Notification.Name("autumn.focusComposer")
    static let autumnToggleInspector = Notification.Name("autumn.toggleInspector")
    static let autumnOpenSettings = Notification.Name("autumn.openSettings")
}

/// Menu bar commands wired to ⌘ shortcuts. Mounted on the WindowGroup.
struct AppCommands: Commands {
    var body: some Commands {
        CommandGroup(replacing: .newItem) {
            Button("新对话") {
                NotificationCenter.default.post(name: .autumnNewConversation, object: nil)
            }
            .keyboardShortcut("n", modifiers: .command)
        }

        CommandMenu("会话") {
            Button("清空当前对话") {
                NotificationCenter.default.post(name: .autumnClearConversation, object: nil)
            }
            .keyboardShortcut("k", modifiers: [.command, .shift])

            Button("结束会话（清空短期记忆）") {
                NotificationCenter.default.post(name: .autumnEndSession, object: nil)
            }
            .keyboardShortcut("e", modifiers: [.command, .shift])

            Divider()

            Button("聚焦输入框") {
                NotificationCenter.default.post(name: .autumnFocusComposer, object: nil)
            }
            .keyboardShortcut("l", modifiers: .command)

            Button("切换检视面板") {
                NotificationCenter.default.post(name: .autumnToggleInspector, object: nil)
            }
            .keyboardShortcut("i", modifiers: [.command, .shift])
        }

        CommandGroup(replacing: .appSettings) {
            Button("设置…") {
                NotificationCenter.default.post(name: .autumnOpenSettings, object: nil)
            }
            .keyboardShortcut(",", modifiers: .command)
        }
    }
}
