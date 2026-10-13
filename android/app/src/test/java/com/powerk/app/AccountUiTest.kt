package com.powerk.app

import android.content.Context
import androidx.compose.foundation.layout.*
import androidx.compose.material3.Surface
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalLayoutDirection
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.SemanticsActions
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.text.TextLayoutResult
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.unit.LayoutDirection
import androidx.compose.ui.unit.dp
import androidx.test.core.app.ApplicationProvider
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode

@RunWith(RobolectricTestRunner::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
@Config(sdk = [35], qualifiers = "en-rUS-w412dp-h1000dp-mdpi")
class AccountUiTest {
    @get:Rule val compose = createComposeRule()
    @Test fun viewerAndOfflineSwitchesAnnounceDisabledAndIgnoreTaps() {
        var strip by mutableStateOf(visualSnapshot(true).strips.single().copy(role = StripRole.Viewer))
        var commands = 0
        compose.setContent { PowerkTheme(ThemeChoice()) { Surface(Modifier.fillMaxSize()) {
            Column(Modifier.padding(18.dp)) {
                StripCard(strip, false, "EGP", emptyMap(), { _, _, _ -> commands++ }, {})
            }
        } } }
        val switches = SemanticsMatcher.expectValue(SemanticsProperties.Role, Role.Switch)
        for (offline in listOf(false, true)) {
            if (offline) compose.runOnIdle { strip = strip.copy(role = StripRole.Owner, online = false) }
            compose.onAllNodes(switches).assertCountEquals(4)
            repeat(4) { index ->
                val node = compose.onAllNodes(switches)[index]
                node.assertIsNotEnabled()
                if (index == 0 || index == 3) node.assertIsOn() else node.assertIsOff()
                node.performTouchInput { click() }
            }
            compose.runOnIdle { assertEquals(0, commands) }
        }
    }

    @Config(qualifiers = "en-rUS-w360dp-h1000dp-mdpi")
    @Test fun roleAndOnlineChipsFitWithoutClippingAt360dpEnglish() = badgesFit(english = true)

    @Config(qualifiers = "ar-rEG-w360dp-h1000dp-mdpi")
    @Test fun roleAndOnlineChipsFitWithoutClippingAt360dpArabic() = badgesFit(english = false)

    private fun badgesFit(english: Boolean) {
        val strip = visualSnapshot(english).strips.single()
        var role by mutableStateOf(StripRole.Owner)
        var theme by mutableStateOf(AppTheme.Kraft)
        val resources = ApplicationProvider.getApplicationContext<Context>().resources
        compose.setContent { PowerkTheme(ThemeChoice(theme)) {
            CompositionLocalProvider(LocalLayoutDirection provides if (english) LayoutDirection.Ltr else LayoutDirection.Rtl) {
                Surface(Modifier.fillMaxSize()) { Column(Modifier.padding(18.dp)) {
                    StripCard(strip.copy(role = role), false, "EGP", emptyMap(), { _, _, _ -> }, {}, onManage = {})
                } }
            }
        } }
        for (choice in AppTheme.entries) for (badge in StripRole.entries) {
            compose.runOnIdle { role = badge; theme = choice }
            val roleNode = compose.onNodeWithText(resources.getString(badge.label), useUnmergedTree = true)
            val onlineNode = compose.onNodeWithText(resources.getString(R.string.state_online), useUnmergedTree = true)
            val roleBounds = roleNode.fetchSemanticsNode().boundsInRoot
            val onlineBounds = onlineNode.fetchSemanticsNode().boundsInRoot
            val root = compose.onRoot().fetchSemanticsNode().boundsInRoot
            assertTrue("Role badge has its own row below the status chip", roleBounds.top >= onlineBounds.bottom)
            for (node in listOf(roleNode, onlineNode)) {
                val bounds = node.fetchSemanticsNode().boundsInRoot
                assertTrue(bounds.left >= root.left && bounds.right <= root.right)
                val layouts = mutableListOf<TextLayoutResult>()
                node.performSemanticsAction(SemanticsActions.GetTextLayoutResult) { it(layouts) }
                assertEquals(1, layouts.size)
                val layout = layouts.single()
                val label = "${layout.layoutInput.text.text} ($choice, $badge)"
                assertEquals("$label stays on one line", 1, layout.lineCount)
                assertFalse("$label must not be ellipsized", layout.isLineEllipsized(0))
                assertEquals("$label must include every character", layout.layoutInput.text.length, layout.getLineEnd(0))
                // multiParagraph.width is the available width, not the text width, so compare the drawn line instead.
                val lineWidth = layout.getLineRight(0) - layout.getLineLeft(0)
                assertTrue("$label must fit: box=${layout.size}, line=$lineWidth",
                    lineWidth <= layout.size.width + 0.5f && layout.multiParagraph.height <= layout.size.height + 0.5f)
            }
        }
    }
    @Test fun targetPickerExcludesViewersAndOffersControlStrips() {
        val strip = visualSnapshot(true).strips.single()
        val viewer = strip.copy(mac = "VIEWER", name = "Read only", role = StripRole.Viewer)
        val controller = strip.copy(mac = "CONTROL", name = "Can control", role = StripRole.Control)
        compose.setContent { PowerkTheme(ThemeChoice()) { Surface { TargetList(listOf(viewer, controller)) {} } } }
        compose.onNodeWithText("READ ONLY").assertDoesNotExist()
        compose.onNodeWithText("CAN CONTROL").assertExists()
        compose.onNodeWithText("CONTROL").assertExists()
    }
    @Test fun readOnlySettingsHaveNoSaveAction() {
        compose.setContent { PowerkTheme(ThemeChoice()) { Surface {
            StripSettingsForm(ServerSettings("EGP", 2.14, 500.0, 60.0, 3500.0), editable = false)
        } } }
        compose.onNodeWithText("Only the owner can change these settings.").assertExists()
        compose.onNodeWithText("Save").assertDoesNotExist()
    }
    @Test fun registerShowsRulesAndRequiresPhoneAndPassword() {
        compose.setContent { PowerkTheme(ThemeChoice()) { Surface { AuthForm(register = true) } } }
        compose.onNodeWithText("Use 10–128 characters. Avoid common passwords and your phone number.").assertExists()
        compose.onNode(hasText("Create account") and hasClickAction()).assertIsNotEnabled()
        compose.onNodeWithText("Phone number").performTextInput("01001234567")
        compose.onNodeWithText("Password").performTextInput("uncommon phrase 2026")
        compose.onNode(hasText("Create account") and hasClickAction()).assertIsEnabled()
    }
}
