package com.powerk.app

import android.app.Application
import android.app.NotificationManager
import android.content.Context
import android.content.Intent
import androidx.test.core.app.ApplicationProvider
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35], application = Application::class)
class PushNotificationsTest {
    private val data = mapOf("type" to "event", "mac" to "AABBCCDDEEFF", "outlet" to "2",
        "event_id" to "4102444800", "code" to "temp_high")

    @Test fun warningInfoAndTestPayloadsMapToCorrectChannels() {
        listOf("offline", "temp_high", "power_high", "budget", "rule_skipped", "rule_failed").forEach {
            assertEquals("alerts", parsePushPayload(data + ("code" to it))!!.channel)
        }
        listOf("online", "rule_fired", "autooff", "onoff", "name_changed", "rule_created", "rule_updated", "rule_deleted").forEach {
            assertEquals("info", parsePushPayload(data + ("code" to it))!!.channel)
        }
        val test = parsePushPayload(data + ("type" to "test") + ("code" to "test"))!!
        assertEquals("info", test.channel)
        assertEquals(0L, test.eventId)
        assertEquals("", test.mac)
        assertNull(parsePushPayload(data + ("type" to "future")))
        assertEquals("alerts", parsePushPayload(data + ("code" to "future"), "alerts")!!.channel)
        assertEquals("info", parsePushPayload(data + ("code" to "future"))!!.channel)
    }

    @Test fun notificationIntentAndBackgroundDataExtrasOpenAlertsAndKeepLongId() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val payload = parsePushPayload(data)!!
        val intent = notificationIntent(context, payload)
        assertEquals(3, notificationInitialTab(intent))
        assertEquals(MainActivity::class.java.name, intent.component!!.className)
        assertEquals("4102444800", intent.getStringExtra("event_id"))
        assertEquals("2", intent.getStringExtra("outlet"))
        assertEquals("AABBCCDDEEFF", intent.getStringExtra("mac"))
        assertTrue(intent.flags and Intent.FLAG_ACTIVITY_SINGLE_TOP != 0)
        assertEquals("AABBCCDDEEFF:temp_high", payload.tag)
        val backgroundTap = Intent().apply { this@PushNotificationsTest.data.forEach { (key, value) -> putExtra(key, value) } }
        assertEquals(3, notificationInitialTab(backgroundTap))
        assertEquals(3, notificationInitialTab(Intent().putExtra("type", "test")))
        assertEquals(2, notificationInitialTab(Intent().putExtra(MainActivity.EXTRA_TAB, "energy")))
        assertEquals(0, notificationInitialTab(Intent()))
        assertNotEquals(intent.data, notificationIntent(context, payload.copy(eventId = 42)).data)
    }

    @Test fun malformedOptionalFieldsFailSafelyAndNoPayloadGrantsStripAccess() {
        val payload = parsePushPayload(data + mapOf("outlet" to "999", "event_id" to "NaN", "mac" to "../other"))!!
        assertEquals(0, payload.outlet)
        assertEquals(0L, payload.eventId)
        assertEquals("", payload.mac)
        assertEquals(3, notificationInitialTab(notificationIntent(ApplicationProvider.getApplicationContext(), payload)))
    }

    @Test fun appCreatesBothChannelsWithRequiredImportance() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        PushNotifications.createChannels(context)
        val manager = context.getSystemService(NotificationManager::class.java)
        assertEquals(NotificationManager.IMPORTANCE_HIGH, manager.getNotificationChannel("alerts").importance)
        assertEquals(NotificationManager.IMPORTANCE_DEFAULT, manager.getNotificationChannel("info").importance)
    }

    @Test fun notificationsResponseParsesReadonlyFcmBlockAndNeverSendsIt() {
        val preferences = AccountApi.parseNotifications(JSONObject("""{"fcm":{"enabled":true,"devices":2},"alerts":{}}"""))
        assertTrue(preferences.fcmEnabled)
        assertEquals(2, preferences.fcmDevices)
        assertFalse(notificationBody("", "", "", false, emptyMap()).has("fcm"))
        val oldServer = AccountApi.parseNotifications(JSONObject("{}"))
        assertFalse(oldServer.fcmEnabled)
        assertEquals(0, oldServer.fcmDevices)
    }
}
