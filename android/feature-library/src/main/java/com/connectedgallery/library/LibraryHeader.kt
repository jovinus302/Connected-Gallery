package com.connectedgallery.library

import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

@Composable fun LibraryHeader(count: Int, onConnect: () -> Unit, settings: @Composable () -> Unit) {
    Column(Modifier.fillMaxWidth().padding(start = 20.dp, end = 12.dp, top = 16.dp, bottom = 12.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text("CONNECTED GALLERY", style = MaterialTheme.typography.labelSmall, letterSpacing = 2.sp, color = MaterialTheme.colorScheme.primary)
                Spacer(Modifier.height(6.dp))
                Text("갤러리", style = MaterialTheme.typography.headlineLarge)
            }
            settings()
        }
        Spacer(Modifier.height(10.dp))
        Text("사진을 열고, 궁금한 대상을 눌러보세요.", style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Spacer(Modifier.height(16.dp))
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            Text("내 사진", style = MaterialTheme.typography.titleSmall)
            Text("  ·  ${count}장", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.weight(1f))
            FilledTonalButton(onClick = onConnect, contentPadding = PaddingValues(horizontal = 18.dp, vertical = 10.dp)) { Text("사진 연결") }
        }
    }
    HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
}
