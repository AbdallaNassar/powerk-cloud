package com.powerk.app

import android.os.SystemClock
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalResources
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleOwner
import androidx.lifecycle.repeatOnLifecycle
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import org.json.JSONObject

@Composable
fun RoleBadge(role: StripRole) {
    val c = LocalPowerkColors.current
    Surface(shape = CircleShape, color = c.card, contentColor = c.ink,
        border = BorderStroke(1.dp, c.line)) {
        Text(stringResource(role.label), Modifier.padding(horizontal = 10.dp, vertical = 4.dp),
            style = MaterialTheme.typography.labelMedium)
    }
}

@Composable
fun AddStripEmpty(onAdd: () -> Unit) {
    Column(Modifier.fillMaxWidth().padding(vertical = 32.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
        HighlightTitle(stringResource(R.string.add_strip))
        Text(stringResource(R.string.add_strip_empty))
        Button(onClick = onAdd, modifier = Modifier.fillMaxWidth()) { Text(stringResource(R.string.add_strip)) }
    }
}

@Composable
fun ClaimScreen(onDone: () -> Unit) {
    val work = rememberAccountWork()
    val context = LocalContext.current
    val resources = LocalResources.current
    val lifecycle = (context.findActivity() as LifecycleOwner).lifecycle
    var id by rememberSaveable { mutableStateOf("") }
    var deadline by rememberSaveable { mutableStateOf(0L) }
    var state by remember { mutableStateOf<ClaimState>(if (id.isEmpty()) ClaimState.Entry
        else claimTick(ClaimState.Pending(id, deadline), SystemClock.elapsedRealtime())) }
    var pollError by remember { mutableStateOf<String?>(null) }
    val latestState by rememberUpdatedState(state)
    LaunchedEffect(id) {
        if (id.isEmpty()) return@LaunchedEffect
        lifecycle.repeatOnLifecycle(Lifecycle.State.STARTED) {
            launch {
                while (latestState is ClaimState.Pending) {
                    state = claimTick(latestState as ClaimState.Pending, SystemClock.elapsedRealtime())
                    delay(250)
                }
            }
            while (latestState is ClaimState.Pending) {
                try {
                    val pending = latestState as ClaimState.Pending
                    val reply = AccountApi.claimPoll(work.connection, pending)
                    if (!work.current()) return@repeatOnLifecycle
                    // Do not overwrite a newer countdown value with the request's old tick.
                    if (reply !is ClaimState.Pending) {
                        state = reply
                        if (reply is ClaimState.Done) onDone()
                    }
                    pollError = null
                } catch (e: Exception) {
                    if (e is kotlinx.coroutines.CancellationException) throw e
                    if (!work.current()) return@repeatOnLifecycle
                    pollError = uiError(resources, e)
                    if ((e as? ServerException)?.status == 404)
                        state = ClaimState.Expired
                }
                delay(1000)
            }
        }
    }
    ClaimContent(state, work.busy, work.error ?: pollError, onStart = { code ->
        work.run {
            val pending = AccountApi.claim(work.connection, code, SystemClock::elapsedRealtime)
            if (work.current()) { state = pending; deadline = pending.deadline; id = pending.id }
        }
    }, onReset = { id = ""; state = ClaimState.Entry; pollError = null })
}

@Composable
fun ClaimContent(state: ClaimState, busy: Boolean = false, error: String? = null,
    onStart: (String) -> Unit = {}, onReset: () -> Unit = {}) {
    var code by rememberSaveable { mutableStateOf("") }
    Column(Modifier.fillMaxWidth().verticalScroll(rememberScrollState()).padding(18.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp)) {
        when (state) {
            ClaimState.Entry -> {
                Text(stringResource(R.string.claim_code_hint))
                OutlinedTextField(code, { code = normalizeNumber(it).uppercase(java.util.Locale.ROOT).filter { c -> c in '0'..'9' || c in 'A'..'F' }.take(7) },
                    label = { Text(stringResource(R.string.claim_code)) }, singleLine = true,
                    textStyle = LocalPowerkType.current.figures, enabled = !busy, modifier = Modifier.fillMaxWidth())
                Text(stringResource(R.string.claim_online_hint), style = MaterialTheme.typography.bodySmall)
                Button(enabled = code.length == 7 && !busy, onClick = { onStart(code) }, modifier = Modifier.fillMaxWidth()) {
                    Text(stringResource(R.string.claim_start))
                }
            }
            is ClaimState.Pending -> {
                HighlightTitle(stringResource(if (state.seconds == 0) R.string.claim_checking else R.string.claim_press_button))
                Text(stringResource(R.string.claim_seconds, state.seconds), style = MaterialTheme.typography.displayMedium)
                Text(stringResource(if (state.seconds == 0) R.string.claim_checking_body else R.string.claim_button_warning))
                LinearProgressIndicator(progress = { state.seconds / 60f }, modifier = Modifier.fillMaxWidth())
            }
            is ClaimState.Done -> {
                HighlightTitle(stringResource(R.string.claim_done))
                Text(stringResource(R.string.claim_done_body))
                Text(state.mac, style = LocalPowerkType.current.figures)
            }
            ClaimState.Expired -> {
                HighlightTitle(stringResource(R.string.claim_expired))
                Text(stringResource(R.string.claim_expired_body))
                Button(onClick = onReset) { Text(stringResource(R.string.try_again)) }
            }
        }
        if (busy) LinearProgressIndicator(Modifier.fillMaxWidth())
        error?.let { ErrorBanner(it) }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun StripManagementSheet(strip: Strip, onDismiss: () -> Unit, onChanged: () -> Unit) {
    var page by remember { mutableStateOf("menu") }
    var confirm by remember { mutableStateOf(false) }
    val work = rememberAccountWork()
    ModalBottomSheet(onDismissRequest = onDismiss, containerColor = MaterialTheme.colorScheme.background,
        sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)) {
        when (page) {
            "settings" -> StripSettingsPanel(strip)
            "people" -> PeoplePanel(strip, onChanged = { onChanged(); onDismiss() })
            else -> Column(Modifier.fillMaxWidth().verticalScroll(rememberScrollState()).padding(18.dp),
                verticalArrangement = Arrangement.spacedBy(14.dp)) {
                HighlightTitle(strip.displayName)
                RoleBadge(strip.role)
                OutlinedButton(onClick = { page = "settings" }, modifier = Modifier.fillMaxWidth()) { Text(stringResource(R.string.strip_settings)) }
                if (strip.role.canManage) OutlinedButton(onClick = { page = "people" }, modifier = Modifier.fillMaxWidth()) { Text(stringResource(R.string.people)) }
                TextButton(enabled = !work.busy, onClick = { confirm = true }) {
                    Text(stringResource(if (strip.role.canManage) R.string.unclaim else R.string.leave_strip))
                }
                WorkStatus(work)
            }
        }
        if (page != "menu") TextButton(onClick = { page = "menu" }, modifier = Modifier.padding(horizontal = 18.dp)) { Text(stringResource(R.string.back)) }
        Spacer(Modifier.height(18.dp))
    }
    if (confirm) ConfirmStripAction(strip, work.busy, work.error, { confirm = false }) {
        work.run {
            if (strip.role.canManage) AccountApi.unclaim(work.connection, strip.mac) else AccountApi.leave(work.connection, strip.mac)
            if (work.current()) { onChanged(); onDismiss() }
        }
    }
}

@Composable
private fun ConfirmStripAction(strip: Strip, busy: Boolean, error: String?, onDismiss: () -> Unit, onConfirm: () -> Unit) {
    var typed by remember { mutableStateOf("") }
    AlertDialog(onDismissRequest = { if (!busy) onDismiss() },
        title = { Text(stringResource(if (strip.role.canManage) R.string.unclaim else R.string.leave_strip)) },
        text = { Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text(stringResource(if (strip.role.canManage) R.string.unclaim_body else R.string.leave_body, strip.displayName))
            if (strip.role.canManage) Field(typed, { typed = it }, R.string.confirm_strip_name)
            error?.let { ErrorBanner(it) }
        } }, confirmButton = {
            TextButton(enabled = !busy && (!strip.role.canManage || typed == strip.displayName), onClick = onConfirm) {
                Text(stringResource(if (strip.role.canManage) R.string.unclaim else R.string.leave_strip))
            }
        }, dismissButton = { TextButton(enabled = !busy, onClick = onDismiss) { Text(stringResource(R.string.cancel)) } })
}

@Composable
fun PeoplePanel(strip: Strip, fixture: List<StripMember>? = null, onChanged: () -> Unit = {}) {
    val work = rememberAccountWork()
    val resources = LocalResources.current
    var people by remember { mutableStateOf(fixture.orEmpty()) }
    var transfer by remember { mutableStateOf<StripMember?>(null) }
    suspend fun load() {
        val result = AccountApi.people(work.connection, strip.mac)
        if (work.current()) people = result
    }
    LaunchedEffect(strip.mac) { if (fixture == null) work.run { load() } }
    PeopleContent(people, work.busy, work.error, work.status, onShare = { phone, role ->
        work.run {
            AccountApi.share(work.connection, strip.mac, phone, role)
            load()
            if (work.current()) work.status = resources.getString(R.string.share_result)
        }
    }, onRole = { member, role -> work.run { AccountApi.role(work.connection, strip.mac, member.userId, role); load() } },
        onRemove = { member -> work.run { AccountApi.remove(work.connection, strip.mac, member.userId); load() } },
        onTransfer = { transfer = it })
    transfer?.let { member ->
        AlertDialog(onDismissRequest = { if (!work.busy) transfer = null },
            title = { Text(stringResource(R.string.transfer_ownership)) }, text = {
                Column { Text(stringResource(R.string.transfer_body, member.phone)); work.error?.let { ErrorBanner(it) } }
            }, confirmButton = {
                TextButton(enabled = !work.busy, onClick = {
                    work.run { AccountApi.transfer(work.connection, strip.mac, member.phone); if (work.current()) onChanged() }
                }) { Text(stringResource(R.string.transfer_ownership)) }
            }, dismissButton = { TextButton(enabled = !work.busy, onClick = { transfer = null }) { Text(stringResource(R.string.cancel)) } })
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
fun PeopleContent(people: List<StripMember>, busy: Boolean = false, error: String? = null, status: String? = null,
    onShare: (String, StripRole) -> Unit = { _, _ -> }, onRole: (StripMember, StripRole) -> Unit = { _, _ -> },
    onRemove: (StripMember) -> Unit = {}, onTransfer: (StripMember) -> Unit = {}) {
    var phone by remember { mutableStateOf("") }
    var role by remember { mutableStateOf(StripRole.Control) }
    Column(Modifier.fillMaxWidth().verticalScroll(rememberScrollState()).padding(18.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        HighlightTitle(stringResource(R.string.people))
        Text(stringResource(R.string.share_hint))
        PhoneField(phone, { phone = it }, !busy)
        RoleChoice(role, !busy) { role = it }
        Button(enabled = phone.isNotBlank() && !busy, onClick = { onShare(phone, role) }) { Text(stringResource(R.string.share_strip)) }
        if (busy) LinearProgressIndicator(Modifier.fillMaxWidth())
        error?.let { ErrorBanner(it) }
        status?.let { Text(it) }
        people.forEach { member -> key(member.userId) {
            DashedDivider()
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(member.phone, Modifier.weight(1f), style = LocalPowerkType.current.figures)
                RoleBadge(member.role)
            }
            if (!member.role.canManage) {
                RoleChoice(member.role, !busy) { onRole(member, it) }
                FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    TextButton(enabled = !busy, onClick = { onRemove(member) }) { Text(stringResource(R.string.remove_person)) }
                    TextButton(enabled = !busy, onClick = { onTransfer(member) }) { Text(stringResource(R.string.transfer_ownership)) }
                }
            }
        } }
    }
}

@Composable
private fun RoleChoice(role: StripRole, enabled: Boolean, onRole: (StripRole) -> Unit) {
    SingleChoiceSegmentedButtonRow(Modifier.fillMaxWidth()) {
        listOf(StripRole.Control, StripRole.Viewer).forEach { choice ->
            SegmentedButton(selected = role == choice, onClick = { onRole(choice) }, enabled = enabled,
                shape = Wobble2, colors = paperSegmentColors()) { Text(stringResource(choice.label)) }
        }
    }
}

@Composable
fun StripSettingsPanel(strip: Strip, fixture: ServerSettings? = null) {
    val work = rememberAccountWork()
    val resources = LocalResources.current
    var settings by remember { mutableStateOf(fixture) }
    fun load() = work.run {
        val result = AccountApi.stripSettings(work.connection, strip.mac)
        if (work.current()) settings = result
    }
    LaunchedEffect(strip.mac) { if (fixture == null) load() }
    Column(Modifier.fillMaxWidth().verticalScroll(rememberScrollState()).padding(18.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
        HighlightTitle(stringResource(R.string.strip_settings))
        Text(strip.displayName, style = MaterialTheme.typography.titleMedium)
        WorkStatus(work)
        if (settings == null && !work.busy) TextButton(onClick = ::load) { Text(stringResource(R.string.try_again)) }
        settings?.let { s -> StripSettingsForm(s, strip.role.canManage, work.busy) { body ->
            work.run {
                val result = AccountApi.saveStripSettings(work.connection, strip.mac, body)
                if (work.current()) { settings = result; work.status = resources.getString(R.string.saved) }
            }
        } }
    }
}

@Composable
fun StripSettingsForm(settings: ServerSettings, editable: Boolean, busy: Boolean = false, onSave: (JSONObject) -> Unit = {}) {
    var currency by remember(settings) { mutableStateOf(settings.currency) }
    var price by remember(settings) { mutableStateOf(settings.priceKwh.toString()) }
    var budget by remember(settings) { mutableStateOf(settings.budget?.toString().orEmpty()) }
    var temp by remember(settings) { mutableStateOf(settings.tempMaxC.toString()) }
    var power by remember(settings) { mutableStateOf(settings.powerMaxW.toString()) }
    Column(verticalArrangement = Arrangement.spacedBy(14.dp)) {
        if (!editable) Text(stringResource(R.string.settings_owner_only), style = MaterialTheme.typography.bodySmall)
        Field(currency, { currency = it.take(8) }, R.string.currency, readOnly = !editable, enabled = !busy)
        Field(price, { price = it }, R.string.price_kwh, numeric = true, readOnly = !editable, enabled = !busy)
        Field(budget, { budget = it }, R.string.monthly_budget, numeric = true, readOnly = !editable, enabled = !busy)
        Text(stringResource(R.string.budget_hint), style = MaterialTheme.typography.bodySmall)
        Field(temp, { temp = it }, R.string.max_temp, numeric = true, readOnly = !editable, enabled = !busy)
        Field(power, { power = it }, R.string.max_power, numeric = true, readOnly = !editable, enabled = !busy)
        val pv = price.apiDouble(); val bv = budget.apiDouble(); val tv = temp.apiDouble(); val wv = power.apiDouble()
        val valid = currency.isNotBlank() && pv != null && pv in 0.0..1000.0 &&
            (budget.isBlank() || bv != null && bv.isFinite() && bv > 0) &&
            tv != null && tv in 30.0..120.0 && wv != null && wv in 100.0..10000.0
        if (editable) {
            if (!valid) Text(stringResource(R.string.settings_validation), color = MaterialTheme.colorScheme.error)
            Button(enabled = valid && !busy, onClick = {
                onSave(JSONObject().put("currency", currency).put("price_kwh", pv)
                    .put("budget", bv ?: JSONObject.NULL).put("temp_max_c", tv).put("power_max_w", wv))
            }, modifier = Modifier.fillMaxWidth()) { Text(stringResource(R.string.save)) }
        }
    }
}
