package com.powerk.app

import android.Manifest
import android.content.Context
import android.content.Intent
import android.os.Build
import android.provider.Settings
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.LifecycleOwner
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

@Composable
internal fun DevicePushPermissionPrompt(connection: ServerConnection) {
    if (!BuildConfig.FCM_ENABLED || Build.VERSION.SDK_INT < 33 || connection.legacy || connection.accountId == null) return
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var show by remember { mutableStateOf(false) }
    val launcher = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { PushDevices.connectionChanged() }
    LaunchedEffect(connection) {
        val asked = withContext(Dispatchers.IO) {
            context.getSharedPreferences("push_permission", Context.MODE_PRIVATE).getBoolean("explained", false)
        }
        show = !asked && !notificationsAllowed(context)
    }
    fun finish(request: Boolean) {
        show = false
        scope.launch {
            withContext(Dispatchers.IO) {
                context.getSharedPreferences("push_permission", Context.MODE_PRIVATE).edit().putBoolean("explained", true).commit()
            }
            if (request && connection.isCurrent(Server.connection)) launcher.launch(Manifest.permission.POST_NOTIFICATIONS)
        }
    }
    if (show) AlertDialog(onDismissRequest = { finish(false) },
        title = { Text(stringResource(R.string.push_permission_title)) },
        text = { Text(stringResource(R.string.push_permission_explanation)) },
        confirmButton = { TextButton(onClick = { finish(true) }) { Text(stringResource(R.string.push_allow)) } },
        dismissButton = { TextButton(onClick = { finish(false) }) { Text(stringResource(R.string.push_later)) } })
}

@Composable
internal fun DevicePushSettings(preferences: NotificationPreferences?, legacy: Boolean = Server.legacy) {
    val context = LocalContext.current
    val state by PushDevices.state.collectAsState()
    var allowed by remember { mutableStateOf(notificationsAllowed(context)) }
    val lifecycle = (context.findActivity() as? LifecycleOwner)?.lifecycle
    DisposableEffect(lifecycle) {
        val observer = LifecycleEventObserver { _, event ->
            if (event == Lifecycle.Event.ON_RESUME) { allowed = notificationsAllowed(context); PushDevices.connectionChanged() }
        }
        lifecycle?.addObserver(observer)
        onDispose { lifecycle?.removeObserver(observer) }
    }
    DevicePushStatus(legacy, state.available, allowed,
        state.connection == Server.connection && state.registered && state.hasToken,
        state.failed, preferences) {
        context.startActivity(Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS).putExtra(Settings.EXTRA_APP_PACKAGE, context.packageName))
    }
}

/** Pure surface for screenshot/UI fixtures; no token, Firebase or network reads. */
@Composable
internal fun DevicePushStatus(legacy: Boolean, available: Boolean, allowed: Boolean,
    registered: Boolean, failed: Boolean, preferences: NotificationPreferences?, onSettings: () -> Unit) {
    PaperCard(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(18.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text(markerText(stringResource(R.string.push_device_title)), style = MaterialTheme.typography.titleMedium)
            Text(stringResource(when {
                legacy -> R.string.push_legacy
                !available -> R.string.push_not_in_build
                !allowed -> R.string.push_permission_off
                preferences?.fcmEnabled == false -> R.string.push_server_off
                registered && preferences?.fcmEnabled == true && preferences.fcmDevices > 0 -> R.string.push_device_enabled
                failed -> R.string.push_registration_failed
                else -> R.string.push_registration_pending
            }))
            if (!legacy && available) {
                if (allowed) Text(stringResource(R.string.push_permission_on), style = MaterialTheme.typography.bodySmall)
                Text(stringResource(if (registered) R.string.push_token_registered else R.string.push_token_pending), style = MaterialTheme.typography.bodySmall)
                preferences?.let { Text(stringResource(R.string.push_device_count, it.fcmDevices), style = MaterialTheme.typography.bodySmall) }
            }
            OutlinedButton(onClick = onSettings) { Text(stringResource(R.string.push_system_settings)) }
        }
    }
}
