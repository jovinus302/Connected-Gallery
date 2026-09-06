package com.connectedgallery.library
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.grid.*
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.unit.dp
import coil3.compose.AsyncImage
import com.connectedgallery.domain.Photo

@Composable fun LibraryScreen(photos:List<Photo>,onOpen:(String)->Unit,modifier:Modifier=Modifier) {
 if(photos.isEmpty()) Box(modifier.padding(24.dp)) { Text("사진을 연결하면 여기에서 탐색을 시작할 수 있어요.") }
 else LazyVerticalGrid(columns=GridCells.Fixed(3),modifier=modifier,contentPadding=PaddingValues(4.dp),horizontalArrangement=Arrangement.spacedBy(4.dp),verticalArrangement=Arrangement.spacedBy(4.dp)) {
  items(photos,key={it.id}) { p -> AsyncImage(model=p.local_uri,contentDescription=p.captured_at?.take(10)?:"사진",contentScale=ContentScale.Crop,modifier=Modifier.aspectRatio(1f).clickable { onOpen(p.id) }) }
 }
}
