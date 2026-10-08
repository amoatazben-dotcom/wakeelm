package com.wakeelm.client

import android.app.Application
import android.content.Context
import androidx.work.*
import dagger.hilt.android.HiltAndroidApp
import dagger.hilt.android.EntryPointAccessors
import dagger.hilt.EntryPoint
import dagger.hilt.InstallIn
import dagger.hilt.components.SingletonComponent
import com.wakeelm.client.core.SessionStorage
import com.wakeelm.client.data.ProviderRepository
import com.wakeelm.client.data.ConversationRepository
import java.util.concurrent.TimeUnit

@HiltAndroidApp class WakeelmApp: Application() {
    override fun onCreate() {
        super.onCreate()
        WorkManager.getInstance(this).enqueueUniquePeriodicWork("workspace-cache", ExistingPeriodicWorkPolicy.KEEP,
            PeriodicWorkRequestBuilder<CacheWorker>(6, TimeUnit.HOURS).setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build()).build())
    }
}
@EntryPoint @InstallIn(SingletonComponent::class) interface SyncDependencies {
    fun session(): SessionStorage
    fun providers(): ProviderRepository
    fun conversations(): ConversationRepository
}
class CacheWorker(context: Context, params: WorkerParameters): CoroutineWorker(context, params) {
    override suspend fun doWork(): Result {
        val deps = EntryPointAccessors.fromApplication(applicationContext, SyncDependencies::class.java)
        if (deps.session().read() == null) return Result.success()
        return try { deps.providers().refresh(); deps.conversations().refresh(); Result.success() }
        catch (_: Exception) { if (runAttemptCount < 2) Result.retry() else Result.failure() }
    }
}
