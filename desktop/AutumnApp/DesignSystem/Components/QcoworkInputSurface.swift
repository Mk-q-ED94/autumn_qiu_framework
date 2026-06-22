import SwiftUI

extension View {
    func autumnInputSurface(isFocused: Bool = false) -> some View {
        self
            .padding(.horizontal, Qcowork.spacing.md)
            .padding(.vertical, Qcowork.spacing.sm)
            .background(
                RoundedRectangle(cornerRadius: Qcowork.radius.md, style: .continuous)
                    .fill(Qcowork.colors.surfaceElevated)
            )
            .overlay(
                RoundedRectangle(cornerRadius: Qcowork.radius.md, style: .continuous)
                    .strokeBorder(
                        isFocused ? Qcowork.colors.flame.opacity(0.65) : Qcowork.colors.gold.opacity(0.16),
                        lineWidth: isFocused ? Qcowork.stroke.medium : Qcowork.stroke.hairline
                    )
            )
    }
}
