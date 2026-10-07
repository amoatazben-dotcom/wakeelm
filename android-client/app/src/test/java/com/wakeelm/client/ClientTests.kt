package com.wakeelm.client

import com.wakeelm.client.core.*
import com.wakeelm.client.ui.*
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.flow.toList
import kotlinx.serialization.json.Json
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.Assert.*
import org.junit.Test

class MemorySession(var tokens: Tokens? = null): SessionStorage {
    override fun read() = tokens
    override fun write(tokens: Tokens) { this.tokens = tokens }
    override fun rotate(expected: String, tokens: Tokens): Boolean { if(this.tokens?.refresh_token != expected) return false; this.tokens = tokens; return true }
    override fun clearIf(expected: String) { if(tokens?.refresh_token == expected) clear() }
    override fun clear() { tokens = null }
}
class ClientTests {
    private val json = Json { ignoreUnknownKeys = true }
    @Test fun auth_header_is_added_only_to_account_calls() {
        MockWebServer().use { server ->
            server.enqueue(MockResponse().setBody("{}")); server.enqueue(MockResponse().setBody("{}"))
            val store = MemorySession(Tokens("access-secret", "refresh-secret"))
            val client = OkHttpClient.Builder().addInterceptor(AuthInterceptor(store)).build()
            client.newCall(Request.Builder().url(server.url("/api/v1/me")).build()).execute().close()
            assertEquals("Bearer access-secret", server.takeRequest().getHeader("Authorization"))
            client.newCall(Request.Builder().url(server.url("/api/v1/auth/exchange")).build()).execute().close()
            assertNull(server.takeRequest().getHeader("Authorization"))
        }
    }
    @Test fun refresh_rotates_once_and_retries_original_call() {
        MockWebServer().use { server ->
            server.enqueue(MockResponse().setResponseCode(401))
            server.enqueue(MockResponse().setBody("""{"access_token":"new","refresh_token":"rotated","expires_in":900}"""))
            server.enqueue(MockResponse().setBody("{}"))
            val store = MemorySession(Tokens("old", "refresh")); val plain = OkHttpClient()
            val client = plain.newBuilder().addInterceptor(AuthInterceptor(store)).authenticator(RefreshAuthenticator(store, server.url("/").toString(), plain, json)).build()
            client.newCall(Request.Builder().url(server.url("/api/v1/me")).build()).execute().use { assertEquals(200, it.code) }
            assertEquals("/api/v1/me", server.takeRequest().path)
            assertEquals("/api/v1/auth/refresh", server.takeRequest().path)
            assertEquals("Bearer new", server.takeRequest().getHeader("Authorization"))
            assertEquals("rotated", store.read()?.refresh_token)
        }
    }
    @Test fun refresh_failure_clears_session_without_loop() {
        MockWebServer().use { server ->
            server.enqueue(MockResponse().setResponseCode(401)); server.enqueue(MockResponse().setResponseCode(401))
            val store = MemorySession(Tokens("old", "invalid")); val plain = OkHttpClient()
            val client = plain.newBuilder().addInterceptor(AuthInterceptor(store)).authenticator(RefreshAuthenticator(store, server.url("/").toString(), plain, json)).build()
            client.newCall(Request.Builder().url(server.url("/api/v1/me")).build()).execute().use { assertEquals(401, it.code) }
            assertNull(store.read()); assertEquals(2, server.requestCount)
        }
    }
    @Test fun sse_chunks_complete_and_fallback_are_not_buffered_response() = runTest {
        MockWebServer().use { server ->
            server.enqueue(MockResponse().setHeader("Content-Type", "text/event-stream").setBody("event: started\ndata: {\"id\":\"a\",\"model_id\":1}\n\nevent: delta\ndata: {\"text\":\"مرحبا\"}\n\nevent: fallback\ndata: {\"model_id\":2}\n\nevent: delta\ndata: {\"text\":\"Hello\"}\n\nevent: done\ndata: {\"status\":\"COMPLETED\"}\n\n"))
            val events = SseChatStreamClient(OkHttpClient(), server.url("/").toString(), json).stream(SendInput("conversation", "request", "hi")).toList()
            assertEquals(5, events.size); assertEquals(StreamEvent.Delta("مرحبا"), events[1]); assertTrue(events[2] is StreamEvent.Fallback); assertEquals(StreamEvent.Done(MessageStatus.COMPLETED), events.last())
        }
    }
    @Test fun markdown_code_and_safe_tables_keep_structure() {
        val blocks = markdownBlocks("# Title\n```kotlin\nval x = 1\n```\n|a|b|\n|---|---|\n|1|2|")
        assertEquals(MarkdownBlock.Code("kotlin", "val x = 1"), blocks[1])
        assertEquals(listOf("1","2"), (blocks[2] as MarkdownBlock.Table).rows.last())
        assertEquals("bold code", inlineMarkdown("**bold** `code`").text)
    }
    @Test fun model_filters_require_reported_evidence() {
        val free = AiModel(1,1,"Model","a","AVAILABLE","FREE_REPORTED",setOf("coding"),64000)
        val paid = free.copy(id=2, price="PAID", status="UNTESTED", capabilities=emptySet(), contextLength=null)
        assertEquals(listOf(free), filterModels(listOf(free,paid),"free"))
        assertEquals(listOf(free), filterModels(listOf(free,paid),"coding"))
        assertEquals(listOf(free), filterModels(listOf(free,paid),"long"))
        assertTrue(filterModels(listOf(free,paid),"fast").isEmpty())
    }
    @Test fun errors_use_safe_codes() { assertEquals("OFFLINE", java.io.IOException("secret").safeCode()); assertEquals("INTERNAL", IllegalStateException("secret").safeCode()) }
}
