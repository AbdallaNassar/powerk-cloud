package com.powerk.app

import androidx.compose.runtime.Immutable
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.net.URLEncoder

enum class StripRole(val wire: String, val label: Int) {
    Owner("owner", R.string.role_owner), Control("control", R.string.role_control), Viewer("viewer", R.string.role_viewer);
    val canControl: Boolean get() = this != Viewer
    val canManage: Boolean get() = this == Owner
    companion object {
        // Missing role is the pre-account legacy shape; unknown future roles fail closed.
        fun parse(value: String) = when (value) { "", "owner" -> Owner; "control" -> Control; else -> Viewer }
    }
}

@Immutable
data class AccountSession(val id: String, val createdAt: Long, val lastUsedAt: Long,
    val userAgent: String, val ip: String, val current: Boolean)
@Immutable
data class StripMember(val userId: Long, val phone: String, val role: StripRole, val addedAt: Long)
@Immutable
data class NotificationPreferences(val ntfyUrl: String, val telegramChat: String,
    val telegramConfigured: Boolean, val alerts: Map<String, Map<String, Boolean>>,
    val fcmEnabled: Boolean = false, val fcmDevices: Int = 0)

val notificationCodes = listOf("offline", "online", "temp_high", "power_high", "budget", "rule_fired",
    "rule_skipped", "rule_failed", "autooff", "onoff", "name_changed", "rule_created", "rule_updated", "rule_deleted")
val notificationLabels = listOf(R.string.notify_offline, R.string.notify_online, R.string.alarm_temp,
    R.string.alarm_power, R.string.monthly_budget, R.string.notify_rule_fired, R.string.notify_rule_skipped,
    R.string.notify_rule_failed, R.string.kind_autooff, R.string.notify_onoff, R.string.notify_name,
    R.string.notify_rule_created, R.string.notify_rule_updated, R.string.notify_rule_deleted)

@Immutable
sealed interface ClaimState {
    data object Entry : ClaimState
    data class Pending(val id: String, val deadline: Long, val seconds: Int = 60) : ClaimState
    data class Done(val mac: String) : ClaimState
    data object Expired : ClaimState
}

/** A monotonic clock drives the UI; a final poll at zero can still find a just-completed claim. */
internal fun claimTick(pending: ClaimState.Pending, now: Long) =
    pending.copy(seconds = ((pending.deadline - now + 999) / 1000).coerceIn(0, 60).toInt())
internal fun claimStatus(pending: ClaimState.Pending, reply: JSONObject): ClaimState = when (reply.getString("status")) {
    "done" -> ClaimState.Done(reply.getString("mac"))
    "expired" -> ClaimState.Expired
    "pending" -> pending
    else -> throw ServerException("", messageRes = R.string.server_response_invalid)
}

object AccountApi {
    private fun path(mac: String) = "strips/${URLEncoder.encode(mac, "UTF-8")}"
    private fun encoded(value: String) = URLEncoder.encode(value, "UTF-8")
    private suspend fun <T> parsed(c: ServerConnection, path: String, method: String = "GET",
        body: JSONObject? = null, parse: (JSONObject) -> T): T = withContext(Dispatchers.IO) {
        parse(Api.call(c, path, method, body))
    }
    suspend fun sessions(c: ServerConnection) = parsed(c, "auth/sessions", parse = ::parseSessions)
    suspend fun deleteSession(c: ServerConnection, session: AccountSession) {
        try {
            if (session.current) PushDevices.beforeSignOut(c)
            Api.call(c, "auth/sessions/${encoded(session.id)}", "DELETE")
        }
        finally { if (session.current) withContext(NonCancellable + Dispatchers.IO) {
            synchronized(AuthClient.client.stateLock) { if (c.isCurrent(Server.connection)) AuthClient.clear() }
        } }
    }
    suspend fun password(c: ServerConnection, old: String, new: String) {
        Api.call(c, "auth/password", "POST", JSONObject().put("current_password", old).put("new_password", new))
    }
    suspend fun claim(c: ServerConnection, code: String, now: () -> Long): ClaimState.Pending =
        parsed(c, "strips/claim", "POST", JSONObject().put("code", code)) {
            val seconds = it.getInt("expires_in").coerceIn(0, 60)
            ClaimState.Pending(it.getString("claim_id"), now() + seconds * 1000, seconds)
        }
    suspend fun claimPoll(c: ServerConnection, pending: ClaimState.Pending): ClaimState =
        parsed(c, "strips/claim/${encoded(pending.id)}") { claimStatus(pending, it) }
    suspend fun people(c: ServerConnection, mac: String) = parsed(c, "${path(mac)}/access", parse = ::parsePeople)
    suspend fun share(c: ServerConnection, mac: String, phone: String, role: StripRole) {
        require(role != StripRole.Owner)
        Api.call(c, "${path(mac)}/access", "POST", JSONObject().put("phone", normalizeNumber(phone)).put("role", role.wire))
    }
    suspend fun role(c: ServerConnection, mac: String, id: Long, role: StripRole) {
        require(role != StripRole.Owner)
        Api.call(c, "${path(mac)}/access/$id", "PUT", JSONObject().put("role", role.wire))
    }
    suspend fun remove(c: ServerConnection, mac: String, id: Long) { Api.call(c, "${path(mac)}/access/$id", "DELETE") }
    suspend fun transfer(c: ServerConnection, mac: String, phone: String) {
        Api.call(c, "${path(mac)}/transfer", "POST", JSONObject().put("phone", normalizeNumber(phone)))
    }
    suspend fun leave(c: ServerConnection, mac: String) { Api.call(c, "${path(mac)}/leave", "POST", JSONObject()) }
    suspend fun unclaim(c: ServerConnection, mac: String) { Api.call(c, path(mac), "DELETE") }
    suspend fun stripSettings(c: ServerConnection, mac: String) = parsed(c, "${path(mac)}/settings", parse = Api::parseSettings)
    suspend fun saveStripSettings(c: ServerConnection, mac: String, body: JSONObject) =
        parsed(c, "${path(mac)}/settings", "PUT", body, Api::parseSettings)
    suspend fun notifications(c: ServerConnection) = parsed(c, "me/notifications", parse = ::parseNotifications)
    suspend fun saveNotifications(c: ServerConnection, body: JSONObject) =
        parsed(c, "me/notifications", "PUT", body, ::parseNotifications)
    suspend fun registerPushToken(c: ServerConnection, token: String, version: String) {
        require(!c.legacy && c.accountId != null)
        Api.call(c, "me/push-tokens", "POST", JSONObject().put("token", token)
            .put("platform", "android").put("app_version", version))
    }
    suspend fun deletePushToken(c: ServerConnection, token: String) {
        require(!c.legacy && c.accountId != null)
        Api.call(c, "me/push-tokens/${encoded(token)}", "DELETE")
    }

    internal fun parseSessions(o: JSONObject) = o.objects("sessions").map {
        AccountSession(it.getString("id"), it.getLong("created_at"), it.getLong("last_used_at"),
            it.text("user_agent"), it.text("ip"), it.optBoolean("current"))
    }
    internal fun parsePeople(o: JSONObject) = o.objects("access").map {
        StripMember(it.getLong("user_id"), it.getString("phone"), StripRole.parse(it.getString("role")), it.getLong("added_at"))
    }
    internal fun parseNotifications(o: JSONObject): NotificationPreferences {
        val alerts = o.optJSONObject("alerts") ?: JSONObject()
        val strips = alerts.keys().asSequence().associateWith { mac ->
            val prefs = alerts.getJSONObject(mac)
            notificationCodes.filter { prefs.has(it) }.associateWith { prefs.getBoolean(it) }
        }
        val fcm = o.optJSONObject("fcm")
        return NotificationPreferences(o.text("ntfy_url"), o.text("telegram_chat"), o.optBoolean("telegram_configured"), strips,
            fcm?.optBoolean("enabled") ?: false, fcm?.optInt("devices")?.coerceAtLeast(0) ?: 0)
    }
}
