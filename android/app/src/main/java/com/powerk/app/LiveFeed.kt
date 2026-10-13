package com.powerk.app

import android.content.Context
import kotlinx.coroutines.*
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.*
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import org.json.JSONObject
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.random.Random

internal sealed interface FeedMessage {
    data class State(val snapshot: Snapshot) : FeedMessage
    data class Device(val strip: Strip) : FeedMessage
    data class Activity(val event: Event, val unread: Int) : FeedMessage
    data object Access : FeedMessage
    data object Ping : FeedMessage
}

internal fun parseFeedMessage(text: String, legacy: Boolean): FeedMessage? {
    val o = JSONObject(text)
    return when (o.text("type")) {
        "state" -> FeedMessage.State(Api.parseSnapshot(o, legacy))
        "strip" -> FeedMessage.Device(Api.parseStrip(o.getJSONObject("strip"), legacy))
        "event" -> FeedMessage.Activity(Api.parseEvent(o), o.optInt("unread_alerts").coerceAtLeast(0))
        "access" -> FeedMessage.Access
        "ping" -> FeedMessage.Ping // Receipt is the heartbeat; no reply or UI write.
        else -> null
    }
}

/** Reuse equal rows/collections even when a full HTTP or socket snapshot was decoded anew. */
internal fun retainSnapshot(old: Snapshot?, next: Snapshot): Snapshot {
    if (old != null && old == next) return old
    if (old == null) return next
    val byMac = old.strips.associateBy { it.mac }
    val rows = next.strips.map { row -> byMac[row.mac]?.takeIf { it == row } ?: row }
    return next.copy(strips = if (old.strips == rows) old.strips else rows)
}

internal fun Snapshot.withStrip(strip: Strip): Snapshot {
    val index = strips.indexOfFirst { it.mac == strip.mac }
    if (index >= 0 && strips[index] == strip) return this
    val rows = if (index < 0) strips + strip else strips.toMutableList().apply { set(index, strip) }.toList()
    val first = rows.first()
    val sameCurrency = rows.all { it.currency == first.currency }
    return copy(strips = rows, currency = first.currency, priceKwh = first.priceKwh, budget = first.budget,
        monthKwh = if (sameCurrency) rows.sumOf { it.monthKwh } else first.monthKwh,
        monthCost = if (sameCurrency) rows.sumOf { it.monthCost } else first.monthCost)
}

internal fun pollIntervalMillis(healthy: Boolean) = if (healthy) 60_000L else 2_000L

/** Base 1, 2, 4, 8, 16, 30 seconds; ±20% jitter, capped at 30 seconds.
 * Rate limits get a separate 30–45 second floor, including before the first snapshot. */
internal fun reconnectDelayMillis(failures: Int, code: Int?, random: Double): Long {
    val jitter = random.coerceIn(0.0, 1.0)
    if (code == 4429 || code == 429) return 30_000L + (15_000L * jitter).toLong()
    val base = (1_000L shl failures.coerceIn(0, 5)).coerceAtMost(30_000L)
    return (base * (0.8 + 0.4 * jitter)).toLong().coerceAtMost(30_000L)
}

internal sealed interface SocketSignal {
    data class Text(val value: String) : SocketSignal
    data class Closed(val code: Int? = null) : SocketSignal
}
internal fun interface FeedSocket { fun cancel() }
internal fun interface FeedSockets {
    fun open(connection: ServerConnection, headers: Map<String, String>, receive: (SocketSignal) -> Unit): FeedSocket
}

private class OkHttpFeedSockets : FeedSockets {
    // No redirects may carry credentials to another origin. This client is never used for REST.
    private val client = OkHttpClient.Builder().followRedirects(false).followSslRedirects(false)
        .connectTimeout(10, TimeUnit.SECONDS).readTimeout(0, TimeUnit.MILLISECONDS)
        .retryOnConnectionFailure(false).build()

    override fun open(connection: ServerConnection, headers: Map<String, String>, receive: (SocketSignal) -> Unit): FeedSocket {
        val request = Request.Builder().url("${connection.base}/api/ws").apply {
            headers.forEach { (name, value) -> header(name, value) }
        }.build() // OkHttp accepts HTTP(S) and performs the WS(S) upgrade on the same origin.
        val ended = AtomicBoolean()
        fun closed(code: Int?) { if (ended.compareAndSet(false, true)) receive(SocketSignal.Closed(code)) }
        val socket = client.newWebSocket(request, object : WebSocketListener() {
            override fun onMessage(webSocket: WebSocket, text: String) { receive(SocketSignal.Text(text)) }
            override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
                webSocket.close(code, null)
                closed(code)
            }
            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) { closed(code) }
            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) { closed(response?.code) }
        })
        return FeedSocket { socket.cancel() }
    }
}

internal data class FeedState(val connection: ServerConnection? = null, val snapshot: Snapshot? = null,
    val healthy: Boolean = false, val loading: Boolean = false, val error: Exception? = null)
internal sealed interface FeedEvent {
    val connection: ServerConnection
    data class Received(override val connection: ServerConnection, val event: Event) : FeedEvent
    data class Reload(override val connection: ServerConnection, val clear: Boolean = false) : FeedEvent
}

/** All parsing/network/widget work runs on the supplied IO scope. Tests inject sockets/auth/clock. */
internal class LiveFeedClient(private val scope: CoroutineScope, private val sockets: FeedSockets,
    private val authorization: (ServerConnection) -> FeedAuthorization,
    private val fetch: suspend (ServerConnection) -> Snapshot, private val current: () -> ServerConnection,
    private val random: () -> Double = { Random.nextDouble() },
    private val snapshotChanged: suspend (ServerConnection, Snapshot) -> Unit = { _, _ -> }) {
    private class Run(val connection: ServerConnection) {
        val refresh = Channel<Unit>(Channel.CONFLATED)
        val widgets = Channel<Unit>(Channel.CONFLATED)
        val fetchLock = Mutex()
        var version = 0L
        var acceptStrips = false
        var socket: FeedSocket? = null
        var job: Job? = null
    }
    private val lock = Any()
    private var active: Run? = null
    private val mutableState = MutableStateFlow(FeedState())
    val state = mutableState.asStateFlow()
    private val mutableEvents = MutableSharedFlow<FeedEvent>(extraBufferCapacity = 32)
    val events = mutableEvents.asSharedFlow()
    private fun valid(run: Run) = active === run && run.connection.isCurrent(current())

    fun setActive(connection: ServerConnection?) = synchronized(lock) {
        val target = connection?.takeIf { it.authorized }
        if (active?.connection == target && active != null) return@synchronized
        active?.let { it.socket?.cancel(); it.job?.cancel() }
        active = null
        mutableState.value = FeedState(connection = target)
        if (target != null) {
            val run = Run(target)
            active = run
            run.job = scope.launch {
                coroutineScope {
                    launch {
                        state.map { it.healthy }.distinctUntilChanged().collectLatest { healthy ->
                            if (healthy) delay(pollIntervalMillis(true))
                            while (isActive) {
                                refresh(run)
                                delay(pollIntervalMillis(healthy))
                            }
                        }
                    }
                    launch { for (ignored in run.refresh) refresh(run) }
                    launch {
                        // Widget binder/render work is conflated and limited to the old polling cadence.
                        for (ignored in run.widgets) {
                            val snapshot = synchronized(lock) { state.value.snapshot.takeIf { valid(run) } }
                            if (snapshot != null) try { snapshotChanged(run.connection, snapshot) }
                            catch (e: Exception) { if (e is CancellationException) throw e }
                            delay(2_000)
                        }
                    }
                    socketLoop(run)
                }
            }
        }
    }

    suspend fun refresh(connection: ServerConnection, userInitiated: Boolean = false) {
        val run = synchronized(lock) { active?.takeIf { it.connection == connection && valid(it) } } ?: return
        refresh(run, userInitiated)
    }

    // Background polls never touch `loading`: toggling it every 2 s made the outlets list jump.
    private suspend fun refresh(run: Run, userInitiated: Boolean = false) = run.fetchLock.withLock {
        val version = synchronized(lock) {
            if (!valid(run)) return@withLock
            if (userInitiated) mutableState.value = state.value.copy(loading = true)
            run.version
        }
        try {
            val result = fetch(run.connection)
            currentCoroutineContext().ensureActive()
            synchronized(lock) {
                // A response started before a live change/access invalidation cannot roll it back.
                if (valid(run) && version == run.version) {
                    publishSnapshot(run, retainSnapshot(state.value.snapshot, result))
                    run.acceptStrips = true
                    mutableState.value = state.value.copy(error = null)
                } else if (valid(run) && !run.acceptStrips) run.refresh.trySend(Unit)
            }
        } catch (e: Exception) {
            if (e is CancellationException) throw e
            synchronized(lock) { if (valid(run)) mutableState.value = state.value.copy(error = e) }
        } finally {
            if (userInitiated) synchronized(lock) { if (valid(run)) mutableState.value = state.value.copy(loading = false) }
        }
    }

    // Caller holds lock. Equal data does not write snapshot state or wake widgets.
    private fun publishSnapshot(run: Run, snapshot: Snapshot?) {
        run.version++
        if (state.value.snapshot != snapshot) {
            mutableState.value = state.value.copy(snapshot = snapshot)
            if (snapshot != null) run.widgets.trySend(Unit)
        }
    }

    private suspend fun message(run: Run, message: FeedMessage) {
        val event = synchronized(lock) {
            if (!valid(run)) return
            when (message) {
                is FeedMessage.State -> {
                    publishSnapshot(run, retainSnapshot(state.value.snapshot, message.snapshot))
                    run.acceptStrips = true
                    mutableState.value = state.value.copy(healthy = true, error = null)
                    FeedEvent.Reload(run.connection, clear = true) // Access may have changed while disconnected.
                }
                is FeedMessage.Device -> {
                    if (run.acceptStrips) state.value.snapshot?.let { publishSnapshot(run, it.withStrip(message.strip)) }
                    null
                }
                is FeedMessage.Activity -> {
                    state.value.snapshot?.let { publishSnapshot(run, it.copy(unreadAlerts = message.unread)) }
                    FeedEvent.Received(run.connection, message.event)
                }
                FeedMessage.Access -> {
                    run.acceptStrips = false
                    publishSnapshot(run, null) // Drop lost access immediately, including in-flight HTTP data.
                    run.refresh.trySend(Unit)
                    FeedEvent.Reload(run.connection, clear = true)
                }
                FeedMessage.Ping -> null
            }
        }
        if (event != null) mutableEvents.emit(event)
    }

    private suspend fun socketLoop(run: Run) {
        var failures = 0
        var retriedAuth = false
        while (currentCoroutineContext().isActive && synchronized(lock) { valid(run) }) {
            var code: Int? = null
            var auth: FeedAuthorization? = null
            val incoming = Channel<SocketSignal>(32)
            try {
                auth = authorization(run.connection)
                val socket = sockets.open(run.connection, auth.headers) { signal ->
                    // Bounded consumer: overflow forces a fresh snapshot instead of silently dropping a strip.
                    if (incoming.trySend(signal).isFailure) incoming.close()
                }
                synchronized(lock) {
                    if (valid(run)) run.socket = socket else socket.cancel()
                }
                while (currentCoroutineContext().isActive) {
                    val signal = withTimeoutOrNull(55_000) { incoming.receiveCatching().getOrNull() } ?: break
                    when (signal) {
                        is SocketSignal.Closed -> { code = signal.code; break }
                        is SocketSignal.Text -> {
                            val parsed = parseFeedMessage(signal.value, run.connection.legacy) ?: continue
                            message(run, parsed)
                            if (parsed is FeedMessage.State) { failures = 0; retriedAuth = false }
                        }
                    }
                }
            } catch (e: Exception) {
                if (e is CancellationException) throw e
                // Parsing, upgrade and connection errors all fall back to HTTP and back off.
            } finally {
                incoming.close()
                synchronized(lock) {
                    run.socket?.cancel(); run.socket = null
                    if (valid(run)) mutableState.value = state.value.copy(healthy = false)
                }
            }
            if (!synchronized(lock) { valid(run) }) return
            if (code == 4401 && !run.connection.legacy && auth != null) {
                if (retriedAuth) { auth.rejectedAfterRefresh(); return }
                try {
                    auth.refresh() // Shares REST/widget/tile refresh, including uncertain-delivery handling.
                    retriedAuth = true
                    continue
                } catch (e: Exception) { if (e is CancellationException) throw e }
            }
            delay(reconnectDelayMillis(failures++, code, random()))
        }
    }
}

/** One instance per process, not per screen. Only STARTED MainActivity owners attach. */
internal object LiveFeed {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val owners = mutableSetOf<Any>()
    private var context: Context? = null
    val client = LiveFeedClient(scope, OkHttpFeedSockets(), { AuthClient.client.feedAuthorization(it) },
        Api::snapshot, { Server.connection }, snapshotChanged = { c, snapshot ->
            context?.let { WidgetUpdates.freshSnapshot(it, snapshot, c) }
        })
    @Synchronized fun started(owner: Any, context: Context) {
        this.context = context.applicationContext
        owners.add(owner)
        connectionChanged()
    }
    @Synchronized fun stopped(owner: Any) { owners.remove(owner); connectionChanged() }
    @Synchronized fun connectionChanged() { client.setActive(Server.connection.takeIf { owners.isNotEmpty() }) }
}
