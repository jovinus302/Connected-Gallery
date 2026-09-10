package com.connectedgallery.library

import androidx.compose.animation.Crossfade
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.grid.*
import androidx.compose.foundation.lazy.staggeredgrid.*
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.selection.selectableGroup
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import coil3.compose.AsyncImage
import com.connectedgallery.coreui.*
import com.connectedgallery.domain.Photo

enum class LibraryTab(val label: String) { Home("홈"), Dates("날짜별") }

/** Hoisted above the photo journey so each tab keeps its own position when a photo closes. */
class LibraryState(
    val tab: MutableState<LibraryTab>,
    val homeScroll: LazyStaggeredGridState,
    val datesScroll: LazyGridState,
)

@Composable fun rememberLibraryState(): LibraryState {
    val tab = rememberSaveable { mutableStateOf(LibraryTab.Home) }
    val home = rememberLazyStaggeredGridState()
    val dates = rememberLazyGridState()
    return remember { LibraryState(tab, home, dates) }
}

@Composable fun LibraryScreen(photos: List<Photo>, onOpen: (String) -> Unit, modifier: Modifier = Modifier,
    state: LibraryState = rememberLibraryState()) {
    Column(modifier) {
        Row(Modifier.fillMaxWidth().selectableGroup().padding(horizontal = 20.dp, vertical = 8.dp),
            horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            LibraryTab.entries.forEach { tab ->
                val selected = state.tab.value == tab
                Box(Modifier.clip(RoundedCornerShape(50))
                    .background(if (selected) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.surface)
                    .selectable(selected, role = Role.Tab, onClick = { state.tab.value = tab })
                    .heightIn(min = 48.dp).padding(horizontal = 24.dp, vertical = 12.dp), contentAlignment = Alignment.Center) {
                    Text(tab.label, style = MaterialTheme.typography.labelLarge,
                        color = if (selected) MaterialTheme.colorScheme.onPrimary else MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
        }
        HorizontalDivider(Modifier.padding(horizontal = 20.dp), color = MaterialTheme.colorScheme.outlineVariant)
        if (photos.isEmpty()) {
            Column(Modifier.fillMaxSize().padding(32.dp), horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.Center) {
                Icon(GalleryIcons.Photo, null, Modifier.size(36.dp), tint = GalleryEvidence)
                Spacer(Modifier.height(24.dp))
                Text("연결의 시작은, 한 장의 사진", style = MaterialTheme.typography.titleLarge, textAlign = TextAlign.Center)
                Spacer(Modifier.height(10.dp))
                Text("상단의 ‘사진 연결’에서 사진을 허용해 주세요.\n사진 속 대상을 따라 다른 순간을 찾을 수 있어요.",
                    color = MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.bodyMedium, textAlign = TextAlign.Center)
            }
        } else Crossfade(state.tab.value, Modifier.weight(1f), animationSpec = tween(180), label = "library-tab") { tab ->
            when (tab) {
                LibraryTab.Home -> HomePhotos(photos, state.homeScroll, onOpen)
                LibraryTab.Dates -> DatedPhotos(photos, state.datesScroll, onOpen)
            }
        }
    }
}

@Composable private fun HomePhotos(photos: List<Photo>, scroll: LazyStaggeredGridState, onOpen: (String) -> Unit) {
    BoxWithConstraints(Modifier.fillMaxSize()) {
        LazyVerticalStaggeredGrid(columns = StaggeredGridCells.Fixed(if (maxWidth >= 600.dp) 3 else 2), state = scroll,
            modifier = Modifier.fillMaxSize().testTag("home-grid"), contentPadding = PaddingValues(20.dp),
            horizontalArrangement = Arrangement.spacedBy(12.dp), verticalItemSpacing = 12.dp) {
            itemsIndexed(photos, key = { _, photo -> photo.id }) { index, photo ->
                // Preserve source proportions; square photos use the approved home's varied framing.
                val ratio = if (photo.width == photo.height) listOf(.78f, 1.08f, 1.22f, .86f)[index % 4]
                    else (photo.width.toFloat() / photo.height.coerceAtLeast(1)).coerceIn(.65f, 1.4f)
                AsyncImage(photo.local_uri, "사진 열기", contentScale = ContentScale.Crop,
                    modifier = Modifier.fillMaxWidth().aspectRatio(ratio).clip(RoundedCornerShape(20.dp))
                        .background(MaterialTheme.colorScheme.surfaceVariant).testTag("home-photo:${photo.id}")
                        .clickable(role = Role.Button) { onOpen(photo.id) })
            }
        }
    }
}

@Composable private fun DatedPhotos(photos: List<Photo>, scroll: LazyGridState, onOpen: (String) -> Unit) {
    val dated = remember(photos) { photos.groupBy { it.galleryDate() }.entries.sortedWith(compareByDescending { it.key }) }
    BoxWithConstraints(Modifier.fillMaxSize()) {
        LazyVerticalGrid(columns = GridCells.Fixed(if (maxWidth >= 600.dp) 5 else 3), state = scroll,
            modifier = Modifier.fillMaxSize().testTag("dates-grid"), contentPadding = PaddingValues(start = 20.dp, end = 20.dp, bottom = 24.dp),
            horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            item(key = "sort", span = { GridItemSpan(maxLineSpan) }) {
                Row(Modifier.fillMaxWidth().padding(vertical = 18.dp), verticalAlignment = Alignment.CenterVertically) {
                    Text("날짜별 사진", style = MaterialTheme.typography.titleSmall, modifier = Modifier.weight(1f))
                    Text("최신 날짜순 ↓", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
            dated.forEach { (date, groupPhotos) ->
                item(key = "date:$date", span = { GridItemSpan(maxLineSpan) }) {
                    Row(Modifier.fillMaxWidth().padding(top = 12.dp, bottom = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                        Text(date?.galleryLabel() ?: "촬영일을 알 수 없는 사진", style = MaterialTheme.typography.titleSmall, modifier = Modifier.weight(1f))
                        Text("${groupPhotos.size}장", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                }
                items(groupPhotos, key = { it.id }) { photo ->
                    AsyncImage(photo.local_uri, date?.let { "${it.galleryLabel()} 사진" } ?: "사진", contentScale = ContentScale.Crop,
                        modifier = Modifier.aspectRatio(1f).clip(RoundedCornerShape(12.dp))
                            .background(MaterialTheme.colorScheme.surfaceVariant).testTag("date-photo:${photo.id}")
                            .clickable(role = Role.Button) { onOpen(photo.id) })
                }
            }
        }
    }
}
