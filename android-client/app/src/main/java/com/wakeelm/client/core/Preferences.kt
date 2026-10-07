package com.wakeelm.client.core

import android.content.Context
import androidx.datastore.preferences.core.*
import androidx.datastore.preferences.preferencesDataStore
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.flow.map
import javax.inject.Inject
import javax.inject.Singleton

val Context.clientPreferences by preferencesDataStore("client_settings")
data class Preferences(val language: String = "ar", val theme: String = "system", val tab: String = "home", val onboarded: Boolean = false, val routing: String = "MANUAL_ONLY", val modelId: Long? = null)
@Singleton class PreferencesStore @Inject constructor(@ApplicationContext context: Context) {
    private val store = context.clientPreferences
    val values = store.data.map { Preferences(it[LANGUAGE] ?: "ar", it[THEME] ?: "system", it[TAB] ?: "home", it[ONBOARDING] ?: false, it[ROUTING] ?: "MANUAL_ONLY", it[MODEL]) }
    suspend fun language(value: String) { require(value in setOf("ar", "en")); store.edit { it[LANGUAGE] = value } }
    suspend fun theme(value: String) { require(value in setOf("system", "light", "dark")); store.edit { it[THEME] = value } }
    suspend fun tab(value: String) { store.edit { it[TAB] = value } }
    suspend fun onboarding(value: Boolean) { store.edit { it[ONBOARDING] = value } }
    suspend fun routing(value: Routing) { store.edit { it[ROUTING] = value.policy; value.active_model_id?.let { id -> it[MODEL] = id } ?: it.remove(MODEL) } }
    suspend fun clearAccount() { store.edit { it.remove(MODEL); it.remove(ROUTING); it[ONBOARDING] = false; it[TAB] = "home" } }
    companion object {
        val LANGUAGE = stringPreferencesKey("language"); val THEME = stringPreferencesKey("theme")
        val TAB = stringPreferencesKey("lastSelectedTab"); val ONBOARDING = booleanPreferencesKey("onboardingCompleted")
        val ROUTING = stringPreferencesKey("routingPreference"); val MODEL = longPreferencesKey("activeModelId")
    }
}
