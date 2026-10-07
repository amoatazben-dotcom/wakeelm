package com.wakeelm.client.core

import android.content.Context
import androidx.room.*
import kotlinx.coroutines.flow.Flow
import javax.inject.Inject
import javax.inject.Singleton

@Entity(tableName = "providers") data class ProviderEntity(@PrimaryKey val id: Long, val name: String, val url: String, val status: String, val hint: String)
@Entity(tableName = "models") data class ModelEntity(@PrimaryKey val id: Long, val providerId: Long, val name: String, val externalId: String, val status: String, val price: String, val capabilities: String, val contextLength: Long?)
@Entity(tableName = "conversations") data class ConversationEntity(@PrimaryKey val id: String, val title: String)
@Entity(tableName = "messages", indices = [Index("conversationId")]) data class MessageEntity(@PrimaryKey val id: String, val conversationId: String, val requestId: String, val role: String, val sealedContent: String, val status: String, val sequence: Long)
@Entity(tableName = "profile") data class ProfileEntity(@PrimaryKey val id: Long, val name: String, val language: String)
@Dao interface CacheDao {
    @Query("SELECT * FROM providers ORDER BY id") fun providers(): Flow<List<ProviderEntity>>
    @Query("SELECT * FROM models ORDER BY id") fun models(): Flow<List<ModelEntity>>
    @Query("SELECT * FROM conversations ORDER BY rowid DESC") fun conversations(): Flow<List<ConversationEntity>>
    @Query("SELECT * FROM messages WHERE conversationId = :id ORDER BY sequence, rowid") fun messages(id: String): Flow<List<MessageEntity>>
    @Query("SELECT * FROM messages WHERE conversationId = :conversationId AND requestId = :requestId AND role = :role LIMIT 1")
    suspend fun message(conversationId: String, requestId: String, role: String): MessageEntity?
    @Upsert suspend fun providers(rows: List<ProviderEntity>)
    @Upsert suspend fun models(rows: List<ModelEntity>)
    @Upsert suspend fun conversations(rows: List<ConversationEntity>)
    @Upsert suspend fun messages(rows: List<MessageEntity>)
    @Upsert suspend fun profile(row: ProfileEntity)
    @Query("DELETE FROM providers") suspend fun clearProviders()
    @Query("DELETE FROM models") suspend fun clearModels()
    @Query("DELETE FROM conversations") suspend fun clearConversations()
    @Query("DELETE FROM messages") suspend fun clearMessages()
    @Query("DELETE FROM profile") suspend fun clearProfile()
    @Query("DELETE FROM messages WHERE conversationId = :id") suspend fun clearConversationMessages(id: String)
    @Transaction suspend fun replaceProviders(rows: List<ProviderEntity>) { clearProviders(); providers(rows) }
    @Transaction suspend fun replaceModels(rows: List<ModelEntity>) { clearModels(); models(rows) }
    @Transaction suspend fun replaceConversations(rows: List<ConversationEntity>) { clearConversations(); conversations(rows) }
    @Transaction suspend fun replaceMessages(id: String, rows: List<MessageEntity>) { clearConversationMessages(id); messages(rows) }
    @Transaction suspend fun clearAccount() { clearMessages(); clearConversations(); clearProviders(); clearModels(); clearProfile() }
}
@Database(entities = [ProviderEntity::class, ModelEntity::class, ConversationEntity::class, MessageEntity::class, ProfileEntity::class], version = 1, exportSchema = true)
abstract class ClientDatabase: RoomDatabase() { abstract fun cache(): CacheDao }
