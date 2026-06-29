import SwiftUI

/// Block-level markdown for chat prose.
///
/// SwiftUI's `Text(LocalizedStringKey)` renders *inline* markdown (bold, italic,
/// `code`, links) but not block elements, so bullet/numbered lists and headings
/// otherwise show up as literal `- item` / `## Heading` text. This view splits a
/// prose segment into blocks and styles lists and headings, while every plain
/// paragraph still goes through the same inline-markdown `Text` as before — so
/// anything not confidently recognised renders exactly as it did, never worse.
///
/// Fenced code blocks are split out upstream by `MessageContentParser`, so this
/// only ever sees prose.
struct MarkdownBlockView: View {
    let text: String

    var body: some View {
        VStack(alignment: .leading, spacing: Qcowork.spacing.sm) {
            ForEach(Array(MarkdownBlockParser.parse(text).enumerated()), id: \.offset) { _, block in
                blockView(block)
            }
        }
    }

    @ViewBuilder
    private func blockView(_ block: MarkdownBlock) -> some View {
        switch block {
        case .heading(let level, let content):
            Text(.init(content))
                .font(headingFont(level))
                .textSelection(.enabled)
                .fixedSize(horizontal: false, vertical: true)
        case .paragraph(let content):
            Text(.init(content))
                .font(Qcowork.typography.body)
                .textSelection(.enabled)
                .fixedSize(horizontal: false, vertical: true)
        case .bulleted(let items):
            listBlock(items.enumerated().map { (_, item) in (marker: "•", item: item) })
        case .numbered(let items):
            listBlock(items.enumerated().map { (idx, item) in (marker: "\(idx + 1).", item: item) })
        }
    }

    private func listBlock(_ rows: [(marker: String, item: String)]) -> some View {
        VStack(alignment: .leading, spacing: Qcowork.spacing.xs) {
            ForEach(Array(rows.enumerated()), id: \.offset) { _, row in
                HStack(alignment: .top, spacing: Qcowork.spacing.sm) {
                    Text(row.marker)
                        .font(Qcowork.typography.body)
                        .foregroundStyle(.secondary)
                        .frame(minWidth: 16, alignment: .trailing)
                    Text(.init(row.item))
                        .font(Qcowork.typography.body)
                        .textSelection(.enabled)
                        .fixedSize(horizontal: false, vertical: true)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
            }
        }
        .padding(.leading, Qcowork.spacing.xs)
    }

    private func headingFont(_ level: Int) -> Font {
        switch level {
        case 1:  return Qcowork.typography.title
        case 2:  return Qcowork.typography.headline
        default: return Qcowork.typography.bodyMedium
        }
    }
}

// MARK: - Parser

enum MarkdownBlock: Equatable {
    case heading(level: Int, text: String)
    case paragraph(String)
    case bulleted([String])
    case numbered([String])
}

enum MarkdownBlockParser {
    /// Split prose into block elements. Conservative: a line becomes a list item
    /// or heading only on an unambiguous prefix (`- ` / `* ` / `+ `, `1. ` / `1) `,
    /// `#`–`###` + space); everything else accumulates into paragraphs joined with
    /// their original newlines, so non-list prose renders identically to before.
    static func parse(_ text: String) -> [MarkdownBlock] {
        var blocks: [MarkdownBlock] = []
        var paragraph: [String] = []
        var bullets: [String] = []
        var numbers: [String] = []

        func flushParagraph() {
            if !paragraph.isEmpty {
                blocks.append(.paragraph(paragraph.joined(separator: "\n")))
                paragraph.removeAll()
            }
        }
        func flushBullets() {
            if !bullets.isEmpty { blocks.append(.bulleted(bullets)); bullets.removeAll() }
        }
        func flushNumbers() {
            if !numbers.isEmpty { blocks.append(.numbered(numbers)); numbers.removeAll() }
        }
        func flushAll() { flushParagraph(); flushBullets(); flushNumbers() }

        for line in text.components(separatedBy: "\n") {
            let trimmed = line.trimmingCharacters(in: .whitespaces)
            if trimmed.isEmpty {
                flushAll()
                continue
            }
            if let heading = headingMatch(trimmed) {
                flushAll()
                blocks.append(.heading(level: heading.level, text: heading.text))
            } else if let item = bulletMatch(trimmed) {
                flushParagraph(); flushNumbers()
                bullets.append(item)
            } else if let item = numberMatch(trimmed) {
                flushParagraph(); flushBullets()
                numbers.append(item)
            } else {
                flushBullets(); flushNumbers()
                paragraph.append(line)
            }
        }
        flushAll()
        return blocks
    }

    private static func headingMatch(_ s: String) -> (level: Int, text: String)? {
        var level = 0
        var idx = s.startIndex
        while idx < s.endIndex, s[idx] == "#", level < 3 {
            level += 1
            idx = s.index(after: idx)
        }
        guard level > 0, idx < s.endIndex, s[idx] == " " else { return nil }
        let body = String(s[s.index(after: idx)...]).trimmingCharacters(in: .whitespaces)
        return body.isEmpty ? nil : (level, body)
    }

    private static func bulletMatch(_ s: String) -> String? {
        guard let first = s.first, first == "-" || first == "*" || first == "+" else { return nil }
        let afterFirst = s.index(after: s.startIndex)
        guard afterFirst < s.endIndex, s[afterFirst] == " " else { return nil }
        let item = String(s[afterFirst...]).trimmingCharacters(in: .whitespaces)
        return item.isEmpty ? nil : item
    }

    private static func numberMatch(_ s: String) -> String? {
        var idx = s.startIndex
        var digits = 0
        while idx < s.endIndex, s[idx].isNumber {
            digits += 1
            idx = s.index(after: idx)
        }
        guard digits > 0, digits <= 3, idx < s.endIndex else { return nil }
        guard s[idx] == "." || s[idx] == ")" else { return nil }
        let afterSep = s.index(after: idx)
        guard afterSep < s.endIndex, s[afterSep] == " " else { return nil }
        let item = String(s[afterSep...]).trimmingCharacters(in: .whitespaces)
        return item.isEmpty ? nil : item
    }
}
