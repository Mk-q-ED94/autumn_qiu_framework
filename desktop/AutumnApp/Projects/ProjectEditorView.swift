import SwiftUI

/// Modal sheet for creating a new project or editing an existing one.
struct ProjectEditorView: View {
    enum Mode: Equatable {
        case create
        case edit(Project)

        var isCreating: Bool {
            if case .create = self { return true }
            return false
        }
    }

    let mode: Mode
    let onSubmit: (String, String, String) -> Void  // name, instructions, colorTag
    let onCancel: () -> Void

    @State private var name: String
    @State private var instructions: String
    @State private var colorTag: String
    @FocusState private var nameFocused: Bool

    init(
        mode: Mode,
        onSubmit: @escaping (String, String, String) -> Void,
        onCancel: @escaping () -> Void
    ) {
        self.mode = mode
        self.onSubmit = onSubmit
        self.onCancel = onCancel

        switch mode {
        case .create:
            _name = State(initialValue: "")
            _instructions = State(initialValue: "")
            _colorTag = State(initialValue: ProjectPalette.allTags.first ?? "leaf")
        case .edit(let project):
            _name = State(initialValue: project.name)
            _instructions = State(initialValue: project.instructions)
            _colorTag = State(initialValue: project.colorTag)
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: Autumn.spacing.md) {
            header

            VStack(alignment: .leading, spacing: Autumn.spacing.xs) {
                Text("项目名称")
                    .font(Autumn.typography.captionStrong)
                TextField("例如：客户支持机器人", text: $name)
                    .textFieldStyle(.plain)
                    .autumnInputSurface(isFocused: nameFocused)
                    .focused($nameFocused)
                    .onSubmit(submit)
            }

            VStack(alignment: .leading, spacing: Autumn.spacing.xs) {
                Text("项目指令")
                    .font(Autumn.typography.captionStrong)
                Text("项目内的所有对话发送给 A1/A2/A3 时，将在用户输入前附带这段指令。")
                    .font(Autumn.typography.caption)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
                TextEditor(text: $instructions)
                    .font(Autumn.typography.body)
                    .frame(minHeight: 160)
                    .padding(Autumn.spacing.xs)
                    .background(
                        RoundedRectangle(cornerRadius: Autumn.radius.sm, style: .continuous)
                            .fill(Autumn.colors.surfaceElevated)
                    )
                    .overlay(
                        RoundedRectangle(cornerRadius: Autumn.radius.sm, style: .continuous)
                            .strokeBorder(Color.secondary.opacity(0.18), lineWidth: 1)
                    )
            }

            VStack(alignment: .leading, spacing: Autumn.spacing.xs) {
                Text("颜色")
                    .font(Autumn.typography.captionStrong)
                colorPicker
            }

            Spacer(minLength: 0)

            actionRow
        }
        .padding(Autumn.spacing.lg)
        .frame(minWidth: 460, minHeight: 480)
        .onAppear { nameFocused = true }
    }

    private var header: some View {
        HStack(spacing: Autumn.spacing.sm) {
            Image(systemName: ProjectPalette.icon(for: colorTag))
                .foregroundStyle(ProjectPalette.color(for: colorTag))
                .imageScale(.large)
            Text(mode.isCreating ? "新建项目" : "编辑项目")
                .font(Autumn.typography.title)
            Spacer()
        }
    }

    private var colorPicker: some View {
        HStack(spacing: Autumn.spacing.sm) {
            ForEach(ProjectPalette.allTags, id: \.self) { tag in
                Button {
                    colorTag = tag
                } label: {
                    Image(systemName: ProjectPalette.icon(for: tag))
                        .foregroundStyle(.white)
                        .padding(8)
                        .background(
                            Circle().fill(ProjectPalette.color(for: tag))
                        )
                        .overlay(
                            Circle()
                                .strokeBorder(
                                    colorTag == tag ? Color.primary : Color.clear,
                                    lineWidth: 2
                                )
                        )
                }
                .buttonStyle(.plain)
                .help(tag)
            }
            Spacer()
        }
    }

    private var actionRow: some View {
        HStack {
            Spacer()
            Button("取消", action: onCancel)
                .keyboardShortcut(.cancelAction)
            Button(mode.isCreating ? "创建" : "保存", action: submit)
                .keyboardShortcut(.defaultAction)
                .disabled(name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
        }
    }

    private func submit() {
        let cleanedName = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !cleanedName.isEmpty else { return }
        onSubmit(cleanedName, instructions, colorTag)
    }
}
