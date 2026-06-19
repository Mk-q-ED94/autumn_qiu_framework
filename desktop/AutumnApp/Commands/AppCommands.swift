import SwiftUI

/// Menu bar commands wired to ⌘ shortcuts. Mounted on the WindowGroup.
struct AppCommands: Commands {
    @FocusedValue(\.workspaceCommandActions) private var workspaceActions
    @FocusedValue(\.chatCommandActions) private var chatActions

    var body: some Commands {
        CommandGroup(replacing: .newItem) {
            Button("新对话") {
                workspaceActions?.newConversation()
            }
            .keyboardShortcut("n", modifiers: .command)
            .disabled(workspaceActions == nil)
        }

        CommandMenu("会话") {
            Button("清空当前对话") {
                chatActions?.clearConversation()
            }
            .keyboardShortcut("k", modifiers: [.command, .shift])
            .disabled(chatActions == nil)

            Button("结束会话（清空短期记忆）") {
                chatActions?.endSession()
            }
            .keyboardShortcut("e", modifiers: [.command, .shift])
            .disabled(chatActions == nil)

            Divider()

            Button("聚焦输入框") {
                chatActions?.focusComposer()
            }
            .keyboardShortcut("l", modifiers: .command)
            .disabled(chatActions == nil)

            Button("切换检视面板") {
                workspaceActions?.toggleInspector()
            }
            .keyboardShortcut("i", modifiers: [.command, .shift])
            .disabled(workspaceActions == nil)
        }

        CommandGroup(replacing: .appSettings) {
            SettingsLink {
                Text("设置…")
            }
            .keyboardShortcut(",", modifiers: .command)
        }
    }
}
