import SwiftUI

/// Consistent empty / first-run state for any screen.
struct EmptyStateView: View {
    let icon: String
    let title: String
    let message: String
    let actionTitle: String?
    let action: (() -> Void)?

    init(
        icon: String,
        title: String,
        message: String,
        actionTitle: String? = nil,
        action: (() -> Void)? = nil
    ) {
        self.icon = icon
        self.title = title
        self.message = message
        self.actionTitle = actionTitle
        self.action = action
    }

    var body: some View {
        VStack(spacing: Qcowork.spacing.md) {
            ZStack {
                Circle()
                    .fill(Qcowork.colors.brandGradient)
                    .frame(width: 72, height: 72)
                    .opacity(0.92)
                Image(systemName: icon)
                    .font(.system(size: 30, weight: .medium))
                    .foregroundStyle(.white)
            }
            VStack(spacing: Qcowork.spacing.xs) {
                Text(title)
                    .font(Qcowork.typography.title)
                Text(message)
                    .font(Qcowork.typography.callout)
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)
                    .fixedSize(horizontal: false, vertical: true)
                    .frame(maxWidth: 380)
            }
            if let actionTitle, let action {
                QcoworkPrimaryButton(action: action) {
                    Text(actionTitle)
                }
                .padding(.top, Qcowork.spacing.xs)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .padding(Qcowork.spacing.xl)
    }
}
