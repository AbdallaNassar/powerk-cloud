package com.powerk.app

import kotlinx.coroutines.runBlocking
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

class AccountModelsTest {
    @Test fun baseUrlsRequireTlsExceptLiteralPrivateNetworksAndLocalNames() {
        listOf("https://powerk.example.com", "https://example.com:8443/", "http://192.168.1.7:8080",
            "http://10.0.0.1", "http://172.16.0.1", "http://172.31.255.255", "http://127.0.0.1",
            "http://localhost:8080", "http://powerk.local", "http://[::1]:8080", "http://[fd00::1]").forEach {
            assertNotNull(it, validateServerUrl(it))
        }
        listOf("", "192.168.1.7:8080", "http://example.com", "http://8.8.8.8", "http://172.32.0.1",
            "http://192.168.1.7.evil.test", "http://2130706433", "http://127.1", "http://0177.0.0.1",
            "http://[2001:4860::1]", "https://user:secret@example.com", "https://example.com/api",
            "https://example.com/?token=secret", "https://example.com/#x", "ftp://192.168.1.7",
            "https://example.com:0", "https://example.com:65536", "https://example.com:-3").forEach {
            assertNull(it, validateServerUrl(it))
        }
        assertEquals(DEFAULT_SERVER_URL, validateServerUrl(" $DEFAULT_SERVER_URL/ ")!!.base)
        assertTrue(validateServerUrl("http://192.168.0.1")!!.insecure)
        assertFalse(validateServerUrl(DEFAULT_SERVER_URL)!!.insecure)
    }
    @Test fun newShapesPreserveRolePerStripPricesAndLongSessionTimes() {
        val snapshot = Api.parseSnapshot(JSONObject("""{"devices":[
          {"mac":"A","role":"owner","currency":"EGP","price_kwh":2.14,"budget":500},
          {"mac":"B","role":"viewer","currency":"USD","price_kwh":0.2,"budget":null}],"future":true}"""))
        assertEquals(StripRole.Owner, snapshot.strips[0].role)
        assertEquals(StripRole.Viewer, snapshot.strips[1].role)
        assertEquals("USD", snapshot.strips[1].currency)
        assertEquals(0.2, snapshot.strips[1].priceKwh, 0.0)
        assertNull(snapshot.strips[1].budget)
        val sessions = AccountApi.parseSessions(JSONObject("""{"sessions":[{"id":"family","created_at":4102444800,
          "last_used_at":4102444801,"current":true,"ip":"127.0.0.1","user_agent":"Android","future":true}]}"""))
        assertEquals(4102444801L, sessions.single().lastUsedAt)
        assertTrue(sessions.single().current)
        val members = AccountApi.parsePeople(JSONObject("""{"access":[{"user_id":7,"phone":"+201001234567",
          "role":"control","added_at":4102444800}]}"""))
        assertEquals(StripRole.Control, members.single().role)
        assertEquals(4102444800L, members.single().addedAt)
    }
    @Test fun rolesGateControlsAndUnknownRolesFailClosed() = runBlocking {
        assertTrue(StripRole.Owner.canManage)
        assertTrue(StripRole.Control.canControl)
        assertFalse(StripRole.Control.canManage)
        assertFalse(StripRole.Viewer.canControl)
        assertFalse(StripRole.parse("future-role").canControl)
        val viewer = Api.parseSnapshot(JSONObject("""{"devices":[{"mac":"ABC","online":true,"role":"viewer",
            "outlets":[{"n":1,"on":true}]}]}"""))
        var writes = 0
        try {
            toggleFresh(OutletTarget("ABC", 1, "Outlet"), { viewer }) { _, _, _ -> writes++; true }
            fail()
        } catch (e: ServerException) {
            assertEquals(403, e.status)
            assertEquals(R.string.no_access, e.messageRes)
        }
        assertEquals(0, writes)
    }
    @Test fun claimCountsDownAndAcceptsDoneEvenAtDeadline() {
        val pending = ClaimState.Pending("claim", 60000)
        assertEquals(60, claimTick(pending, 0).seconds)
        assertEquals(1, claimTick(pending, 59001).seconds)
        val zero = claimTick(pending, 61000)
        assertEquals(0, zero.seconds)
        assertEquals(pending, claimStatus(pending, JSONObject("""{"status":"pending"}""")))
        assertEquals(ClaimState.Done("ABC"), claimStatus(zero, JSONObject("""{"status":"done","mac":"ABC"}""")))
        assertEquals(zero, claimStatus(zero, JSONObject("""{"status":"pending"}""")))
        assertEquals(ClaimState.Expired, claimStatus(pending, JSONObject("""{"status":"expired"}""")))
    }
    @Test fun notificationsArePerStripAndTokenRemainsWriteOnly() {
        val prefs = AccountApi.parseNotifications(JSONObject("""{"ntfy_url":"https://ntfy.sh/topic",
          "telegram_chat":"123","telegram_configured":true,"alerts":{"A":{"offline":true,"online":false,"future":true}}}"""))
        assertTrue(prefs.telegramConfigured)
        assertEquals(mapOf("offline" to true, "online" to false), prefs.alerts["A"])
        val body = notificationBody(prefs.ntfyUrl, prefs.telegramChat, "", false, prefs.alerts)
        assertFalse(body.has("telegram_token"))
        assertFalse(body.getJSONObject("alerts").getJSONObject("A").getBoolean("online"))
        assertEquals("", notificationBody("", "", "", true, emptyMap()).getString("telegram_token"))
        assertEquals("new", notificationBody("", "", "new", false, emptyMap()).getString("telegram_token"))
    }
    @Test fun accountChangesInvalidateResponsesEvenAtSameServer() = runBlocking {
        val before = ServerConnection(DEFAULT_SERVER_URL, accountId = 1, legacy = false)
        val after = before.copy(accountId = 2, revision = 1)
        assertNull(connectionResult(before, { after }) { "other account data" })
        assertFalse(before.copy(accountId = null).authorized)
        assertTrue(before.authorized)
    }
    @Test fun retryAfterAcceptsSecondsAndHttpDates() {
        assertEquals(30000L, retryAfterMillis("30", 0))
        assertEquals(10000L, retryAfterMillis("Thu, 01 Jan 1970 00:00:10 GMT", 0))
        assertEquals(5000L, retryAfterMillis("bad", 0))
    }
}
