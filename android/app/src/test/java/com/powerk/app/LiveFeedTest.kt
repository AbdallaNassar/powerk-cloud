package com.powerk.app

import kotlinx.coroutines.*
import kotlinx.coroutines.flow.collect
import kotlinx.coroutines.test.*
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class LiveFeedTest {
    private val account = ServerConnection("https://example.test", accountId = 1, legacy = false)
    private class Sockets : FeedSockets {
        class Open(val connection: ServerConnection, val headers: Map<String, String>, val send: (SocketSignal) -> Unit) {
            var cancelled = false
            fun text(value: String) = send(SocketSignal.Text(value))
            fun close(code: Int? = null) = send(SocketSignal.Closed(code))
        }
        val opened = mutableListOf<Open>()
        override fun open(connection: ServerConnection, headers: Map<String, String>, receive: (SocketSignal) -> Unit): FeedSocket {
            val open = Open(connection, headers, receive)
            opened += open
            return FeedSocket { open.cancelled = true }
        }
        val latest get() = opened.last()
    }
    private val state = """{"type":"state","currency":"EGP","price_kwh":2,"month_kwh":3,"month_cost":6,
        "devices":[{"mac":"A","name":"Desk","role":"owner","currency":"EGP","price_kwh":2,"month_kwh":1,"month_cost":2},
        {"mac":"B","name":"Kitchen","role":"viewer","currency":"EGP","price_kwh":2,"month_kwh":2,"month_cost":4}]}"""
    private val snapshot get() = Api.parseSnapshot(JSONObject(state), false)
    private fun auth() = FeedAuthorization(mapOf("Authorization" to "Bearer access"), {}, {})

    @Test fun messagesReplaceSnapshotUpsertOneStripAndPreserveEqualRows() = runTest {
        val sockets = Sockets()
        val feed = LiveFeedClient(backgroundScope, sockets, { auth() }, { snapshot }, { account })
        feed.setActive(account); runCurrent()
        sockets.latest.text(state); runCurrent()
        val original = feed.state.value.snapshot!!
        sockets.latest.text(state); runCurrent()
        assertSame(original, feed.state.value.snapshot)
        sockets.latest.text("""{"type":"strip","strip":{"mac":"A","name":"New desk","role":"control",
            "currency":"EGP","price_kwh":2,"month_kwh":4,"month_cost":8}}""")
        runCurrent()
        val changed = feed.state.value.snapshot!!
        assertEquals("New desk", changed.strips[0].name)
        assertEquals(StripRole.Control, changed.strips[0].role)
        assertSame(original.strips[1], changed.strips[1])
        assertEquals(6.0, changed.monthKwh, 0.0)
        assertEquals(12.0, changed.monthCost, 0.0)
        sockets.latest.text("""{"type":"strip","strip":{"mac":"C","currency":"USD","month_kwh":100,"month_cost":10}}""")
        runCurrent()
        assertEquals(3, feed.state.value.snapshot!!.strips.size)
        assertEquals(4.0, feed.state.value.snapshot!!.monthKwh, 0.0) // Mixed currencies: first strip only.
        assertEquals(8.0, feed.state.value.snapshot!!.monthCost, 0.0)
        assertEquals(StripRole.Viewer, feed.state.value.snapshot!!.strips.last().role)
    }

    @Test fun eventUpdatesBadgeAndVisibleEventsAccessInvalidatesAndRefetchesPingDoesNotWrite() = runTest {
        val sockets = Sockets()
        var pending: CompletableDeferred<Snapshot>? = null
        var polls = 0
        val feed = LiveFeedClient(backgroundScope, sockets, { auth() }, { polls++; pending?.await() ?: snapshot }, { account })
        val updates = mutableListOf<FeedEvent>()
        backgroundScope.launch { feed.events.collect { updates += it } }
        feed.setActive(account); runCurrent()
        sockets.latest.text(state); runCurrent()
        sockets.latest.text("""{"type":"event","id":4102444800,"ts":4102444801,"mac":"A","code":"offline","level":"warn","unread_alerts":7}""")
        runCurrent()
        assertEquals(7, feed.state.value.snapshot!!.unreadAlerts)
        assertEquals(4102444800L, (updates.last() as FeedEvent.Received).event.id)
        val same = feed.state.value
        sockets.latest.text("""{"type":"ping","unread_alerts":100}""")
        sockets.latest.text("""{"type":"future","private":"ignore"}""")
        runCurrent()
        assertSame(same, feed.state.value)
        pending = CompletableDeferred()
        val count = polls
        sockets.latest.text("""{"type":"access"}"""); runCurrent()
        assertNull(feed.state.value.snapshot)
        assertTrue((updates.last() as FeedEvent.Reload).clear)
        assertEquals(count + 1, polls)
        sockets.latest.text("""{"type":"strip","strip":{"mac":"B"}}"""); runCurrent()
        assertNull(feed.state.value.snapshot) // Cannot republish a removed row while the refetch is pending.
        pending!!.complete(snapshot.copy(strips = emptyList())); runCurrent()
        assertTrue(feed.state.value.snapshot!!.strips.isEmpty())
    }

    @Test fun pollsEveryTwoSecondsUntilSnapshotThenEveryMinuteAndImmediatelyOnFailure() = runTest {
        val sockets = Sockets()
        var polls = 0
        val feed = LiveFeedClient(backgroundScope, sockets, { auth() }, { polls++; snapshot }, { account }, { 0.5 })
        feed.setActive(account); runCurrent()
        assertEquals(1, polls)
        assertFalse(feed.state.value.healthy) // An upgrade/open alone is not healthy.
        advanceTimeBy(2_000); runCurrent(); assertEquals(2, polls)
        sockets.latest.text(state); runCurrent()
        assertTrue(feed.state.value.healthy)
        advanceTimeBy(25_000); sockets.latest.text("""{"type":"ping"}"""); runCurrent()
        advanceTimeBy(25_000); sockets.latest.text("""{"type":"ping"}"""); runCurrent()
        assertEquals(2, polls)
        advanceTimeBy(10_000); runCurrent(); assertEquals(3, polls)
        sockets.latest.close(1001); runCurrent()
        assertFalse(feed.state.value.healthy)
        assertEquals(4, polls)
        advanceTimeBy(2_000); runCurrent(); assertEquals(5, polls)
        feed.setActive(null); runCurrent()
        assertTrue(sockets.latest.cancelled)
        advanceTimeBy(60_000); runCurrent(); assertEquals(5, polls)
    }

    @Test fun missedHeartbeatDisconnectsAndRateLimitWaitsLonger() = runTest {
        val sockets = Sockets()
        val feed = LiveFeedClient(backgroundScope, sockets, { auth() }, { snapshot }, { account }, { 0.0 })
        feed.setActive(account); runCurrent(); sockets.latest.text(state); runCurrent()
        advanceTimeBy(55_000); runCurrent()
        assertFalse(feed.state.value.healthy)
        assertTrue(sockets.latest.cancelled)
        advanceTimeBy(800); runCurrent()
        assertEquals(2, sockets.opened.size)
        sockets.latest.close(4429); runCurrent()
        advanceTimeBy(29_999); runCurrent(); assertEquals(2, sockets.opened.size)
        advanceTimeBy(1); runCurrent(); assertEquals(3, sockets.opened.size)
    }

    @Test fun authCloseRefreshesOnceAndReconnectsThenRepeatedRejectionSignsOut() = runTest {
        val sockets = Sockets()
        var c = account
        var refreshes = 0
        var signouts = 0
        val feed = LiveFeedClient(backgroundScope, sockets, {
            FeedAuthorization(mapOf("Authorization" to "Bearer ${if (refreshes == 0) "old" else "rotated"}"),
                { refreshes++ }, { signouts++; c = c.copy(accountId = null, revision = 1) })
        }, { snapshot }, { c })
        feed.setActive(c); runCurrent()
        assertEquals("Bearer old", sockets.latest.headers["Authorization"])
        sockets.latest.close(4401); runCurrent()
        assertEquals(1, refreshes)
        assertEquals(2, sockets.opened.size)
        assertEquals("Bearer rotated", sockets.latest.headers["Authorization"])
        sockets.latest.close(4401); runCurrent()
        assertEquals(1, refreshes); assertEquals(1, signouts)
        assertEquals(2, sockets.opened.size)
    }

    @Test fun legacyUsesXTokenAndDoesNotRefreshAccounts() = runTest {
        val c = account.copy(accountId = null, legacy = true, token = "legacy")
        val sessions = SessionClient(object : TokenStore {
            override fun read(): Credentials? = null
            override fun write(value: Credentials?) { fail("No account writes") }
        }, HttpTransport { _, _, _, _ -> error("No account HTTP") }, { c }, { fail() })
        val sockets = Sockets()
        val feed = LiveFeedClient(backgroundScope, sockets, sessions::feedAuthorization, { snapshot }, { c }, { 0.5 })
        feed.setActive(c); runCurrent()
        assertEquals(mapOf("X-Token" to "legacy"), sockets.latest.headers)
        sockets.latest.close(4401); runCurrent()
        advanceTimeBy(1_000); runCurrent(); assertEquals(2, sockets.opened.size)
    }

    @Test fun lateHttpCannotOverwriteLiveChangeAndOldSocketCannotCrossAccountRevision() = runTest {
        val sockets = Sockets()
        val http = CompletableDeferred<Snapshot>()
        var c = account
        val feed = LiveFeedClient(backgroundScope, sockets, { auth() }, { http.await() }, { c })
        feed.setActive(c); runCurrent()
        val oldSocket = sockets.latest
        oldSocket.text(state); runCurrent()
        http.complete(snapshot.copy(serverIp = "stale")); runCurrent()
        assertNotEquals("stale", feed.state.value.snapshot!!.serverIp)
        c = c.copy(accountId = 2, revision = 1)
        feed.setActive(c); runCurrent()
        val current = feed.state.value
        oldSocket.text(state); runCurrent()
        assertTrue(oldSocket.cancelled)
        assertSame(current, feed.state.value)
        assertEquals(c, feed.state.value.connection)
    }

    @Test fun backoffHasExponentialBaseJitterBoundsAndRateLimitFloor() {
        val bases = listOf(1_000L, 2_000L, 4_000L, 8_000L, 16_000L, 30_000L, 30_000L)
        bases.forEachIndexed { failure, base ->
            assertEquals(base, reconnectDelayMillis(failure, 1001, 0.5))
            for (code in listOf(null, 4408, 1008, 1001)) {
                val low = reconnectDelayMillis(failure, code, 0.0)
                val high = reconnectDelayMillis(failure, code, 1.0)
                assertEquals((base * .8).toLong(), low)
                assertEquals((base * 1.2).toLong().coerceAtMost(30_000), high)
            }
        }
        assertEquals(30_000L, reconnectDelayMillis(0, 4429, 0.0))
        assertEquals(45_000L, reconnectDelayMillis(10, 4429, 1.0))
    }

    @Test fun alertMergeDeduplicatesSocketAndHttpByLongEventId() {
        val event = Api.parseEvent(JSONObject("""{"id":4102444800,"code":"offline"}"""))
        val older = event.copy(id = 1)
        val merged = mergeLiveEvents(listOf(event), listOf(event.copy(), older))
        assertEquals(listOf(4102444800L, 1L), merged.map { it.id })
        assertSame(event, merged.first())
    }

    @Test fun widgetRenderFailureDoesNotStopTheSocketOrPolling() = runTest {
        val sockets = Sockets()
        var polls = 0
        val feed = LiveFeedClient(backgroundScope, sockets, { auth() }, { polls++; snapshot }, { account },
            snapshotChanged = { _, _ -> throw IllegalStateException("Widget binder unavailable") })
        feed.setActive(account); runCurrent()
        sockets.latest.text(state); runCurrent()
        assertTrue(feed.state.value.healthy)
        sockets.latest.close(4408); runCurrent()
        assertFalse(feed.state.value.healthy)
        assertEquals(2, polls)
    }
}
