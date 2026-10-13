package com.powerk.app

import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.Spring
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.spring
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.scaleOut
import androidx.compose.animation.slideInVertically
import androidx.compose.animation.slideOutVertically
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material.icons.filled.DateRange
import androidx.compose.material.icons.filled.Notifications
import androidx.compose.material.icons.filled.Star
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Badge
import androidx.compose.material3.BadgedBox
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.TopAppBar
import androidx.activity.compose.BackHandler
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularWavyProgressIndicator
import androidx.compose.material3.ElevatedCard
import androidx.compose.material3.ExperimentalMaterial3ExpressiveApi
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SegmentedButton
import androidx.compose.material3.SegmentedButtonDefaults
import androidx.compose.material3.ShortNavigationBar
import androidx.compose.material3.ShortNavigationBarItem
import androidx.compose.material3.SingleChoiceSegmentedButtonRow
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.runtime.structuralEqualityPolicy
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.rotate
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.graphics.lerp
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalResources
import androidx.compose.ui.platform.LocalHapticFeedback
import androidx.compose.ui.platform.LocalLayoutDirection
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.role
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.toggleableState
import androidx.compose.ui.state.ToggleableState
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.LayoutDirection
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.delay
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlin.math.roundToInt
import androidx.compose.material3.ButtonDefaults
import androidx.compose.ui.unit.sp

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun PowerkApp(initialTab: Int = 0, navigationRequest: Int = 0) {
    // Destroy every screen/editor/snackbar immediately on an account or server change.
    // Refresh-token rotation intentionally leaves this identity unchanged.
    val connection = Server.connection
    key(connection) {
        if (connection.authorized) ConnectedApp(initialTab, navigationRequest) else SignInScreen()
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun ConnectedApp(initialTab: Int, navigationRequest: Int) {
    var tab by remember { mutableIntStateOf(initialTab) }
    val feed = LiveFeed.client.state.collectAsState()
    // Narrow reads: strip changes do not invalidate the scaffold or unrelated tabs.
    val shownSnapshot by remember {
        derivedStateOf(structuralEqualityPolicy()) { feed.value.snapshot.takeIf { feed.value.connection == Server.connection } }
    }
    val unreadAlerts by remember { derivedStateOf(structuralEqualityPolicy()) { shownSnapshot?.unreadAlerts ?: 0 } }
    val loading by remember { derivedStateOf { feed.value.loading } }
    var showSplash by remember { mutableStateOf(true) }
    val snackbar = remember { SnackbarHostState() }
    val scope = rememberCoroutineScope()
    val context = LocalContext.current
    val resources = LocalResources.current
    val error by remember(resources) { derivedStateOf { feed.value.error?.let { uiError(resources, it) } } }
    var settingsOpen by remember { mutableStateOf(false) }
    LaunchedEffect(initialTab, navigationRequest) { tab = initialTab; settingsOpen = false }
    BackHandler(settingsOpen) { settingsOpen = false }
    // "mac:outlet" -> state we are switching to right now (optimistic UI while the strip answers)
    val pending = remember { mutableStateMapOf<String, Boolean>() }

    // Only a refresh the user asked for shows the loading state; background polls stay silent so nothing jumps or spins.
    suspend fun refresh(userInitiated: Boolean = false) {
        withContext(Dispatchers.IO) { LiveFeed.client.refresh(Server.connection, userInitiated) }
    }

    LaunchedEffect(Unit) {
        delay(1100)
        showSplash = false
    }

    LaunchedEffect(Server.connection) {
        withContext(Dispatchers.IO) { WidgetUpdates.renderAll(context) }
        pending.clear()
    }

    fun command(mac: String, outlet: Int, on: Boolean) {
        val connection = Server.connection
        val keys = if (outlet == 0) (1..4).map { "$mac:$it" } else listOf("$mac:$outlet")
        if (keys.any { pending.containsKey(it) }) return
        keys.forEach { pending[it] = on }
        scope.launch {
            try {
                val confirmed = Api.setOutlet(connection, mac, outlet, on)
                if (connection.isCurrent(Server.connection)) {
                    refresh()
                    if (!confirmed) snackbar.showSnackbar(resources.getString(R.string.not_confirmed))
                }
            } catch (e: Exception) {
                if (e is kotlinx.coroutines.CancellationException) throw e
                if (connection.isCurrent(Server.connection)) snackbar.showSnackbar(uiError(resources, e))
            } finally {
                if (connection.isCurrent(Server.connection)) keys.forEach { pending.remove(it) }
            }
        }
    }

    Box(Modifier.fillMaxSize().background(MaterialTheme.colorScheme.background)) {
        Scaffold(
            containerColor = MaterialTheme.colorScheme.background,
            contentColor = MaterialTheme.colorScheme.onBackground,
            snackbarHost = { SnackbarHost(snackbar) },
            topBar = {
                TopAppBar(title = { Text("POWERK", style = LocalPowerkType.current.brand) },
                    navigationIcon = {
                        if (settingsOpen) IconButton(onClick = { settingsOpen = false }) {
                            Icon(Icons.AutoMirrored.Filled.ArrowBack, stringResource(R.string.back))
                        }
                     }, actions = {
                         TextButton(onClick = {
                             Lang.set(context, if (resources.configuration.locales[0].language == "ar") "en" else "ar")
                             WidgetUpdates.appearanceChanged(context)
                         }) { Text(if (resources.configuration.locales[0].language == "ar") "EN" else "العربية") }
                        if (!settingsOpen) IconButton(onClick = { settingsOpen = true }) {
                            Icon(Icons.Filled.Settings, stringResource(R.string.open_settings))
                        }
                    })
            },
            bottomBar = {
                if (!settingsOpen) {
                Column {
                DashedDivider()
                ShortNavigationBar(containerColor = LocalPowerkColors.current.bar) {
                    val labels = remember { listOf(R.string.tab_plugs, R.string.tab_rules, R.string.tab_energy, R.string.tab_alerts) }
                    val icons = remember { listOf(Icons.Filled.Home, Icons.Filled.DateRange, Icons.Filled.Star, Icons.Filled.Notifications) }
                    labels.forEachIndexed { index, label ->
                        ShortNavigationBarItem(selected = tab == index, onClick = { tab = index },
                            icon = {
                                BadgedBox(badge = {
                                    if (index == 3 && unreadAlerts > 0) Badge { Text(unreadAlerts.toString()) }
                                }) { Icon(icons[index], contentDescription = null) }
                            }, label = { Text(stringResource(label)) })
                    }
                }
                }
                }
            },
        ) { padding ->
            AnimatedContent(
                targetState = if (settingsOpen) 4 else tab,
                transitionSpec = {
                    val forward = targetState > initialState
                    val shift = if (forward) 1 else -1
                    (fadeIn(tween(240)) + slideInVertically(tween(280)) { it / 10 * shift }) togetherWith
                        (fadeOut(tween(140)) + slideOutVertically(tween(200)) { -it / 14 * shift })
                },
                label = "tab",
                modifier = Modifier.fillMaxSize().padding(padding),
            ) { current ->
                if (current == 0) {
                    PlugsScreen(
                        snapshot = shownSnapshot,
                        error = error,
                        loading = loading,
                        pending = pending,
                        onRefresh = { scope.launch { refresh(userInitiated = true) } },
                        onOpenSettings = { settingsOpen = true },
                        onCommand = { mac, outlet, on -> command(mac, outlet, on) },
                    )
                } else {
                    Column(Modifier.fillMaxSize()) {
                        if (error != null) ErrorBanner(error!!)
                        when (current) {
                            1 -> RulesScreen(shownSnapshot)
                            2 -> EnergyScreen(shownSnapshot)
                            3 -> AlertsScreen(shownSnapshot) { scope.launch { refresh() } }
                            4 -> SettingsScreen(shownSnapshot)
                        }
                    }
                }
            }
        }

        AnimatedVisibility(
            visible = showSplash,
            exit = fadeOut(tween(420)) + scaleOut(tween(420), targetScale = 1.06f),
        ) { Splash() }
        if (!showSplash) DevicePushPermissionPrompt(Server.connection)
    }
}

@OptIn(ExperimentalMaterial3ExpressiveApi::class)
@Composable
private fun Splash() {
    val appear = remember { Animatable(0f) }
    LaunchedEffect(Unit) { appear.animateTo(1f, spring(dampingRatio = 0.55f, stiffness = Spring.StiffnessLow)) }
    val scheme = MaterialTheme.colorScheme

    Box(
        Modifier
             .fillMaxSize()
            .background(scheme.background),
        contentAlignment = Alignment.Center,
    ) {
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            Box(
                Modifier
                    .size(150.dp)
                    .graphicsLayer {
                        val p = appear.value
                        scaleX = 0.62f + 0.38f * p
                        scaleY = 0.62f + 0.38f * p
                        alpha = p
                        rotationZ = -28f * (1f - p)
                    },
                contentAlignment = Alignment.Center,
            ) {
                Icon(
                    painter = painterResource(R.drawable.ic_launcher_foreground),
                    contentDescription = null,
                    modifier = Modifier.size(150.dp),
                    tint = scheme.primary,
                )
            }
            Spacer(Modifier.height(18.dp))
            Text(
                "POWERK",
                style = LocalPowerkType.current.brand.copy(fontSize = 36.sp),
                fontWeight = FontWeight.SemiBold,
                color = scheme.onSurface,
                modifier = Modifier.graphicsLayer { alpha = appear.value },
            )
            Text(
                stringResource(R.string.splash_tagline),
                style = MaterialTheme.typography.bodyMedium,
                color = scheme.onSurfaceVariant,
                modifier = Modifier.graphicsLayer { alpha = appear.value },
            )
            Spacer(Modifier.height(38.dp))
            CircularWavyProgressIndicator(Modifier.size(30.dp))
        }
    }
}

@OptIn(ExperimentalMaterial3ExpressiveApi::class)
@Composable
fun PlugsScreen(
    snapshot: Snapshot?,
    error: String?,
    loading: Boolean,
    pending: Map<String, Boolean>,
    onRefresh: () -> Unit,
    onOpenSettings: () -> Unit,
    onCommand: (String, Int, Boolean) -> Unit,
) {
    val strips = remember(snapshot?.strips) { snapshot?.strips.orEmpty() }
    PlugsContent(strips, snapshot != null, snapshot?.currency.orEmpty(), error, loading,
        pending, onRefresh, onOpenSettings, onCommand)
}

@OptIn(ExperimentalMaterial3ExpressiveApi::class)
@Composable
private fun PlugsContent(
    strips: List<Strip>, hasSnapshot: Boolean, currency: String, error: String?, loading: Boolean,
    pending: Map<String, Boolean>, onRefresh: () -> Unit, onOpenSettings: () -> Unit,
    onCommand: (String, Int, Boolean) -> Unit,
) {
    var claimOpen by androidx.compose.runtime.saveable.rememberSaveable { mutableStateOf(false) }
    var managing by remember { mutableStateOf<String?>(null) }
    if (claimOpen) AccountDialog(R.string.add_strip, { claimOpen = false }) { ClaimScreen(onRefresh) }
    strips.firstOrNull { it.mac == managing }?.let { strip ->
        key(strip.mac, strip.role) { StripManagementSheet(strip, { managing = null }, onRefresh) }
    }
    var renameTarget by remember { mutableStateOf<Pair<Strip, Int>?>(null) }
    renameTarget?.let { (strip, n) ->
        if (strips.any { it.mac == strip.mac && it.role.canControl }) RenameDialog(strip, n, onDismiss = { renameTarget = null }, onSaved = onRefresh)
    }

    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(start = 18.dp, end = 18.dp, top = 20.dp, bottom = 36.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        if (!Server.legacy && strips.isNotEmpty()) item {
            OutlinedButton(onClick = { claimOpen = true }, modifier = Modifier.fillMaxWidth()) { Text(stringResource(R.string.add_strip)) }
        }
        // Shown only for an empty list; toggling it with every poll would push the whole list down and back up.
        if (strips.isEmpty()) item {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End) {
                IconButton(onClick = onRefresh, enabled = Server.configured && !loading) {
                    Icon(Icons.Filled.Refresh, stringResource(R.string.refresh))
                }
            }
        }

        item {
            AnimatedVisibility(
                visible = error != null,
                enter = fadeIn() + slideInVertically { -it / 3 },
                exit = fadeOut(),
            ) {
                MessageCard(error ?: "", isError = true, icon = Icons.Filled.Warning)
            }
        }

        if (!Server.configured) {
            item {
                EmptyState(
                    title = stringResource(R.string.no_server_title),
                    body = stringResource(R.string.no_server_body),
                    action = stringResource(R.string.open_settings),
                    onAction = onOpenSettings,
                )
            }
        } else {
            items(strips, key = { it.mac }) { strip ->
                val currentStrip by rememberUpdatedState(strip)
                val rename: (Int) -> Unit = remember { { n -> renameTarget = currentStrip to n } }
                val manage: (() -> Unit)? = remember(strip.mac, Server.legacy) {
                    if (Server.legacy) null else ({ managing = strip.mac })
                }
                StripCard(
                    strip = strip,
                    showMac = strips.size > 1,
                    currency = strip.currency.ifBlank { currency },
                    pending = pending,
                    onCommand = onCommand,
                    onRename = rename,
                    onManage = manage,
                    modifier = Modifier.animateItem(),
                )
            }

            if (hasSnapshot && strips.isEmpty()) {
                item {
                    if (!Server.legacy) AddStripEmpty { claimOpen = true } else EmptyState(
                        title = stringResource(R.string.no_strip_title),
                        body = stringResource(R.string.no_strip_body),
                    )
                }
            }

            if (!hasSnapshot && error == null) {
                item {
                    Column(
                        Modifier.fillMaxWidth().padding(top = 60.dp),
                        horizontalAlignment = Alignment.CenterHorizontally,
                    ) {
                        CircularWavyProgressIndicator(Modifier.size(34.dp))
                        Spacer(Modifier.height(14.dp))
                        Text(
                            stringResource(R.string.connecting, Server.host),
                            style = MaterialTheme.typography.bodyMedium,
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun Header(
    stripCount: Int,
    onlineCount: Int,
    configured: Boolean,
    loading: Boolean,
    onRefresh: () -> Unit,
) {
    val spin = rememberInfiniteTransition(label = "refresh")
    val angle by spin.animateFloat(
        initialValue = 0f,
        targetValue = 360f,
        animationSpec = infiniteRepeatable(tween(900, easing = LinearEasing)),
        label = "angle",
    )
    Row(verticalAlignment = Alignment.CenterVertically) {
        Column(Modifier.weight(1f)) {
            Text(
                stringResource(R.string.app_name),
                style = MaterialTheme.typography.headlineMedium,
                fontWeight = FontWeight.SemiBold,
            )
            val subtitle = when {
                !configured -> stringResource(R.string.header_no_server)
                onlineCount > 0 -> stringResource(R.string.header_online, onlineCount, Server.host)
                stripCount > 0 -> stringResource(R.string.header_known_offline, stripCount)
                else -> stringResource(R.string.header_waiting, Server.host)
            }
            Text(subtitle, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        IconButton(onClick = onRefresh, enabled = configured && !loading) {
            Icon(
                Icons.Filled.Refresh,
                contentDescription = stringResource(R.string.refresh),
                modifier = Modifier.rotate(if (loading) angle else 0f),
            )
        }
    }
}

@OptIn(ExperimentalMaterial3ExpressiveApi::class)
@Composable
internal fun StripCard(
    strip: Strip,
    showMac: Boolean,
    currency: String,
    pending: Map<String, Boolean>,
    onCommand: (String, Int, Boolean) -> Unit,
    onRename: (Int) -> Unit,
    onManage: (() -> Unit)? = null,
    modifier: Modifier = Modifier,
) {
    val mac = strip.mac
    // A tap on another strip should not invalidate this strip's content.
    val pendingOutlets by remember(mac, pending) {
        derivedStateOf(structuralEqualityPolicy()) { (1..4).map { pending["$mac:$it"] } }
    }
    val allPending = pendingOutlets.any { it != null }
    val c = LocalPowerkColors.current
    val still = reducedMotion()
    Column(modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(16.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Box(Modifier.weight(1f)) { HighlightTitle(strip.displayName) }
                if (strip.role.canControl) IconButton(onClick = { onRename(0) }) { Icon(Icons.Filled.Edit, stringResource(R.string.rename)) }
                StatusChip(strip.online)
            }
            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                RoleBadge(strip.role)
                Spacer(Modifier.weight(1f))
                if (onManage != null) TextButton(onClick = onManage) { Text(stringResource(R.string.manage_strip)) }
            }
            AlarmChips(strip.alarms)
            Box(Modifier.fillMaxWidth().padding(top = 8.dp).rotate(if (still) 0f else -.4f)) {
                PaperCard(Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(20.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        Text(stringResource(R.string.using_now), style = LocalPowerkType.current.hand, color = c.ink2)
                        Text(if (strip.online) "${decimal(strip.powerW, 1)} W" else "— W",
                            style = MaterialTheme.typography.displayMedium.copy(textDirection = androidx.compose.ui.text.style.TextDirection.Ltr))
                        Text(listOfNotNull(strip.voltage?.let { "${decimal(it, 1)} V" }, strip.currentA?.let { "${decimal(it, 2)} A" })
                            .joinToString(" · "), style = LocalPowerkType.current.figures, color = c.ink2)
                        DashedDivider(Modifier.padding(vertical = 4.dp))
                        Row(horizontalArrangement = Arrangement.spacedBy(16.dp)) {
                            Column(Modifier.weight(1f)) {
                                Text(stringResource(R.string.summary_today), style = LocalPowerkType.current.hand, color = c.ink2)
                                Text("${decimal(strip.todayKwh, 2)} kWh", style = LocalPowerkType.current.figures)
                            }
                            Column(Modifier.weight(1f)) {
                                Text(stringResource(R.string.summary_month), style = LocalPowerkType.current.hand, color = c.ink2)
                                Text("${decimal(strip.monthCost, 1)} $currency", style = LocalPowerkType.current.figures)
                            }
                        }
                    }
                }
                Box(Modifier.align(Alignment.TopStart).offset(x = 28.dp, y = (-12).dp)
                    .rotate(if (still) 0f else -5f).shadow(2.dp).size(92.dp, 24.dp).background(c.tape))
                Box(Modifier.align(Alignment.TopEnd).offset(x = (-34).dp, y = (-10).dp)
                    .rotate(if (still) 0f else 4f).shadow(2.dp).size(70.dp, 22.dp).background(c.tape))
            }

            for (row in 0 until 2) {
                Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    for (column in 0 until 2) {
                        val outlet = strip.outlet(row * 2 + column + 1)
                        if (outlet == null) {
                            Spacer(Modifier.weight(1f))
                        } else {
                            val n = outlet.n
                            key(n) {
                                OutletTile(
                                    outlet = outlet,
                                    on = pendingOutlets[n - 1] ?: outlet.on,
                                    pending = pendingOutlets[n - 1] != null,
                                    enabled = strip.online,
                                    controllable = strip.role.canControl,
                                    onToggle = { onCommand(mac, n, it) },
                                    onRename = { onRename(n) },
                                    modifier = Modifier.weight(1f),
                                )
                            }
                        }
                    }
                }
            }

            Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                Button(onClick = { onCommand(strip.mac, 0, true) }, enabled = strip.online && strip.role.canControl && !allPending,
                    shape = Wobble2, border = BorderStroke(2.dp, c.ink), colors = ButtonDefaults.buttonColors(containerColor = c.ink, contentColor = c.bg),
                    modifier = Modifier.weight(1f).heightIn(min = 52.dp)) { Text(stringResource(R.string.turn_all_on)) }
                OutlinedButton(onClick = { onCommand(strip.mac, 0, false) }, enabled = strip.online && strip.role.canControl && !allPending,
                    shape = Wobble2, border = BorderStroke(2.dp, c.ink), colors = ButtonDefaults.outlinedButtonColors(contentColor = c.ink),
                    modifier = Modifier.weight(1f).heightIn(min = 52.dp)) { Text(stringResource(R.string.turn_all_off)) }
            }
    }
}

@OptIn(ExperimentalMaterial3ExpressiveApi::class)
@Composable
private fun OutletTile(
    outlet: Outlet,
    on: Boolean,
    pending: Boolean,
    enabled: Boolean,
    controllable: Boolean,
    onToggle: (Boolean) -> Unit,
    onRename: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val scheme = MaterialTheme.colorScheme
    val haptics = LocalHapticFeedback.current
    val progress by animateFloatAsState(
        targetValue = if (on) 1f else 0f,
        animationSpec = spring(dampingRatio = 0.55f, stiffness = Spring.StiffnessMediumLow),
        label = "toggle",
    )
    val c = LocalPowerkColors.current
    val container = lerp(c.card, c.accent, progress)
    val content = lerp(c.ink, c.onAccent, progress)
    val secondary = if (on) c.onAccentSecondary else c.ink2
    val still = reducedMotion()

    Surface(
        onClick = {
            haptics.performHapticFeedback(HapticFeedbackType.LongPress)
            onToggle(!on)
        },
        enabled = enabled && controllable && !pending,
        shape = Wobble2,
        border = BorderStroke(2.dp, c.ink),
        color = container,
        contentColor = content,
        modifier = modifier
            .heightIn(min = 164.dp)
            .semantics {
                role = Role.Switch
                toggleableState = if (on) ToggleableState.On else ToggleableState.Off
            }
            .rotate(if (still) 0f else if (outlet.n % 2 == 1) -.7f else .6f),
    ) {
        Column(
            Modifier.fillMaxWidth().padding(horizontal = 14.dp, vertical = 12.dp),
            verticalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    markerText(outlet.name.ifBlank { stringResource(R.string.outlet_n, outlet.n) }),
                    style = MaterialTheme.typography.titleMedium,
                    modifier = Modifier.weight(1f),
                )
            }
            AlarmChips(outlet.alarms)
            Text(
                "${stringResource(if (!enabled) R.string.state_offline else if (pending) R.string.switching else if (on) R.string.state_on else R.string.state_off)} · ${isolateFigures("${outlet.tempC}°")}",
                style = LocalPowerkType.current.hand.copy(fontSize = 12.sp, lineHeight = 20.sp),
                color = secondary,
            )
            Text(
                if (enabled) "${decimal(outlet.powerW, 1)} W" else "— W",
                style = LocalPowerkType.current.figures.copy(fontSize = 24.sp),
            )
            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                Box(Modifier.weight(1f)) {
                    if (pending) CircularWavyProgressIndicator(Modifier.size(22.dp), color = content)
                    else MiniSwitch(progress = progress, onColor = c.switchOn, enabled = enabled && controllable)
                }
                if (controllable) IconButton(onClick = onRename, modifier = Modifier.size(48.dp)) {
                    Icon(Icons.Filled.Edit, stringResource(R.string.rename), tint = content, modifier = Modifier.size(18.dp))
                }
            }
        }
    }
}

/** Small animated switch drawn inside an outlet tile: track + sliding thumb. */
@Composable
private fun MiniSwitch(progress: Float, onColor: Color, enabled: Boolean) {
    val scheme = MaterialTheme.colorScheme
    // Match Material's disabled controls for both offline strips and read-only access.
    val track = if (enabled) lerp(LocalPowerkColors.current.fill, onColor, progress)
        else scheme.onSurface.copy(alpha = .12f)
    val thumb = if (enabled) LocalPowerkColors.current.switchThumb else scheme.onSurface.copy(alpha = .38f)

    Box(
        Modifier
            .size(width = 38.dp, height = 22.dp)
            .clip(CircleShape)
            .background(track),
    ) {
        Box(
            Modifier
                .offset(x = (2 + 16 * progress).dp, y = 2.dp)
                .size(18.dp)
                .clip(CircleShape)
                .background(thumb),
        )
    }
}

@Composable
private fun PowerRing(watts: Double, enabled: Boolean) {
    val target = (watts / 2000.0).coerceIn(0.0, 1.0).toFloat()
    val sweep by animateFloatAsState(
        targetValue = target,
        animationSpec = spring(dampingRatio = 0.7f, stiffness = Spring.StiffnessLow),
        label = "sweep",
    )
    val scheme = MaterialTheme.colorScheme
    val track = scheme.surfaceContainerHighest
    val arc = if (enabled && watts > 0.05) scheme.primary else scheme.outlineVariant

    Box(Modifier.size(142.dp), contentAlignment = Alignment.Center) {
        Canvas(Modifier.fillMaxSize()) {
            val stroke = 12.dp.toPx()
            val inset = stroke / 2f
            val arcSize = Size(size.width - stroke, size.height - stroke)
            drawArc(
                color = track,
                startAngle = 135f,
                sweepAngle = 270f,
                useCenter = false,
                topLeft = Offset(inset, inset),
                size = arcSize,
                style = Stroke(width = stroke, cap = StrokeCap.Round),
            )
            drawArc(
                color = arc,
                startAngle = 135f,
                sweepAngle = 270f * sweep,
                useCenter = false,
                topLeft = Offset(inset, inset),
                size = arcSize,
                style = Stroke(width = stroke, cap = StrokeCap.Round),
            )
        }
        // fixed-width inner column keeps the numbers clear of the ring stroke
        Column(
            Modifier.width(92.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Row(verticalAlignment = Alignment.Bottom) {
                Text(
                    "${watts.roundToInt()}",
                    style = MaterialTheme.typography.displaySmall,
                    fontWeight = FontWeight.SemiBold,
                    maxLines = 1,
                    softWrap = false,
                )
                Spacer(Modifier.width(3.dp))
                Text(
                    stringResource(R.string.unit_watts),
                    style = MaterialTheme.typography.labelLarge,
                    color = scheme.onSurfaceVariant,
                    modifier = Modifier.padding(bottom = 6.dp),
                )
            }
            Text(
                stringResource(R.string.watts_now),
                style = MaterialTheme.typography.labelSmall,
                color = scheme.onSurfaceVariant,
                maxLines = 1,
            )
        }
    }
}

@Composable
private fun MetricPill(value: String) {
    Surface(
        shape = CircleShape,
        color = MaterialTheme.colorScheme.surfaceContainerHighest,
        contentColor = MaterialTheme.colorScheme.onSurfaceVariant,
    ) {
        CompositionLocalProvider(LocalLayoutDirection provides LayoutDirection.Ltr) {
            Text(
                value,
                Modifier.padding(horizontal = 12.dp, vertical = 7.dp),
                style = MaterialTheme.typography.labelLarge,
                maxLines = 1,
                softWrap = false,
            )
        }
    }
}

@Composable
private fun StatusDot(online: Boolean) {
    val pulse = rememberInfiniteTransition(label = "dot")
    val alpha by pulse.animateFloat(
        initialValue = 0.35f,
        targetValue = 1f,
        animationSpec = infiniteRepeatable(tween(900), RepeatMode.Reverse),
        label = "alpha",
    )
    Box(
        Modifier
            .size(11.dp)
            .graphicsLayer { this.alpha = if (online) 1f else alpha }
            .background(
                if (online) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.error,
                CircleShape,
            )
    )
}

@Composable
private fun MessageCard(text: String, isError: Boolean, icon: androidx.compose.ui.graphics.vector.ImageVector? = null) {
    Card(
        Modifier.fillMaxWidth(),
        border = BorderStroke(1.5.dp, LocalPowerkColors.current.ink),
        colors = CardDefaults.cardColors(
            containerColor = if (isError) MaterialTheme.colorScheme.errorContainer
            else MaterialTheme.colorScheme.surfaceContainerHighest,
            contentColor = if (isError) MaterialTheme.colorScheme.onErrorContainer
            else MaterialTheme.colorScheme.onSurface,
        ),
    ) {
        Row(
            Modifier.padding(16.dp),
            horizontalArrangement = Arrangement.spacedBy(12.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            if (icon != null) Icon(icon, contentDescription = null)
            Text(text, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.weight(1f))
        }
    }
}

@Composable
private fun EmptyState(title: String, body: String, action: String? = null, onAction: (() -> Unit)? = null) {
    Column(
        Modifier.fillMaxWidth().padding(top = 40.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Surface(shape = CircleShape, color = MaterialTheme.colorScheme.surfaceContainerHighest) {
            Icon(
                Icons.Filled.Info,
                contentDescription = null,
                modifier = Modifier.padding(18.dp).size(30.dp),
                tint = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        Spacer(Modifier.height(16.dp))
        Text(title, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
        Spacer(Modifier.height(6.dp))
        Text(
            body,
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            textAlign = TextAlign.Center,
            modifier = Modifier.padding(horizontal = 12.dp),
        )
        if (action != null && onAction != null) {
            Spacer(Modifier.height(18.dp))
            Button(onClick = onAction) { Text(action) }
        }
    }
}

@OptIn(ExperimentalMaterial3ExpressiveApi::class)
@Composable
fun SettingsScreen(snapshot: Snapshot?, serverSettingsFixture: ServerSettings? = null) {
    val strips = remember(snapshot?.strips) { snapshot?.strips.orEmpty() }
    SettingsContent(strips, serverSettingsFixture)
}

@OptIn(ExperimentalMaterial3ExpressiveApi::class)
@Composable
private fun SettingsContent(strips: List<Strip>, serverSettingsFixture: ServerSettings?) {
    var lang by remember { mutableStateOf(Lang.code) }
    val context = LocalContext.current
    Column(
        Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(18.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        HighlightTitle(stringResource(R.string.settings_title))
        ThemePicker()
        if (!Server.legacy && Server.configured) AccountSection()
        strips.forEach { strip -> key(strip.mac) { StripInfoCard(strip) } }

        PaperCard(Modifier.fillMaxWidth()) {
            Column(Modifier.padding(18.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
                Text(
                    markerText(stringResource(R.string.language_title)),
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.SemiBold,
                )
                val options = listOf(
                    null to stringResource(R.string.lang_system),
                    "en" to stringResource(R.string.lang_english),
                    "ar" to stringResource(R.string.lang_arabic),
                )
                SingleChoiceSegmentedButtonRow(Modifier.fillMaxWidth()) {
                    options.forEachIndexed { index, (value, label) ->
                        SegmentedButton(
                            selected = lang == value,
                            onClick = {
                                if (lang != value) {
                                    lang = value
                                    Lang.set(context, value)
                                }
                            },
                            shape = Wobble2,
                            colors = paperSegmentColors(),
                        ) { Text(label) }
                    }
                }
            }
        }

        ConnectionSection()
        if (Server.legacy) ServerSettingsSection(serverSettingsFixture)
        if (Server.configured) {
            NotificationSection(strips)
        }
        if (Server.configured) TileTargetSection(strips)

        PaperCard(Modifier.fillMaxWidth()) {
            Column(Modifier.padding(18.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Text(
                    markerText(stringResource(R.string.setup_title)),
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.SemiBold,
                )
                SetupStep(1, stringResource(R.string.setup_step_1))
                SetupStep(2, stringResource(R.string.setup_step_2))
                SetupStep(3, stringResource(R.string.setup_step_3))
                CompositionLocalProvider(LocalLayoutDirection provides LayoutDirection.Ltr) {
                    Text(
                        "python powerk.py provision --ip <ip> --ssid WIFI --password PW",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.padding(start = 30.dp),
                    )
                }
                SetupStep(4, stringResource(R.string.setup_step_4))
                DashedDivider(Modifier.padding(vertical = 4.dp))
                Text(
                    stringResource(R.string.setup_footer),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
    }
}

@Composable
private fun SetupStep(number: Int, text: String) {
    Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
        Surface(
            shape = CircleShape,
            color = MaterialTheme.colorScheme.primaryContainer,
            contentColor = MaterialTheme.colorScheme.onPrimaryContainer,
            modifier = Modifier.size(22.dp),
        ) {
            Box(contentAlignment = Alignment.Center) {
                Text("$number", style = MaterialTheme.typography.labelSmall, fontWeight = FontWeight.Bold)
            }
        }
        Text(text, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.weight(1f))
    }
}
