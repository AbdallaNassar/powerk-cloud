package com.powerk.baselineprofile

import android.os.SystemClock
import androidx.benchmark.macro.MacrobenchmarkScope
import androidx.benchmark.macro.junit4.BaselineProfileRule
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.filters.LargeTest
import androidx.test.uiautomator.By
import androidx.test.uiautomator.BySelector
import androidx.test.uiautomator.Direction
import androidx.test.uiautomator.UiDevice
import androidx.test.uiautomator.Until
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import java.util.regex.Pattern

/** Run with the app language set to English and a reachable, populated test server. */
@RunWith(AndroidJUnit4::class)
@LargeTest
class BaselineProfileGenerator {
    @get:Rule
    val baselineProfile = BaselineProfileRule()

    @Test
    fun startup() = baselineProfile.collect(
        packageName = PACKAGE_NAME,
        includeInStartupProfile = true,
    ) {
        openOutlets()
    }

    @Test
    fun tabsAndScrolling() = baselineProfile.collect(packageName = PACKAGE_NAME) {
        openOutlets()
        device.scrollCurrentScreen()

        // The Outlets screen is labelled "Plugs" in the existing English UI.
        for (tab in listOf("Rules", "Energy", "Alerts")) {
            checkNotNull(device.wait(Until.findObject(By.text(tab)), TIMEOUT_MS)) {
                "Missing $tab tab; set the app language to English before generating profiles."
            }.click()
            check(device.wait(Until.hasObject(By.text(tab.uppercase())), TIMEOUT_MS)) {
                "$tab screen did not appear."
            }
            val content: BySelector = when (tab) {
                "Rules" -> By.desc("Rule enabled")
                "Energy" -> By.desc("Energy use by time bucket")
                else -> By.text(Pattern.compile("Activity|Warning|Alert"))
            }
            device.awaitContent(content, tab)
            // Include the complete existing tab transition before scrolling.
            SystemClock.sleep(350)
            device.waitForIdle()
            device.scrollCurrentScreen()
        }

        checkNotNull(device.wait(Until.findObject(By.desc("Open settings")), TIMEOUT_MS)).click()
        check(device.wait(Until.hasObject(By.text("SETTINGS")), TIMEOUT_MS))
        SystemClock.sleep(1_000)
        device.scrollCurrentScreen()
        device.pressBack()
        checkNotNull(device.wait(Until.findObject(By.text("Plugs")), TIMEOUT_MS)).click()
        device.waitForIdle()
    }

    private fun MacrobenchmarkScope.openOutlets() {
        pressHome()
        startActivityAndWait()
        check(device.wait(Until.hasObject(By.text("Plugs")), TIMEOUT_MS)) {
            "Outlets navigation did not appear; set the app language to English."
        }
        // The splash overlays an already-composed screen for 1.1 s plus a 420 ms exit.
        SystemClock.sleep(1_600)
        check(device.wait(Until.hasObject(By.text("Using now")), TIMEOUT_MS)) {
            "Outlets did not load; configure a reachable server with at least one strip."
        }
        device.waitForIdle()
    }

    private fun UiDevice.scrollCurrentScreen() {
        // A short list may expose no scrollable node. Never tap a control to
        // manufacture content; a populated server gives the best profile coverage.
        repeat(3) {
            val list = findObject(By.scrollable(true)) ?: return@repeat
            list.setGestureMargin(displayWidth / 5)
            list.scroll(Direction.DOWN, 0.8f)
            waitForIdle()
        }
        repeat(3) {
            val list = findObject(By.scrollable(true)) ?: return@repeat
            list.setGestureMargin(displayWidth / 5)
            list.scroll(Direction.UP, 0.8f)
            waitForIdle()
        }
    }

    private fun UiDevice.awaitContent(selector: BySelector, screen: String) {
        val deadline = SystemClock.uptimeMillis() + TIMEOUT_MS
        while (SystemClock.uptimeMillis() < deadline) {
            if (wait(Until.hasObject(selector), 500)) return
            // The Energy chart can start below the fold (small phones/many strips).
            findObject(By.scrollable(true))?.let { list ->
                list.setGestureMargin(displayWidth / 5)
                list.scroll(Direction.DOWN, 0.5f)
            }
        }
        error("$screen content did not load; use a server with strips, rules, history and events.")
    }

    private companion object {
        const val PACKAGE_NAME = "com.powerk.app"
        const val TIMEOUT_MS = 20_000L
    }
}
