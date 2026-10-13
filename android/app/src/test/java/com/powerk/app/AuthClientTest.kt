package com.powerk.app

import kotlinx.coroutines.*
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import java.io.IOException
import java.net.ConnectException
import java.net.NoRouteToHostException
import java.net.SocketTimeoutException
import java.net.UnknownHostException
import java.util.concurrent.ConcurrentLinkedQueue
import java.util.concurrent.atomic.AtomicInteger
import javax.net.ssl.SSLHandshakeException

class AuthClientTest {
    @Test fun webSocketAndLateRest401ShareOneRefreshAttempt() = runBlocking {
        val c = ServerConnection(initial.base, accountId = 1, legacy = false)
        val store = MemoryStore(initial)
        val restSent = CompletableDeferred<Unit>()
        val rotationDone = CompletableDeferred<Unit>()
        val refreshes = AtomicInteger()
        val client = SessionClient(store, HttpTransport { url, _, _, headers ->
            if (url.endsWith("auth/refresh")) {
                refreshes.incrementAndGet()
                pair().also { rotationDone.complete(Unit) }
            } else if (headers["Authorization"] == "Bearer old-access") {
                restSent.complete(Unit)
                rotationDone.await()
                unauthorized
            } else ok
        }, { c }, { fail("Rotation must preserve account identity") })
        val socket = client.feedAuthorization(c)
        assertEquals("Bearer old-access", socket.headers["Authorization"])
        withTimeout(10_000) {
            val rest = async { client.request(c, "state", "GET", null) }
            restSent.await()
            (1..16).map { async { socket.refresh() } }.awaitAll()
            assertTrue(rest.await().getBoolean("ok"))
        }
        assertEquals(1, refreshes.get())
        assertEquals("Bearer new-access", client.feedAuthorization(c).headers["Authorization"])
    }

    private val initial = Credentials("https://example.test", 1, "+201001234567", "old-access", "single-use")
    private class MemoryStore(initial: Credentials?) : TokenStore {
        @Volatile var value = initial
        override fun read() = value
        override fun write(value: Credentials?) { this.value = value }
    }
    private fun pair(access: String = "new-access", refresh: String = "rotated") = HttpReply(200,
        """{"user":{"id":1,"phone":"+201001234567"},"access_token":"$access","refresh_token":"$refresh","expires_in":900}""")
    private val unauthorized = HttpReply(401, """{"error":"session required"}""")
    private val ok = HttpReply(200, """{"ok":true}""")

    @Test fun manyParallel401sRefreshExactlyOnceAndLate401UsesRotatedPair() = runBlocking {
        val count = 32
        val arrivals = AtomicInteger()
        val refreshes = AtomicInteger()
        val retries = AtomicInteger()
        val allSent = CompletableDeferred<Unit>()
        val refreshed = CompletableDeferred<Unit>()
        val store = MemoryStore(initial)
        val c = ServerConnection(initial.base, accountId = 1, legacy = false)
        val client = SessionClient(store, HttpTransport { url, _, body, headers ->
            assertFalse(headers.containsKey("X-Token"))
            assertFalse(headers.containsKey("X-Powerk-Client"))
            if (url.endsWith("auth/refresh")) {
                refreshes.incrementAndGet()
                assertEquals("single-use", JSONObject(body!!).getString("refresh_token"))
                assertEquals("single-use", store.value!!.refresh)
                assertNotNull(store.value!!.refreshUncertainSince) // Crash-safe reservation before IO.
                refreshed.complete(Unit)
                pair()
            } else if (headers["Authorization"] == "Bearer old-access") {
                val n = arrivals.incrementAndGet()
                if (n == count) allSent.complete(Unit)
                allSent.await()
                if (n == 1) { refreshed.await(); delay(30) } // A straggling response after refresh.
                unauthorized
            } else {
                assertEquals("Bearer new-access", headers["Authorization"])
                retries.incrementAndGet()
                ok
            }
        }, { c }, { fail("refresh must not change account identity") })
        withTimeout(10000) {
            (1..count).map { async(Dispatchers.Default) { client.request(c, "state", "GET", null) } }
                .awaitAll().forEach { assertTrue(it.getBoolean("ok")) }
        }
        assertEquals(1, refreshes.get())
        assertEquals(count, retries.get())
        assertEquals("rotated", store.value!!.refresh)
    }

    @Test fun retryIsOnceAndSecond401SignsOut() = runBlocking {
        val store = MemoryStore(initial)
        var c = ServerConnection(initial.base, accountId = 1, legacy = false)
        val captured = c
        var refreshes = 0
        var commands = 0
        var wipes = 0
        val client = SessionClient(store, HttpTransport { url, _, _, _ ->
            if (url.endsWith("auth/refresh")) { refreshes++; pair() } else { commands++; unauthorized }
        }, { c }, { wipes++; c = c.copy(accountId = null, revision = c.revision + 1) })
        try { client.request(captured, "onoff", "POST", JSONObject().put("on", true)); fail() }
        catch (e: ServerException) { assertEquals(401, e.status) }
        assertEquals(1, refreshes)
        assertEquals(2, commands)
        assertEquals(1, wipes)
        assertNull(store.value)
    }

    @Test fun definiteRejectionSignsOutWithoutReplayingRefresh() = runBlocking {
        for (rejection in listOf(unauthorized, HttpReply(403, "{}"),
            HttpReply(200, pair().body.replace("\"id\":1", "\"id\":2")))) {
            val store = MemoryStore(initial)
            var c = ServerConnection(initial.base, accountId = 1, legacy = false)
            val captured = c
            val refreshes = AtomicInteger()
            val arrivals = AtomicInteger()
            val allSent = CompletableDeferred<Unit>()
            var wipes = 0
            val client = SessionClient(store, HttpTransport { url, _, _, _ ->
                if (url.endsWith("auth/refresh")) {
                    refreshes.incrementAndGet()
                    rejection
                } else {
                    if (arrivals.incrementAndGet() == 16) allSent.complete(Unit)
                    allSent.await(); unauthorized
                }
            }, { c }, { wipes++; c = c.copy(accountId = null, revision = c.revision + 1) })
            withTimeout(10000) {
                (1..16).map { async { runCatching { client.request(captured, "state", "GET", null) } } }
                    .awaitAll().forEach { assertTrue(it.isFailure) }
            }
            assertEquals(1, refreshes.get())
            assertEquals(1, wipes)
            assertNull(store.value)
        }
    }

    @Test fun definitelyUnsentRefreshRestoresCredentialsAndAllowsLaterRetry() = runBlocking {
        for (failure in listOf(UnknownHostException(), ConnectException(), NoRouteToHostException(),
            RequestNotSentException(SSLHandshakeException("handshake before body")), ServerException("", 429))) {
            val store = MemoryStore(initial)
            val c = ServerConnection(initial.base, accountId = 1, legacy = false)
            var now = 1000L
            var refreshes = 0
            val transport = HttpTransport { url, _, _, headers ->
                if (url.endsWith("auth/refresh")) {
                    if (++refreshes == 1) throw failure
                    pair()
                } else if (headers["Authorization"] == "Bearer old-access") unauthorized else ok
            }
            val client = SessionClient(store, transport, { c }, { fail("Unsent refresh must not sign out") }, { now })
            val error = runCatching { client.request(c, "state", "GET", null) }.exceptionOrNull()
            assertEquals(R.string.connection_failed, (error as ServerException).messageRes)
            assertEquals(initial, store.value)
            assertTrue(client.canRestore(c.base))
            now += 60000 // A known-unsent attempt must not impose a recovery deadline, even after restart.
            val restarted = SessionClient(store, transport, { c }, { fail() }, { now })
            assertTrue(restarted.request(c, "state", "GET", null).getBoolean("ok"))
            assertEquals(2, refreshes)
        }
    }

    @Test fun transientRefreshFailureIsSharedIncludingLate401s() = runBlocking {
        for (failure in listOf(UnknownHostException(), SocketTimeoutException(), ServerException("", 503))) {
            val store = MemoryStore(initial)
            val c = ServerConnection(initial.base, accountId = 1, legacy = false)
            val arrivals = AtomicInteger()
            val refreshes = AtomicInteger()
            val allSent = CompletableDeferred<Unit>()
            val firstOutcome = CompletableDeferred<Unit>()
            val client = SessionClient(store, HttpTransport { url, _, _, _ ->
                if (url.endsWith("auth/refresh")) {
                    refreshes.incrementAndGet()
                    throw failure
                } else {
                    val n = arrivals.incrementAndGet()
                    if (n == 16) allSent.complete(Unit)
                    allSent.await()
                    if (n == 1) firstOutcome.await() // The refresh has already failed before this 401.
                    unauthorized
                }
            }, { c }, { fail("Transient refresh must not sign out") })
            val outcomes = withTimeout(10000) {
                (1..16).map { async(Dispatchers.Default) {
                    runCatching { client.request(c, "state", "GET", null) }.also { firstOutcome.complete(Unit) }
                } }.awaitAll()
            }
            val error = outcomes.first().exceptionOrNull()
            assertNotNull(error)
            outcomes.forEach { assertSame(error, it.exceptionOrNull()) }
            assertEquals(1, refreshes.get())
            assertEquals("single-use", store.value!!.refresh)
        }
    }

    @Test fun uncertainRefreshReusesSameTokenOnceWithinFiftySeconds() = runBlocking {
        for (failure in listOf(SocketTimeoutException(), IOException("lost response"),
            SSLHandshakeException("not known to precede body"), ServerException("", 500),
            ServerException("", 502), ServerException("", 503))) {
            val store = MemoryStore(initial)
            val c = ServerConnection(initial.base, accountId = 1, legacy = false)
            var now = 1000L
            val tokens = mutableListOf<String>()
            val transport = HttpTransport { url, _, body, headers ->
                if (url.endsWith("auth/refresh")) {
                    tokens += JSONObject(body!!).getString("refresh_token")
                    if (tokens.size == 1) {
                        if (failure is ServerException) HttpReply(failure.status, "{}") else throw failure
                    } else pair()
                } else if (headers["Authorization"] == "Bearer old-access") unauthorized else ok
            }
            val client = SessionClient(store, transport, { c }, { fail() }, { now })
            val error = runCatching { client.request(c, "state", "GET", null) }.exceptionOrNull()
            assertEquals(R.string.connection_failed, (error as ServerException).messageRes)
            assertEquals(initial.copy(refreshUncertainSince = 1000), store.value)
            now += 49999
            // Restart must retain the grace deadline and the original token.
            val restarted = SessionClient(store, transport, { c }, { fail() }, { now })
            assertTrue(restarted.canRestore(c.base))
            assertTrue(restarted.request(c, "state", "GET", null).getBoolean("ok"))
            assertEquals(listOf("single-use", "single-use"), tokens)
            assertEquals(initial.copy(access = "new-access", refresh = "rotated"), store.value)
        }
    }

    @Test fun lostGraceRetryCannotBeSentAThirdTimeEvenAfterRestart() = runBlocking {
        val store = MemoryStore(initial)
        val c = ServerConnection(initial.base, accountId = 1, legacy = false)
        var now = 1000L
        var wipes = 0
        val tokens = mutableListOf<String>()
        val transport = HttpTransport { url, _, body, _ ->
            if (url.endsWith("auth/refresh")) {
                tokens += JSONObject(body!!).getString("refresh_token")
                throw IOException("lost response")
            } else unauthorized
        }
        val client = SessionClient(store, transport, { c }, { wipes++ }, { now })
        assertTrue(runCatching { client.request(c, "state", "GET", null) }.isFailure)
        now += 40000
        assertTrue(runCatching { client.request(c, "state", "GET", null) }.isFailure)
        assertEquals(0, wipes)
        assertEquals(initial.copy(refreshUncertainSince = 1000, refreshRetryUsed = true), store.value)
        val restarted = SessionClient(store, transport, { c }, { wipes++ }, { now })
        val error = runCatching { restarted.request(c, "state", "GET", null) }.exceptionOrNull()
        assertEquals(401, (error as ServerException).status)
        assertEquals(listOf("single-use", "single-use"), tokens)
        assertEquals(1, wipes)
        assertNull(store.value)
    }

    @Test fun parallelRecoveryRequestsShareTheOneGraceReuse() = runBlocking {
        val store = MemoryStore(initial)
        val c = ServerConnection(initial.base, accountId = 1, legacy = false)
        val arrivals = AtomicInteger()
        val barriers = List(2) { CompletableDeferred<Unit>() }
        val tokens = ConcurrentLinkedQueue<String>()
        val client = SessionClient(store, HttpTransport { url, _, body, headers ->
            if (url.endsWith("auth/refresh")) {
                tokens.add(JSONObject(body!!).getString("refresh_token"))
                if (tokens.size == 1) throw SocketTimeoutException()
                pair()
            } else if (headers["Authorization"] == "Bearer old-access") {
                val n = arrivals.incrementAndGet()
                val gate = barriers[(n - 1) / 16]
                if (n % 16 == 0) gate.complete(Unit)
                gate.await()
                unauthorized
            } else ok
        }, { c }, { fail() }, { 1000L })
        withTimeout(10000) {
            val failures = (1..16).map { async(Dispatchers.Default) {
                runCatching { client.request(c, "state", "GET", null) }
            } }.awaitAll()
            failures.forEach { assertTrue(it.isFailure) }
            (1..16).map { async(Dispatchers.Default) { client.request(c, "state", "GET", null) } }
                .awaitAll().forEach { assertTrue(it.getBoolean("ok")) }
        }
        assertEquals(listOf("single-use", "single-use"), tokens.toList())
        assertEquals("rotated", store.value!!.refresh)
    }

    @Test fun uncertainTokenExpiresAtFiftySecondsAndRejectsClockRollback() = runBlocking {
        for (elapsed in listOf(50000L, -1L)) {
            val store = MemoryStore(initial)
            val c = ServerConnection(initial.base, accountId = 1, legacy = false)
            var now = 1000L
            var refreshes = 0
            var wipes = 0
            val transport = HttpTransport { url, _, _, _ ->
                if (url.endsWith("auth/refresh")) { refreshes++; throw SocketTimeoutException() } else unauthorized
            }
            val client = SessionClient(store, transport, { c }, { wipes++ }, { now })
            assertTrue(runCatching { client.request(c, "state", "GET", null) }.isFailure)
            now += elapsed
            val restarted = SessionClient(store, transport, { c }, { wipes++ }, { now })
            assertTrue(restarted.canRestore(c.base)) // Expiry only signs out when another 401 needs refresh.
            assertEquals(0, wipes)
            val error = runCatching { restarted.request(c, "state", "GET", null) }.exceptionOrNull()
            assertEquals(401, (error as ServerException).status)
            assertEquals(1, refreshes)
            assertEquals(1, wipes)
            assertNull(store.value)
        }
    }

    @Test fun crashBeforeUnsentFailureRecoveryStillLeavesARecoverableStoredSession() = runBlocking {
        val store = MemoryStore(initial)
        val c = ServerConnection(initial.base, accountId = 1, legacy = false)
        var atCrash: Credentials? = null
        val client = SessionClient(store, HttpTransport { url, _, _, _ ->
            if (url.endsWith("auth/refresh")) {
                atCrash = store.read() // Process could die before the catch/restore executes.
                throw UnknownHostException()
            } else unauthorized
        }, { c }, { fail() }, { 1000L })
        assertTrue(runCatching { client.request(c, "state", "GET", null) }.isFailure)
        assertEquals(initial, store.value)
        val restartedStore = MemoryStore(atCrash)
        val restarted = SessionClient(restartedStore, HttpTransport { url, _, body, headers ->
            if (url.endsWith("auth/refresh")) {
                assertEquals("single-use", JSONObject(body!!).getString("refresh_token"))
                pair()
            } else if (headers["Authorization"] == "Bearer old-access") unauthorized else ok
        }, { c }, { fail() }, { 2000L })
        assertTrue(restarted.canRestore(c.base))
        assertTrue(restarted.request(c, "state", "GET", null).getBoolean("ok"))
        assertEquals("rotated", restartedStore.value!!.refresh)
    }

    @Test fun cooldownBetween401AndRefreshDoesNotConsumeToken() = runBlocking {
        val store = MemoryStore(initial)
        val c = ServerConnection(initial.base, accountId = 1, legacy = false)
        val started = CompletableDeferred<Unit>()
        val release = CompletableDeferred<Unit>()
        var now = 1000L
        var refreshes = 0
        val client = SessionClient(store, HttpTransport { url, _, _, headers ->
            when {
                url.endsWith("auth/refresh") -> { refreshes++; pair() }
                url.endsWith("limited") -> HttpReply(429, "{}", "10")
                headers["Authorization"] == "Bearer old-access" -> {
                    started.complete(Unit); release.await(); unauthorized
                }
                else -> ok
            }
        }, { c }, { fail() }, { now })
        withTimeout(10000) {
            val waiting = async { runCatching { client.request(c, "state", "GET", null) } }
            started.await()
            assertTrue(runCatching { client.request(c, "limited", "GET", null) }.isFailure)
            release.complete(Unit)
            val error = waiting.await().exceptionOrNull() as ServerException
            assertEquals(R.string.connection_failed, error.messageRes)
        }
        assertEquals(0, refreshes)
        assertEquals(initial, store.value)
        now += 10001
        assertTrue(client.request(c, "state", "GET", null).getBoolean("ok"))
        assertEquals(1, refreshes)
    }

    @Test fun definitelyUnsentGraceRetryDoesNotSpendOrExtendTheGraceWindow() = runBlocking {
        val store = MemoryStore(initial.copy(refreshUncertainSince = 1000))
        val c = ServerConnection(initial.base, accountId = 1, legacy = false)
        var refreshes = 0
        val client = SessionClient(store, HttpTransport { url, _, _, headers ->
            if (url.endsWith("auth/refresh")) {
                if (++refreshes == 1) throw ConnectException()
                pair()
            } else if (headers["Authorization"] == "Bearer old-access") unauthorized else ok
        }, { c }, { fail() }, { 2000L })
        assertTrue(runCatching { client.request(c, "state", "GET", null) }.isFailure)
        assertEquals(initial.copy(refreshUncertainSince = 1000), store.value)
        assertTrue(client.request(c, "state", "GET", null).getBoolean("ok"))
        assertEquals(2, refreshes)
    }

    @Test fun leavingScreenDuringRefreshStillPersistsTheRotatedPair() = runBlocking {
        val store = MemoryStore(initial)
        val c = ServerConnection(initial.base, accountId = 1, legacy = false)
        val started = CompletableDeferred<Unit>()
        val release = CompletableDeferred<Unit>()
        val client = SessionClient(store, HttpTransport { url, _, _, headers ->
            if (url.endsWith("auth/refresh")) { started.complete(Unit); release.await(); pair() }
            else if (headers["Authorization"] == "Bearer old-access") unauthorized else ok
        }, { c }, { fail() })
        val job = launch { client.request(c, "state", "GET", null) }
        started.await(); job.cancel(); release.complete(Unit); job.join()
        assertEquals("rotated", store.value!!.refresh)
        assertTrue(client.request(c, "state", "GET", null).getBoolean("ok"))
    }

    @Test fun oldRefreshCannotRestoreTokensAfterAnAccountChange() = runBlocking {
        val store = MemoryStore(initial)
        var c = ServerConnection(initial.base, accountId = 1, legacy = false)
        val old = c
        val started = CompletableDeferred<Unit>()
        val release = CompletableDeferred<Unit>()
        val client = SessionClient(store, HttpTransport { url, _, _, _ ->
            if (url.endsWith("auth/refresh")) { started.complete(Unit); release.await(); pair() } else unauthorized
        }, { c }, { id -> c = c.copy(accountId = id, revision = c.revision + 1) })
        val job = async { runCatching { client.request(old, "state", "GET", null) } }
        started.await(); client.clear(); release.complete(Unit)
        assertTrue(job.await().isFailure)
        assertNull(store.value)
    }

    @Test fun rateLimitPreventsFurtherNetworkCallsUntilRetryAfter() = runBlocking {
        val store = MemoryStore(initial)
        val c = ServerConnection(initial.base, accountId = 1, legacy = false)
        var now = 1000L
        var calls = 0
        val client = SessionClient(store, HttpTransport { _, _, _, _ ->
            calls++; if (calls == 1) HttpReply(429, "{}", "10") else ok
        }, { c }, { fail() }, { now })
        repeat(5) {
            try { client.request(c, "state", "GET", null); fail() }
            catch (e: ServerException) { assertEquals(429, e.status) }
        }
        assertEquals(1, calls)
        now += 10001
        assertTrue(client.request(c, "state", "GET", null).getBoolean("ok"))
        assertEquals(2, calls)
    }

    @Test fun mutationRetryPreservesMethodBodyAndDoesNotReplayOtherFailures() = runBlocking {
        val store = MemoryStore(initial)
        val c = ServerConnection(initial.base, accountId = 1, legacy = false)
        val bodies = mutableListOf<String?>()
        val client = SessionClient(store, HttpTransport { url, method, body, headers ->
            if (url.endsWith("auth/refresh")) pair() else {
                assertEquals("POST", method); bodies += body
                if (headers["Authorization"] == "Bearer old-access") unauthorized
                else HttpReply(502, """{"error":"outcome unknown"}""")
            }
        }, { c }, { fail() })
        try { client.request(c, "onoff", "POST", JSONObject().put("on", false)); fail() }
        catch (e: ServerException) { assertEquals(502, e.status) }
        assertEquals(listOf("""{"on":false}""", """{"on":false}"""), bodies)
    }
}
