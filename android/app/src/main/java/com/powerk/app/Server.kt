package com.powerk.app

import android.app.Activity
import android.app.LocaleManager
import android.content.Context
import android.content.ContextWrapper
import android.content.SharedPreferences
import android.content.res.Configuration
import android.os.Build
import android.os.LocaleList
import androidx.annotation.RequiresApi
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import java.util.Locale
import kotlinx.coroutines.launch
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.withContext

/** Observable request identity. Tokens rotate without changing identity; account/server changes do. */
object Server {
    private var prefs: SharedPreferences? = null
    private var context: Context? = null
    var connection by mutableStateOf(ServerConnection(DEFAULT_SERVER_URL, legacy = false))
        private set

    fun init(context: Context) {
        if (prefs != null) return
        val p = context.applicationContext.getSharedPreferences("powerk", Context.MODE_PRIVATE)
        prefs = p
        this.context = context.applicationContext
        AuthClient.init(context.applicationContext)
        val oldHost = p.getString("host", "").orEmpty()
        val migrated = if (oldHost.isBlank()) null else validateServerUrl("http://$oldHost:${p.getInt("port", 8080)}")
        val savedUrl = validateServerUrl(p.getString("base_url", null).orEmpty())
        val base = savedUrl?.base ?: migrated?.base ?: DEFAULT_SERVER_URL
        val canMigrate = savedUrl != null || migrated != null
        val legacy = canMigrate && p.getBoolean("legacy", oldHost.isNotBlank())
        val oldToken = p.getString("token", "").orEmpty()
        // Never move a credential from a rejected old address to the default server.
        if (!canMigrate) AuthClient.vault.saveLegacy("")
        else if (oldToken.isNotEmpty()) AuthClient.vault.saveLegacy(oldToken)
        p.edit().putString("base_url", base).putBoolean("legacy", legacy)
            .remove("host").remove("port").remove("token").commit()
        val restore = !legacy && AuthClient.client.canRestore(base)
        connection = ServerConnection(base, if (legacy) AuthClient.vault.legacyToken() else "",
            accountId = if (restore) AuthClient.accountId else null, legacy = legacy)
        if (AuthClient.accountId != null && !restore) AuthClient.clear()
        else if (!connection.authorized) changed()
    }

    /** Compatibility helper for existing fixtures and LAN setups. */
    fun save(newHost: String, newPort: Int, newToken: String) {
        replaceConnection("http://${newHost.trim()}:${newPort.coerceIn(1, 65535)}", true, newToken)
    }
    suspend fun saveUrl(url: String, legacy: Boolean, sharedToken: String = "") = withContext(NonCancellable + Dispatchers.IO) {
        val base = requireNotNull(validateServerUrl(url)).base
        val token = if (legacy) sharedToken.trim() else ""
        val captured = connection
        if (captured.base == base && captured.legacy == legacy && captured.token == token) return@withContext
        PushDevices.beforeSignOut(captured)
        synchronized(AuthClient.client.stateLock) {
            // Deleting a push token can discover that the old session was revoked and sign it out.
            val signedOutDuringCleanup = connection == captured.copy(accountId = null, revision = captured.revision + 1)
            if (captured.isCurrent(connection) || signedOutDuringCleanup) replaceConnection(base, legacy, token)
        }
    }
    private fun replaceConnection(url: String, legacy: Boolean, sharedToken: String = "") {
        val validated = requireNotNull(validateServerUrl(url))
        val token = if (legacy) sharedToken.trim() else ""
        if (connection.base == validated.base && connection.legacy == legacy && connection.token == token) return
        synchronized(AuthClient.client.stateLock) {
            AuthClient.clear()
            AuthClient.vault.saveLegacy(token)
            connection = ServerConnection(validated.base, token, connection.revision + 1, legacy = legacy)
            prefs?.edit()?.putString("base_url", validated.base)?.putBoolean("legacy", legacy)?.commit()
            changed()
        }
    }
    internal fun accountChanged(id: Long?) {
        connection = connection.copy(accountId = id, revision = connection.revision + 1)
        changed()
    }
    private fun changed() {
        LiveFeed.connectionChanged()
        PushDevices.connectionChanged()
        WidgetUpdates.clearSnapshot()
        WidgetUpdates.pending.clear()
        context?.let { c ->
            // Saved targets and their names belong to the old account/server.
            c.getSharedPreferences("targets", Context.MODE_PRIVATE).edit().clear().apply()
            WidgetUpdates.scope.launch { WidgetUpdates.renderAll(c) }
            runCatching {
                android.service.quicksettings.TileService.requestListeningState(c,
                    android.content.ComponentName(c, OutletTileService::class.java))
            }
        }
    }
    val configured: Boolean get() = connection.authorized
    val base: String get() = connection.base
    val host: String get() = java.net.URI(base).host.orEmpty()
    val token: String get() = connection.token
    val legacy: Boolean get() = connection.legacy
}

/** In-app language: null follows the phone language. */
object Lang {
    var code: String? = null
        private set

    private var prefs: SharedPreferences? = null

    fun init(context: Context) {
        if (prefs != null) return
        val p = context.applicationContext.getSharedPreferences("powerk", Context.MODE_PRIVATE)
        prefs = p
        code = p.getString("lang", "").orEmpty().ifBlank { null }
    }

    /** Applies a new choice immediately: platform per-app locale on 33+, recreate below that. */
    fun set(context: Context, value: String?) {
        code = value
        prefs?.edit()?.putString("lang", value.orEmpty())?.apply()
        WidgetUpdates.appearanceChanged(context)
        val activity = context.findActivity() ?: return
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            setPlatformLocales(activity, value)
        } else {
            activity.applyLocale(value)
            activity.recreate()
        }
    }

    /** Called from Activity.onCreate so the first composition already uses the stored language. */
    fun applyStored(activity: Activity) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU && code != null) {
            activity.applyLocale(code)
        }
    }

    @RequiresApi(Build.VERSION_CODES.TIRAMISU)
    private fun setPlatformLocales(activity: Activity, value: String?) {
        val manager = activity.getSystemService(LocaleManager::class.java) ?: return
        manager.applicationLocales =
            if (value == null) LocaleList.getEmptyLocaleList() else LocaleList.forLanguageTags(value)
    }

    @Suppress("DEPRECATION")
    private fun Activity.applyLocale(value: String?) {
        val locale = if (value == null) LocaleList.getDefault()[0] else Locale.forLanguageTag(value)
        Locale.setDefault(locale)
        val config = Configuration(resources.configuration).apply { setLocale(locale) }
        resources.updateConfiguration(config, resources.displayMetrics)
    }
}

internal tailrec fun Context.findActivity(): Activity? = when (this) {
    is Activity -> this
    is ContextWrapper -> baseContext.findActivity()
    else -> null
}
