package com.wakeelm.client.ui

import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalClipboard
import androidx.compose.ui.platform.ClipEntry
import android.content.ClipData
import kotlinx.coroutines.launch
import androidx.compose.ui.platform.LocalLayoutDirection
import androidx.compose.ui.text.*
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.unit.LayoutDirection
import androidx.compose.ui.unit.dp
import com.wakeelm.client.R
import androidx.compose.ui.res.stringResource

sealed interface MarkdownBlock {
    data class Text(val value: String): MarkdownBlock
    data class Code(val language: String, val value: String): MarkdownBlock
    data class Table(val rows: List<List<String>>): MarkdownBlock
}
fun markdownBlocks(value: String): List<MarkdownBlock> {
    val lines = value.lines(); val result = mutableListOf<MarkdownBlock>(); var i = 0
    while (i < lines.size) {
        if (lines[i].startsWith("```")) {
            val language = lines[i++].removePrefix("```"); val code = mutableListOf<String>()
            while (i < lines.size && !lines[i].startsWith("```")) code += lines[i++]
            if (i < lines.size) i++
            result += MarkdownBlock.Code(language, code.joinToString("\n"))
        } else if (i + 1 < lines.size && lines[i].contains('|') && Regex("^[\\s|:-]+$").matches(lines[i + 1]) && lines[i+1].contains('-')) {
            val rows = mutableListOf<List<String>>()
            rows += lines[i].trim().trim('|').split('|').map { it.trim() }; i += 2
            while (i < lines.size && lines[i].contains('|')) rows += lines[i++].trim().trim('|').split('|').map { it.trim() }
            result += MarkdownBlock.Table(rows)
        } else result += MarkdownBlock.Text(lines[i++])
    }
    return result
}
fun inlineMarkdown(value: String): AnnotatedString = buildAnnotatedString {
    val pattern = Regex("\\*\\*(.+?)\\*\\*|\\*(.+?)\\*|`([^`]+)`|\\[([^]]+)]\\((https?://[^\\s)]+)\\)")
    var position = 0
    pattern.findAll(value).forEach { match ->
        append(value.substring(position, match.range.first))
        when {
            match.groups[1] != null -> withStyle(SpanStyle(fontWeight = FontWeight.Bold)) { append(match.groupValues[1]) }
            match.groups[2] != null -> withStyle(SpanStyle(fontStyle = FontStyle.Italic)) { append(match.groupValues[2]) }
            match.groups[3] != null -> withStyle(SpanStyle(fontFamily = FontFamily.Monospace, background = Color(0x227F8DAA))) { append(match.groupValues[3]) }
            else -> withLink(LinkAnnotation.Url(match.groupValues[5])) { append(match.groupValues[4]) }
        }
        position = match.range.last + 1
    }
    append(value.substring(position))
}
@Composable fun Markdown(value: String) {
    val blocks = remember(value) { markdownBlocks(value) }
    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
        blocks.forEach { block -> when(block) {
            is MarkdownBlock.Code -> CodeBlock(block)
            is MarkdownBlock.Table -> Row(Modifier.horizontalScroll(rememberScrollState())) {
                Column { block.rows.forEachIndexed { index, row -> Row { row.forEach { cell ->
                    Surface(tonalElevation = if(index == 0) 3.dp else 0.dp, modifier = Modifier.widthIn(min = 100.dp, max = 220.dp)) {
                        Text(inlineMarkdown(cell), Modifier.padding(8.dp), fontWeight = if(index == 0) FontWeight.Bold else FontWeight.Normal)
                    }
                } }; HorizontalDivider() } }
            }
            is MarkdownBlock.Text -> {
                val heading = block.value.takeWhile { it == '#' }.length
                val text = if(heading in 1..6) block.value.drop(heading).trimStart() else block.value.replace(Regex("^\\s*[-*] "), "• ")
                SelectionContainer { Text(inlineMarkdown(text), style = if(heading in 1..3) MaterialTheme.typography.titleLarge else MaterialTheme.typography.bodyLarge) }
            }
        } }
    }
}
@Composable private fun CodeBlock(block: MarkdownBlock.Code) {
    val clipboard = LocalClipboard.current
    val scope = rememberCoroutineScope()
    Surface(color = MaterialTheme.colorScheme.surfaceContainerHighest, shape = MaterialTheme.shapes.medium) {
        Column(Modifier.padding(12.dp)) {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) { Text(block.language, style = MaterialTheme.typography.labelMedium); TextButton(onClick = { scope.launch { clipboard.setClipEntry(ClipEntry(ClipData.newPlainText("Wakeelm code", block.value))) } }) { Text(stringResource(R.string.copy)) } }
            CompositionLocalProvider(LocalLayoutDirection provides LayoutDirection.Ltr) {
                SelectionContainer { Text(block.value, Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()), fontFamily = FontFamily.Monospace, style = MaterialTheme.typography.bodyMedium) }
            }
        }
    }
}
