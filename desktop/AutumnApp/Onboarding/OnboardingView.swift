import SwiftUI

/// First-run welcome screen shown when no model credentials are set.
struct OnboardingView: View {
    let onDismiss: () -> Void
    let onOpenSettings: () -> Void

    var body: some View {
        ZStack {
            AutumnPageBackground()

            VStack(spacing: Autumn.spacing.xl) {
                hero
                features
                actions
            }
            .padding(Autumn.spacing.xxl)
            .frame(maxWidth: 720)
        }
    }

    // ── pieces ──

    private var hero: some View {
        VStack(spacing: Autumn.spacing.md) {
            ZStack {
                Circle()
                    .fill(Autumn.colors.gold.opacity(0.18))
                    .frame(width: 96, height: 96)
                Image(systemName: "leaf.fill")
                    .font(.system(size: 42, weight: .medium))
                    .foregroundStyle(Autumn.colors.brandGradient)
            }

            VStack(spacing: Autumn.spacing.xs) {
                Text("欢迎使用 秋 Autumn")
                    .font(Autumn.typography.display)
                Text("三模型协作的工作流框架")
                    .font(Autumn.typography.callout)
                    .foregroundStyle(.secondary)
            }
        }
    }

    private var features: some View {
        HStack(alignment: .top, spacing: Autumn.spacing.md) {
            FeatureCard(
                icon: "wand.and.stars",
                title: "A1 总控",
                detail: "路由分类、最终质检。"
            )
            FeatureCard(
                icon: "checklist",
                title: "A2 任务",
                detail: "执行结构化任务。"
            )
            FeatureCard(
                icon: "bubble.left.and.bubble.right",
                title: "A3 协作",
                detail: "对话、转换 mission。"
            )
        }
    }

    private var actions: some View {
        VStack(spacing: Autumn.spacing.sm) {
            AutumnPrimaryButton(
                size: .large,
                action: onOpenSettings
            ) {
                HStack(spacing: Autumn.spacing.sm) {
                    Image(systemName: "key.fill")
                    Text("配置 A1 / A2 / A3 模型")
                }
            }

            AutumnGhostButton(action: onDismiss) {
                Text("稍后再说")
            }
        }
    }
}

private struct FeatureCard: View {
    let icon: String
    let title: String
    let detail: String

    var body: some View {
        AutumnCard(emphasis: .standard) {
            VStack(alignment: .leading, spacing: Autumn.spacing.sm) {
                Image(systemName: icon)
                    .font(.system(size: 20, weight: .medium))
                    .foregroundStyle(.tint)
                Text(title)
                    .font(Autumn.typography.headline)
                Text(detail)
                    .font(Autumn.typography.caption)
                    .foregroundStyle(.secondary)
            }
        }
    }
}
