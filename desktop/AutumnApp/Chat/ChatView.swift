import SwiftUI

struct ChatView: View {
    @StateObject private var vm: ChatViewModel

    init(settings: AppSettings) {
        _vm = StateObject(wrappedValue: ChatViewModel(settings: settings))
    }

    var body: some View {
        VStack(spacing: 0) {
            messagesList
            errorBanner
            inputBar
        }
        .navigationTitle("协作")
        .toolbar {
            ToolbarItem(placement: .primaryAction) {
                Menu {
                    Button("清空对话", role: .destructive) { vm.clear() }
                    Button("结束会话") { Task { await vm.endSession() } }
                } label: {
                    Image(systemName: "ellipsis.circle")
                }
            }
        }
    }

    private var messagesList: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 12) {
                    if vm.messages.isEmpty {
                        emptyState
                    } else {
                        ForEach(vm.messages) { message in
                            MessageRow(message: message)
                                .id(message.id)
                        }
                    }
                }
                .padding()
            }
            .onChange(of: vm.messages.last?.id) { _, newID in
                guard let newID else { return }
                withAnimation(.easeOut(duration: 0.2)) {
                    proxy.scrollTo(newID, anchor: .bottom)
                }
            }
        }
    }

    private var emptyState: some View {
        VStack(spacing: 10) {
            Image(systemName: "leaf.fill")
                .font(.system(size: 34))
                .foregroundStyle(.tint)
            Text("开始一次协作")
                .font(.title3.weight(.semibold))
            Text("输入任务、问题或 mission")
                .font(.callout)
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, minHeight: 240)
    }

    @ViewBuilder
    private var errorBanner: some View {
        if let error = vm.errorMessage {
            Text(error)
                .font(.caption)
                .foregroundStyle(.red)
                .padding(.horizontal)
                .padding(.bottom, 4)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    private var inputBar: some View {
        HStack(alignment: .bottom, spacing: 8) {
            TextField("输入消息…", text: $vm.input, axis: .vertical)
                .lineLimit(1...6)
                .textFieldStyle(.roundedBorder)
                .disabled(vm.isRunning)
                .onSubmit { Task { await vm.send() } }

            Button {
                Task { await vm.send() }
            } label: {
                if vm.isRunning {
                    ProgressView().controlSize(.small)
                } else {
                    Image(systemName: "paperplane.fill")
                        .font(.title3)
                }
            }
            .buttonStyle(.borderedProminent)
            .disabled(vm.input.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || vm.isRunning)
        }
        .padding()
        .background(.regularMaterial)
    }
}

private struct MessageRow: View {
    let message: ChatMessage

    var body: some View {
        HStack(alignment: .top) {
            if message.role == .user {
                Spacer(minLength: 40)
                bubble
            } else {
                bubble
                Spacer(minLength: 40)
            }
        }
    }

    private var bubble: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(message.text.isEmpty ? "…" : message.text)
                .textSelection(.enabled)

            if message.role == .assistant, let trace = message.trace {
                WorkflowTraceView(trace: trace)
            }
        }
            .padding(.horizontal, 12)
            .padding(.vertical, 9)
            .background(
                message.role == .user
                    ? Color.accentColor.opacity(0.18)
                    : Color.secondary.opacity(0.12)
            )
            .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
            .frame(maxWidth: 540, alignment: message.role == .user ? .trailing : .leading)
    }
}
