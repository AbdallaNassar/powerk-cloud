package com.powerk.app

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalLayoutDirection
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.unit.LayoutDirection
import androidx.compose.ui.unit.dp
import com.github.takahirom.roborazzi.captureRoboImage
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode

/** All fixtures are synthetic. No login, transport, clocks or token store run in visual tests. */
@RunWith(RobolectricTestRunner::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
@Config(sdk = [35], qualifiers = "en-rUS-w412dp-h1000dp-mdpi")
class AccountScreenshotTest {
    @get:Rule val compose = createComposeRule()

    @OptIn(ExperimentalMaterial3Api::class)
    private fun capture(screen: String, theme: AppTheme, arabic: Boolean = false) {
        val strip = visualSnapshot(!arabic).strips.single().copy(role = StripRole.Viewer)
        val people = listOf(StripMember(1, "+201001234567", StripRole.Owner, 1800000000),
            StripMember(2, "+201001234568", StripRole.Control, 1800000001))
        compose.setContent {
            PowerkTheme(ThemeChoice(theme)) {
                CompositionLocalProvider(LocalLayoutDirection provides if (arabic) LayoutDirection.Rtl else LayoutDirection.Ltr) {
                    if (screen == "people") {
                        ModalBottomSheet(onDismissRequest = {}, modifier = Modifier.testTag("account-shot"),
                            sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true),
                            containerColor = MaterialTheme.colorScheme.background) { PeopleContent(people) }
                    } else Surface(Modifier.fillMaxSize().testTag("account-shot")) {
                        when (screen) {
                            "login" -> AuthForm(false)
                            "register" -> AuthForm(true)
                            "empty" -> Box(Modifier.padding(18.dp)) { AddStripEmpty {} }
                            "claim" -> ClaimContent(ClaimState.Pending("synthetic-claim", 60000, 42))
                            "settings" -> Column(Modifier.verticalScroll(rememberScrollState()).padding(18.dp),
                                verticalArrangement = Arrangement.spacedBy(14.dp)) {
                                HighlightTitle(androidx.compose.ui.res.stringResource(R.string.strip_settings))
                                StripSettingsForm(ServerSettings("EGP", 2.14, 500.0, 60.0, 3500.0), true)
                            }
                            "viewer" -> Column(Modifier.verticalScroll(rememberScrollState()).padding(18.dp)) {
                                StripCard(strip, false, "EGP", emptyMap(), { _, _, _ -> }, {}, onManage = {})
                            }
                            "notifications" -> Column(Modifier.verticalScroll(rememberScrollState()).padding(18.dp),
                                verticalArrangement = Arrangement.spacedBy(14.dp)) {
                                HighlightTitle(androidx.compose.ui.res.stringResource(R.string.personal_notifications))
                                DevicePushStatus(false, true, true, true, false,
                                    NotificationPreferences("", "", false, emptyMap(), true, 1), {})
                            }
                        }
                    }
                }
            }
        }
        compose.waitForIdle()
        if (screen == "viewer") {
            val resources = androidx.test.core.app.ApplicationProvider.getApplicationContext<android.content.Context>().resources
            compose.onAllNodesWithContentDescription(resources.getString(R.string.rename)).assertCountEquals(0)
            val switches = androidx.compose.ui.test.SemanticsMatcher.expectValue(
                androidx.compose.ui.semantics.SemanticsProperties.Role, androidx.compose.ui.semantics.Role.Switch)
            compose.onAllNodes(switches).assertCountEquals(4)
            repeat(4) { compose.onAllNodes(switches)[it].assertIsNotEnabled() }
            compose.onAllNodes(hasClickAction() and isEnabled()).fetchSemanticsNodes().also {
                org.junit.Assert.assertEquals("Only Manage strip may be enabled for a viewer", 1, it.size)
            }
        }
        compose.onNodeWithTag("account-shot").captureRoboImage(
            "build/outputs/roborazzi/account_${screen}_${if (arabic) "ar" else "en"}_${theme.name.lowercase()}.png")
    }
    @Test fun loginKraftEN() = capture("login", AppTheme.Kraft, false)
    @Config(qualifiers = "ar-rEG-w412dp-h1000dp-mdpi")
    @Test fun loginKraftAR() = capture("login", AppTheme.Kraft, true)
    @Test fun loginNightEN() = capture("login", AppTheme.Night, false)
    @Config(qualifiers = "ar-rEG-w412dp-h1000dp-mdpi")
    @Test fun loginNightAR() = capture("login", AppTheme.Night, true)
    @Test fun registerKraftEN() = capture("register", AppTheme.Kraft, false)
    @Config(qualifiers = "ar-rEG-w412dp-h1000dp-mdpi")
    @Test fun registerKraftAR() = capture("register", AppTheme.Kraft, true)
    @Test fun registerNightEN() = capture("register", AppTheme.Night, false)
    @Config(qualifiers = "ar-rEG-w412dp-h1000dp-mdpi")
    @Test fun registerNightAR() = capture("register", AppTheme.Night, true)
    @Test fun emptyKraftEN() = capture("empty", AppTheme.Kraft, false)
    @Config(qualifiers = "ar-rEG-w412dp-h1000dp-mdpi")
    @Test fun emptyKraftAR() = capture("empty", AppTheme.Kraft, true)
    @Test fun emptyNightEN() = capture("empty", AppTheme.Night, false)
    @Config(qualifiers = "ar-rEG-w412dp-h1000dp-mdpi")
    @Test fun emptyNightAR() = capture("empty", AppTheme.Night, true)
    @Test fun claimKraftEN() = capture("claim", AppTheme.Kraft, false)
    @Config(qualifiers = "ar-rEG-w412dp-h1000dp-mdpi")
    @Test fun claimKraftAR() = capture("claim", AppTheme.Kraft, true)
    @Test fun claimNightEN() = capture("claim", AppTheme.Night, false)
    @Config(qualifiers = "ar-rEG-w412dp-h1000dp-mdpi")
    @Test fun claimNightAR() = capture("claim", AppTheme.Night, true)
    @Test fun peopleKraftEN() = capture("people", AppTheme.Kraft, false)
    @Config(qualifiers = "ar-rEG-w412dp-h1000dp-mdpi")
    @Test fun peopleKraftAR() = capture("people", AppTheme.Kraft, true)
    @Test fun peopleNightEN() = capture("people", AppTheme.Night, false)
    @Config(qualifiers = "ar-rEG-w412dp-h1000dp-mdpi")
    @Test fun peopleNightAR() = capture("people", AppTheme.Night, true)
    @Test fun settingsKraftEN() = capture("settings", AppTheme.Kraft, false)
    @Config(qualifiers = "ar-rEG-w412dp-h1000dp-mdpi")
    @Test fun settingsKraftAR() = capture("settings", AppTheme.Kraft, true)
    @Test fun settingsNightEN() = capture("settings", AppTheme.Night, false)
    @Config(qualifiers = "ar-rEG-w412dp-h1000dp-mdpi")
    @Test fun settingsNightAR() = capture("settings", AppTheme.Night, true)
    @Test fun viewerKraftEN() = capture("viewer", AppTheme.Kraft, false)
    @Config(qualifiers = "ar-rEG-w412dp-h1000dp-mdpi")
    @Test fun viewerKraftAR() = capture("viewer", AppTheme.Kraft, true)
    @Test fun viewerNightEN() = capture("viewer", AppTheme.Night, false)
    @Config(qualifiers = "ar-rEG-w412dp-h1000dp-mdpi")
    @Test fun viewerNightAR() = capture("viewer", AppTheme.Night, true)
    @Test fun notificationsKraftEN() = capture("notifications", AppTheme.Kraft, false)
    @Config(qualifiers = "ar-rEG-w412dp-h1000dp-mdpi")
    @Test fun notificationsKraftAR() = capture("notifications", AppTheme.Kraft, true)
    @Test fun notificationsNightEN() = capture("notifications", AppTheme.Night, false)
    @Config(qualifiers = "ar-rEG-w412dp-h1000dp-mdpi")
    @Test fun notificationsNightAR() = capture("notifications", AppTheme.Night, true)
}
