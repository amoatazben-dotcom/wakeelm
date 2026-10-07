package com.wakeelm.client.core

import android.content.Context
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.flow.callbackFlow
import kotlinx.coroutines.flow.buffer
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.MediaType.Companion.toMediaType
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonPrimitive
import okhttp3.*
import okhttp3.sse.EventSource
import okhttp3.sse.EventSourceListener
import okhttp3.sse.EventSources
import retrofit2.http.*
import java.io.IOException
import java.util.concurrent.TimeUnit
import javax.inject.Inject
import javax.inject.Singleton

interface ClientApi {
    @POST("api/v1/auth/exchange") suspend fun exchange(@Body value: Credential): Tokens
    @POST("api/v1/auth/logout") suspend fun logout(): Map<String, Boolean>
    @GET("api/v1/me") suspend fun me(): ProfileDto
    @GET("api/v1/health/client") suspend fun health(): Health
    @GET("api/v1/providers") suspend fun providers(): List<ProviderDto>
    @POST("api/v1/providers") suspend fun addProvider(@Body data: ProviderInput): ProviderDto
    @PUT("api/v1/providers/{id}") suspend fun updateProvider(@Path("id") id: Long, @Body data: ProviderInput): ProviderDto
    @DELETE("api/v1/providers/{id}") suspend fun deleteProvider(@Path("id") id: Long): Map<String, Boolean>
    @POST("api/v1/providers/{id}/test") suspend fun testProvider(@Path("id") id: Long): ProviderDto
    @POST("api/v1/providers/{id}/models") suspend fun discover(@Path("id") id: Long): ProviderDto
    @GET("api/v1/models") suspend fun models(): List<ModelDto>
    @POST("api/v1/models/{id}/select") suspend fun selectModel(@Path("id") id: Long): Map<String, Long>
    @GET("api/v1/routing/preferences") suspend fun routing(): Routing
    @PUT("api/v1/routing/preferences") suspend fun setRouting(@Body value: Routing): Routing
    @GET("api/v1/conversations") suspend fun conversations(): List<ConversationDto>
    @POST("api/v1/conversations") suspend fun newConversation(@Body data: ConversationInput): ConversationDto
    @GET("api/v1/conversations/{id}/messages") suspend fun messages(@Path("id") id: String): List<MessageDto>
}

class AuthInterceptor(private val store: SessionStorage): Interceptor {
    override fun intercept(chain: Interceptor.Chain): Response {
        val builder = chain.request().newBuilder()
        if (!chain.request().url.encodedPath.startsWith("/api/v1/auth/")) {
            store.read()?.let { builder.header("Authorization", "Bearer ${it.access_token}") }
        } else if (chain.request().url.encodedPath.endsWith("logout")) {
            store.read()?.let { builder.header("Authorization", "Bearer ${it.access_token}") }
        }
        return chain.proceed(builder.build())
    }
}

class RefreshAuthenticator(private val store: SessionStorage, private val baseUrl: String, private val client: OkHttpClient, private val json: Json): Authenticator {
    @Synchronized override fun authenticate(route: Route?, response: Response): Request? {
        if (response.request.url.encodedPath.startsWith("/api/v1/auth/") || response.priorResponse != null) return null
        val current = store.read() ?: return null
        val stale = response.request.header("Authorization")
        if (stale != "Bearer ${current.access_token}") return response.request.newBuilder().header("Authorization", "Bearer ${current.access_token}").build()
        val body = json.encodeToString(Credential(current.refresh_token)).jsonBody()
        try {
            client.newCall(Request.Builder().url(baseUrl + "api/v1/auth/refresh").post(body).build()).execute().use {
                if (!it.isSuccessful) { if (it.code == 401) store.clearIf(current.refresh_token); return null }
                val tokens = json.decodeFromString<Tokens>(it.body.string())
                if (!store.rotate(current.refresh_token, tokens)) return null
                return response.request.newBuilder().header("Authorization", "Bearer ${tokens.access_token}").build()
            }
        } catch (_: Exception) { return null }
    }
}
fun String.jsonBody(): RequestBody = toRequestBody("application/json".toMediaType())

interface ChatStreamClient { fun stream(input: SendInput): kotlinx.coroutines.flow.Flow<StreamEvent> }
class SseChatStreamClient(private val client: OkHttpClient, private val baseUrl: String, private val json: Json): ChatStreamClient {
    override fun stream(input: SendInput) = callbackFlow {
        var terminal = false
        val source = EventSources.createFactory(client).newEventSource(
            Request.Builder().url(baseUrl + "api/v1/chat/stream").header("Accept", "text/event-stream")
                .post(json.encodeToString(input).jsonBody()).build(),
            object: EventSourceListener() {
                override fun onEvent(eventSource: EventSource, id: String?, type: String?, data: String) {
                    try {
                        val obj = json.parseToJsonElement(data) as kotlinx.serialization.json.JsonObject
                        fun field(key: String) = obj[key]?.jsonPrimitive?.content ?: throw ApiFailure("INVALID_RESPONSE")
                        val event = when(type) {
                            "started" -> StreamEvent.Started(field("id"), field("model_id").toLong())
                            "delta" -> StreamEvent.Delta(field("text"))
                            "fallback" -> StreamEvent.Fallback(field("model_id").toLong())
                            "snapshot" -> StreamEvent.Snapshot(json.decodeFromString<MessageDto>(data))
                            "done" -> StreamEvent.Done(MessageStatus.valueOf(field("status")))
                            "error" -> StreamEvent.Error(field("code"))
                            else -> return
                        }
                        if (trySend(event).isFailure) { close(ApiFailure("STREAM_OVERFLOW")); eventSource.cancel(); return }
                        if (event is StreamEvent.Done || event is StreamEvent.Error) { terminal = true; close(); eventSource.cancel() }
                    } catch (_: Exception) { close(ApiFailure("INVALID_RESPONSE")); eventSource.cancel() }
                }
                override fun onClosed(eventSource: EventSource) { if (!terminal) close(ApiFailure("INTERRUPTED")) }
                override fun onFailure(eventSource: EventSource, t: Throwable?, response: Response?) {
                    if (!terminal) close(ApiFailure(when(response?.code) { 401 -> "AUTH_REQUIRED"; 429 -> "RATE_LIMITED"; 409 -> "GENERATION_ACTIVE"; else -> "OFFLINE" }))
                }
            }
        )
        awaitClose { source.cancel() }
    }.buffer(256)
}

interface NetworkStatus { val online: kotlinx.coroutines.flow.Flow<Boolean> }

@Singleton class NetworkMonitor @Inject constructor(@ApplicationContext context: Context): NetworkStatus {
    private val manager = context.getSystemService(ConnectivityManager::class.java)
    fun available(): Boolean = manager.getNetworkCapabilities(manager.activeNetwork)?.hasCapability(NetworkCapabilities.NET_CAPABILITY_VALIDATED) == true
    override val online = callbackFlow {
        trySend(available())
        val listener = object: ConnectivityManager.NetworkCallback() {
            override fun onAvailable(network: Network) { trySend(available()) }
            override fun onLost(network: Network) { trySend(available()) }
            override fun onCapabilitiesChanged(network: Network, capabilities: NetworkCapabilities) { trySend(available()) }
        }
        manager.registerDefaultNetworkCallback(listener)
        awaitClose { manager.unregisterNetworkCallback(listener) }
    }
}
fun Throwable.safeCode(): String = when(this) {
    is ApiFailure -> code
    is retrofit2.HttpException -> {
        val remote = try {
            val obj = Json.parseToJsonElement(response()?.errorBody()?.string().orEmpty()) as kotlinx.serialization.json.JsonObject
            (obj["error"] ?: obj["detail"])?.jsonPrimitive?.content
        } catch (_: Exception) { null }
        if (remote != null && Regex("^[A-Z_]{2,64}$").matches(remote)) remote
        else when(code()) { 401 -> "AUTH_REQUIRED"; 429 -> "RATE_LIMITED"; 404 -> "NOT_FOUND"; 422 -> "INVALID_INPUT"; else -> "REQUEST_FAILED" }
    }
    is IOException -> "OFFLINE"
    else -> "INTERNAL"
}
