package com.wakeelm.client.core

import android.content.Context
import android.annotation.SuppressLint
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.serialization.json.Json
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec
import javax.inject.Inject
import javax.inject.Singleton

interface SessionStorage { fun read(): Tokens?; fun write(tokens: Tokens); fun rotate(expected: String, tokens: Tokens): Boolean; fun clear(); fun clearIf(expected: String) }

@Singleton class SessionStore @Inject constructor(@ApplicationContext context: Context): SessionStorage {
    private val prefs = context.getSharedPreferences("secure_session", Context.MODE_PRIVATE)
    private val alias = "wakeelm.session.v1"
    private fun key(): SecretKey {
        val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (store.getKey(alias, null) as? SecretKey)?.let { return it }
        return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore").apply {
            init(KeyGenParameterSpec.Builder(alias, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build())
        }.generateKey()
    }
    @Synchronized override fun read(): Tokens? {
        val raw = prefs.getString("sealed", null) ?: return null
        return try {
            val parts = raw.split(":")
            val cipher = Cipher.getInstance("AES/GCM/NoPadding")
            cipher.init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, Base64.decode(parts[0], Base64.NO_WRAP)))
            Json.decodeFromString<Tokens>(cipher.doFinal(Base64.decode(parts[1], Base64.NO_WRAP)).decodeToString())
        } catch (_: Exception) { clear(); null }
    }
    @Synchronized override fun write(tokens: Tokens) {
        val cipher = Cipher.getInstance("AES/GCM/NoPadding").apply { init(Cipher.ENCRYPT_MODE, key()) }
        val iv = Base64.encodeToString(cipher.iv, Base64.NO_WRAP)
        val encrypted = Base64.encodeToString(cipher.doFinal(Json.encodeToString(tokens).encodeToByteArray()), Base64.NO_WRAP)
        check(prefs.edit().putString("sealed", "$iv:$encrypted").commit())
    }
    @Synchronized override fun rotate(expected: String, tokens: Tokens): Boolean {
        if (read()?.refresh_token != expected) return false
        write(tokens)
        return true
    }
    @Synchronized override fun clearIf(expected: String) { if(read()?.refresh_token == expected) clear() }
    @SuppressLint("ApplySharedPref") // Durable erasure must complete before another account loads.
    @Synchronized override fun clear() { prefs.edit().clear().commit() }
}
