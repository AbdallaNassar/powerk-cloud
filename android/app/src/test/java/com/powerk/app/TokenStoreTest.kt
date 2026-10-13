package com.powerk.app

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import javax.crypto.KeyGenerator

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35])
class TokenStoreTest {
    @Test fun uncertainRefreshDeadlineAndSpentRetrySurviveEncryptedStoreReload() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val prefs = context.getSharedPreferences("test-uncertain-vault", Context.MODE_PRIVATE)
        val key = KeyGenerator.getInstance("AES").apply { init(256) }.generateKey()
        val original = Credentials("https://example.test", 7, "+201001234567", "access", "refresh",
            refreshUncertainSince = 1800000000000L)
        for (value in listOf(original, original.copy(refreshRetryUsed = true))) {
            EncryptedTokenStore(prefs) { key }.write(value)
            assertEquals(value, EncryptedTokenStore(prefs) { key }.read())
        }
        EncryptedTokenStore(prefs) { key }.write(null)
        assertNull(EncryptedTokenStore(prefs) { key }.read())
    }
    @Test fun aesGcmRoundTripRandomIvAndWipe() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val prefs = context.getSharedPreferences("test-vault", Context.MODE_PRIVATE)
        val key = KeyGenerator.getInstance("AES").apply { init(256) }.generateKey()
        val vault = EncryptedTokenStore(prefs) { key }
        val pair = Credentials("https://example.test", 7, "+201001234567", "access-secret", "refresh-secret")
        vault.write(pair)
        val ciphertext = prefs.getString("session", "")!!
        assertFalse(ciphertext.contains("access-secret"))
        assertFalse(ciphertext.contains("refresh-secret"))
        assertEquals(pair, EncryptedTokenStore(prefs) { key }.read())
        vault.write(pair)
        assertNotEquals(ciphertext, prefs.getString("session", ""))
        vault.write(null)
        assertNull(vault.read())
        assertFalse(prefs.contains("session"))
    }
    @Test fun tamperingOrKeyLossFailsClosedAndRemovesCiphertext() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val prefs = context.getSharedPreferences("test-vault", Context.MODE_PRIVATE)
        val key = KeyGenerator.getInstance("AES").generateKey()
        val vault = EncryptedTokenStore(prefs) { key }
        vault.write(Credentials("https://example.test", 1, "phone", "access", "refresh"))
        val otherKey = KeyGenerator.getInstance("AES").generateKey()
        assertNull(EncryptedTokenStore(prefs) { otherKey }.read())
        assertFalse(prefs.contains("session"))
        prefs.edit().putString("session", "broken ciphertext").commit()
        assertNull(vault.read())
        assertFalse(prefs.contains("session"))
    }
    @Test fun legacyTokenIsEncryptedAndCanBeWiped() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val prefs = context.getSharedPreferences("test-vault", Context.MODE_PRIVATE)
        val key = KeyGenerator.getInstance("AES").generateKey()
        val vault = EncryptedTokenStore(prefs) { key }
        vault.saveLegacy("shared-secret")
        assertEquals("shared-secret", vault.legacyToken())
        assertFalse(prefs.getString("legacy", "")!!.contains("shared-secret"))
        vault.saveLegacy("")
        assertEquals("", vault.legacyToken())
        assertFalse(prefs.contains("legacy"))
    }
}
