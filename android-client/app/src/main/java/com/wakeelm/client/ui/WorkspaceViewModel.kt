package com.wakeelm.client.ui

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.wakeelm.client.core.*
import com.wakeelm.client.data.*
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.*
import javax.inject.Inject

data class WorkspaceState(val restoring: Boolean = true, val signedIn: Boolean = false, val busy: Boolean = false, val error: String? = null, val online: Boolean = true, val health: String = "UNKNOWN", val routing: Routing = Routing(), val conversationId: String? = null, val messages: List<Message> = emptyList(), val generating: Boolean = false, val fallback: Boolean = false)
@HiltViewModel class WorkspaceViewModel @Inject constructor(
    private val auth: AuthRepository, val preferences: PreferencesStore,
    private val providersRepo: ProviderRepository, private val modelsRepo: ModelRepository,
    private val conversationsRepo: ConversationRepository, private val send: SendMessageUseCase,
    private val api: ClientApi, network: NetworkStatus,
): ViewModel() {
    private val mutable = MutableStateFlow(WorkspaceState())
    val state = mutable.asStateFlow()
    val prefs = preferences.values.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), Preferences())
    val providers = providersRepo.providers.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), emptyList())
    val models = providersRepo.models.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), emptyList())
    val conversations = conversationsRepo.conversations.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), emptyList())
    private var observing: Job? = null
    private var generation: Job? = null
    init {
        viewModelScope.launch { network.online.collect { value -> mutable.update { it.copy(online = value) } } }
        viewModelScope.launch {
            val restored = auth.restore()
            mutable.update { it.copy(restoring = false, signedIn = restored) }
            if (restored) refresh()
        }
    }
    private fun operation(block: suspend () -> Unit) = viewModelScope.launch {
        mutable.update { it.copy(busy = true, error = null) }
        try { block() } catch (e: CancellationException) { throw e } catch (e: Exception) {
            mutable.update { it.copy(error = e.safeCode()) }
        } finally { mutable.update { it.copy(busy = false) } }
    }
    fun login(code: String) = operation { auth.login(code); mutable.update { it.copy(signedIn = true) }; refresh() }
    fun logout() = operation { generation?.cancelAndJoin(); observing?.cancel(); auth.logout(); mutable.value = WorkspaceState(restoring = false) }
    fun refresh() = operation {
        val health = try { api.health().status } catch (_: Exception) { "OFFLINE" }; mutable.update { it.copy(health = health) }
        if (state.value.signedIn) { providersRepo.refresh(); conversationsRepo.refresh(); val routing = modelsRepo.routing(); mutable.update { it.copy(routing = routing) } }
    }
    suspend fun saveProvider(input: ProviderInput, id: Long?) { providersRepo.add(input, id) }
    fun testProvider(id: Long) = operation { providersRepo.test(id) }
    fun deleteProvider(id: Long) = operation { providersRepo.delete(id) }
    fun choose(id: Long) = operation { val routing = modelsRepo.select(id); mutable.update { it.copy(routing = routing) } }
    fun route(policy: String, fallback: Boolean) = operation { val routing = modelsRepo.route(Routing(policy, fallback)); mutable.update { it.copy(routing = routing) } }
    fun newConversation() = operation { open(conversationsRepo.new()) }
    fun open(id: String) {
        if (state.value.generating) return
        observing?.cancel()
        mutable.update { it.copy(conversationId = id, messages = emptyList(), fallback = false) }
        observing = viewModelScope.launch { conversationsRepo.observe(id).collect { rows -> mutable.update { it.copy(messages = rows) } } }
        operation { conversationsRepo.refreshMessages(id) }
    }
    fun sendMessage(text: String, requestId: String? = null) {
        val id = state.value.conversationId ?: return
        if (state.value.generating) return
        generation = viewModelScope.launch {
            mutable.update { it.copy(generating = true, error = null, fallback = false) }
            try { send(id, text, requestId).collect { event -> if (event is StreamEvent.Fallback) mutable.update { it.copy(fallback = true) } } }
            catch (e: CancellationException) { throw e }
            catch (e: Exception) { mutable.update { it.copy(error = e.safeCode()) } }
            finally { mutable.update { it.copy(generating = false) } }
        }
    }
    fun retry(message: Message, recover: Boolean) {
        val original = state.value.messages.firstOrNull { it.role == "user" && it.requestId == message.requestId } ?: return
        sendMessage(original.content, if (recover) message.requestId else null)
    }
    fun cancel() { generation?.cancel() }
    fun dismissError() { mutable.update { it.copy(error = null) } }
}
