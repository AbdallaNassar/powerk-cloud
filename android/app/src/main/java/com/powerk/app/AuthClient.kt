package com.powerk.app

import android.content.Context
import android.content.SharedPreferences
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.io.IOException
import java.net.ConnectException
import java.net.HttpURLConnection
import java.net.NoRouteToHostException
import java.net.UnknownHostException
import java.net.URL
import java.security.KeyStore
import java.time.ZonedDateTime
import java.time.format.DateTimeFormatter
import java.util.concurrent.ConcurrentHashMap
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

internal data class Credentials(val base: String, val userId: Long, val phone: String,
    val access: String, val refresh: String,
    val refreshUncertainSince: Long? = null, val refreshRetryUsed: Boolean = false) {
    override fun toString() = "Credentials(redacted)"
}

internal interface TokenStore {
    fun read(): Credentials?
    fun write(value: Credentials?)
}

/** One authenticated ciphertext, no plaintext tokens or backup. Key never leaves Android Keystore. */
internal class EncryptedTokenStore(private val prefs: SharedPreferences,
    private val key: () -> SecretKey = ::keystoreKey) : TokenStore {
    private fun encrypt(value: String): String {
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.ENCRYPT_MODE, key())
        cipher.updateAAD("powerk.credentials.v1".toByteArray())
        return Base64.encodeToString(cipher.iv + cipher.doFinal(value.toByteArray(Charsets.UTF_8)), Base64.NO_WRAP)
    }
    private fun decrypt(value: String): String {
        val bytes = Base64.decode(value, Base64.NO_WRAP)
        require(bytes.size >= 28)
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, bytes.copyOfRange(0, 12)))
        cipher.updateAAD("powerk.credentials.v1".toByteArray())
        return cipher.doFinal(bytes.copyOfRange(12, bytes.size)).toString(Charsets.UTF_8)
    }
    override fun read(): Credentials? = try {
        prefs.getString("session", null)?.let { raw ->
            val o = JSONObject(decrypt(raw))
            Credentials(o.getString("base"), o.getLong("id"), o.getString("phone"),
                o.getString("access"), o.getString("refresh"),
                if (o.has("refresh_uncertain_since")) o.getLong("refresh_uncertain_since") else null,
                o.optBoolean("refresh_retry_used", false))
        }
    } catch (_: Exception) { write(null); null }

    override fun write(value: Credentials?) {
        val edit = prefs.edit()
        if (value == null) edit.remove("session") else edit.putString("session", encrypt(JSONObject()
            .put("base", value.base).put("id", value.userId).put("phone", value.phone)
            .put("access", value.access).put("refresh", value.refresh)
            .put("refresh_uncertain_since", value.refreshUncertainSince)
            .put("refresh_retry_used", value.refreshRetryUsed).toString()))
        check(edit.commit()) { "Credential storage unavailable" }
    }
    fun legacyToken(): String = try { prefs.getString("legacy", null)?.let(::decrypt).orEmpty() }
        catch (_: Exception) { saveLegacy(""); "" }
    fun saveLegacy(value: String) {
        val edit = prefs.edit()
        if (value.isEmpty()) edit.remove("legacy") else edit.putString("legacy", encrypt(value))
        check(edit.commit()) { "Credential storage unavailable" }
    }
}

private fun keystoreKey(): SecretKey {
    val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
    (store.getKey("powerk.session.v1", null) as? SecretKey)?.let { return it }
    return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore").apply {
        init(KeyGenParameterSpec.Builder("powerk.session.v1", KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
            .setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
            .setKeySize(256).setRandomizedEncryptionRequired(true).build())
    }.generateKey()
}

internal data class HttpReply(val status: Int, val body: String, val retryAfter: String? = null)
internal fun interface HttpTransport {
    suspend fun send(url: String, method: String, body: String?, headers: Map<String, String>): HttpReply
}

/** The transport knows no request body could have reached the server (including TLS setup). */
internal class RequestNotSentException(cause: IOException) : IOException("Request not sent", cause)

/** No redirects, automatic refresh retries, cookie mode, or credentials in URLs. */
internal object UrlTransport : HttpTransport {
    private val backoff = ConcurrentHashMap<String, Long>()
    override suspend fun send(url: String, method: String, body: String?, headers: Map<String, String>) =
        withContext(Dispatchers.IO) {
            val base = url.substringBefore("/api/")
            val now = System.currentTimeMillis()
            if ((backoff[base] ?: 0) > now) throw ServerException("", 429)
            wire(url, method, body, headers).also {
                if (it.status == 429) backoff[base] = now + retryAfterMillis(it.retryAfter, now)
            }
        }

    fun wire(url: String, method: String, body: String?, headers: Map<String, String>): HttpReply {
        val c = URL(url).openConnection() as HttpURLConnection
        var mayHaveSent = false
        try {
            c.instanceFollowRedirects = false
            c.useCaches = false
            c.connectTimeout = 4000
            c.readTimeout = 15000
            c.requestMethod = method
            headers.forEach { (k, v) -> c.setRequestProperty(k, v) }
            if (method == "POST" || method == "PUT") {
                val bytes = (body ?: "{}").toByteArray(Charsets.UTF_8)
                c.doOutput = true
                // Streaming mode also prevents HttpURLConnection replaying a POST after an IO failure.
                c.setFixedLengthStreamingMode(bytes.size)
                c.setRequestProperty("Content-Type", "application/json")
                // Getting the streaming output connects/handshakes before writing any body.
                c.outputStream.use {
                    mayHaveSent = true // Even a failed write may have delivered part/all of it.
                    it.write(bytes)
                }
            }
            mayHaveSent = true
            val status = c.responseCode
            val stream = if (status in 200..299) c.inputStream else c.errorStream
            return HttpReply(status, stream?.bufferedReader(Charsets.UTF_8)?.use { it.readText() }.orEmpty(),
                c.getHeaderField("Retry-After"))
        } catch (e: IOException) {
            if (!mayHaveSent) throw RequestNotSentException(e)
            throw e
        } finally { c.disconnect() }
    }
}

internal fun HttpReply.json(): JSONObject {
    if (status !in 200..299) {
        val error = runCatching { JSONObject(body).text("error") }.getOrDefault("").ifBlank { "HTTP $status" }
        throw ServerException(error, status)
    }
    return JSONObject(body)
}

internal fun retryAfterMillis(value: String?, now: Long): Long =
    value?.trim()?.toLongOrNull()?.coerceIn(1, 86400)?.times(1000)
        ?: runCatching { (ZonedDateTime.parse(value, DateTimeFormatter.RFC_1123_DATE_TIME).toInstant().toEpochMilli() - now)
            .coerceIn(1000, 86400000) }.getOrDefault(5000)

/** Captures the same refresh attempt as REST, before opening a socket. Never log headers. */
internal class FeedAuthorization(val headers: Map<String, String>,
    val refresh: suspend () -> Unit, val rejectedAfterRefresh: () -> Unit)

/** Testable process coordinator. AuthClient owns the only production instance. */
internal class SessionClient(private val store: TokenStore, private val transport: HttpTransport,
    private val current: () -> ServerConnection, private val identityChanged: (Long?) -> Unit,
    private val now: () -> Long = System::currentTimeMillis) {
    internal val stateLock = Any()
    private val refreshLock = Mutex()
    private class RefreshAttempt(val connection: ServerConnection, val access: String) {
        val result = CompletableDeferred<Credentials>()
    }
    // Requests capture their attempt BEFORE sending. Late 401s share its failure as well as
    // its success; a new request after completion may start the next recovery attempt.
    private var refreshAttempt: RefreshAttempt? = null // Guarded by stateLock.
    @Volatile private var credentials = store.read()
    private val cooldown = ConcurrentHashMap<String, Long>()
    val userId: Long? get() = credentials?.userId
    val phone: String get() = credentials?.phone.orEmpty()
    fun canRestore(base: String): Boolean = credentials?.let { it.base == base && it.refresh.isNotBlank() } == true

    private fun checkCurrent(c: ServerConnection) {
        if (!c.isCurrent(current())) throw ServerException("", messageRes = R.string.connection_changed)
    }
    fun clear() = synchronized(stateLock) {
        credentials = null
        refreshAttempt = null
        try { store.write(null) } finally { identityChanged(null) }
    }
    private fun clearIfCurrent(c: ServerConnection) = synchronized(stateLock) {
        if (c.isCurrent(current())) clear()
    }
    private suspend fun send(c: ServerConnection, path: String, method: String, body: JSONObject?,
        headers: Map<String, String> = emptyMap()): HttpReply {
        checkCurrent(c)
        if ((cooldown[c.base] ?: 0) > now()) throw ServerException("", 429)
        val reply = transport.send("${c.base}/api/$path", method, body?.toString(), headers)
        if (reply.status == 429) cooldown[c.base] = now() + retryAfterMillis(reply.retryAfter, now())
        checkCurrent(c)
        return reply
    }
    suspend fun login(c: ServerConnection, phone: String, password: String, register: Boolean) {
        val reply = send(c, "auth/${if (register) "register" else "login"}", "POST",
            JSONObject().put("phone", normalizeNumber(phone)).put("password", password)).json()
        val next = parseCredentials(c.base, reply)
        synchronized(stateLock) {
            checkCurrent(c)
            store.write(next)
            credentials = next
            identityChanged(next.userId)
        }
    }
    suspend fun request(c: ServerConnection, path: String, method: String, body: JSONObject?): JSONObject {
        if (c.legacy) return send(c, path, method, body,
            if (c.token.isBlank()) emptyMap() else mapOf("X-Token" to c.token)).json()
        val (used, attempt) = capture(c)
        val first = send(c, path, method, body, mapOf("Authorization" to "Bearer ${used.access}"))
        if (path == "auth/password" && first.status == 401 &&
            runCatching { JSONObject(first.body).text("error") }.getOrNull() == "wrong phone or password") return first.json()
        if (first.status != 401) return first.json()
        val refreshed = refresh(c, attempt)
        val retry = send(c, path, method, body, mapOf("Authorization" to "Bearer ${refreshed.access}"))
        if (retry.status == 401) clearIfCurrent(c)
        return retry.json() // Exactly one retry of the original request, including mutations.
    }
    private fun capture(c: ServerConnection): Pair<Credentials, RefreshAttempt> = synchronized(stateLock) {
        checkCurrent(c)
        val saved = credentials?.takeIf { it.base == c.base && it.userId == c.accountId }
            ?: throw ServerException("", 401)
        val attempt = refreshAttempt?.takeIf {
            it.connection == c && it.access == saved.access && !it.result.isCompleted
        } ?: RefreshAttempt(c, saved.access).also { refreshAttempt = it }
        saved to attempt
    }
    internal fun feedAuthorization(c: ServerConnection): FeedAuthorization {
        if (c.legacy) {
            checkCurrent(c)
            return FeedAuthorization(mapOf("X-Token" to c.token), {}, {})
        }
        val (used, attempt) = capture(c)
        return FeedAuthorization(mapOf("Authorization" to "Bearer ${used.access}"),
            { refresh(c, attempt); Unit }, { clearIfCurrent(c) })
    }
    private suspend fun refresh(c: ServerConnection, attempt: RefreshAttempt): Credentials =
        withContext(NonCancellable + Dispatchers.IO) {
            refreshLock.withLock {
                if (!attempt.result.isCompleted) {
                    try { attempt.result.complete(rotate(c, attempt.access)) }
                    catch (e: Exception) { attempt.result.completeExceptionally(e) }
                }
            }
            attempt.result.await()
        }

    private suspend fun rotate(c: ServerConnection, rejectedAccess: String): Credentials {
        val old = synchronized(stateLock) {
            checkCurrent(c)
            val saved = credentials ?: throw ServerException("", 401)
            if (saved.access != rejectedAccess) return saved
            val age = saved.refreshUncertainSince?.let { now() - it }
            if (saved.refresh.isBlank() || saved.refreshRetryUsed || (age != null && age !in 0L until 50000L)) {
                clearIfCurrent(c)
                throw ServerException("", 401)
            }
            // Keep the token, but reserve its use durably before IO. After process death we
            // must assume delivery, and allow only the server's one grace reuse, within 50s.
            val reserved = saved.copy(refreshUncertainSince = saved.refreshUncertainSince ?: now(),
                refreshRetryUsed = saved.refreshUncertainSince != null)
            store.write(reserved)
            credentials = reserved
            saved
        }
        try {
            val reply = send(c, "auth/refresh", "POST", JSONObject().put("refresh_token", old.refresh))
            if (reply.status !in 200..299) reply.json()
            // A malformed successful reply may also have consumed the token.
            val next = try { parseCredentials(c.base, reply.json()) }
                catch (e: Exception) { throw IOException("Invalid refresh response", e) }
            if (next.userId != old.userId) throw ServerException("", 401)
            synchronized(stateLock) {
                checkCurrent(c)
                store.write(next)
                credentials = next
            }
            return next
        } catch (e: Exception) {
            val unsent = e is RequestNotSentException || e is UnknownHostException ||
                e is ConnectException || e is NoRouteToHostException || (e is ServerException && e.status == 429)
            val uncertain = e is IOException || (e is ServerException && e.status in 500..599)
            if (unsent) {
                synchronized(stateLock) {
                    checkCurrent(c)
                    // Also return an unspent grace retry if this attempt never left the phone.
                    store.write(old)
                    credentials = old
                }
            } else if (!uncertain) {
                clearIfCurrent(c)
                throw e
            }
            // Uncertain delivery keeps the reserved credentials/deadline in memory AND at rest.
            throw ServerException("", messageRes = R.string.connection_failed).apply { initCause(e) }
        }
    }
}

internal fun parseCredentials(base: String, o: JSONObject): Credentials {
    val user = o.getJSONObject("user")
    return Credentials(base, user.getLong("id"), user.getString("phone"),
        o.getString("access_token"), o.getString("refresh_token")).also {
        require(it.access.isNotBlank() && it.refresh.isNotBlank())
    }
}

object AuthClient {
    internal lateinit var vault: EncryptedTokenStore
    internal lateinit var client: SessionClient
    internal fun init(context: Context) {
        if (::client.isInitialized) return
        vault = EncryptedTokenStore(context.getSharedPreferences("credentials", Context.MODE_PRIVATE))
        client = SessionClient(vault, UrlTransport, { Server.connection }, { Server.accountChanged(it) })
    }
    internal val accountId: Long? get() = client.userId
    val phone: String get() = client.phone
    internal fun clear() = client.clear()
    suspend fun login(c: ServerConnection, phone: String, password: String, register: Boolean) =
        withContext(Dispatchers.IO) { client.login(c, phone, password, register) }
    internal suspend fun request(c: ServerConnection, path: String, method: String, body: JSONObject?): JSONObject {
        if (c.legacy) {
            fun check() {
                if (::client.isInitialized && !c.isCurrent(Server.connection))
                    throw ServerException("", messageRes = R.string.connection_changed)
            }
            check()
            val reply = UrlTransport.send("${c.base}/api/$path", method, body?.toString(),
                if (c.token.isEmpty()) emptyMap() else mapOf("X-Token" to c.token))
            check()
            return reply.json()
        }
        return client.request(c, path, method, body)
    }
    suspend fun signOut(c: ServerConnection = Server.connection) {
        // Try revocation, but always wipe local credentials, even offline or after cancellation.
        try {
            PushDevices.beforeSignOut(c)
            request(c, "auth/logout", "POST", JSONObject())
        }
        finally { withContext(NonCancellable + Dispatchers.IO) {
            synchronized(client.stateLock) { if (c.isCurrent(Server.connection)) clear() }
        } }
    }
}
