package com.powerk.app

import android.os.Bundle
import android.content.Intent
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.setValue
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge

class MainActivity : ComponentActivity() {
    private var requestedTab by mutableIntStateOf(0)
    private var navigationRequest by mutableIntStateOf(0)
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        Server.init(this)
        Lang.init(this)
        Lang.applyStored(this)
        requestedTab = notificationInitialTab(intent)
        setContent {
            PowerkTheme {
                PowerkApp(requestedTab, navigationRequest)
            }
        }
    }
    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        requestedTab = notificationInitialTab(intent)
        navigationRequest++
    }
    override fun onStart() {
        super.onStart()
        LiveFeed.started(this, this)
        PushDevices.connectionChanged()
    }
    override fun onStop() {
        LiveFeed.stopped(this)
        super.onStop()
    }
    companion object { const val EXTRA_TAB = "com.powerk.app.TAB" }
}
