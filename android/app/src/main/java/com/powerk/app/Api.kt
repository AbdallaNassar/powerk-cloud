package com.powerk.app

import androidx.compose.runtime.Immutable
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.net.URLEncoder

// Collection properties are read-only snapshots: parsers create them once and callers
// must replace models rather than mutate a backing collection after publication.
@Immutable
data class Outlet(val n: Int, val on: Boolean, val powerW: Double, val energyKwh: Double,
    val tempC: Int, val name: String = "", val alarms: List<String> = emptyList())
@Immutable
data class Strip(val mac: String, val name: String, val model: String, val fw: String,
    val online: Boolean, val on: Boolean, val powerW: Double, val energyKwh: Double,
    val voltage: Double?, val currentA: Double?, val rssi: Int?, val outlets: List<Outlet>,
    val label: String = "", val alarms: List<String> = emptyList(), val reportedAt: Long? = null,
    val todayKwh: Double = 0.0, val monthKwh: Double = 0.0, val monthCost: Double = 0.0,
    val ip: String = "", val role: StripRole = StripRole.Owner,
    val currency: String = "", val priceKwh: Double = 0.0, val budget: Double? = null) {
    val displayName: String get() = label.ifBlank { name }
}
@Immutable
data class Snapshot(val serverIp: String, val strips: List<Strip>, val currency: String = "",
    val priceKwh: Double = 0.0, val budget: Double? = null, val monthKwh: Double = 0.0,
    val monthCost: Double = 0.0, val unreadAlerts: Int = 0, val serverTime: Long? = null,
    val utcOffsetSeconds: Int = 0, val apiVersion: Int = 1, val port: Int = 0)
@Immutable
data class Rule(val id: String, val kind: String, val mac: String, val outlets: List<Int>,
    val enabled: Boolean = true, val label: String = "", val nextAt: Long? = null,
    val phase: String? = null, val at: String = "", val days: List<Int> = emptyList(),
    val on: Boolean = false, val fireAt: Long? = null, val onMin: Int = 1,
    val offMin: Int = 1, val belowW: Double = 1.0, val forMin: Int = 1)
@Immutable
data class Bucket(val t: Long, val kwh: Double, val cost: Double)
@Immutable
data class OutletEnergy(val n: Int, val kwh: Double)
@Immutable
data class History(val range: String, val unit: String, val currency: String,
    val buckets: List<Bucket>, val totalKwh: Double, val totalCost: Double,
    val perOutlet: List<OutletEnergy>)
@Immutable
data class ServerSettings(val currency: String = "", val priceKwh: Double = 0.0,
    val budget: Double? = null, val tempMaxC: Double = 60.0, val powerMaxW: Double = 3500.0,
    val ntfyUrl: String = "", val telegramChat: String = "", val telegramConfigured: Boolean = false)
// JSONObject is mutable; do not assert @Immutable for Event or EventPage.
data class Event(val id: Long, val ts: Long, val level: String, val code: String,
    val mac: String, val outlet: Int, val text: String, val params: JSONObject)
data class EventPage(val events: List<Event>, val unreadAlerts: Int)
@Immutable
data class FailedChannel(val channel: String, val error: String)
@Immutable
data class NotificationResult(val ok: Boolean, val sent: List<String>,
    val failed: List<FailedChannel>, val error: String)

/** Targets are always identified by number, never by position or name. */
fun Strip.outletOn(n: Int): Boolean = outlet(n)?.on ?: false
fun Strip.outlet(n: Int): Outlet? = outlets.firstOrNull { it.n == n }
class ServerException(message: String, val status: Int = 0, val messageRes: Int? = null) : Exception(message)

object Api {
    internal suspend fun call(connection: ServerConnection, path: String,
        method: String = "GET", body: JSONObject? = null): JSONObject = withContext(Dispatchers.IO) {
        AuthClient.request(connection, path, method, body)
    }
    // Keep both JSON decoding and model/list construction off the UI dispatcher.
    private suspend fun <T> parsedCall(connection: ServerConnection, path: String,
        method: String = "GET", body: JSONObject? = null, parse: (JSONObject) -> T): T =
        withContext(Dispatchers.IO) { parse(call(connection, path, method, body)) }

    suspend fun snapshot(connection: ServerConnection) = parsedCall(connection, "state") { parseSnapshot(it, connection.legacy) }
    suspend fun setOutlet(connection: ServerConnection, mac: String, outlet: Int, on: Boolean): Boolean {
        val response = call(connection, "onoff", "POST", JSONObject()
            .put("mac", mac).put("outlet", outlet).put("on", on))
        if (!response.optBoolean("ok")) throw ServerException(response.optString("error", "command failed"))
        return commandConfirmed(response)
    }
    internal fun commandConfirmed(response: JSONObject): Boolean = response.optBoolean("confirmed", true)
    suspend fun rename(connection: ServerConnection, mac: String, outlet: Int, name: String) {
        call(connection, "name", "POST", JSONObject().put("mac", mac).put("outlet", outlet).put("name", name))
    }
    suspend fun rules(connection: ServerConnection, mac: String? = null): List<Rule> =
        parsedCall(connection, "rules" + (mac?.let { "?mac=${encode(it)}" } ?: ""), parse = ::parseRules)
    suspend fun createRule(connection: ServerConnection, body: JSONObject): Rule =
        parsedCall(connection, "rules", "POST", body) { parseRule(it.getJSONObject("rule")) }
    suspend fun updateRule(connection: ServerConnection, id: String, body: JSONObject): Rule =
        parsedCall(connection, "rules/${encode(id)}", "PUT", body) { parseRule(it.getJSONObject("rule")) }
    suspend fun deleteRule(connection: ServerConnection, id: String) {
        call(connection, "rules/${encode(id)}", "DELETE")
    }
    suspend fun history(connection: ServerConnection, mac: String, range: String, outlet: Int? = null): History =
        parsedCall(connection, "history?mac=${encode(mac)}&range=${encode(range)}" +
            (outlet?.let { "&outlet=$it" } ?: ""), parse = ::parseHistory)
    suspend fun settings(connection: ServerConnection): ServerSettings = parsedCall(connection, "settings", parse = ::parseSettings)
    suspend fun saveSettings(connection: ServerConnection, body: JSONObject): ServerSettings =
        parsedCall(connection, "settings", "PUT", body, parse = ::parseSettings)
    suspend fun events(connection: ServerConnection, beforeId: Long? = null, limit: Int = 50): EventPage =
        parsedCall(connection, "events?limit=$limit" + (beforeId?.let { "&before_id=$it" } ?: ""), parse = ::parseEvents)
    suspend fun readEvents(connection: ServerConnection, throughId: Long? = null): Int =
        call(connection, "events/read", "POST", JSONObject().apply {
            throughId?.let { put("through_id", it) }
        }).optInt("unread_alerts")
    suspend fun testAlerts(connection: ServerConnection): NotificationResult =
        parsedCall(connection, "alerts/test", "POST", JSONObject(), parse = ::parseNotification)

    internal fun request(url: String, body: String?, token: String,
        method: String = if (body == null) "GET" else "POST"): String {
        return UrlTransport.wire(url, method, body,
            if (token.isBlank()) emptyMap() else mapOf("X-Token" to token)).let { reply ->
            if (reply.status !in 200..299) reply.json()
            reply.body
        }
    }
    private fun encode(value: String) = URLEncoder.encode(value, "UTF-8")

    internal fun parseSnapshot(o: JSONObject, legacy: Boolean = true) = Snapshot(o.optString("local_ip"),
        o.objects("devices").map { parseStrip(it, legacy) }, o.text("currency"), o.number("price_kwh"),
        o.nullableNumber("budget"), o.number("month_kwh"), o.number("month_cost"),
        o.optInt("unread_alerts"), o.longOrNull("server_time"), o.optInt("utc_offset_seconds"),
        o.optInt("api_version", 1), o.optInt("port"))
    internal fun parseStrip(o: JSONObject, legacy: Boolean) = Strip(o.text("mac"), o.text("name"), o.text("model"),
        o.text("fw"), o.optBoolean("online"), o.optBoolean("on"), o.number("power_w"),
        o.number("energy_kwh"), o.nullableNumber("voltage"), o.nullableNumber("current_a"),
        if (o.isNull("rssi")) null else o.optInt("rssi"), o.objects("outlets").map { x ->
            Outlet(x.optInt("n"), x.optBoolean("on"), x.number("power_w"), x.number("energy_kwh"),
                x.optInt("temp_c"), x.text("name"), x.alarms())
        }, o.text("label"), o.alarms(), o.longOrNull("reported_at"), o.number("today_kwh"),
        o.number("month_kwh"), o.number("month_cost"), o.text("ip"), if (!legacy && o.text("role").isBlank()) StripRole.Viewer else StripRole.parse(o.text("role")),
        o.text("currency"), o.number("price_kwh"), o.nullableNumber("budget"))
    internal fun parseRules(o: JSONObject) = o.objects("rules").map(::parseRule)
    internal fun parseRule(o: JSONObject) = Rule(o.text("id"), o.text("kind"), o.text("mac"),
        o.ints("outlets"), o.optBoolean("enabled", true), o.text("label"), o.longOrNull("next_at"),
        o.text("phase").ifBlank { null }, o.text("at"), o.ints("days"), o.optBoolean("on"),
        o.longOrNull("fire_at"), o.optInt("on_min", 1), o.optInt("off_min", 1),
        o.number("below_w", 1.0), o.optInt("for_min", 1))
    internal fun parseHistory(o: JSONObject) = History(o.text("range"), o.text("unit"), o.text("currency"),
        o.objects("buckets").map { Bucket(it.optLong("t"), it.number("kwh"), it.number("cost")) },
        o.number("total_kwh"), o.number("total_cost"),
        o.objects("per_outlet").map { OutletEnergy(it.optInt("n"), it.number("kwh")) })
    internal fun parseSettings(o: JSONObject) = ServerSettings(o.text("currency"), o.number("price_kwh"),
        o.nullableNumber("budget"), o.number("temp_max_c", 60.0), o.number("power_max_w", 3500.0),
        o.text("ntfy_url"), o.text("telegram_chat"), o.optBoolean("telegram_configured"))
    internal fun parseEvent(o: JSONObject) = Event(o.optLong("id"), o.optLong("ts"), o.text("level"),
        o.text("code"), o.text("mac"), o.optInt("outlet"), o.text("text"), o.optJSONObject("params") ?: JSONObject())
    internal fun parseEvents(o: JSONObject) = EventPage(o.objects("events").map(::parseEvent)
        .sortedByDescending { it.id }, o.optInt("unread_alerts"))
    internal fun parseNotification(o: JSONObject) = NotificationResult(o.optBoolean("ok"), o.strings("sent"),
        o.objects("failed").map { FailedChannel(it.text("channel"), it.text("error")) }, o.text("error"))
}

internal fun JSONObject.text(key: String): String = if (isNull(key)) "" else optString(key)
internal fun JSONObject.number(key: String, default: Double = 0.0): Double =
    optDouble(key, default).takeIf { it.isFinite() } ?: default
internal fun JSONObject.nullableNumber(key: String): Double? =
    if (isNull(key)) null else optDouble(key).takeIf { it.isFinite() }
internal fun JSONObject.longOrNull(key: String): Long? = if (isNull(key)) null else optLong(key)
internal fun JSONObject.objects(key: String): List<JSONObject> = optJSONArray(key)?.let { a ->
    (0 until a.length()).mapNotNull { a.optJSONObject(it) }
}.orEmpty()
internal fun JSONObject.strings(key: String): List<String> = optJSONArray(key)?.let { a ->
    (0 until a.length()).mapNotNull { if (a.isNull(it)) null else a.optString(it).ifBlank { null } }
}.orEmpty()
internal fun JSONObject.ints(key: String): List<Int> = optJSONArray(key)?.let { a ->
    (0 until a.length()).map { a.optInt(it) }
}.orEmpty()
private fun JSONObject.alarms(): List<String> = strings("alarms").ifEmpty {
    text("alarm").ifBlank { null }?.let(::listOf).orEmpty()
}
