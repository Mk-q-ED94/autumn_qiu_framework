import SwiftUI

struct WorkspaceCommandActions {
    let newConversation: () -> Void
    let toggleInspector: () -> Void
}

struct ChatCommandActions {
    let clearConversation: () -> Void
    let endSession: () -> Void
    let focusComposer: () -> Void
}

private struct WorkspaceCommandActionsKey: FocusedValueKey {
    typealias Value = WorkspaceCommandActions
}

private struct ChatCommandActionsKey: FocusedValueKey {
    typealias Value = ChatCommandActions
}

extension FocusedValues {
    var workspaceCommandActions: WorkspaceCommandActions? {
        get { self[WorkspaceCommandActionsKey.self] }
        set { self[WorkspaceCommandActionsKey.self] = newValue }
    }

    var chatCommandActions: ChatCommandActions? {
        get { self[ChatCommandActionsKey.self] }
        set { self[ChatCommandActionsKey.self] = newValue }
    }
}
