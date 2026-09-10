package com.connectedgallery.coreui

import androidx.compose.foundation.Canvas
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.Alignment
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.unit.IntSize
import androidx.compose.ui.unit.dp
import coil3.compose.AsyncImage
import com.connectedgallery.domain.*
import me.saket.telephoto.zoomable.*

fun normalizedPoint(px:Float,py:Float,width:Float,height:Float,sx:Float,sy:Float,tx:Float,ty:Float,pivotX:Float=0f,pivotY:Float=0f):Pair<Float,Float> {
 return ((px-tx-pivotX)/sx+pivotX)/width to ((py-ty-pivotY)/sy+pivotY)/height
}

@Composable fun PhotoCanvas(photo:Photo,regions:List<Region>,reveal:Boolean,selected:RegionBox?,onTap:(List<Region>)->Unit,onLongPress:(Float,Float)->Unit,modifier:Modifier=Modifier,background:Color=GalleryInk) {
 // Gesture recognition outlives recomposition while analysis arrives. Keep
 // its observations and callbacks current without resetting the user's zoom.
 val currentRegions by rememberUpdatedState(regions)
 val currentOnTap by rememberUpdatedState(onTap)
 val currentOnLongPress by rememberUpdatedState(onLongPress)
 val selectionAlpha by animateFloatAsState(if(selected != null) 1f else 0f, tween(180), label="selection-outline")
 BoxWithConstraints(modifier.background(background),contentAlignment=Alignment.Center) {
  val ratio=photo.width.toFloat()/photo.height.coerceAtLeast(1)
  val fit=if(ratio>maxWidth.value/maxHeight.value) Modifier.fillMaxWidth().aspectRatio(ratio) else Modifier.fillMaxHeight().aspectRatio(ratio)
  key(photo.id) {
   val zoom=rememberZoomableState()
   var size by remember { mutableStateOf(IntSize(1,1)) }
   fun point(offset:Offset):Pair<Float,Float> {
    val t=zoom.contentTransformation
    if(!t.isSpecified)return -1f to -1f
    return normalizedPoint(offset.x,offset.y,size.width.toFloat(),size.height.toFloat(),t.scale.scaleX,t.scale.scaleY,t.offset.x,t.offset.y,t.transformOrigin.pivotFractionX*size.width,t.transformOrigin.pivotFractionY*size.height)
   }
   Box(fit.onSizeChanged { size=it }.zoomable(zoom,onClick={ offset ->
    val (x,y)=point(offset);currentOnTap(currentRegions.filter { it.box.contains(x,y) })
   },onLongClick={ offset -> val(x,y)=point(offset);if(x in 0f..1f && y in 0f..1f)currentOnLongPress(x,y) })) {
    AsyncImage(model=photo.local_uri,contentDescription="사진. 대상을 누르거나 길게 눌러 탐색하세요",contentScale=ContentScale.FillBounds,modifier=Modifier.fillMaxSize())
    Canvas(Modifier.fillMaxSize()) {
     if(reveal) regions.forEach { r -> val b=r.box;drawRoundRect(Color.White.copy(alpha=.65f),Offset(b.x*size.width,b.y*size.height),Size(b.width*size.width,b.height*size.height),CornerRadius(8.dp.toPx()),style=Stroke(1.dp.toPx())) }
     selected?.let { b ->
      val origin=Offset(b.x*size.width,b.y*size.height)
      val bounds=Size(b.width*size.width,b.height*size.height)
      drawRoundRect(GalleryInk.copy(alpha=selectionAlpha),origin,bounds,CornerRadius(10.dp.toPx()),style=Stroke(5.dp.toPx()))
      drawRoundRect(GallerySelection.copy(alpha=selectionAlpha),origin,bounds,CornerRadius(10.dp.toPx()),style=Stroke(2.dp.toPx()))
     }
    }
   }
  }
 }
}
