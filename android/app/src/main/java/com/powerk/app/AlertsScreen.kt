package com.powerk.app

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalResources
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.launch
import kotlinx.coroutines.CoroutineStart
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.collect
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleOwner
import androidx.lifecycle.repeatOnLifecycle

internal fun mergeLiveEvents(existing: List<Event>, incoming: List<Event>): List<Event> =
    (existing + incoming).distinctBy { it.id }.sortedByDescending { it.id }

@Composable
fun warningColor(): Color = LocalPowerkColors.current.warn

@Composable
fun AlertsScreen(snapshot: Snapshot?, onRead: () -> Unit) {
    val strips = remember(snapshot?.strips) { snapshot?.strips.orEmpty() }
    AlertsContent(strips, snapshot?.utcOffsetSeconds ?: 0, onRead)
}

@Composable
private fun AlertsContent(strips: List<Strip>, utcOffsetSeconds: Int, onRead: () -> Unit) {
    var events by remember { mutableStateOf<List<Event>>(emptyList()) }
    var error by remember { mutableStateOf<String?>(null) }
    var busy by remember { mutableStateOf(false) }
    var more by remember { mutableStateOf(false) }
    var accessVersion by remember { mutableIntStateOf(0) }
    var reloadWanted by remember { mutableStateOf(false) }
    val readRequests = remember { Channel<Long>(Channel.CONFLATED) }
    var requestedThrough by remember { mutableLongStateOf(0) }
    val resources = LocalResources.current
    val scope = rememberCoroutineScope()
    val lifecycle = (LocalContext.current.findActivity() as? LifecycleOwner)?.lifecycle
    val latestOnRead by rememberUpdatedState(onRead)
    val stripsByMac = remember(strips) { strips.distinctBy { it.mac }.associateBy { it.mac } }
    fun queueRead(id: Long) {
        if (id > requestedThrough) { requestedThrough = id; readRequests.trySend(id) }
    }
    suspend fun load(older: Boolean = false) {
        if (busy) { if (!older) reloadWanted = true; return }
        if (!Server.configured) { error = resources.getString(R.string.no_server_title); return }
        val connection = Server.connection
        val version = accessVersion
        busy = true
        try {
            val page = connectionResult(connection, { Server.connection }) {
                Api.events(it, if (older) events.minOfOrNull { it.id } else null)
            }
            if (page != null && version == accessVersion) {
                events = mergeLiveEvents(events, page.events)
                more = page.events.size == 50
                error = null
                if (!older) page.events.maxOfOrNull { it.id }?.let(::queueRead)
            }
        } catch (e: Exception) {
            if (e is kotlinx.coroutines.CancellationException) throw e
            if (connection.isCurrent(Server.connection)) error = uiError(resources, e)
        } finally { if (connection.isCurrent(Server.connection)) busy = false }
        if (reloadWanted && connection.isCurrent(Server.connection)) { reloadWanted = false; load() }
    }
    LaunchedEffect(Server.connection, lifecycle) {
        events = emptyList(); error = null; more = false; busy = false
        suspend fun observe() = kotlinx.coroutines.coroutineScope {
            requestedThrough = 0 // A read may have been cancelled when the activity last stopped.
            launch(start = CoroutineStart.UNDISPATCHED) {
                LiveFeed.client.events.collect { update ->
                    if (update.connection.isCurrent(Server.connection)) when (update) {
                        is FeedEvent.Received -> {
                            events = mergeLiveEvents(events, listOf(update.event))
                            queueRead(update.event.id)
                        }
                        is FeedEvent.Reload -> {
                            if (update.clear) { accessVersion++; events = emptyList(); more = false }
                            launch { load() }
                        }
                    }
                }
            }
            launch {
                for (first in readRequests) {
                    // Coalesce bursts; do not turn a four-frame/second feed into four REST writes.
                    delay(2_000)
                    var through = first
                    while (true) { through = maxOf(through, readRequests.tryReceive().getOrNull() ?: break) }
                    val c = Server.connection
                    try {
                        Api.readEvents(c, through)
                        if (c.isCurrent(Server.connection)) latestOnRead()
                    } catch (e: Exception) {
                        if (e is kotlinx.coroutines.CancellationException) throw e
                        if (c.isCurrent(Server.connection)) { requestedThrough = 0; error = uiError(resources, e) }
                    }
                }
            }
            load()
        }
        if (lifecycle != null) lifecycle.repeatOnLifecycle(Lifecycle.State.STARTED) { observe() } else observe()
    }
    LazyColumn(contentPadding = PaddingValues(18.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        item {
            HighlightTitle(stringResource(R.string.tab_alerts))
            TextButton(enabled = !busy, onClick = { scope.launch { load() } }) { Text(stringResource(R.string.refresh)) }
            error?.let { ErrorBanner(it) }
            if (busy) LinearProgressIndicator(Modifier.fillMaxWidth())
            if (events.isEmpty() && !busy && error == null) Text(stringResource(R.string.no_alerts))
        }
        items(events, key = { it.id }) { event ->
            val strip = stripsByMac[event.mac]
            val target = listOfNotNull(strip?.displayName ?: event.mac.ifBlank { null },
                if (event.outlet > 0) strip?.outlet(event.outlet)?.displayName(resources)
                    ?: resources.getString(R.string.outlet_n, event.outlet) else null).joinToString(" · ")
            // Keep the mutable wire JSONObject outside the skippable card boundary.
            AlertCard(event.level, target, resources.eventText(event), serverLocalTime(event.ts, utcOffsetSeconds))
        }
        if (more) item {
            OutlinedButton(enabled = !busy, onClick = { scope.launch { load(true) } }, modifier = Modifier.fillMaxWidth()) {
                Text(stringResource(R.string.load_more))
            }
        }
    }
}

@Composable
private fun AlertCard(level: String, target: String, text: String, time: String) {
    val scheme = MaterialTheme.colorScheme
    val color = when (level) { "alert" -> scheme.error; "warn" -> warningColor(); else -> LocalPowerkColors.current.ok }
    PaperCard(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text(stringResource(when (level) { "alert" -> R.string.level_alert; "warn" -> R.string.level_warn; else -> R.string.level_info }),
                color = color, style = MaterialTheme.typography.labelLarge)
            if (target.isNotBlank()) Text(markerText(target), style = MaterialTheme.typography.titleMedium)
            Text(text)
            DashedDivider()
            Text(time, style = LocalPowerkType.current.figures)
        }
    }
}
