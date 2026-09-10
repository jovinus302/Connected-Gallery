package com.connectedgallery.library

import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.connectedgallery.coreui.GalleryBrand

@Composable fun LibraryHeader(count: Int, onConnect: () -> Unit, settings: @Composable () -> Unit, tab: LibraryTab = LibraryTab.Home) {
    Column(Modifier.fillMaxWidth().padding(start = 20.dp, end = 12.dp, top = 8.dp, bottom = 4.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            GalleryBrand(Modifier.weight(1f))
            settings()
        }
        Spacer(Modifier.height(16.dp))
        Text(if (tab == LibraryTab.Home) "어떤 장면이\n눈에 들어오나요?" else "날짜를 따라\n사진을 찾아보세요", style = MaterialTheme.typography.headlineLarge)
        Spacer(Modifier.height(8.dp))
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            Text("내 사진 · ${count}장", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.weight(1f))
            TextButton(onClick = onConnect, modifier = Modifier.heightIn(min = 48.dp), contentPadding = PaddingValues(horizontal = 18.dp, vertical = 10.dp)) { Text("사진 연결") }
        }
    }
}
