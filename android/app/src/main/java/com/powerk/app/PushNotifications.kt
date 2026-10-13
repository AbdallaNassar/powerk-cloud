package com.powerk.app

import android.Manifest
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import com.google.firebase.messaging.FirebaseMessagingService
import com.google.firebase.messaging.RemoteMessage

private val warningCodes = setOf("offline", "temp_high", "power_high", "budget", "rule_skipped", "rule_failed")
internal data class PushPayload(val type: String, val mac: String, val outlet: Int, val eventId: Long,
    val code: String, val channel: String) {
    val tag: String get() = "$mac:$code"
}

internal fun parsePushPayload(data: Map<String, String>, suppliedChannel: String? = null): PushPayload? {
    val type = data["type"]?.takeIf { it == "event" || it == "test" } ?: return null
    val code = data["code"].orEmpty()
    val mac = data["mac"].orEmpty().takeIf { it.matches(Regex("[0-9A-F]{12}")) }.orEmpty()
    val outlet = data["outlet"]?.toIntOrNull()?.takeIf { it in 0..4 } ?: 0
    val eventId = data["event_id"]?.toLongOrNull()?.coerceAtLeast(0) ?: 0
    val channel = when {
        type == "test" -> "info"
        code in warningCodes -> "alerts"
        code in notificationCodes -> "info"
        suppliedChannel == "alerts" -> "alerts"
        else -> "info"
    }
    return PushPayload(type, if (type == "test") "" else mac, if (type == "test") 0 else outlet,
        if (type == "test") 0 else eventId, code, channel)
}

/** Both locally displayed notifications and FCM's background notification/data extras land here.
 * A tap only selects Alerts; its contents are always loaded with the current account's auth. */
internal fun notificationInitialTab(intent: Intent): Int {
    if (intent.getStringExtra("type") in listOf("event", "test")) return 3
    return when (intent.getStringExtra(MainActivity.EXTRA_TAB)) { "alerts" -> 3; "energy" -> 2; else -> 0 }
}

internal fun notificationIntent(context: Context, payload: PushPayload): Intent =
    Intent(context, MainActivity::class.java).apply {
        flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_SINGLE_TOP
        data = Uri.Builder().scheme("powerk").authority("alerts").appendPath(payload.tag)
            .appendPath(payload.eventId.toString()).build()
        putExtra(MainActivity.EXTRA_TAB, "alerts")
        putExtra("type", payload.type)
        putExtra("mac", payload.mac)
        putExtra("outlet", payload.outlet.toString())
        putExtra("event_id", payload.eventId.toString())
        putExtra("code", payload.code)
    }

internal fun notificationsAllowed(context: Context): Boolean = NotificationManagerCompat.from(context).areNotificationsEnabled() &&
    (Build.VERSION.SDK_INT < 33 || ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED)

internal object PushNotifications {
    fun createChannels(context: Context) {
        val localized = context.localized()
        context.getSystemService(NotificationManager::class.java)?.createNotificationChannels(listOf(
            NotificationChannel("alerts", localized.getString(R.string.push_channel_alerts), NotificationManager.IMPORTANCE_HIGH),
            NotificationChannel("info", localized.getString(R.string.push_channel_info), NotificationManager.IMPORTANCE_DEFAULT)))
    }

    fun show(context: Context, payload: PushPayload, title: String?, body: String?) {
        if (!notificationsAllowed(context)) return
        createChannels(context)
        val localized = context.localized()
        val codeIndex = notificationCodes.indexOf(payload.code)
        val fallbackTitle = when {
            payload.type == "test" -> localized.getString(R.string.push_test_title)
            codeIndex >= 0 -> localized.getString(notificationLabels[codeIndex])
            else -> localized.getString(R.string.app_name)
        }
        val fallbackBody = when {
            payload.type == "test" -> localized.getString(R.string.push_test_body)
            payload.mac.isNotBlank() -> if (payload.outlet > 0) localized.getString(R.string.push_outlet_body, payload.mac, payload.outlet) else payload.mac
            else -> localized.getString(R.string.push_open_alerts)
        }
        val content = body?.takeIf { it.isNotBlank() } ?: fallbackBody
        val pending = PendingIntent.getActivity(context, payload.tag.hashCode(), notificationIntent(context, payload),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
        val notification = NotificationCompat.Builder(context, payload.channel)
            .setSmallIcon(R.drawable.ic_notification).setContentTitle(title?.takeIf { it.isNotBlank() } ?: fallbackTitle)
            .setContentText(content).setStyle(NotificationCompat.BigTextStyle().bigText(content))
            .setContentIntent(pending).setAutoCancel(true).setOnlyAlertOnce(true)
            .setVisibility(NotificationCompat.VISIBILITY_PRIVATE).build()
        try { NotificationManagerCompat.from(context).notify(payload.tag, 0, notification) }
        catch (_: SecurityException) { /* Permission may be revoked between the check and notify. */ }
    }
}

class PowerkMessagingService : FirebaseMessagingService() {
    override fun onNewToken(token: String) {
        PushDevices.onNewToken()
    }
    override fun onMessageReceived(message: RemoteMessage) {
        val c = Server.connection
        if (c.legacy || c.accountId == null || !PushDevices.acceptsMessages(c)) return
        val payload = parsePushPayload(message.data, message.notification?.channelId) ?: return
        // Firebase invokes this for foreground notification+data and for data-only in either state.
        // Background notification+data is displayed by Firebase on the same pre-created channels.
        PushNotifications.show(this, payload, message.notification?.title, message.notification?.body)
    }
}
