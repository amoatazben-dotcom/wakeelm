package com.wakeelm.client.ui

import android.content.res.Configuration
import android.content.ClipData
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.*
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.unit.LayoutDirection
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.navigation3.runtime.*
import androidx.navigation3.ui.NavDisplay
import com.wakeelm.client.R
import com.wakeelm.client.BuildConfig
import com.wakeelm.client.core.*
import kotlinx.coroutines.launch
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import java.util.Locale

@Serializable data class Screen(val name: String): NavKey
@Composable fun localized(code: String): String {
    val context = LocalContext.current
    val id = context.resources.getIdentifier(if(code == "long") "long_context" else code.lowercase(), "string", context.packageName)
    return if (id == 0) stringResource(R.string.request_failed) else stringResource(id)
}
@Composable fun WorkspaceApp(vm: WorkspaceViewModel) {
    val prefs by vm.prefs.collectAsStateWithLifecycle()
    val context = LocalContext.current
    val localizedContext = remember(context, prefs.language) {
        context.createConfigurationContext(Configuration(context.resources.configuration).apply { setLocale(Locale.forLanguageTag(prefs.language)); setLayoutDirection(Locale.forLanguageTag(prefs.language)) })
    }
    val dark = when(prefs.theme) { "dark" -> true; "light" -> false; else -> isSystemInDarkTheme() }
    CompositionLocalProvider(LocalContext provides localizedContext, LocalConfiguration provides localizedContext.resources.configuration,
        LocalLayoutDirection provides if(prefs.language == "ar") LayoutDirection.Rtl else LayoutDirection.Ltr) {
        MaterialTheme(colorScheme = if(dark) darkColorScheme(primary = Color(0xFF8BC9BF), secondary = Color(0xFFAEC6F5)) else lightColorScheme(primary = Color(0xFF21685F), secondary = Color(0xFF3D5D92))) {
            Surface(Modifier.fillMaxSize()) { WorkspaceShell(vm) }
        }
    }
}
@Composable private fun WorkspaceShell(vm: WorkspaceViewModel) {
    val state by vm.state.collectAsStateWithLifecycle(); val prefs by vm.prefs.collectAsStateWithLifecycle()
    val scope = rememberCoroutineScope()
    if(state.restoring) { Box(Modifier.fillMaxSize(), contentAlignment = androidx.compose.ui.Alignment.Center) { CircularProgressIndicator() }; return }
    if(!state.signedIn) { Login(vm, state); return }
    val backStack = rememberNavBackStack(Screen(prefs.tab))
    val current = (backStack.lastOrNull() as? Screen)?.name ?: "home"
    fun go(name: String) { backStack.add(Screen(name)) }
    val tabs = listOf("home", "chats", "projects", "tasks", "more")
    BoxWithConstraints {
        val wide = maxWidth >= 840.dp
        Scaffold(bottomBar = {
            if(!wide) NavigationBar { tabs.forEach { name -> NavigationBarItem(selected = current == name,
                onClick = { if(!state.generating) { backStack.clear(); backStack.add(Screen(name)); scope.launch { vm.preferences.tab(name) } } },
                icon = { Text(when(name) { "home" -> "⌂"; "chats" -> "✦"; "projects" -> "▣"; "tasks" -> "✓"; else -> "⋯" }) }, label = { Text(localized(name)) }) } }
        }) { padding ->
            Row(Modifier.fillMaxSize().padding(padding)) {
                if(wide) NavigationRail { tabs.forEach { name -> NavigationRailItem(selected = current == name, onClick = { if(!state.generating) { backStack.clear(); backStack.add(Screen(name)); scope.launch { vm.preferences.tab(name) } } }, icon = { Text(localized(name)) }) } }
                Column(Modifier.weight(1f).widthIn(max = 1200.dp)) {
                    Row(Modifier.fillMaxWidth().padding(16.dp), horizontalArrangement = Arrangement.SpaceBetween) {
                        Text(stringResource(R.string.app_name), style = MaterialTheme.typography.titleLarge)
                        if(backStack.size > 1) TextButton(onClick = { if(!state.generating) backStack.removeLastOrNull() }) { Text("←") }
                    }
                    if(!state.online) Text(stringResource(R.string.offline_cache), Modifier.padding(horizontal = 16.dp), color = MaterialTheme.colorScheme.error)
                    if(state.busy) LinearProgressIndicator(Modifier.fillMaxWidth())
                    state.error?.let { code -> Row(Modifier.padding(12.dp)) { Text(localized(code), Modifier.weight(1f), color = MaterialTheme.colorScheme.error); TextButton(onClick = vm::dismissError) { Text(stringResource(R.string.cancel)) } } }
                    NavDisplay(backStack = backStack, onBack = { if(!state.generating && backStack.size > 1) backStack.removeLastOrNull() }, entryProvider = entryProvider {
                        entry<Screen> { screen -> when(screen.name) {
                            "home" -> Home(vm, state, ::go)
                            "chats" -> Chats(vm) { go("chat") }
                            "chat" -> Chat(vm, state)
                            "providers" -> Providers(vm)
                            "models" -> Models(vm, state)
                            "more", "settings" -> Settings(vm, prefs, state)
                            else -> Box(Modifier.fillMaxSize().padding(24.dp)) { Text(stringResource(R.string.future)) }
                        } }
                    })
                }
            }
        }
    }
}
@Composable private fun Login(vm: WorkspaceViewModel, state: WorkspaceState) {
    var code by remember { mutableStateOf("") }
    Column(Modifier.fillMaxSize().safeDrawingPadding().padding(24.dp), verticalArrangement = Arrangement.Center) {
        Text(stringResource(R.string.welcome), style = MaterialTheme.typography.headlineLarge)
        Spacer(Modifier.height(24.dp)); Text(stringResource(R.string.login_help))
        OutlinedTextField(code, { code = it }, label = { Text(stringResource(R.string.code)) }, modifier = Modifier.fillMaxWidth(), visualTransformation = PasswordVisualTransformation(), singleLine = true)
        state.error?.let { Text(localized(it), color = MaterialTheme.colorScheme.error) }
        Button(enabled = code.isNotBlank() && !state.busy, onClick = { vm.login(code); code = "" }) { Text(stringResource(R.string.login)) }
        if(state.busy) CircularProgressIndicator()
    }
}
@Composable private fun Home(vm: WorkspaceViewModel, state: WorkspaceState, go: (String) -> Unit) {
    val models by vm.models.collectAsStateWithLifecycle()
    Column(Modifier.padding(24.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
        Text(stringResource(R.string.welcome), style = MaterialTheme.typography.headlineMedium)
        ElevatedCard(Modifier.fillMaxWidth()) { Column(Modifier.padding(20.dp)) { Text(stringResource(R.string.current_model)); Text(models.find { it.id == state.routing.active_model_id }?.name ?: localized("no_active_model"), style = MaterialTheme.typography.titleLarge); Text(localized(state.routing.policy)) } }
        Button(onClick = { vm.newConversation(); go("chat") }, enabled = state.online && !state.busy) { Text(stringResource(R.string.new_chat)) }
        listOf("providers", "models", "settings").forEach { name -> OutlinedButton(onClick = { go(name) }, modifier = Modifier.fillMaxWidth()) { Text(localized(name)) } }
        Text(stringResource(R.string.footer), style = MaterialTheme.typography.labelSmall)
    }
}
@Composable private fun Chats(vm: WorkspaceViewModel, open: () -> Unit) {
    val rows by vm.conversations.collectAsStateWithLifecycle()
    Column(Modifier.padding(16.dp)) {
        Button(onClick = { vm.newConversation(); open() }) { Text(stringResource(R.string.new_chat)) }
        OutlinedButton(onClick = { vm.refresh() }) { Text(stringResource(R.string.refresh)) }
        if(rows.isEmpty()) Text(stringResource(R.string.empty))
        LazyColumn { items(rows, key = { it.id }) { row -> OutlinedCard(onClick = { vm.open(row.id); open() }, Modifier.fillMaxWidth().padding(vertical = 4.dp)) { Text(row.title.ifBlank { stringResource(R.string.new_chat) }, Modifier.padding(16.dp)) } } }
    }
}
@Composable private fun Chat(vm: WorkspaceViewModel, state: WorkspaceState) {
    var draft by remember { mutableStateOf("") }
    val list = rememberLazyListState(); val scope = rememberCoroutineScope(); val clipboard = LocalClipboard.current
    val models by vm.models.collectAsStateWithLifecycle()
    LaunchedEffect(state.messages.lastOrNull()?.content?.length) { if(state.messages.isNotEmpty() && list.firstVisibleItemIndex >= state.messages.size - 3) list.animateScrollToItem(state.messages.lastIndex) }
    Column(Modifier.fillMaxSize().padding(horizontal = 16.dp).imePadding()) {
        Text(models.find { it.id == state.routing.active_model_id }?.name ?: localized(state.routing.policy), style = MaterialTheme.typography.titleSmall)
        if(state.fallback) Text(stringResource(R.string.fallback_notice), color = MaterialTheme.colorScheme.tertiary)
        LazyColumn(state = list, modifier = Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            items(state.messages, key = { it.id }) { message ->
                Surface(color = if(message.role == "user") MaterialTheme.colorScheme.secondaryContainer else MaterialTheme.colorScheme.surfaceContainer, shape = MaterialTheme.shapes.large) {
                    Column(Modifier.fillMaxWidth().padding(16.dp)) {
                        Text(stringResource(if(message.role == "user") R.string.you else R.string.assistant), style = MaterialTheme.typography.labelMedium)
                        Markdown(message.content)
                        Text(localized(message.status.name), style = MaterialTheme.typography.labelSmall)
                        Row { TextButton(onClick = { scope.launch { clipboard.setClipEntry(ClipEntry(ClipData.newPlainText("Wakeelm message", message.content))) } }) { Text(stringResource(R.string.copy)) }
                            if(message.role == "assistant" && message.status in setOf(MessageStatus.FAILED, MessageStatus.CANCELLED)) {
                                TextButton(enabled = !state.generating, onClick = { vm.retry(message, false) }) { Text(stringResource(R.string.retry)) }
                                TextButton(enabled = !state.generating, onClick = { vm.retry(message, true) }) { Text(stringResource(R.string.reconnect)) }
                            }
                        }
                    }
                }
            }
        }
        TextButton(onClick = { scope.launch { if(state.messages.isNotEmpty()) list.animateScrollToItem(state.messages.lastIndex) } }) { Text(stringResource(R.string.scroll_bottom)) }
        Row(verticalAlignment = androidx.compose.ui.Alignment.CenterVertically) {
            OutlinedTextField(draft, { if(it.length <= 16000) draft = it }, Modifier.weight(1f), placeholder = { Text(stringResource(R.string.message)) }, maxLines = 5)
            if(state.generating) TextButton(onClick = vm::cancel) { Text(stringResource(R.string.cancel)) }
            else TextButton(enabled = draft.isNotBlank() && state.online && state.conversationId != null, onClick = { vm.sendMessage(draft); draft = "" }) { Text(stringResource(R.string.send)) }
        }
    }
}
@Composable private fun Providers(vm: WorkspaceViewModel) {
    val rows by vm.providers.collectAsStateWithLifecycle()
    val state by vm.state.collectAsStateWithLifecycle()
    var adding by remember { mutableStateOf(false) }; var editing by remember { mutableStateOf<Provider?>(null) }
    Column(Modifier.padding(16.dp)) {
        Text(stringResource(R.string.providers), style = MaterialTheme.typography.headlineMedium)
        Row { Button(onClick = { adding = true }) { Text(stringResource(R.string.add_provider)) }; TextButton(onClick = { vm.refresh() }) { Text(stringResource(R.string.refresh)) } }
        if(rows.isEmpty()) Text(stringResource(R.string.empty))
        LazyColumn { items(rows, key = { it.id }) { row -> ElevatedCard(Modifier.fillMaxWidth().padding(vertical = 8.dp)) { Column(Modifier.padding(16.dp)) {
            Text(row.name, style = MaterialTheme.typography.titleLarge); Text(row.url); Text(if(state.busy) stringResource(R.string.checking) else localized(row.status)); Text(row.hint)
            Row { TextButton(onClick = { vm.testProvider(row.id) }, enabled = !state.busy) { Text(stringResource(R.string.test)) }; TextButton(onClick = { editing = row; adding = true }) { Text(stringResource(R.string.manage)) }; TextButton(onClick = { vm.deleteProvider(row.id) }, enabled = !state.busy) { Text(stringResource(R.string.delete)) } }
        } } } }
    }
    if(adding) ProviderDialog(vm, editing) { adding = false; editing = null }
}
@Composable private fun ProviderDialog(vm: WorkspaceViewModel, editing: Provider?, dismiss: () -> Unit) {
    var name by remember { mutableStateOf(editing?.name ?: "") }; var url by remember { mutableStateOf(editing?.url ?: "https://openrouter.ai/api/v1") }
    // Sensitive inputs are never rememberSaveable, Room, DataStore, or ViewModel state.
    var token by remember { mutableStateOf("") }; var headers by remember { mutableStateOf("") }; var visible by remember { mutableStateOf(false) }
    var busy by remember { mutableStateOf(false) }; var error by remember { mutableStateOf<String?>(null) }
    val clipboard = LocalClipboard.current; val scope = rememberCoroutineScope()
    fun close() { token = ""; headers = ""; dismiss() }
    AlertDialog(onDismissRequest = { if(!busy) close() }, title = { Text(stringResource(R.string.add_provider)) }, text = {
        Column(Modifier.heightIn(max = 450.dp).verticalScroll(androidx.compose.foundation.rememberScrollState())) {
            OutlinedTextField(name, { name = it }, label = { Text(stringResource(R.string.name)) })
            OutlinedTextField(url, { url = it }, label = { Text(stringResource(R.string.base_url)) }, singleLine = true)
            OutlinedTextField(token, { token = it }, label = { Text(stringResource(R.string.api_token)) }, visualTransformation = if(visible) VisualTransformation.None else PasswordVisualTransformation(), singleLine = true)
            Row { TextButton(onClick = { visible = !visible }) { Text(stringResource(if(visible) R.string.hide else R.string.show)) }; TextButton(onClick = { scope.launch { token = clipboard.getClipEntry()?.clipData?.getItemAt(0)?.text?.toString().orEmpty() } }) { Text(stringResource(R.string.paste)) } }
            OutlinedTextField(headers, { headers = it }, label = { Text(stringResource(R.string.headers)) })
            error?.let { Text(localized(it), color = MaterialTheme.colorScheme.error) }
        }
    }, confirmButton = { TextButton(enabled = !busy && name.isNotBlank() && token.isNotBlank() && url.startsWith("https://"), onClick = {
        scope.launch {
            busy = true; error = null
            try {
                val custom = if(headers.isBlank()) emptyMap() else Json.decodeFromString<Map<String,String>>(headers)
                vm.saveProvider(ProviderInput(name.trim(), url.trim(), token, custom), editing?.id)
                token = ""; headers = ""; close()
            } catch (e: Exception) { error = e.safeCode() }
            finally { busy = false }
        }
    }) { Text(stringResource(R.string.save)) } }, dismissButton = { TextButton(enabled = !busy, onClick = ::close) { Text(stringResource(R.string.cancel)) } })
}
fun filterModels(rows: List<AiModel>, filter: String): List<AiModel> = rows.filter { model -> when(filter) {
    "free" -> model.price in setOf("FREE_VERIFIED", "FREE_REPORTED")
    "working" -> model.status == "AVAILABLE"
    "tool_calling", "vision", "reasoning", "coding" -> filter in model.capabilities
    "long" -> (model.contextLength ?: 0) >= 32000
    "fast" -> "fast" in model.capabilities // Never infer speed from a model's name.
    else -> true
} }
@Composable private fun Models(vm: WorkspaceViewModel, state: WorkspaceState) {
    val rows by vm.models.collectAsStateWithLifecycle(); val providers by vm.providers.collectAsStateWithLifecycle()
    var filter by remember { mutableStateOf("all") }; var detail by remember { mutableStateOf<AiModel?>(null) }
    Column(Modifier.padding(16.dp)) {
        Text(stringResource(R.string.models), style = MaterialTheme.typography.headlineMedium)
        TextButton(onClick = { vm.refresh() }) { Text(stringResource(R.string.refresh)) }
        Row(Modifier.horizontalScroll(androidx.compose.foundation.rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            listOf("free", "working", "tool_calling", "vision", "reasoning", "coding", "fast", "long", "all").forEach { name -> FilterChip(selected = filter == name, onClick = { filter = name }, label = { Text(localized(name)) }) }
        }
        Row(Modifier.horizontalScroll(androidx.compose.foundation.rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            listOf("AUTO", "PREFER_FREE", "PREFER_FAST", "PREFER_CHEAP", "PREFER_STRONGEST", "PREFER_CODING", "MANUAL_ONLY").forEach { policy -> FilterChip(selected = state.routing.policy == policy, enabled = !state.busy && (policy == "MANUAL_ONLY" || state.routing.automatic_enabled), onClick = { vm.route(policy, state.routing.fallback_enabled) }, label = { Text(localized(policy)) }) }
        }
        Row(verticalAlignment = androidx.compose.ui.Alignment.CenterVertically) { Text(stringResource(R.string.fallback)); Switch(checked = state.routing.fallback_enabled, enabled = !state.busy, onCheckedChange = { vm.route(state.routing.policy, it) }) }
        val filtered = remember(rows, filter) { filterModels(rows, filter) }
        if(filtered.isEmpty()) Text(stringResource(if(filter == "fast") R.string.fast_unknown else R.string.empty))
        LazyColumn { items(filtered, key = { it.id }) { model -> OutlinedCard(Modifier.fillMaxWidth().padding(vertical = 6.dp)) { Column(Modifier.padding(16.dp)) {
            Text(model.name, style = MaterialTheme.typography.titleMedium); Text(providers.find { it.id == model.providerId }?.name.orEmpty()); Text(localized(model.status) + " · " + localized(model.price))
            Text(model.capabilities.joinToString(" · ")); Text(stringResource(R.string.context) + ": " + (model.contextLength?.toString() ?: stringResource(R.string.unknown)))
            Row { TextButton(onClick = { vm.choose(model.id) }, enabled = !state.busy && model.status != "UNSUPPORTED") { Text(stringResource(if(state.routing.active_model_id == model.id) R.string.selected else R.string.select)) }; TextButton(onClick = { detail = model }) { Text(stringResource(R.string.details)) } }
        } } } }
    }
    detail?.let { model -> AlertDialog(onDismissRequest = { detail = null }, title = { Text(model.name) }, text = { Column { Text(model.externalId); Text(model.capabilities.joinToString(" · ")); Text(localized(model.price)); Text(localized(model.status)) } }, confirmButton = { TextButton(onClick = { detail = null }) { Text(stringResource(R.string.cancel)) } }) }
}
@Composable private fun Settings(vm: WorkspaceViewModel, prefs: Preferences, state: WorkspaceState) {
    val scope = rememberCoroutineScope()
    Column(Modifier.fillMaxSize().verticalScroll(androidx.compose.foundation.rememberScrollState()).padding(24.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
        Text(stringResource(R.string.settings), style = MaterialTheme.typography.headlineMedium)
        Text(stringResource(R.string.language))
        Row { listOf("ar" to R.string.arabic, "en" to R.string.english).forEach { (language, label) -> FilterChip(selected = prefs.language == language, onClick = { scope.launch { vm.preferences.language(language) } }, label = { Text(stringResource(label)) }) } }
        Text(stringResource(R.string.theme))
        Row { listOf("system", "light", "dark").forEach { theme -> FilterChip(selected = prefs.theme == theme, onClick = { scope.launch { vm.preferences.theme(theme) } }, label = { Text(localized(theme)) }) } }
        Text(stringResource(R.string.backend) + ": " + localized(state.health)); TextButton(onClick = { vm.refresh() }) { Text(stringResource(R.string.refresh)) }
        Text(stringResource(R.string.security), style = MaterialTheme.typography.titleMedium); Text(stringResource(R.string.security_detail))
        Text(stringResource(R.string.version) + ": " + BuildConfig.VERSION_NAME)
        OutlinedButton(onClick = { vm.logout() }) { Text(stringResource(R.string.logout)) }
    }
}
