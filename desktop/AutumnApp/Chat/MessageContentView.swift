import SwiftUI
#if os(macOS)
import AppKit
#elseif os(iOS)
import UIKit
#endif

/// Renders a message body by parsing fenced markdown code blocks and rendering each
/// segment with the appropriate affordances — selectable text for prose, copy-on-hover
/// for code. Plain text segments use SwiftUI's `LocalizedStringKey` markdown so bold /
/// italic / links still render inline.
struct MessageContentView: View {
    let text: String

    var body: some View {
        VStack(alignment: .leading, spacing: Autumn.spacing.sm) {
            ForEach(Array(MessageContentParser.parse(text).enumerated()), id: \.offset) { _, segment in
                segmentView(for: segment)
            }
        }
    }

    @ViewBuilder
    private func segmentView(for segment: MessageSegment) -> some View {
        switch segment {
        case .text(let content):
            let trimmed = content.trimmingCharacters(in: .whitespacesAndNewlines)
            if !trimmed.isEmpty {
                Text(.init(content))
                    .font(Autumn.typography.body)
                    .textSelection(.enabled)
                    .fixedSize(horizontal: false, vertical: true)
            }
        case .code(let language, let code):
            CodeBlockView(language: language, code: code)
        }
    }
}

enum MessageSegment: Equatable {
    case text(String)
    case code(language: String?, content: String)
}

enum MessageContentParser {
    /// Parse fenced code blocks of the form ``` `lang\n…\n` ``` out of `text`.
    /// Anything outside a fence is returned as a text segment so caller-side
    /// markdown rendering still applies.
    static func parse(_ text: String) -> [MessageSegment] {
        // Pattern captures: opening fence + optional language token + body + closing fence.
        // dotMatchesLineSeparators lets `.` cross newlines inside the body.
        let pattern = #"```([A-Za-z0-9_+\-.]*)\n([\s\S]*?)```"#
        guard let regex = try? NSRegularExpression(pattern: pattern, options: [.dotMatchesLineSeparators]) else {
            return [.text(text)]
        }
        let nsText = text as NSString
        let matches = regex.matches(in: text, range: NSRange(location: 0, length: nsText.length))

        var segments: [MessageSegment] = []
        var cursor = 0
        for match in matches {
            let fullRange = match.range
            if fullRange.location > cursor {
                let pre = nsText.substring(with: NSRange(location: cursor, length: fullRange.location - cursor))
                segments.append(.text(pre))
            }
            let langRange = match.range(at: 1)
            let codeRange = match.range(at: 2)
            let lang = langRange.length > 0 ? nsText.substring(with: langRange) : nil
            let code = nsText.substring(with: codeRange)
            segments.append(.code(language: lang, content: code))
            cursor = fullRange.location + fullRange.length
        }
        if cursor < nsText.length {
            segments.append(.text(nsText.substring(from: cursor)))
        }
        return segments.isEmpty ? [.text(text)] : segments
    }
}

private struct CodeBlockView: View {
    let language: String?
    let code: String
    @State private var isHovering: Bool = false
    @State private var copied: Bool = false

    var body: some View {
        ZStack(alignment: .topTrailing) {
            ScrollView(.horizontal, showsIndicators: false) {
                Text(code)
                    .font(.system(.callout, design: .monospaced))
                    .textSelection(.enabled)
                    .padding(Autumn.spacing.md)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            .background(
                RoundedRectangle(cornerRadius: Autumn.radius.sm, style: .continuous)
                    .fill(Color.primary.opacity(0.05))
            )
            .overlay(
                RoundedRectangle(cornerRadius: Autumn.radius.sm, style: .continuous)
                    .strokeBorder(Color.secondary.opacity(0.12), lineWidth: Autumn.stroke.hairline)
            )

            HStack(spacing: Autumn.spacing.xs) {
                if let language, !language.isEmpty {
                    Text(language)
                        .font(.system(.caption2, design: .monospaced).weight(.semibold))
                        .foregroundStyle(.secondary)
                        .padding(.horizontal, 6)
                        .padding(.vertical, 2)
                        .background(
                            RoundedRectangle(cornerRadius: Autumn.radius.xs, style: .continuous)
                                .fill(Color.secondary.opacity(0.15))
                        )
                        .opacity(isHovering || copied ? 1 : 0.6)
                }

                if isHovering || copied {
                    Button(action: copyToClipboard) {
                        HStack(spacing: 4) {
                            Image(systemName: copied ? "checkmark" : "doc.on.doc")
                                .font(.caption2.weight(.semibold))
                            Text(copied ? "已复制" : "复制")
                                .font(.caption2.weight(.medium))
                        }
                        .padding(.horizontal, 8)
                        .padding(.vertical, 4)
                        .background(.regularMaterial)
                        .foregroundStyle(copied ? Autumn.colors.success : .primary)
                        .clipShape(Capsule())
                    }
                    .buttonStyle(.plain)
                    .transition(.opacity.combined(with: .scale(scale: 0.92)))
                }
            }
            .padding(Autumn.spacing.xs)
            .animation(Autumn.motion.snappy, value: isHovering)
            .animation(Autumn.motion.snappy, value: copied)
        }
        .onHover { hovering in
            isHovering = hovering
        }
    }

    private func copyToClipboard() {
        #if os(macOS)
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(code, forType: .string)
        #elseif os(iOS)
        UIPasteboard.general.string = code
        #endif
        copied = true
        Task {
            try? await Task.sleep(nanoseconds: 1_500_000_000)
            await MainActor.run { copied = false }
        }
    }
}
