package com.powerk.app

import android.content.res.Resources
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalResources
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/** Shared busy/error behavior; no request survives into another connection's UI state. */
@Stable
internal class AccountWork(val connection: ServerConnection, private val scope: CoroutineScope,
    private val resources: Resources) {
    var busy by mutableStateOf(false)
        private set
    var error by mutableStateOf<String?>(null)
        private set
    var status by mutableStateOf<String?>(null)
    fun current() = connection.isCurrent(Server.connection)
    fun run(block: suspend () -> Unit) {
        if (busy || !current()) return
        busy = true; error = null; status = null
        scope.launch {
            try { block() }
            catch (e: Exception) {
                if (e is kotlinx.coroutines.CancellationException) throw e
                if (current()) error = uiError(resources, e)
            } finally { if (current()) busy = false }
        }
    }
}

@Composable
internal fun rememberAccountWork(): AccountWork {
    val scope = rememberCoroutineScope()
    val resources = LocalResources.current
    val connection = Server.connection
    return remember(connection, resources) { AccountWork(connection, scope, resources) }
}

@Composable
internal fun WorkStatus(work: AccountWork) {
    if (work.busy) LinearProgressIndicator(Modifier.fillMaxWidth())
    work.error?.let { ErrorBanner(it) }
    work.status?.let { Text(it, style = MaterialTheme.typography.bodyMedium) }
}

@Composable
internal fun AccountDialog(title: Int, onDismiss: () -> Unit, content: @Composable () -> Unit) {
    Dialog(onDismissRequest = onDismiss, properties = DialogProperties(usePlatformDefaultWidth = false)) {
        Surface(Modifier.fillMaxSize().safeDrawingPadding().imePadding(), color = MaterialTheme.colorScheme.background) {
            Column {
                Row(Modifier.fillMaxWidth().padding(horizontal = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                    IconButton(onClick = onDismiss) { Icon(Icons.AutoMirrored.Filled.ArrowBack, stringResource(R.string.back)) }
                    Text(markerText(stringResource(title)), style = MaterialTheme.typography.titleLarge)
                }
                Box(Modifier.weight(1f)) { content() }
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SignInScreen() {
    var register by remember { mutableStateOf(false) }
    var settings by remember { mutableStateOf(false) }
    val work = rememberAccountWork()
    val context = LocalContext.current
    val resources = LocalResources.current
    BackHandler(settings || register) { if (settings) settings = false else register = false }
    Scaffold(topBar = {
        TopAppBar(title = { Text("POWERK", style = LocalPowerkType.current.brand) }, actions = {
            TextButton(onClick = { Lang.set(context, if (resources.configuration.locales[0].language == "ar") "en" else "ar") }) {
                Text(if (resources.configuration.locales[0].language == "ar") "EN" else "العربية")
            }
            IconButton(onClick = { settings = !settings }) { Icon(Icons.Default.Settings, stringResource(R.string.open_settings)) }
        })
    }) { padding ->
        Box(Modifier.padding(padding)) {
            if (settings) SettingsScreen(null)
            else AuthForm(register, work.busy, work.error, Server.base,
                onMode = { register = !register }, onServer = { settings = true }) { phone, password ->
                work.run { AuthClient.login(work.connection, phone, password, register) }
            }
        }
    }
}

@Composable
fun AuthForm(register: Boolean, busy: Boolean = false, error: String? = null,
    server: String = DEFAULT_SERVER_URL, onMode: () -> Unit = {}, onServer: () -> Unit = {},
    onSubmit: (String, String) -> Unit = { _, _ -> }) {
    var phone by remember(register) { mutableStateOf("") }
    var password by remember(register) { mutableStateOf("") }
    Column(Modifier.fillMaxSize().imePadding().verticalScroll(rememberScrollState()).padding(18.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp)) {
        HighlightTitle(stringResource(if (register) R.string.create_account else R.string.sign_in))
        Text(stringResource(R.string.account_intro))
        PaperCard(Modifier.fillMaxWidth()) {
            Column(Modifier.padding(18.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
                PhoneField(phone, { phone = it }, enabled = !busy)
                PasswordField(password, { password = it }, R.string.password, enabled = !busy)
                if (register) Text(stringResource(R.string.password_rules), style = MaterialTheme.typography.bodySmall)
                if (server.startsWith("http:")) ErrorBanner(stringResource(R.string.lan_http_warning))
                if (busy) LinearProgressIndicator(Modifier.fillMaxWidth())
                error?.let { ErrorBanner(it) }
                Button(enabled = !busy && phone.isNotBlank() && Character.codePointCount(password, 0, password.length) in (if (register) 10 else 1)..128,
                    onClick = { onSubmit(phone, password) }, modifier = Modifier.fillMaxWidth()) {
                    Text(stringResource(if (register) R.string.create_account else R.string.sign_in))
                }
                TextButton(enabled = !busy, onClick = onMode) {
                    Text(stringResource(if (register) R.string.have_account else R.string.need_account))
                }
            }
        }
        Text(server, style = LocalPowerkType.current.figures)
        TextButton(enabled = !busy, onClick = onServer) { Text(stringResource(R.string.change_server)) }
    }
}

@Composable
internal fun PhoneField(value: String, change: (String) -> Unit, enabled: Boolean = true) {
    OutlinedTextField(value, change, label = { Text(stringResource(R.string.phone)) },
        supportingText = { Text(stringResource(R.string.phone_hint)) }, singleLine = true,
        enabled = enabled, keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Phone),
        textStyle = LocalPowerkType.current.figures.copy(textDirection = androidx.compose.ui.text.style.TextDirection.Ltr),
        modifier = Modifier.fillMaxWidth())
}

@Composable
internal fun PasswordField(value: String, change: (String) -> Unit, label: Int, enabled: Boolean = true,
    maxLength: Int = 128) {
    var visible by remember { mutableStateOf(false) }
    OutlinedTextField(value, { text ->
        change(if (Character.codePointCount(text, 0, text.length) <= maxLength) text else text.substring(0, Character.offsetByCodePoints(text, 0, maxLength)))
    }, label = { Text(stringResource(label)) },
        singleLine = true, enabled = enabled, modifier = Modifier.fillMaxWidth(),
        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
        visualTransformation = if (visible) VisualTransformation.None else PasswordVisualTransformation(),
        trailingIcon = { TextButton(onClick = { visible = !visible }) {
            Text(stringResource(if (visible) R.string.hide_password else R.string.show_password))
        } })
}

@Composable
fun ConnectionSection() {
    var url by remember { mutableStateOf(Server.base) }
    var legacy by remember { mutableStateOf(Server.legacy) }
    var token by remember { mutableStateOf(Server.token) }
    val work = rememberAccountWork()
    val resources = LocalResources.current
    val context = LocalContext.current
    val valid = remember(url) { validateServerUrl(url) }
    PaperCard(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(18.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
            Text(markerText(stringResource(R.string.server_title)), style = MaterialTheme.typography.titleMedium)
            OutlinedTextField(url, { url = it }, label = { Text(stringResource(R.string.server_url)) },
                singleLine = true, enabled = !work.busy, modifier = Modifier.fillMaxWidth(),
                textStyle = LocalPowerkType.current.figures.copy(textDirection = androidx.compose.ui.text.style.TextDirection.Ltr),
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri))
            if (valid == null) Text(stringResource(R.string.server_url_invalid), color = MaterialTheme.colorScheme.error)
            if (valid?.insecure == true) ErrorBanner(stringResource(R.string.lan_http_warning))
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(stringResource(R.string.legacy_advanced), Modifier.weight(1f))
                Switch(legacy, { legacy = it }, enabled = !work.busy, colors = paperSwitchColors(),
                    modifier = Modifier.semanticsLabel(stringResource(R.string.legacy_advanced)))
            }
            if (legacy) {
                Text(stringResource(R.string.legacy_hint), style = MaterialTheme.typography.bodySmall)
                PasswordField(token, { token = it }, R.string.field_token, !work.busy, maxLength = Int.MAX_VALUE)
            }
            WorkStatus(work)
            Button(enabled = valid != null && !work.busy, onClick = {
                work.run {
                    withContext(Dispatchers.IO) { Server.saveUrl(url, legacy, token) }
                    if (work.current()) work.status = resources.getString(R.string.saved)
                }
            }, modifier = Modifier.fillMaxWidth()) { Text(stringResource(R.string.save)) }
            OutlinedButton(onClick = {
                context.startActivity(android.content.Intent(android.content.Intent.ACTION_VIEW, android.net.Uri.parse(Server.base)))
            }, modifier = Modifier.fillMaxWidth()) { Text(stringResource(R.string.open_web_ui)) }
        }
    }
}

@Composable
fun AccountSection() {
    var page by remember { mutableStateOf<String?>(null) }
    val work = rememberAccountWork()
    PaperCard(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(18.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text(markerText(stringResource(R.string.account_title)), style = MaterialTheme.typography.titleMedium)
            Text(AuthClient.phone, style = LocalPowerkType.current.figures)
            TextButton(onClick = { page = "password" }, enabled = !work.busy) { Text(stringResource(R.string.change_password)) }
            TextButton(onClick = { page = "sessions" }, enabled = !work.busy) { Text(stringResource(R.string.active_sessions)) }
            OutlinedButton(onClick = { work.run { AuthClient.signOut(work.connection) } }, enabled = !work.busy) {
                Text(stringResource(R.string.sign_out))
            }
            WorkStatus(work)
        }
    }
    when (page) {
        "password" -> AccountDialog(R.string.change_password, { page = null }) { PasswordScreen() }
        "sessions" -> AccountDialog(R.string.active_sessions, { page = null }) { SessionsScreen() }
    }
}

@Composable
private fun PasswordScreen() {
    val work = rememberAccountWork()
    val resources = LocalResources.current
    var old by remember { mutableStateOf("") }
    var new by remember { mutableStateOf("") }
    Column(Modifier.verticalScroll(rememberScrollState()).padding(18.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
        PasswordField(old, { old = it }, R.string.current_password, !work.busy)
        PasswordField(new, { new = it }, R.string.new_password, !work.busy)
        Text(stringResource(R.string.password_rules))
        Text(stringResource(R.string.password_sessions_hint), style = MaterialTheme.typography.bodySmall)
        WorkStatus(work)
        Button(enabled = !work.busy && old.isNotEmpty() && Character.codePointCount(new, 0, new.length) in 10..128, onClick = {
            work.run {
                AccountApi.password(work.connection, old, new)
                if (work.current()) { old = ""; new = ""; work.status = resources.getString(R.string.saved) }
            }
        }) { Text(stringResource(R.string.save)) }
    }
}

@Composable
private fun SessionsScreen() {
    val work = rememberAccountWork()
    var sessions by remember { mutableStateOf<List<AccountSession>>(emptyList()) }
    fun load() = work.run {
        val result = AccountApi.sessions(work.connection)
        if (work.current()) sessions = result
    }
    LaunchedEffect(work) { load() }
    LazyColumn(contentPadding = PaddingValues(18.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
        item { WorkStatus(work); TextButton(enabled = !work.busy, onClick = ::load) { Text(stringResource(R.string.refresh)) } }
        items(sessions, key = { it.id }) { session ->
            PaperCard(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(18.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    if (session.current) Text(stringResource(R.string.this_session), style = MaterialTheme.typography.titleMedium)
                    Text(session.userAgent.ifBlank { stringResource(R.string.unknown_device) })
                    Text(session.ip, style = LocalPowerkType.current.figures)
                    Text(stringResource(R.string.session_created, serverLocalTime(session.createdAt, 0)))
                    Text(stringResource(R.string.session_used, serverLocalTime(session.lastUsedAt, 0)))
                    TextButton(enabled = !work.busy, onClick = {
                        work.run {
                            AccountApi.deleteSession(work.connection, session)
                            if (work.current()) sessions = sessions.filterNot { it.id == session.id }
                        }
                    }) { Text(stringResource(R.string.sign_out)) }
                }
            }
        }
    }
}
