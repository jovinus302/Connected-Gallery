package com.connectedgallery.spaces
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.unit.dp
import coil3.compose.AsyncImage
import com.connectedgallery.domain.*

@Composable fun SpacesScreen(spaces:List<Space>,photos:List<Photo>,onOpen:(String)->Unit,onOrganize:()->Unit,onExclude:(String,String)->Unit,modifier:Modifier=Modifier) {
 LazyColumn(modifier,contentPadding=PaddingValues(16.dp),verticalArrangement=Arrangement.spacedBy(16.dp)) {
  item { Text("다시 꺼내볼 맥락",style=MaterialTheme.typography.headlineSmall);Text("사진에서 발견한 연결로 시작하세요.");TextButton(onClick=onOrganize) { Text("맥락 찾아보기") } }
  items(spaces,key={it.id}) { s ->
   Column {
    Text(s.name,style=MaterialTheme.typography.titleLarge);Text(s.meaning,style=MaterialTheme.typography.bodySmall)
    androidx.compose.foundation.lazy.LazyRow(horizontalArrangement=Arrangement.spacedBy(6.dp)) {
     items(s.items,key={it.photo_id}) { item -> photos.find { it.id==item.photo_id }?.let { p -> Column(Modifier.width(116.dp)) {
      AsyncImage(model=p.local_uri,contentDescription=s.name,contentScale=ContentScale.Crop,modifier=Modifier.aspectRatio(1f).clickable { onOpen(p.id) })
      TextButton(onClick={onExclude(s.id,p.id)}) { Text("여기서 빼기") }
     } } }
    }
   }
  }
 }
}
