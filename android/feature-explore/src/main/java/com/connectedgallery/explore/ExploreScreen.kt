package com.connectedgallery.explore

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import coil3.compose.AsyncImage
import com.connectedgallery.coreui.*
import com.connectedgallery.domain.*
import kotlinx.coroutines.flow.distinctUntilChanged

@Composable fun ExploreScreen(vm: GalleryViewModel, modifier: Modifier = Modifier) {
    val photos by vm.photos.collectAsState()
    val journey by vm.journey.collectAsState()
    val analysis by vm.analysis.collectAsState()
    val busy by vm.exploring.collectAsState()
    val status by vm.status.collectAsState()
    val frame = journey.current ?: return
    val photo = photos.find { it.id == frame.photoId } ?: return
    var reveal by remember(journey.revision) { mutableStateOf(false) }
    var choices by remember(journey.revision) { mutableStateOf<List<Region>>(emptyList()) }
    var pending by remember(journey.revision) { mutableStateOf<SemanticAnchor?>(null) }
    var manual by remember(journey.revision) { mutableStateOf<RegionBox?>(null) }
    var naming by remember(journey.revision) { mutableStateOf<Region?>(null) }
    var personName by remember(journey.revision) { mutableStateOf("") }
    val regions = analysis?.takeIf { it.photo_id == photo.id }?.regions.orEmpty()
    val query = frame.query
    val selecting = pending != null || manual != null
    val contextState = frame.context
    val result = frame.result
    val sections = if (query == null) contextState?.context?.groups.orEmpty() else if (result?.hasValidGroups() == true) result.groups
        else if (result?.items?.isNotEmpty() == true) listOf(ResultGroup("flat", "연결된 사진", "", result.items.map { it.photo_id })) else emptyList()
    val focused = sections.find { it.id == frame.focusedGroup }
    val dark = query == null && focused == null
    val clearSelection: () -> Unit = { pending = null; manual = null; reveal = false; choices = emptyList() }
    val goBack: () -> Unit = { if (selecting || reveal) clearSelection() else vm.back() }
    fun stage(region: Region) {
        pending = SemanticAnchor(region.photo_id, region.id, region.box, region.label, region.kind)
        manual = null; reveal = false; choices = emptyList()
    }
    BackHandler(enabled = selecting || reveal, onBack = clearSelection)

    Column(modifier.fillMaxSize().background(if (dark) GalleryInk else MaterialTheme.colorScheme.surface)) {
        Row(Modifier.fillMaxWidth().heightIn(min = 56.dp).padding(horizontal = 8.dp), verticalAlignment = Alignment.CenterVertically) {
            IconButton(onClick = goBack) { Icon(GalleryIcons.Back, "돌아가기", tint = if (dark) Color.White else MaterialTheme.colorScheme.onSurface) }
            Text(if (query != null) "연결된 사진" else if (focused != null) "함께 볼 사진" else "사진",
                Modifier.weight(1f).padding(horizontal = 8.dp), style = MaterialTheme.typography.titleMedium,
                color = if (dark) Color.White else MaterialTheme.colorScheme.onSurface)
            if (selecting) TextButton(onClick = clearSelection) { Text("선택 해제", color = GallerySelection) }
            else if (dark) photo.galleryDate()?.let {
                Text(it.galleryLabel(), Modifier.padding(end = 12.dp), style = MaterialTheme.typography.labelSmall, color = Color(0xFFC4C9BE))
            }
        }

        val screenRevision = journey.revision
        val canRestore = query != null || contextState?.state in setOf("ready", "empty")
        val panel: @Composable (Modifier) -> Unit = { panelModifier ->
            Surface(panelModifier, shape = if (dark) RoundedCornerShape(topStart = 24.dp, topEnd = 24.dp) else RoundedCornerShape(0.dp)) {
                key(screenRevision, canRestore) {
                    val listState = rememberLazyListState(frame.scrollIndex, frame.scrollOffset)
                    LaunchedEffect(listState, canRestore) {
                        if (canRestore) snapshotFlow { listState.firstVisibleItemIndex to listState.firstVisibleItemScrollOffset }
                            .distinctUntilChanged().collect { vm.scroll(screenRevision, it.first, it.second) }
                    }
                    val photosById = remember(photos) { photos.associateBy { it.id } }
                    val itemsById = result?.items?.associateBy { it.photo_id }.orEmpty()
                    LazyColumn(state = listState, modifier = Modifier.fillMaxSize(),
                        contentPadding = PaddingValues(20.dp), verticalArrangement = Arrangement.spacedBy(20.dp)) {
                        if (query != null) item(key = "selected-subject") {
                            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(16.dp)) {
                                // Fit keeps the selected object visible even when it lies near a photo edge.
                                AsyncImage(photo.local_uri, "선택한 대상의 원본 사진", contentScale = ContentScale.Fit,
                                    modifier = Modifier.size(76.dp).clip(RoundedCornerShape(12.dp)).background(GalleryInk))
                                Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                                    Text("선택한 대상", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.primary)
                                    Text(query.anchor.label, style = MaterialTheme.typography.titleMedium)
                                    if (!result?.label.isNullOrBlank() && result?.label != query.anchor.label)
                                        Text(result!!.label, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                                }
                            }
                        }
                        if (query == null) item(key = "context-status") {
                            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                                Text("함께 볼 사진", style = MaterialTheme.typography.titleLarge)
                                contextState?.capture?.let {
                                    Text("${if (it.source == "demo_fixture") "데모 설정 날짜" else "촬영일"} · ${it.date}",
                                        style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                                }
                                when (contextState?.state) {
                                    "ready", "empty" -> Text(contextState.context?.summary.orEmpty(), style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                                    "failed" -> {
                                        Text("주변 사진의 맥락을 정리하지 못했어요", style = MaterialTheme.typography.bodyMedium)
                                        OutlinedButton(onClick = vm::retryContext) { Text("다시 시도") }
                                    }
                                    "offline" -> {
                                        Text("분석 서버에 연결하지 못했어요. 설정의 ‘서버 연결’을 확인해 주세요", style = MaterialTheme.typography.bodyMedium)
                                        OutlinedButton(onClick = vm::retryContext) { Text("연결 후 다시 시도") }
                                    }
                                    else -> {
                                        Text("이 사진의 주변 맥락을 살펴보고 있어요", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                                        LinearProgressIndicator(Modifier.fillMaxWidth())
                                    }
                                }
                            }
                        }
                        if (query != null && busy) item(key = "loading") {
                            Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                                Text("연결된 사진을 찾고 있어요", style = MaterialTheme.typography.bodyMedium)
                                LinearProgressIndicator(Modifier.fillMaxWidth())
                            }
                        }
                        if (focused != null || query != null) {
                            val visibleGroups = focused?.let { listOf(it) } ?: sections
                            visibleGroups.forEach { group ->
                                item(key = "group:${group.id}") {
                                    GroupHeading(group, if (focused == null && result?.hasValidGroups() == true) ({ vm.focus(group.id) }) else null)
                                }
                                // Remove unavailable photos before chunking so two-column rows stay aligned.
                                val available = group.photo_ids.mapNotNull { photosById[it] }
                                items(available.chunked(2), key = { "${group.id}:${it.first().id}" }) { row ->
                                    Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                                        row.forEach { p -> PhotoThumbnail(p, itemsById[p.id]?.reason ?: group.title,
                                            Modifier.weight(1f), showReason = query != null, onOpen = vm::open) }
                                        if (row.size == 1) Spacer(Modifier.weight(1f))
                                    }
                                }
                            }
                        } else items(sections, key = { "group:${it.id}" }) { group ->
                            Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                                GroupHeading(group, onClick = { vm.focus(group.id) })
                                val rowState = rememberLazyListState(frame.rowPositions[group.id] ?: 0)
                                LaunchedEffect(rowState) {
                                    snapshotFlow { rowState.firstVisibleItemIndex }.distinctUntilChanged().collect { vm.rowScroll(screenRevision, group.id, it) }
                                }
                                LazyRow(state = rowState, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                    items(group.photo_ids, key = { it }) { id ->
                                        photosById[id]?.let { PhotoThumbnail(it, group.title, Modifier.width(120.dp), showReason = false, onOpen = vm::open) }
                                    }
                                }
                            }
                        }
                        if (query != null && !busy) item(key = "connect-status") {
                            when {
                                result == null -> StatusAction("사진 탐색을 마치지 못했어요", "다시 탐색", vm::retry)
                                result.grouping_status == "failed" -> StatusAction("연결은 찾았지만 정리를 마치지 못했어요", "다시 시도", vm::retry)
                                !result.complete -> StatusAction("일부 결과예요", "다시 탐색", vm::retry)
                                result.items.isEmpty() -> StatusAction("연결된 사진을 찾지 못했어요", "다른 대상 선택", vm::back)
                            }
                        }
                        if (status.isNotBlank() && !busy) item(key = "status") {
                            Text(status, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        }
                    }
                }
            }
        }

        if (!dark) panel(Modifier.weight(1f))
        else {
            val viewer: @Composable (Modifier) -> Unit = { viewerModifier ->
                Column(viewerModifier) {
                    PhotoCanvas(photo, regions, reveal, manual ?: pending?.box, onTap = { hits ->
                        if (hits.size == 1) stage(hits.first()) else { reveal = true; choices = hits }
                    }, onLongPress = { x, y ->
                        val hits = regions.filter { it.box.contains(x, y) }
                        if (hits.isNotEmpty()) { choices = hits; reveal = true }
                        else {
                            pending = null; reveal = false
                            manual = RegionBox((x - .125f).coerceIn(0f, .75f), (y - .125f).coerceIn(0f, .75f), .25f, .25f)
                        }
                    }, modifier = Modifier.fillMaxWidth().weight(1f))
                    if (reveal && choices.isEmpty() && !selecting && regions.isNotEmpty()) {
                        LazyRow(contentPadding = PaddingValues(horizontal = 16.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            items(regions, key = { it.id }) { region ->
                                TextButton(onClick = { stage(region) }) { Text(region.label, color = GallerySelection) }
                            }
                        }
                    }
                    if (!selecting) Text(if (regions.isEmpty()) "길게 눌러 탐색할 부분을 지정하세요" else "궁금한 대상을 눌러보세요 · 길게 눌러 영역 선택",
                        Modifier.padding(horizontal = 20.dp, vertical = 12.dp), color = Color(0xFFC4C9BE), style = MaterialTheme.typography.bodySmall)
                }
            }
            if (selecting) {
                viewer(Modifier.weight(1f))
                Column(Modifier.fillMaxWidth().heightIn(max = 280.dp).verticalScroll(rememberScrollState()).padding(20.dp),
                    verticalArrangement = Arrangement.spacedBy(12.dp)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Surface(color = GallerySelection, shape = RoundedCornerShape(50)) {
                            Text(pending?.label ?: "선택한 부분", Modifier.padding(horizontal = 14.dp, vertical = 8.dp), color = GalleryInk, style = MaterialTheme.typography.labelLarge)
                        }
                        Spacer(Modifier.weight(1f))
                        Text("선택됨", color = Color(0xFFC4C9BE), style = MaterialTheme.typography.labelSmall)
                    }
                    manual?.let { box ->
                        Text("선택 영역 크기", color = Color.White, style = MaterialTheme.typography.bodySmall)
                        Slider(value = box.width, onValueChange = { value ->
                            val cx = box.x + box.width / 2; val cy = box.y + box.height / 2
                            manual = RegionBox((cx - value / 2).coerceIn(0f, 1 - value), (cy - value / 2).coerceIn(0f, 1 - value), value, value)
                        }, valueRange = .05f..1f, colors = SliderDefaults.colors(thumbColor = GallerySelection, activeTrackColor = GallerySelection))
                    }
                    Button(onClick = { (pending ?: manual?.let { SemanticAnchor(photo.id, box = it) })?.let(vm::select) },
                        modifier = Modifier.fillMaxWidth().heightIn(min = 52.dp), colors = ButtonDefaults.buttonColors(containerColor = GallerySelection, contentColor = GalleryInk)) {
                        Text("이 대상으로 사진 찾기")
                    }
                }
            } else BoxWithConstraints(Modifier.weight(1f)) {
                if (maxWidth >= 600.dp) Row(Modifier.fillMaxSize()) {
                    viewer(Modifier.weight(1f).fillMaxHeight())
                    panel(Modifier.weight(1f).fillMaxHeight())
                } else Column(Modifier.fillMaxSize()) {
                    viewer(Modifier.fillMaxWidth().weight(1.15f))
                    panel(Modifier.fillMaxWidth().weight(1f))
                }
            }
        }
    }
    if (choices.isNotEmpty()) AlertDialog(onDismissRequest = { choices = emptyList() }, title = { Text("어떤 대상을 따라갈까요?") },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState())) {
                choices.forEach { region ->
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        TextButton(onClick = { stage(region) }, modifier = Modifier.weight(1f)) { Text(region.label) }
                        if (region.kind == "person") TextButton(onClick = { naming = region; choices = emptyList() }) { Text("이름 지정") }
                    }
                }
            }
        }, confirmButton = { TextButton(onClick = { choices = emptyList() }) { Text("닫기") } })
    naming?.let { region ->
        AlertDialog(onDismissRequest = { naming = null }, title = { Text("이 사람의 이름") },
            text = { OutlinedTextField(value = personName, onValueChange = { personName = it }, label = { Text("이름") }, singleLine = true) },
            confirmButton = { TextButton(onClick = { vm.name(region, personName); naming = null }, enabled = personName.isNotBlank()) { Text("저장") } },
            dismissButton = { TextButton(onClick = { naming = null }) { Text("취소") } })
    }
}

@Composable private fun GroupHeading(group: ResultGroup, onClick: (() -> Unit)?) {
    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
        Row(Modifier.fillMaxWidth().then(if (onClick != null) Modifier.clickable(role = Role.Button, onClick = onClick) else Modifier)
            .heightIn(min = 48.dp).padding(vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
            Text(group.title, style = MaterialTheme.typography.titleSmall, modifier = Modifier.weight(1f))
            if (onClick != null) Icon(GalleryIcons.Next, "전체 보기", Modifier.padding(start = 10.dp).size(18.dp), tint = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        if (group.reason.isNotBlank()) Text(group.reason, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

@Composable private fun StatusAction(message: String, action: String, onClick: () -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text(message, style = MaterialTheme.typography.bodyMedium)
        OutlinedButton(onClick = onClick) { Text(action) }
    }
}

@Composable private fun PhotoThumbnail(photo: Photo, reason: String, modifier: Modifier, showReason: Boolean, onOpen: (String) -> Unit) {
    Column(modifier.clickable(role = Role.Button) { onOpen(photo.id) }, verticalArrangement = Arrangement.spacedBy(6.dp)) {
        AsyncImage(model = photo.local_uri, contentDescription = reason, contentScale = ContentScale.Crop,
            modifier = Modifier.fillMaxWidth().aspectRatio(.85f).clip(RoundedCornerShape(10.dp)).background(MaterialTheme.colorScheme.surfaceVariant))
        if (showReason && reason.isNotBlank()) Text(reason, style = MaterialTheme.typography.bodySmall, maxLines = 2, overflow = TextOverflow.Ellipsis, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}
