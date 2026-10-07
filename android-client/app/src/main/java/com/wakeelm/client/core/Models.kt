package com.wakeelm.client.core

import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonObject

// Network DTOs are separate from cached entities and presentation models.
@Serializable data class Tokens(val access_token: String, val refresh_token: String, val expires_in: Int = 900)
@Serializable data class Credential(val value: String)
@Serializable data class ProfileDto(val id: Long, val name: String, val language: String)
@Serializable data class ProviderDto(val id: Long, val name: String, val base_url: String, val status: String, val token_hint: String)
@Serializable data class ProviderInput(val name: String, val base_url: String, val api_token: String, val headers: Map<String, String> = emptyMap())
@Serializable data class ModelDto(val id: Long, val provider_id: Long, val name: String, val external_id: String, val status: String, val pricing: JsonObject = JsonObject(emptyMap()), val capabilities: JsonObject = JsonObject(emptyMap()), val metadata: JsonObject = JsonObject(emptyMap()))
@Serializable data class Routing(val policy: String = "MANUAL_ONLY", val fallback_enabled: Boolean = false, val active_model_id: Long? = null, val automatic_enabled: Boolean = false)
@Serializable data class ConversationDto(val id: String, val title: String)
@Serializable data class ConversationInput(val title: String = "")
@Serializable data class MessageDto(val id: String, val conversation_id: String, val request_id: String, val role: String, val content: String, val status: String)
@Serializable data class SendInput(val conversation_id: String, val request_id: String, val text: String)
@Serializable data class Health(val status: String, val api_version: Int = 1, val streaming: String = "sse")
enum class MessageStatus { SENDING, STREAMING, COMPLETED, FAILED, CANCELLED }
data class Provider(val id: Long, val name: String, val url: String, val status: String, val hint: String)
data class AiModel(val id: Long, val providerId: Long, val name: String, val externalId: String, val status: String, val price: String, val capabilities: Set<String>, val contextLength: Long?)
data class Conversation(val id: String, val title: String)
data class Message(val id: String, val conversationId: String, val requestId: String, val role: String, val content: String, val status: MessageStatus)
sealed interface StreamEvent {
    data class Started(val id: String, val modelId: Long): StreamEvent
    data class Delta(val text: String): StreamEvent
    data class Fallback(val modelId: Long): StreamEvent
    data class Snapshot(val message: MessageDto): StreamEvent
    data class Done(val status: MessageStatus): StreamEvent
    data class Error(val code: String): StreamEvent
}
class ApiFailure(val code: String): Exception(code)
