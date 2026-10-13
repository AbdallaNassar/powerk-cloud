package com.powerk.app

import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.launch
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.ExperimentalCoroutinesApi
import org.junit.Assert.*
import org.junit.Test
import java.io.IOException

@OptIn(ExperimentalCoroutinesApi::class)
class PushTokenClientTest {
    private val account = ServerConnection("https://example.test", accountId = 7, legacy = false)
    private class Store : PushTokenStore {
        var record: PushRecord? = null
        override fun read() = record
        override fun write(record: PushRecord?) { this.record = record }
    }
    private class Device(private val calls: MutableList<String>) : DeviceTokenProvider {
        var value = "fcm:one"
        var automatic = false
        var failDelete = false
        var pending: CompletableDeferred<String>? = null
        override suspend fun token() = pending?.await() ?: value
        override suspend fun delete() {
            calls += "firebase-delete"
            if (failDelete) throw IOException("offline")
            value = "fcm:next"
        }
        override fun autoInit(enabled: Boolean) { automatic = enabled }
    }
    private class Api(private val calls: MutableList<String>) : PushTokenApi {
        var failDelete = false
        var failRegister = false
        override suspend fun register(connection: ServerConnection, token: String) {
            calls += "post:${connection.base}:${connection.accountId}:$token"
            if (failRegister) throw IOException("offline")
        }
        override suspend fun delete(connection: ServerConnection, token: String) {
            calls += "delete:${connection.base}:${connection.accountId}:$token"
            if (failDelete) throw IOException("offline")
        }
    }

    @Test fun signInRegistersOnceAndSignOutDeletesServerBeforeFirebase() = runTest {
        val calls = mutableListOf<String>()
        val store = Store()
        val device = Device(calls)
        var c = account.copy(accountId = null)
        val client = PushTokenClient(store, device, Api(calls), { c })
        client.sync(c)
        assertTrue(calls.isEmpty())
        assertFalse(device.automatic)
        c = account.copy(revision = 1)
        client.sync(c) // Login and registration both publish a new ServerConnection identity.
        assertTrue(client.state.value.registered)
        assertTrue(client.acceptsMessages(c))
        client.sync(c); client.sync(c) // Startup/onNewToken with unchanged token/normal auth refresh.
        assertEquals(1, calls.size)
        client.detach(c)
        client.sync(c) // A queued callback during logout cannot resurrect the old registration.
        assertEquals(listOf("post:https://example.test:7:fcm:one", "delete:https://example.test:7:fcm:one", "firebase-delete"), calls)
        assertNull(store.record)
        assertFalse(device.automatic)
        assertFalse(client.acceptsMessages(c))
        c = c.copy(accountId = null, revision = 2)
        client.sync(c)
        assertFalse(client.state.value.hasToken)
    }

    @Test fun serverAndAccountSwitchDeleteOldTokenBeforeRegisteringNewOne() = runTest {
        for (next in listOf(account.copy(accountId = 8, revision = 1),
            account.copy(base = "https://other.test", revision = 1))) {
            val calls = mutableListOf<String>()
            val store = Store()
            val device = Device(calls)
            var c = account
            val client = PushTokenClient(store, device, Api(calls), { c })
            client.sync(c)
            client.detach(c) // Same transaction as sign-out/server save, while old auth is available.
            c = next
            client.sync(c)
            assertEquals("delete:https://example.test:7:fcm:one", calls[1])
            assertEquals("firebase-delete", calls[2])
            assertEquals("post:${next.base}:${next.accountId}:fcm:next", calls[3])
            assertEquals(next, client.state.value.connection)
        }
    }

    @Test fun rotatedTokenRetiresOldRowAndRegistersNewToken() = runTest {
        val calls = mutableListOf<String>()
        val store = Store()
        val device = Device(calls)
        val client = PushTokenClient(store, device, Api(calls), { account })
        client.sync(account)
        device.value = "fcm:rotated"
        client.sync(account)
        assertEquals(listOf("post:https://example.test:7:fcm:one", "delete:https://example.test:7:fcm:one",
            "post:https://example.test:7:fcm:rotated"), calls)
        assertEquals("fcm:rotated", store.record!!.token)
    }

    @Test fun offlineServerDeletionStillDeletesFirebaseAndRestartRegistersIdempotently() = runTest {
        val calls = mutableListOf<String>()
        val store = Store()
        val device = Device(calls)
        val api = Api(calls)
        val first = PushTokenClient(store, device, api, { account })
        first.sync(account)
        val restarted = PushTokenClient(store, device, api, { account })
        assertTrue(restarted.acceptsMessages(account)) // Data-only cold-start delivery must not await registration HTTP.
        restarted.sync(account)
        assertEquals(2, calls.size) // One startup upsert per process.
        api.failDelete = true
        restarted.detach(account)
        assertEquals("firebase-delete", calls.last())
        assertNull(store.record)
    }

    @Test fun failedFirebaseDeletionSurvivesRestartAndBlocksTokenReuseUntilDeleted() = runTest {
        val calls = mutableListOf<String>()
        val store = Store()
        val device = Device(calls)
        var c = account
        val api = Api(calls)
        val first = PushTokenClient(store, device, api, { c })
        first.sync(c)
        device.failDelete = true
        first.detach(c)
        assertTrue(store.record!!.deleting)
        assertFalse(first.acceptsMessages(c))
        c = c.copy(accountId = 8, revision = 1)
        val restarted = PushTokenClient(store, device, api, { c })
        restarted.sync(c)
        assertTrue(restarted.state.value.failed)
        assertEquals(1, calls.count { it.startsWith("post:") })
        device.failDelete = false
        restarted.sync(c)
        assertTrue(restarted.state.value.registered)
        assertEquals("post:https://example.test:8:fcm:next", calls.last())
        assertFalse(store.record!!.deleting)
    }

    @Test fun failedRegisterRetriesAndLegacyNeverRegisters() = runTest {
        val calls = mutableListOf<String>()
        val store = Store()
        val device = Device(calls)
        var c = account
        val api = Api(calls).apply { failRegister = true }
        val client = PushTokenClient(store, device, api, { c })
        client.sync(c)
        assertTrue(client.state.value.failed)
        assertFalse(client.state.value.registered)
        api.failRegister = false
        client.sync(c)
        assertTrue(client.state.value.registered)
        client.detach(c)
        c = c.copy(legacy = true, accountId = null, revision = 1)
        val count = calls.size
        client.sync(c)
        assertEquals(count, calls.size)
        assertFalse(device.automatic)
    }

    @Test fun lateFirebaseTokenCannotRegisterAgainstAChangedConnection() = runTest {
        val calls = mutableListOf<String>()
        val store = Store()
        val device = Device(calls).apply { pending = CompletableDeferred() }
        var c = account
        val client = PushTokenClient(store, device, Api(calls), { c })
        val job = launch { client.sync(c) }
        runCurrent()
        c = c.copy(accountId = 8, revision = 1)
        device.pending!!.complete("stale-token")
        job.join()
        assertTrue(calls.isEmpty())
        assertNull(store.record)
    }
}
