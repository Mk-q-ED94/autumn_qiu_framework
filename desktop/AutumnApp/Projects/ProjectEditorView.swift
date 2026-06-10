import SwiftUI

/// Modal sheet for creating a new project or editing an existing one.
struct ProjectEditorView: View {
    @EnvironmentObject private var settings: AppSettings

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
    @State private var projectType: String = ""
    @State private var projectDescription: String = ""
    @State private var masterGoal: String = ""
    @State private var longTermGoals: String = ""
    @State private var shortTermGoals: String = ""
    @State private var environment = ProjectEnvironmentConfig()
    @State private var metadataInput: String = ""
    @State private var metadataMessage: String?
    @State private var isLoadingMetadata = false
    @State private var isSavingMetadata = false
    @State private var activeMetadataAction: MetadataAction?
    @FocusState private var nameFocused: Bool

    private enum MetadataAction: Equatable {
        case description, goals, environment
    }

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
            ScrollView {
                VStack(alignment: .leading, spacing: Autumn.spacing.lg) {
                    basicsSection
                    if projectIDString != nil {
                        metadataSection
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            actionRow
        }
        .padding(Autumn.spacing.lg)
        .frame(minWidth: 620, minHeight: 680)
        .onAppear { nameFocused = true }
        .task(id: projectIDString) {
            guard projectIDString != nil else { return }
            await loadMetadata()
        }
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

    private var basicsSection: some View {
        VStack(alignment: .leading, spacing: Autumn.spacing.md) {
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
                    .frame(minHeight: 130)
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
        }
    }

    private var metadataSection: some View {
        VStack(alignment: .leading, spacing: Autumn.spacing.md) {
            HStack {
                Label("项目元数据", systemImage: "folder.badge.gearshape")
                    .font(Autumn.typography.headline)
                Spacer()
                if isLoadingMetadata {
                    ProgressView().controlSize(.small)
                } else {
                    Button {
                        Task { await loadMetadata() }
                    } label: {
                        Image(systemName: "arrow.clockwise")
                    }
                    .buttonStyle(.plain)
                    .help("刷新项目元数据")
                }
            }

            HStack(spacing: Autumn.spacing.sm) {
                TextField("项目类型", text: $projectType)
                    .textFieldStyle(.roundedBorder)
                Button {
                    Task { await saveMetadata() }
                } label: {
                    if isSavingMetadata {
                        ProgressView().controlSize(.small)
                    } else {
                        Label("保存元数据", systemImage: "tray.and.arrow.down")
                    }
                }
                .disabled(isSavingMetadata)
            }

            VStack(alignment: .leading, spacing: Autumn.spacing.xs) {
                Text("项目简介")
                    .font(Autumn.typography.captionStrong)
                TextEditor(text: $projectDescription)
                    .font(Autumn.typography.body)
                    .frame(minHeight: 90)
                    .padding(Autumn.spacing.xs)
                    .background(
                        RoundedRectangle(cornerRadius: Autumn.radius.sm, style: .continuous)
                            .fill(Autumn.colors.surfaceElevated)
                    )
            }

            VStack(alignment: .leading, spacing: Autumn.spacing.xs) {
                Text("目标")
                    .font(Autumn.typography.captionStrong)
                TextField("总目标", text: $masterGoal)
                    .textFieldStyle(.roundedBorder)
                TextEditor(text: $longTermGoals)
                    .font(Autumn.typography.caption)
                    .frame(minHeight: 54)
                    .padding(Autumn.spacing.xs)
                    .background(RoundedRectangle(cornerRadius: Autumn.radius.sm).fill(Autumn.colors.surfaceElevated))
                    .overlay(alignment: .topLeading) {
                        if longTermGoals.isEmpty {
                            Text("长期目标，每行一个")
                                .font(Autumn.typography.caption)
                                .foregroundStyle(.tertiary)
                                .padding(Autumn.spacing.xs + 2)
                                .allowsHitTesting(false)
                        }
                    }
                TextEditor(text: $shortTermGoals)
                    .font(Autumn.typography.caption)
                    .frame(minHeight: 54)
                    .padding(Autumn.spacing.xs)
                    .background(RoundedRectangle(cornerRadius: Autumn.radius.sm).fill(Autumn.colors.surfaceElevated))
                    .overlay(alignment: .topLeading) {
                        if shortTermGoals.isEmpty {
                            Text("短期目标，每行一个")
                                .font(Autumn.typography.caption)
                                .foregroundStyle(.tertiary)
                                .padding(Autumn.spacing.xs + 2)
                                .allowsHitTesting(false)
                        }
                    }
            }

            VStack(alignment: .leading, spacing: Autumn.spacing.xs) {
                Text("A4 草稿输入")
                    .font(Autumn.typography.captionStrong)
                TextField("描述你想让 A4 整理的项目想法或目标", text: $metadataInput, axis: .vertical)
                    .lineLimit(2...4)
                    .textFieldStyle(.roundedBorder)
                HStack(spacing: Autumn.spacing.sm) {
                    metadataActionButton("生成简介", icon: "text.quote", action: .description)
                    metadataActionButton("生成目标", icon: "target", action: .goals)
                    metadataActionButton("推断环境", icon: "sparkles", action: .environment)
                    Spacer()
                }
            }

            environmentSummary

            if let metadataMessage {
                Text(metadataMessage)
                    .font(Autumn.typography.caption)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .padding(.top, Autumn.spacing.sm)
    }

    private func metadataActionButton(_ title: String, icon: String, action: MetadataAction) -> some View {
        Button {
            Task { await runMetadataAction(action) }
        } label: {
            if activeMetadataAction == action {
                ProgressView().controlSize(.small)
            } else {
                Label(title, systemImage: icon)
            }
        }
        .disabled(activeMetadataAction != nil)
    }

    @ViewBuilder
    private var environmentSummary: some View {
        let chips = environmentChips
        if !chips.isEmpty {
            VStack(alignment: .leading, spacing: Autumn.spacing.xs) {
                Text("项目环境")
                    .font(Autumn.typography.captionStrong)
                FlowChips(values: chips)
            }
        }
    }

    private var environmentChips: [String] {
        var values: [String] = []
        values += environment.terrs.map { "Terr · \($0)" }
        values += environment.skills.map { "Skill · \($0)" }
        values += environment.tools.map { "Tool · \($0)" }
        values += environment.mcp.map { "MCP · \($0)" }
        if let agent = environment.agentChannel, !agent.isEmpty {
            values.append("Agent · \(agent)")
        }
        return values
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

    private var projectIDString: String? {
        if case .edit(let project) = mode {
            return project.id.uuidString
        }
        return nil
    }

    private var client: AutumnClient? {
        guard let url = URL(string: settings.serverURL) else { return nil }
        return AutumnClient(baseURL: url)
    }

    private func loadMetadata() async {
        guard let projectID = projectIDString, let client else {
            metadataMessage = "服务器 URL 无效"
            return
        }
        isLoadingMetadata = true
        metadataMessage = nil
        defer { isLoadingMetadata = false }

        do {
            applyMetadata(try await client.projectMetadata(projectID: projectID))
            metadataMessage = "元数据已同步"
        } catch {
            metadataMessage = error.localizedDescription
        }
    }

    private func saveMetadata() async {
        guard let projectID = projectIDString, let client else {
            metadataMessage = "服务器 URL 无效"
            return
        }
        isSavingMetadata = true
        metadataMessage = nil
        defer { isSavingMetadata = false }

        let update = ProjectMetadataUpdate(
            projectType: nilIfEmpty(projectType),
            description: projectDescription,
            goals: currentGoals,
            files: nil,
            environment: nil
        )
        do {
            applyMetadata(try await client.updateProjectMetadata(projectID: projectID, update: update))
            metadataMessage = "元数据已保存"
        } catch {
            metadataMessage = error.localizedDescription
        }
    }

    private func runMetadataAction(_ action: MetadataAction) async {
        guard let projectID = projectIDString, let client else {
            metadataMessage = "服务器 URL 无效"
            return
        }
        activeMetadataAction = action
        metadataMessage = nil
        defer { activeMetadataAction = nil }

        do {
            switch action {
            case .description:
                let input = metadataSeedText
                projectDescription = try await client.draftProjectDescription(
                    projectID: projectID,
                    input: input
                )
                metadataMessage = "简介已生成，保存后写入项目"
            case .goals:
                let goals = try await client.draftProjectGoals(
                    projectID: projectID,
                    input: metadataSeedText
                )
                applyGoals(goals)
                metadataMessage = "目标已生成，保存后写入项目"
            case .environment:
                applyMetadata(try await client.inferProjectEnvironment(projectID: projectID))
                metadataMessage = "环境已推断并写入项目"
            }
        } catch {
            metadataMessage = error.localizedDescription
        }
    }

    private var metadataSeedText: String {
        let raw = metadataInput.trimmingCharacters(in: .whitespacesAndNewlines)
        if !raw.isEmpty { return raw }
        return [name, projectDescription, masterGoal, instructions]
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
            .joined(separator: "\n")
    }

    private var currentGoals: ProjectGoalsConfig {
        ProjectGoalsConfig(
            master: masterGoal,
            longTerm: lines(from: longTermGoals),
            shortTerm: lines(from: shortTermGoals)
        )
    }

    private func applyMetadata(_ meta: ProjectMetadata) {
        projectType = meta.projectType ?? ""
        projectDescription = meta.description
        applyGoals(meta.goals)
        environment = meta.environment
    }

    private func applyGoals(_ goals: ProjectGoalsConfig) {
        masterGoal = goals.master
        longTermGoals = goals.longTerm.joined(separator: "\n")
        shortTermGoals = goals.shortTerm.joined(separator: "\n")
    }

    private func lines(from text: String) -> [String] {
        text
            .split(whereSeparator: { $0.isNewline })
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
    }

    private func nilIfEmpty(_ value: String) -> String? {
        let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty ? nil : trimmed
    }
}

private struct FlowChips: View {
    let values: [String]

    var body: some View {
        LazyVGrid(columns: [GridItem(.adaptive(minimum: 96), spacing: Autumn.spacing.xs)],
                  alignment: .leading,
                  spacing: Autumn.spacing.xs) {
            ForEach(values, id: \.self) { value in
                AutumnBadge(value, tone: .info)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
    }
}
