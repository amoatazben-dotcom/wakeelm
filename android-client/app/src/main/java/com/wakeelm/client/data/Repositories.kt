package com.wakeelm.client.data

import com.wakeelm.client.core.*
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.flow.*
import kotlinx.serialization.json.*
import java.util.UUID
import javax.inject.Inject
import javax.inject.Singleton

fun ProviderDto.entity() = ProviderEntity(id, name, base_url, status, token_hint)
fun ProviderEntity.domain() = Provider(id, name, url, status, hint)
fun ModelDto.entity(): ModelEntity {
    val caps = capabilities.filterValues { (it as? JsonObject)?.get("state")?.jsonPrimitive?.content == "SUPPORTED" }.keys.joinToString(",")
    return ModelEntity(id, provider_id, name, external_id, status, pricing["classification"]?.jsonPrimitive?.content ?: "UNKNOWN", caps, metadata["context_length"]?.jsonPrimitive?.longOrNull)
}
fun ModelEntity.domain() = AiModel(id, providerId, name, externalId, status, price, capabilities.split(",").filter { it.isNotEmpty() }.toSet(), contextLength)

@Singleton class AuthRepository @Inject constructor(private val api: ClientApi, private val store: SessionStorage, private val dao: CacheDao, private val prefs: PreferencesStore, private val guard: AccountGuard) {
    suspend fun restore(): Boolean = guard.run {
        if (store.read() == null) return@run false
        try { val user = api.me(); dao.profile(ProfileEntity(user.id, user.name, user.language)) }
        catch (e: CancellationException) { throw e }
        catch (e: Exception) { if (e.safeCode() == "AUTH_REQUIRED") { localLogout(); return@run false } }
        store.read() != null
    }
    suspend fun login(code: String) = guard.run { dao.clearAccount(); store.write(api.exchange(Credential(code.trim()))); val user = api.me(); dao.profile(ProfileEntity(user.id, user.name, user.language)); prefs.onboarding(true) }
    suspend fun logout() = guard.run { try { api.logout() } catch (e: CancellationException) { throw e } catch (_: Exception) { /* Local sign-out remains available offline. */ } finally { localLogout() } }
    private suspend fun localLogout() { store.clear(); dao.clearAccount(); prefs.clearAccount() }
}
@Singleton class ProviderRepository @Inject constructor(private val api: ClientApi, private val dao: CacheDao, private val guard: AccountGuard) {
    val providers = dao.providers().map { rows -> rows.map { it.domain() } }
    val models = dao.models().map { rows -> rows.map { it.domain() } }
    suspend fun refresh() = guard.run { dao.replaceProviders(api.providers().map { it.entity() }); dao.replaceModels(api.models().map { it.entity() }) }
    suspend fun add(input: ProviderInput, id: Long? = null) = guard.run { val result = if (id == null) api.addProvider(input) else api.updateProvider(id, input); dao.providers(listOf(result.entity())) }
    suspend fun test(id: Long) = guard.run { dao.providers(listOf(api.testProvider(id).entity())); dao.replaceModels(api.models().map { it.entity() }) }
    suspend fun delete(id: Long) { guard.run { api.deleteProvider(id) }; refresh() }
}
@Singleton class ModelRepository @Inject constructor(private val api: ClientApi, private val prefs: PreferencesStore, private val guard: AccountGuard) {
    private suspend fun fetchRouting(): Routing = api.routing().also { prefs.routing(it) }
    suspend fun routing(): Routing = guard.run { fetchRouting() }
    suspend fun select(id: Long): Routing = guard.run { api.selectModel(id); fetchRouting() }
    suspend fun route(value: Routing): Routing = guard.run { api.setRouting(value); fetchRouting() }
}
@Singleton class ConversationRepository @Inject constructor(private val api: ClientApi, private val dao: CacheDao, private val cipher: CacheCipher, private val guard: AccountGuard) {
    val conversations = dao.conversations().map { rows -> rows.map { Conversation(it.id, it.title) } }
    fun observe(id: String) = dao.messages(id).map { rows -> rows.map { Message(it.id, it.conversationId, it.requestId, it.role, cipher.open(it.sealedContent), MessageStatus.valueOf(it.status)) } }
    suspend fun refresh() = guard.run { dao.replaceConversations(api.conversations().map { ConversationEntity(it.id, it.title) }) }
    suspend fun new(): String = guard.run { val row = api.newConversation(ConversationInput()); dao.conversations(listOf(ConversationEntity(row.id, row.title))); row.id }
    suspend fun refreshMessages(id: String) = guard.run {
        dao.replaceMessages(id, api.messages(id).mapIndexed { index, row -> MessageEntity(row.id, row.conversation_id, row.request_id, row.role, cipher.seal(row.content), row.status, index.toLong()) })
    }
}
@Singleton class ChatRepository @Inject constructor(private val stream: ChatStreamClient, private val dao: CacheDao, private val cipher: CacheCipher) {
    fun send(conversationId: String, text: String, requestId: String = UUID.randomUUID().toString()): Flow<StreamEvent> = flow {
        val now = System.currentTimeMillis()
        val user = MessageEntity("u-$requestId", conversationId, requestId, "user", cipher.seal(text), "SENDING", now)
        var assistant = MessageEntity("a-$requestId", conversationId, requestId, "assistant", cipher.seal(""), "STREAMING", now + 1)
        var content = ""
        dao.messages(listOf(user, assistant))
        var finished = false
        try {
            stream.stream(SendInput(conversationId, requestId, text)).collect { event ->
                when(event) {
                    is StreamEvent.Started -> dao.messages(listOf(user.copy(status = "COMPLETED")))
                    is StreamEvent.Delta -> content += event.text
                    is StreamEvent.Fallback -> content = ""
                    is StreamEvent.Snapshot -> { content = event.message.content; assistant = assistant.copy(status = event.message.status) }
                    is StreamEvent.Done -> { assistant = assistant.copy(status = event.status.name); finished = true }
                    is StreamEvent.Error -> throw ApiFailure(event.code)
                }
                dao.messages(listOf(assistant.copy(sealedContent = cipher.seal(content))))
                emit(event)
            }
            if (!finished) throw ApiFailure("INTERRUPTED")
        } catch (e: CancellationException) {
            kotlinx.coroutines.withContext(kotlinx.coroutines.NonCancellable) { dao.messages(listOf(assistant.copy(sealedContent = cipher.seal(content), status = "CANCELLED"))) }
            throw e
        } catch (e: Exception) {
            dao.messages(listOf(user.copy(status = "COMPLETED"), assistant.copy(sealedContent = cipher.seal(content), status = "FAILED")))
            throw e
        }
    }
}
class SendMessageUseCase @Inject constructor(private val chats: ChatRepository) {
    operator fun invoke(id: String, text: String, requestId: String? = null): Flow<StreamEvent> {
        require(text.isNotBlank() && text.length <= 16000)
        return if (requestId == null) chats.send(id, text) else chats.send(id, text, requestId)
    }
}
