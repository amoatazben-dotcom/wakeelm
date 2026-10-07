package com.wakeelm.client

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.room.Room
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.platform.LocalLayoutDirection
import androidx.compose.ui.unit.LayoutDirection
import androidx.compose.material3.MaterialTheme
import com.wakeelm.client.core.*
import com.wakeelm.client.ui.Markdown
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.launch
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.collect
import org.junit.*
import org.junit.Assert.*
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class) class FoundationTests {
    @get:Rule val compose = createComposeRule()
    private val context get() = InstrumentationRegistry.getInstrumentation().targetContext
    @Test fun session_is_encrypted_and_clearable() {
        val store = SessionStore(context); store.write(Tokens("test-access-secret", "test-refresh-secret"))
        assertEquals("test-access-secret", store.read()?.access_token)
        assertFalse(context.getSharedPreferences("secure_session",0).getString("sealed","")!!.contains("test-access-secret"))
        store.clear(); assertNull(store.read())
    }
    @Test fun room_offline_cache_and_account_clear() = runBlocking {
        val db = Room.inMemoryDatabaseBuilder(context, ClientDatabase::class.java).build()
        db.cache().providers(listOf(ProviderEntity(1,"Local","https://example.com","ONLINE","••••")))
        assertEquals("Local", db.cache().providers().first().first().name)
        db.cache().clearAccount(); assertTrue(db.cache().providers().first().isEmpty()); db.close()
    }
    @Test fun language_theme_and_navigation_persist() = runBlocking {
        val first = PreferencesStore(context); first.language("en"); first.theme("dark"); first.tab("chats")
        val restored = PreferencesStore(context).values.first()
        assertEquals("en",restored.language); assertEquals("dark",restored.theme); assertEquals("chats",restored.tab)
        first.language("ar"); first.theme("system"); first.tab("home")
    }
    @Test fun arabic_rtl_and_english_code_render_natively() {
        compose.setContent { CompositionLocalProvider(LocalLayoutDirection provides LayoutDirection.Rtl) { MaterialTheme { Markdown("**مرحبا**\n```kotlin\nval x = 1\n```") } } }
        compose.onNodeWithText("مرحبا").assertExists(); compose.onNodeWithText("val x = 1").assertExists()
    }
}

@RunWith(AndroidJUnit4::class) class RepositoryTests {
    private val context get() = InstrumentationRegistry.getInstrumentation().targetContext
    @Test fun provider_registration_model_cache_and_routing_acknowledgement() = runBlocking {
        val db = Room.inMemoryDatabaseBuilder(context, ClientDatabase::class.java).build()
        var submitted: ProviderInput? = null
        var routing = Routing()
        val api = java.lang.reflect.Proxy.newProxyInstance(ClientApi::class.java.classLoader, arrayOf(ClientApi::class.java)) { _, method, args -> when(method.name) {
            "addProvider" -> { submitted = args[0] as ProviderInput; ProviderDto(1,"Provider","https://example.com/v1","UNKNOWN","••••key") }
            "providers" -> listOf(ProviderDto(1,"Provider","https://example.com/v1","ONLINE","••••key"))
            "models" -> listOf(ModelDto(7,1,"Model","model","AVAILABLE"))
            "testProvider" -> ProviderDto(1,"Provider","https://example.com/v1","ONLINE","••••key")
            "selectModel" -> { routing = routing.copy(active_model_id = args[0] as Long); mapOf("active_model_id" to routing.active_model_id!!) }
            "routing" -> routing
            "setRouting" -> { routing = args[0] as Routing; routing }
            else -> throw UnsupportedOperationException(method.name)
        } } as ClientApi
        val guard = AccountGuard()
        val providers = com.wakeelm.client.data.ProviderRepository(api,db.cache(),guard)
        providers.add(ProviderInput("Provider","https://example.com/v1","transient-test-provider-key"))
        assertEquals("transient-test-provider-key", submitted?.api_token)
        submitted = null
        assertFalse(db.cache().providers().first().toString().contains("transient-test-provider-key"))
        providers.test(1); assertEquals("ONLINE",providers.providers.first().first().status)
        assertEquals(7L,providers.models.first().first().id)
        val models = com.wakeelm.client.data.ModelRepository(api,PreferencesStore(context),guard)
        assertEquals(7L,models.select(7).active_model_id)
        assertEquals("PREFER_FREE",models.route(Routing("PREFER_FREE",true)).policy)
        db.close()
    }
    @Test fun streamed_messages_cache_encrypted_chunks_and_cancellation() = runBlocking {
        val db = Room.inMemoryDatabaseBuilder(context, ClientDatabase::class.java).build()
        val stream = object: ChatStreamClient { override fun stream(input: SendInput) = kotlinx.coroutines.flow.flow<StreamEvent> {
            emit(StreamEvent.Started("assistant",1)); emit(StreamEvent.Delta("partial response")); kotlinx.coroutines.awaitCancellation()
        } }
        val chats = com.wakeelm.client.data.ChatRepository(stream,db.cache(),CacheCipher())
        val job = launch { chats.send("conversation","question","request").collect { } }
        kotlinx.coroutines.withTimeout(10000) {
            db.cache().messages("conversation").first { rows -> rows.any { CacheCipher().open(it.sealedContent) == "partial response" } }
        }
        job.cancel(); job.join()
        val rows = db.cache().messages("conversation").first()
        assertEquals("CANCELLED", rows.last().status)
        assertFalse(rows.last().sealedContent.contains("partial response"))
        db.close()
    }
}

@RunWith(AndroidJUnit4::class) class RecoveryTests {
    @Test fun recovering_same_request_keeps_one_message_pair() = runBlocking {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val db = Room.inMemoryDatabaseBuilder(context, ClientDatabase::class.java).build()
        val stream = object: ChatStreamClient { override fun stream(input: SendInput) = kotlinx.coroutines.flow.flow<StreamEvent> {
            emit(StreamEvent.Started("server-answer",1)); emit(StreamEvent.Delta("answer")); emit(StreamEvent.Done(MessageStatus.COMPLETED))
        } }
        val repository = com.wakeelm.client.data.ChatRepository(stream,db.cache(),CacheCipher())
        repeat(2) { repository.send("conversation","question","same-request").collect { } }
        assertEquals(2,db.cache().messages("conversation").first().size)
        assertTrue(db.cache().messages("conversation").first().all { it.status == "COMPLETED" })
        db.close()
    }
}
