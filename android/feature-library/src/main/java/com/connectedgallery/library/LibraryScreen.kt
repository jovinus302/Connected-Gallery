package com.connectedgallery.library

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.grid.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import coil3.compose.AsyncImage
import com.connectedgallery.coreui.*
import com.connectedgallery.domain.Photo

@Composable fun LibraryScreen(photos: List<Photo>, onOpen: (String) -> Unit, modifier: Modifier = Modifier) {
    if (photos.isEmpty()) {
        Column(modifier.fillMaxWidth().padding(32.dp), horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.Center) {
            Surface(shape = RoundedCornerShape(24.dp), color = MaterialTheme.colorScheme.primaryContainer) {
                Icon(GalleryIcons.Photo, null, Modifier.padding(24.dp).size(36.dp), tint = MaterialTheme.colorScheme.primary)
            }
            Spacer(Modifier.height(24.dp))
            Text("연결의 시작은, 한 장의 사진", style = MaterialTheme.typography.titleLarge, textAlign = TextAlign.Center)
            Spacer(Modifier.height(10.dp))
            Text("상단의 ‘사진 연결’에서 사진을 허용해 주세요.\n사진 속 대상을 따라 다른 순간을 찾을 수 있어요.",
                color = MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.bodyMedium, textAlign = TextAlign.Center)
        }
        return
    }
    val dated = remember(photos) { photos.groupBy { it.galleryDate() }.entries.sortedWith(compareByDescending { it.key }) }
    BoxWithConstraints(modifier) {
        LazyVerticalGrid(columns = GridCells.Fixed(if (maxWidth >= 600.dp) 5 else 3), modifier = Modifier.fillMaxSize(),
            contentPadding = PaddingValues(start = 12.dp, end = 12.dp, bottom = 24.dp),
            horizontalArrangement = Arrangement.spacedBy(4.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            dated.forEach { (date, groupPhotos) ->
                item(key = "date:$date", span = { GridItemSpan(maxLineSpan) }) {
                    Row(Modifier.fillMaxWidth().padding(horizontal = 8.dp).padding(top = 24.dp, bottom = 10.dp),
                        verticalAlignment = Alignment.CenterVertically) {
                        Text(date?.galleryLabel() ?: "촬영일을 알 수 없는 사진", style = MaterialTheme.typography.titleSmall, modifier = Modifier.weight(1f))
                        Text("${groupPhotos.size}장", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                }
                items(groupPhotos, key = { it.id }) { photo ->
                    AsyncImage(model = photo.local_uri, contentDescription = date?.let { "${it.galleryLabel()} 사진" } ?: "사진",
                        contentScale = ContentScale.Crop,
                        modifier = Modifier.aspectRatio(.86f).clip(RoundedCornerShape(6.dp))
                            .background(MaterialTheme.colorScheme.surfaceVariant).clickable { onOpen(photo.id) })
                }
            }
        }
    }
}
