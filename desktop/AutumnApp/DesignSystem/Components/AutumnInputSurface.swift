import SwiftUI

extension View {
    func autumnInputSurface(isFocused: Bool = false) -> some View {
        self
            .padding(.horizontal, Autumn.spacing.md)
            .padding(.vertical, Autumn.spacing.sm)
            .background(
                RoundedRectangle(cornerRadius: Autumn.radius.md, style: .continuous)
                    .fill(Autumn.colors.surfaceElevated)
            )
            .overlay(
                RoundedRectangle(cornerRadius: Autumn.radius.md, style: .continuous)
                    .strokeBorder(
                        isFocused ? Autumn.colors.flame.opacity(0.65) : Autumn.colors.gold.opacity(0.16),
                        lineWidth: isFocused ? Autumn.stroke.medium : Autumn.stroke.hairline
                    )
            )
    }
}
