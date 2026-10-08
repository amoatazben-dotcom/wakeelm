package com.wakeelm.client

import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.room.Room
import androidx.work.WorkManager
import androidx.lifecycle.viewModelScope
import com.wakeelm.client.core.*
import com.wakeelm.client.data.*
import com.wakeelm.client.ui.*
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.*
import org.junit.Rule
import org.junit.Test
import org.junit.Assert.*
import org.junit.runner.RunWith

/** Real native screens/repositories/Room/Keystore; deterministic account API, no paid calls. */
@RunWith(AndroidJUnit4::class) class WorkspaceFlowTest {
    @get:Rule val compose = createComposeRule()
    @Test fun arabic_provider_model_chat_and_english_switch() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        WorkManager.getInstance(context).cancelUniqueWork("workspace-cache").result.get()
        val db = Room.inMemoryDatabaseBuilder(context, ClientDatabase::class.java).build()
        val prefs = PreferencesStore(context)
        runBlocking { prefs.language("ar"); prefs.theme("system"); prefs.tab("home") }
        val session = SessionStore(context).apply { write(Tokens("instrumentation-access", "instrumentation-refresh")) }
        val providerRows = mutableListOf(ProviderDto(1,"Alpha","https://example.com/v1","ONLINE","••••"))
        var routing = Routing()
        val api = java.lang.reflect.Proxy.newProxyInstance(ClientApi::class.java.classLoader, arrayOf(ClientApi::class.java)) { _, method, args -> when(method.name) {
            "me" -> ProfileDto(1,"Test","ar")
            "health" -> Health("ONLINE")
            "providers" -> providerRows.toList()
            "models" -> listOf(ModelDto(7,1,"AgentModel","test-model","AVAILABLE"))
            "routing" -> routing
            "conversations", "messages" -> emptyList<Any>()
            "newConversation" -> ConversationDto("conversation-ui","")
            "addProvider" -> { val input = args[0] as ProviderInput; assertEquals("temporary-test-key",input.api_token); ProviderDto(2,input.name,input.base_url,"UNKNOWN","••••").also { providerRows.add(it) } }
            "selectModel" -> { routing = routing.copy(active_model_id=args[0] as Long); mapOf("active_model_id" to 7L) }
            else -> throw UnsupportedOperationException(method.name)
        } } as ClientApi
        val guard = AccountGuard(); val cipher = CacheCipher()
        val stream = object: ChatStreamClient { override fun stream(input: SendInput) = flow<StreamEvent> {
            emit(StreamEvent.Started("answer-ui",7)); emit(StreamEvent.Delta("مرحبا ")); emit(StreamEvent.Delta("من النموذج")); emit(StreamEvent.Done(MessageStatus.COMPLETED))
        } }
        val vm = WorkspaceViewModel(AuthRepository(api,session,db.cache(),prefs,guard), prefs,
            ProviderRepository(api,db.cache(),guard), ModelRepository(api,prefs,guard),
            ConversationRepository(api,db.cache(),cipher,guard), SendMessageUseCase(ChatRepository(stream,db.cache(),cipher)), api,
            object: NetworkStatus { override val online = flowOf(true) })
        try {
            compose.setContent { WorkspaceApp(vm) }
            compose.waitUntil(20000) { compose.onAllNodesWithText("مزودات API").fetchSemanticsNodes().isNotEmpty() }
            compose.onNodeWithText("مزودات API").performScrollTo().performClick()
            compose.onNodeWithText("إضافة مزود").performClick()
            compose.waitUntil(60000) { compose.onAllNodesWithTag("provider-name").fetchSemanticsNodes().isNotEmpty() }
            compose.onNodeWithTag("provider-name").performTextInput("Added")
            compose.onNodeWithTag("provider-token").performTextInput("temporary-test-key")
            compose.onNodeWithText("حفظ").performClick()
            compose.waitUntil(20000) { compose.onAllNodesWithText("Added").fetchSemanticsNodes().isNotEmpty() }
            assertFalse(runBlocking { db.cache().providers().first().toString() }.contains("temporary-test-key"))
            compose.onNodeWithText("الرئيسية").performClick()
            compose.onNodeWithText("النماذج").performScrollTo().performClick()
            compose.onNodeWithText("اختيار").performClick()
            compose.waitUntil(20000) { compose.onAllNodesWithText("مختار").fetchSemanticsNodes().isNotEmpty() }
            assertEquals(7L, runBlocking { prefs.values.first() }.modelId)
            compose.onNodeWithText("الرئيسية").performClick()
            compose.onNodeWithText("محادثة جديدة").performScrollTo().performClick()
            compose.waitUntil(20000) { vm.state.value.conversationId != null && !vm.state.value.busy }
            compose.onNodeWithText("اكتب رسالتك…").performTextInput("هاي")
            compose.onNodeWithText("إرسال").performClick()
            compose.waitUntil(20000) { compose.onAllNodesWithText("مرحبا من النموذج").fetchSemanticsNodes().isNotEmpty() }
            compose.onNodeWithText("مرحبا من النموذج").assertExists()
            compose.onNodeWithText("المزيد").performClick()
            compose.onNodeWithText("الإنجليزية").performClick()
            compose.waitUntil(10000) { compose.onAllNodesWithText("Home").fetchSemanticsNodes().isNotEmpty() }
            compose.onNodeWithText("Home").assertExists()
            assertEquals("en",runBlocking { prefs.values.first() }.language)
        } catch (error: Throwable) {
            compose.onRoot(useUnmergedTree = true).printToLog("WakeelmUiFailure")
            throw error
        } finally {
            vm.viewModelScope.cancel(); session.clear(); db.close()
            runBlocking { prefs.language("ar"); prefs.tab("home") }
        }
    }
}
