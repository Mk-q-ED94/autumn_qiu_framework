import SwiftUI

/// First-run welcome screen shown when no model credentials are set.
struct OnboardingView: View {
    let onDismiss: () -> Void
    let onOpenSettings: () -> Void

    var body: some View {
        ZStack {
            QcoworkPageBackground()

            VStack(spacing: Qcowork.spacing.xl) {
                hero
                features
                actions
            }
            .padding(Qcowork.spacing.xxl)
            .frame(maxWidth: 720)
        }
    }

    // ── pieces ──

    private var hero: some View {
        VStack(spacing: Qcowork.spacing.md) {
            ZStack {
                Circle()
                    .fill(Qcowork.colors.gold.opacity(0.18))
                    .frame(width: 96, height: 96)
                Image(systemName: "leaf.fill")
                    .font(.system(size: 42, weight: .medium))
                    .foregroundStyle(Qcowork.colors.brandGradient)
            }

            VStack(spacing: Qcowork.spacing.xs) {
                Text("欢迎使用 Qcowork")
                    .font(Qcowork.typography.display)
                Text("三模型协作的工作流框架")
                    .font(Qcowork.typography.callout)
                    .foregroundStyle(.secondary)
            }
        }
    }

    private var features: some View {
        HStack(alignment: .top, spacing: Qcowork.spacing.md) {
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
        VStack(spacing: Qcowork.spacing.sm) {
            QcoworkPrimaryButton(
                size: .large,
                action: onOpenSettings
            ) {
                HStack(spacing: Qcowork.spacing.sm) {
                    Image(systemName: "key.fill")
                    Text("配置 A1 / A2 / A3 模型")
                }
            }

            QcoworkGhostButton(action: onDismiss) {
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
        QcoworkCard(emphasis: .standard) {
            VStack(alignment: .leading, spacing: Qcowork.spacing.sm) {
                Image(systemName: icon)
                    .font(.system(size: 20, weight: .medium))
                    .foregroundStyle(.tint)
                Text(title)
                    .font(Qcowork.typography.headline)
                Text(detail)
                    .font(Qcowork.typography.caption)
                    .foregroundStyle(.secondary)
            }
        }
    }
}
