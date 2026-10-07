package com.wakeelm.client.core

import android.content.Context
import androidx.room.Room
import com.wakeelm.client.BuildConfig
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.android.qualifiers.ApplicationContext
import dagger.hilt.components.SingletonComponent
import kotlinx.serialization.json.Json
import okhttp3.OkHttpClient
import okhttp3.MediaType.Companion.toMediaType
import retrofit2.Retrofit
import retrofit2.converter.kotlinx.serialization.asConverterFactory
import java.util.concurrent.TimeUnit
import javax.inject.Singleton

@Module @InstallIn(SingletonComponent::class) object Bindings {
    @Provides @Singleton fun session(store: SessionStore): SessionStorage = store
    @Provides @Singleton fun json() = Json { ignoreUnknownKeys = true; encodeDefaults = true }
    @Provides @Singleton fun http(store: SessionStorage, json: Json): OkHttpClient {
        val plain = OkHttpClient.Builder().connectTimeout(10, TimeUnit.SECONDS).readTimeout(30, TimeUnit.SECONDS).followRedirects(false).retryOnConnectionFailure(false).build()
        return plain.newBuilder().addInterceptor(AuthInterceptor(store)).authenticator(RefreshAuthenticator(store, BuildConfig.BACKEND_URL, plain, json)).build()
    }
    @Provides @Singleton fun api(http: OkHttpClient, json: Json): ClientApi = Retrofit.Builder().baseUrl(BuildConfig.BACKEND_URL).client(http).addConverterFactory(json.asConverterFactory("application/json".toMediaType())).build().create(ClientApi::class.java)
    @Provides @Singleton fun stream(http: OkHttpClient, json: Json): ChatStreamClient = SseChatStreamClient(http.newBuilder().readTimeout(35, TimeUnit.SECONDS).build(), BuildConfig.BACKEND_URL, json)
    @Provides @Singleton fun database(@ApplicationContext context: Context): ClientDatabase = Room.databaseBuilder(context, ClientDatabase::class.java, "wakeelm-cache.db").build()
    @Provides fun dao(database: ClientDatabase): CacheDao = database.cache()
}
