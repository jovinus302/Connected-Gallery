package com.connectedgallery.explore

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import coil3.compose.AsyncImage
import com.connectedgallery.coreui.PhotoCanvas
import com.connectedgallery.domain.*
import kotlinx.coroutines.flow.distinctUntilChanged

@Composable fun ExploreScreen(vm:GalleryViewModel,modifier:Modifier=Modifier) {
 val photos by vm.photos.collectAsState();val journey by vm.journey.collectAsState()
 val analysis by vm.analysis.collectAsState();val busy by vm.exploring.collectAsState()
 val frame=journey.current?:return;val photo=photos.find { it.id==frame.photoId }?:return
 var reveal by remember(photo.id) { mutableStateOf(false) }
 var choices by remember(photo.id) { mutableStateOf<List<Region>>(emptyList()) }
 var manual by remember(photo.id) { mutableStateOf<RegionBox?>(null) }
 var naming by remember(photo.id) { mutableStateOf<Region?>(null) };var personName by remember(photo.id) { mutableStateOf("") }
 val regions=analysis?.takeIf { it.photo_id==photo.id }?.regions?:emptyList()
 val query=frame.query
 fun select(r:Region) { reveal=false;choices=emptyList();manual=null;vm.select(SemanticAnchor(r.photo_id,r.id,r.box,r.label,r.kind)) }
 Column(modifier) {
  Row(Modifier.fillMaxWidth().padding(horizontal=8.dp),horizontalArrangement=Arrangement.SpaceBetween) {
   TextButton(onClick=vm::back) { Text("돌아가기") }
   Text(query?.let { frame.result?.label?.takeIf(String::isNotBlank)?:it.anchor.label }?:"사진 속 의미를 따라가세요",modifier=Modifier.weight(1f).padding(12.dp),style=MaterialTheme.typography.labelLarge)
  }
  PhotoCanvas(photo,regions,reveal,manual?:query?.anchor?.takeIf { it.photo_id==photo.id }?.box,onTap={ hits ->
   if(hits.size==1)select(hits.first()) else { reveal=true;choices=hits }
  },onLongPress={ x,y ->
   reveal=true;choices=regions.filter { it.box.contains(x,y) }
   if(choices.isEmpty())manual=RegionBox((x-.125f).coerceIn(0f,.75f),(y-.125f).coerceIn(0f,.75f),.25f,.25f)
  },modifier=Modifier.fillMaxWidth().weight(1.3f))
  if(reveal && choices.isEmpty() && manual==null) {
   LazyRow { items(regions) { r -> TextButton(onClick={select(r)}) { Text(r.label) } } }
  }
  if(regions.isEmpty() && manual==null) Text("길게 눌러 탐색할 부분을 지정하세요",Modifier.padding(12.dp),style=MaterialTheme.typography.bodySmall)
  manual?.let { b ->
   Row { TextButton(onClick={manual=null}) { Text("취소") };TextButton(onClick={vm.select(SemanticAnchor(photo.id,box=b));manual=null}) { Text("이 부분 따라가기") } }
   Slider(value=b.width,onValueChange={ v -> val cx=b.x+b.width/2;val cy=b.y+b.height/2;manual=RegionBox((cx-v/2).coerceIn(0f,1-v),(cy-v/2).coerceIn(0f,1-v),v,v) },valueRange=.05f..1f,modifier=Modifier.padding(horizontal=16.dp))
  }
  val contextState=frame.context
  val context=contextState?.context
  val result=frame.result
  val sections=if(query==null) context?.groups.orEmpty() else if(result?.hasValidGroups()==true) result.groups
   else if(result?.items?.isNotEmpty()==true) listOf(ResultGroup("flat","연결된 사진","",result.items.map { it.photo_id })) else emptyList()
  val focused=sections.find { it.id==frame.focusedGroup }
  val screenRevision=journey.revision
  if((query!=null && busy) || (query==null && contextState?.state in setOf(null,"checking","pending","running")))
   LinearProgressIndicator(Modifier.fillMaxWidth())
  val canRestore=query!=null || contextState?.state in setOf("ready","empty")
  key(screenRevision,canRestore) {
   val listState=rememberLazyListState(frame.scrollIndex,frame.scrollOffset)
   LaunchedEffect(listState) { if(canRestore)snapshotFlow { listState.firstVisibleItemIndex to listState.firstVisibleItemScrollOffset }.distinctUntilChanged().collect { vm.scroll(screenRevision,it.first,it.second) } }
   val photosById=photos.associateBy { it.id }
   val itemsById=result?.items?.associateBy { it.photo_id }.orEmpty()
   LazyColumn(state=listState,modifier=Modifier.fillMaxWidth().weight(1f),contentPadding=PaddingValues(12.dp),verticalArrangement=Arrangement.spacedBy(16.dp)) {
    if(query==null) item(key="context-status") {
     Column(verticalArrangement=Arrangement.spacedBy(6.dp)) {
      contextState?.capture?.let { Text("촬영일 · ${it.date}",style=MaterialTheme.typography.labelSmall) }
      when(contextState?.state) {
       "ready","empty" -> Text(context?.summary.orEmpty(),style=MaterialTheme.typography.bodyMedium)
       "failed" -> { Text("주변 사진의 맥락을 정리하지 못했어요");TextButton(onClick=vm::retryContext) { Text("다시 시도") } }
       "offline" -> { Text("PC 연결을 확인하면 주변 사진을 볼 수 있어요");TextButton(onClick=vm::retryContext) { Text("연결 후 다시 시도") } }
       else -> Text("이 사진의 주변 맥락을 살펴보고 있어요",style=MaterialTheme.typography.bodySmall)
      }
     }
    }
    if(focused!=null) {
     item(key="focused-title") { Column { Text(focused.title,style=MaterialTheme.typography.titleMedium);Text(focused.reason,style=MaterialTheme.typography.bodySmall) } }
     items(focused.photo_ids.chunked(2),key={it.first()}) { ids ->
      Row(horizontalArrangement=Arrangement.spacedBy(8.dp)) {
       ids.forEach { id -> photosById[id]?.let { p -> PhotoThumbnail(p,itemsById[id]?.reason?:focused.title,Modifier.weight(1f),vm::open) } }
       if(ids.size==1)Spacer(Modifier.weight(1f))
      }
     }
    } else items(sections,key={"group:"+it.id}) { group ->
     Column(verticalArrangement=Arrangement.spacedBy(6.dp)) {
      Text(group.title,Modifier.fillMaxWidth().clickable { vm.focus(group.id) }.padding(vertical=8.dp),style=MaterialTheme.typography.titleSmall)
      if(group.reason.isNotBlank())Text(group.reason,style=MaterialTheme.typography.bodySmall)
      val rowState=rememberLazyListState(frame.rowPositions[group.id]?:0)
      LaunchedEffect(rowState) { snapshotFlow { rowState.firstVisibleItemIndex }.distinctUntilChanged().collect { vm.rowScroll(screenRevision,group.id,it) } }
      LazyRow(state=rowState,horizontalArrangement=Arrangement.spacedBy(8.dp)) {
       items(group.photo_ids,key={it}) { id -> photosById[id]?.let { p ->
        PhotoThumbnail(p,itemsById[id]?.reason?:group.title,Modifier.width(120.dp),vm::open)
       } }
      }
     }
    }
    if(query!=null && !busy) item(key="connect-status") {
     when {
      result==null -> TextButton(onClick=vm::retry) { Text("다시 탐색") }
      result.grouping_status=="failed" -> TextButton(onClick=vm::retry) { Text("연결은 찾았지만 정리를 마치지 못했어요 · 다시 시도") }
      !result.complete -> TextButton(onClick=vm::retry) { Text("일부 결과예요 · 다시 탐색") }
      result.items.isEmpty() -> Text("연결된 사진을 찾지 못했어요")
     }
    }
   }
  }
 }
 if(choices.isNotEmpty())AlertDialog(onDismissRequest={choices=emptyList()},title={Text("어떤 의미를 따라갈까요?")},text={Column { choices.forEach { r -> Row { TextButton(onClick={select(r)}) { Text(r.label) };if(r.kind=="person")TextButton(onClick={naming=r;choices=emptyList()}) { Text("이름 지정") } } } }},confirmButton={})
 naming?.let { region -> AlertDialog(onDismissRequest={naming=null},title={Text("이 사람의 이름")},text={OutlinedTextField(value=personName,onValueChange={personName=it})},confirmButton={TextButton(onClick={vm.name(region,personName);naming=null}) { Text("저장") }}) }
}

@Composable private fun PhotoThumbnail(photo:Photo,reason:String,modifier:Modifier,onOpen:(String)->Unit) {
 Column(modifier.clickable { onOpen(photo.id) },verticalArrangement=Arrangement.spacedBy(4.dp)) {
  AsyncImage(model=photo.local_uri,contentDescription=reason,contentScale=ContentScale.Crop,modifier=Modifier.fillMaxWidth().height(112.dp))
  if(reason.isNotBlank())Text(reason,style=MaterialTheme.typography.labelSmall,maxLines=2,overflow=TextOverflow.Ellipsis)
 }
}
