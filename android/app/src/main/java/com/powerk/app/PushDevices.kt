package com.powerk.app

import android.content.Context
import com.google.android.gms.tasks.Task
import com.google.firebase.messaging.FirebaseMessaging
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.collect
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import org.json.JSONObject
import java.util.concurrent.Executor
import java.io.IOException
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException

internal data class PushRecord(val base: String, val account: Long, val token: String, val deleting: Boolean = false) {
    fun belongsTo(c: ServerConnection) = !c.legacy && base == c.base && account == c.accountId
    override fun toString() = "PushRecord(redacted)"
}
internal interface PushTokenStore { fun read(): PushRecord?; fun write(record: PushRecord?) }
internal interface DeviceTokenProvider {
    suspend fun token(): String
    suspend fun delete()
    fun autoInit(enabled: Boolean)
}
internal interface PushTokenApi {
    suspend fun register(connection: ServerConnection, token: String)
    suspend fun delete(connection: ServerConnection, token: String)
}
internal data class DevicePushState(val available: Boolean = false, val connection: ServerConnection? = null,
    val hasToken: Boolean = false, val registered: Boolean = false, val failed: Boolean = false)

/** Serialized registration/deletion; a normal access-token refresh never writes a registration.
 * Persist deletion intent before Firebase IO, so a crash/offline logout cannot reuse the old token. */
internal class PushTokenClient(private val store: PushTokenStore, private val provider: DeviceTokenProvider,
    private val api: PushTokenApi, private val current: () -> ServerConnection) {
    private val lock = Mutex()
    private var registered: Pair<ServerConnection, String>? = null
    @Volatile private var suspended: ServerConnection? = null
    private val mutableState = MutableStateFlow(DevicePushState(available = true))
    val state = mutableState.asStateFlow()
    fun acceptsMessages(c: ServerConnection): Boolean = c.isCurrent(current()) && suspended != c &&
        store.read()?.let { it.belongsTo(c) && !it.deleting } == true

    suspend fun sync(c: ServerConnection) = lock.withLock {
        if (!c.isCurrent(current()) || suspended == c) return@withLock
        try {
            val old = store.read()
            if (old != null && (!old.belongsTo(c) || old.deleting || registered?.first?.let { it != c } == true)) remove(c, old)
            if (!c.isCurrent(current())) return@withLock
            if (c.legacy || c.accountId == null) {
                provider.autoInit(false)
                mutableState.value = DevicePushState(available = true, connection = c)
                return@withLock
            }
            provider.autoInit(true)
            val token = provider.token()
            if (!c.isCurrent(current())) return@withLock
            val saved = store.read()
            if (saved != null && saved.token != token && saved.belongsTo(c)) {
                // Firebase rotated the token; retire the old registration without deleting the new Firebase token.
                try { api.delete(c, saved.token) } catch (e: Exception) { if (e is CancellationException) throw e }
            }
            store.write(PushRecord(c.base, requireNotNull(c.accountId), token))
            mutableState.value = DevicePushState(true, c, hasToken = true, registered = registered == (c to token))
            if (registered != (c to token)) {
                api.register(c, token)
                if (!c.isCurrent(current())) return@withLock
                registered = c to token
            }
            mutableState.value = DevicePushState(true, c, hasToken = true, registered = true)
        } catch (e: Exception) {
            if (e is CancellationException) throw e
            if (c.isCurrent(current())) mutableState.value = DevicePushState(true, c,
                hasToken = store.read()?.let { it.belongsTo(c) && !it.deleting } == true, failed = true)
        }
    }

    suspend fun detach(c: ServerConnection) = lock.withLock {
        if (!c.isCurrent(current())) return@withLock
        suspended = c // onNewToken/onStart cannot re-register while logout/server-change is underway.
        registered = null
        mutableState.value = DevicePushState(true, c)
        provider.autoInit(false)
        store.read()?.let { record ->
            try { remove(c, record) } catch (e: Exception) { if (e is CancellationException) throw e }
        }
    }

    private suspend fun remove(c: ServerConnection, record: PushRecord) {
        registered = null
        store.write(record.copy(deleting = true))
        provider.autoInit(false)
        // Best effort, BEFORE deleting Firebase's token. Revocation also removes the server row.
        if (record.belongsTo(c)) {
            try { api.delete(c, record.token) } catch (e: Exception) { if (e is CancellationException) throw e }
        }
        provider.delete() // If offline, retain deleting=true and retry before any later registration.
        store.write(null)
    }
}

private suspend fun <T> Task<T>.awaitPushTask(): T = try {
    withTimeout(15_000) {
        suspendCancellableCoroutine<T> { continuation ->
            addOnCompleteListener(Executor { it.run() }) { task ->
                if (continuation.isActive) {
                    if (task.isSuccessful) continuation.resume(task.result)
                    else continuation.resumeWithException(task.exception ?: IllegalStateException("Firebase task cancelled"))
                }
            }
        }
    }
} catch (e: TimeoutCancellationException) {
    throw IOException("Firebase unavailable", e)
}

internal object PushDevices {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private var client: PushTokenClient? = null
    private var context: Context? = null
    private val mutableState = MutableStateFlow(DevicePushState())
    val state = mutableState.asStateFlow()

    fun init(context: Context) {
        if (this.context != null) return
        this.context = context.applicationContext
        PushNotifications.createChannels(context)
        if (!BuildConfig.FCM_ENABLED) return
        val prefs = context.getSharedPreferences("push_device", Context.MODE_PRIVATE)
        val store = object : PushTokenStore {
            override fun read(): PushRecord? = prefs.getString("registration", null)?.let {
                runCatching {
                    val o = JSONObject(it)
                    PushRecord(o.getString("base"), o.getLong("account"), o.getString("token"), o.optBoolean("deleting"))
                }.getOrNull()
            }
            override fun write(record: PushRecord?) {
                val value = record?.let { JSONObject().put("base", it.base).put("account", it.account)
                    .put("token", it.token).put("deleting", it.deleting).toString() }
                check(prefs.edit().putString("registration", value).commit())
            }
        }
        val provider = object : DeviceTokenProvider {
            override suspend fun token(): String = FirebaseMessaging.getInstance().token.awaitPushTask()
            override suspend fun delete() { FirebaseMessaging.getInstance().deleteToken().awaitPushTask() }
            override fun autoInit(enabled: Boolean) { FirebaseMessaging.getInstance().isAutoInitEnabled = enabled }
        }
        val api = object : PushTokenApi {
            override suspend fun register(connection: ServerConnection, token: String) {
                AccountApi.registerPushToken(connection, token, BuildConfig.VERSION_NAME)
            }
            override suspend fun delete(connection: ServerConnection, token: String) {
                AccountApi.deletePushToken(connection, token)
            }
        }
        val coordinator = PushTokenClient(store, provider, api, { Server.connection })
        client = coordinator
        scope.launch { coordinator.state.collect {
            if (it.connection == null || it.connection.isCurrent(Server.connection)) mutableState.value = it
        } }
        connectionChanged()
    }

    fun connectionChanged() {
        // Hide stale status and displayed notifications immediately, before the serialized IO catches up.
        val c = Server.connection
        if (state.value.connection != c) {
            mutableState.value = DevicePushState(available = BuildConfig.FCM_ENABLED, connection = c)
            context?.getSystemService(android.app.NotificationManager::class.java)?.cancelAll()
        }
        scope.launch { client?.sync(c) }
    }
    fun onNewToken() = connectionChanged() // Read the current Firebase token; ignore callbacks queued before deletion.
    fun acceptsMessages(c: ServerConnection) = BuildConfig.FCM_ENABLED && client?.acceptsMessages(c) == true
    suspend fun beforeSignOut(c: ServerConnection) = withContext(NonCancellable + Dispatchers.IO) {
        client?.detach(c)
    }
}
