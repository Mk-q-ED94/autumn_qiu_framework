import SwiftUI

/// First-run / empty chat surface.
///
/// Replaces the bare `EmptyStateView` with an inviting welcome and four starter
/// prompts — one per workspace identity (clay / amber / slate / memory) — that
/// *populate* the composer rather than auto-send, so the user can edit and watch
/// A1's intent preview classify the turn before running it. Paper & Clay
/// throughout: tokens only, hairline borders, the single clay accent plus the
/// semantic workspace hues.
struct ChatWelcomeView: View {
    /// Fill the composer with the chosen prompt (caller also focuses it).
    let onPickPrompt: (String) -> Void

    var body: some View {
        VStack(spacing: Qcowork.spacing.xl) {
            header
            LazyVGrid(columns: columns, spacing: Qcowork.spacing.md) {
                ForEach(ChatStarter.catalogue) { starter in
                    StarterCard(starter: starter) { onPickPrompt(starter.prompt) }
                }
            }
            .frame(maxWidth: 540)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .padding(Qcowork.spacing.xl)
    }

    private var columns: [GridItem] {
        [
            GridItem(.flexible(), spacing: Qcowork.spacing.md),
            GridItem(.flexible(), spacing: Qcowork.spacing.md),
        ]
    }

    private var header: some View {
        VStack(spacing: Qcowork.spacing.sm) {
            QcoworkLogoMark(size: 40)
            Text("开始一次协作")
                .font(Qcowork.typography.title)
            Text("选择一个示例，或直接描述你的任务 —— A1 会自动分类并路由到合适的工作区。")
                .font(Qcowork.typography.callout)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
                .fixedSize(horizontal: false, vertical: true)
                .frame(maxWidth: 420)
        }
    }
}

// MARK: - Starter catalogue

/// One suggested opening prompt. Each maps to a workspace identity so the four
/// cards double as a legend for how A1 routes: 直答(clay) · 代码(amber) ·
/// 研究(slate) · 记忆(memory).
private struct ChatStarter: Identifiable {
    let title: String
    let icon: String
    let tint: Color
    let prompt: String

    var id: String { title }

    static let catalogue: [ChatStarter] = [
        ChatStarter(
            title: "快速提问",
            icon: "bubble.left.and.text.bubble.right.fill",
            tint: Qcowork.colors.clay,
            prompt: "用三句话解释 4D 记忆的 aim / use / time 三个维度。"
        ),
        ChatStarter(
            title: "写一段代码",
            icon: "curlybraces",
            tint: Qcowork.colors.warning,
            prompt: "写一个 Python 函数，把 snake_case 字符串转成 camelCase，并附几个测试用例。"
        ),
        ChatStarter(
            title: "联网研究",
            icon: "globe",
            tint: Qcowork.colors.slate,
            prompt: "调研几款适合本地部署的开源大模型推理框架，并对比它们的优劣。"
        ),
        ChatStarter(
            title: "记住偏好",
            icon: "brain.head.profile",
            tint: Qcowork.colors.memory,
            prompt: "记住：我喜欢简洁、要点式、并且附带示例的回答。"
        ),
    ]
}

private struct StarterCard: View {
    let starter: ChatStarter
    let onPick: () -> Void

    @State private var isHovered = false

    var body: some View {
        Button(action: onPick) {
            HStack(alignment: .top, spacing: Qcowork.spacing.sm) {
                Image(systemName: starter.icon)
                    .font(.system(size: 14, weight: .semibold))
                    .foregroundStyle(starter.tint)
                    .frame(width: 30, height: 30)
                    .background(
                        RoundedRectangle(cornerRadius: Qcowork.radius.sm, style: .continuous)
                            .fill(starter.tint.opacity(0.12))
                    )
                VStack(alignment: .leading, spacing: 2) {
                    Text(starter.title)
                        .font(Qcowork.typography.bodyMedium)
                        .foregroundStyle(.primary)
                    Text(starter.prompt)
                        .font(Qcowork.typography.caption)
                        .foregroundStyle(.secondary)
                        .multilineTextAlignment(.leading)
                        .lineLimit(2)
                        .fixedSize(horizontal: false, vertical: true)
                }
                Spacer(minLength: 0)
            }
            .padding(Qcowork.spacing.md)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(
                RoundedRectangle(cornerRadius: Qcowork.radius.md, style: .continuous)
                    .fill(isHovered ? Qcowork.colors.surfaceHover : Qcowork.colors.surfaceElevated)
            )
            .overlay(
                RoundedRectangle(cornerRadius: Qcowork.radius.md, style: .continuous)
                    .strokeBorder(
                        isHovered ? starter.tint.opacity(0.45) : Color.primary.opacity(0.085),
                        lineWidth: Qcowork.stroke.hairline
                    )
            )
        }
        .buttonStyle(.plain)
        .onHover { h in withAnimation(Qcowork.motion.soft) { isHovered = h } }
        .help("把示例填入输入框")
    }
}
