package com.powerk.app

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalResources
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import org.json.JSONObject

internal fun notificationBody(ntfy: String, chat: String, token: String, clear: Boolean,
    alerts: Map<String, Map<String, Boolean>>): JSONObject = JSONObject().put("ntfy_url", ntfy)
    .put("telegram_chat", chat).put("alerts", JSONObject().apply {
        alerts.forEach { (mac, codes) -> put(mac, JSONObject().apply { codes.forEach { (code, on) -> put(code, on) } }) }
    }).apply { if (clear || token.isNotEmpty()) put("telegram_token", if (clear) "" else token) }

@Composable
fun NotificationSection(strips: List<Strip>) {
    var open by remember { mutableStateOf(false) }
    PaperCard(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(18.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text(markerText(stringResource(R.string.personal_notifications)), style = MaterialTheme.typography.titleMedium)
            Text(stringResource(R.string.notifications_hint), style = MaterialTheme.typography.bodySmall)
            OutlinedButton(onClick = { open = true }) { Text(stringResource(R.string.notification_settings)) }
        }
    }
    if (open) AccountDialog(R.string.personal_notifications, { open = false }) { NotificationScreen(strips) }
}

@Composable
private fun NotificationScreen(strips: List<Strip>) {
    if (Server.legacy) {
        Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(18.dp)) {
            DevicePushSettings(null, legacy = true)
        }
        return
    }
    val work = rememberAccountWork()
    val resources = LocalResources.current
    var preferences by remember { mutableStateOf<NotificationPreferences?>(null) }
    var ntfy by remember { mutableStateOf("") }
    var chat by remember { mutableStateOf("") }
    var token by remember { mutableStateOf("") }
    var clear by remember { mutableStateOf(false) }
    var alerts by remember { mutableStateOf<Map<String, Map<String, Boolean>>>(emptyMap()) }
    fun bind(value: NotificationPreferences) {
        preferences = value; ntfy = value.ntfyUrl; chat = value.telegramChat
        alerts = value.alerts; token = ""; clear = false
    }
    fun load() = work.run {
        PushDevices.connectionChanged()
        val result = AccountApi.notifications(work.connection)
        if (work.current()) bind(result)
    }
    LaunchedEffect(work) { load() }
    Column(Modifier.fillMaxSize().imePadding().verticalScroll(rememberScrollState()).padding(18.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp)) {
        Text(stringResource(R.string.notifications_hint))
        DevicePushSettings(preferences)
        TextButton(enabled = !work.busy, onClick = ::load) { Text(stringResource(R.string.refresh)) }
        WorkStatus(work)
        if (preferences != null) {
            Field(ntfy, { ntfy = it }, R.string.ntfy_url, enabled = !work.busy)
            Field(chat, { chat = it }, R.string.telegram_chat, enabled = !work.busy)
            PasswordField(token, { token = it; clear = false }, R.string.telegram_token, !work.busy, maxLength = Int.MAX_VALUE)
            Text(stringResource(when {
                clear -> R.string.token_clear_hint
                preferences!!.telegramConfigured -> R.string.telegram_configured
                else -> R.string.token_keep_hint
            }), style = MaterialTheme.typography.bodySmall)
            TextButton(enabled = !work.busy, onClick = { token = ""; clear = true }) { Text(stringResource(R.string.clear_token)) }
            strips.forEach { strip -> key(strip.mac) {
                DashedDivider()
                Text(markerText(strip.displayName), style = MaterialTheme.typography.titleMedium)
                notificationCodes.forEachIndexed { index, code -> key(code) {
                    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                        Text(stringResource(notificationLabels[index]), Modifier.weight(1f))
                        Switch(alerts[strip.mac]?.get(code) ?: false, enabled = !work.busy, onCheckedChange = {
                            alerts = alerts + (strip.mac to (alerts[strip.mac].orEmpty() + (code to it)))
                        }, colors = paperSwitchColors(), modifier = Modifier.semanticsLabel(stringResource(notificationLabels[index])))
                    }
                } }
            } }
            val validUrl = ntfy.isBlank() || runCatching {
                val u = java.net.URI(ntfy)
                u.scheme in listOf("https", "http") && !u.host.isNullOrBlank() && u.userInfo == null
            }.getOrDefault(false)
            if (!validUrl) Text(stringResource(R.string.settings_validation), color = MaterialTheme.colorScheme.error)
            Button(enabled = !work.busy && validUrl, onClick = {
                val body = notificationBody(ntfy, chat, token, clear, alerts.filterKeys { mac -> strips.any { it.mac == mac } })
                work.run {
                    val result = AccountApi.saveNotifications(work.connection, body)
                    if (work.current()) { bind(result); work.status = resources.getString(R.string.saved) }
                }
            }, modifier = Modifier.fillMaxWidth()) { Text(stringResource(R.string.save)) }
            OutlinedButton(enabled = !work.busy, onClick = {
                work.run {
                    val result = Api.testAlerts(work.connection)
                    if (work.current()) work.status = if (!result.ok && result.sent.isEmpty() && result.failed.isEmpty())
                        resources.getString(R.string.no_push_channels) else resources.getString(R.string.notification_result,
                        result.sent.joinToString(", ").ifBlank { resources.getString(R.string.none) },
                        result.failed.joinToString(", ") { it.channel }.ifBlank { resources.getString(R.string.none) })
                }
            }, modifier = Modifier.fillMaxWidth()) { Text(stringResource(R.string.test_notification)) }
            Text(stringResource(R.string.notification_test_saved), style = MaterialTheme.typography.bodySmall)
        }
    }
}
