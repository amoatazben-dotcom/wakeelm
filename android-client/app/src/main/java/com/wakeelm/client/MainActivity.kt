package com.wakeelm.client

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.viewModels
import com.wakeelm.client.ui.WorkspaceApp
import com.wakeelm.client.ui.WorkspaceViewModel
import dagger.hilt.android.AndroidEntryPoint

@AndroidEntryPoint class MainActivity: ComponentActivity() {
    private val model: WorkspaceViewModel by viewModels()
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent { WorkspaceApp(model) }
    }
}
