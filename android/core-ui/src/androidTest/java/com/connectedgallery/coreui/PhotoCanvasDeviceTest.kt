package com.connectedgallery.coreui

import androidx.compose.foundation.layout.size
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.unit.dp
import com.connectedgallery.domain.*
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test

class PhotoCanvasDeviceTest {
 @get:Rule val compose = createComposeRule()
 private val imageDescription = "사진. 대상을 누르거나 길게 눌러 탐색하세요"

 @Test fun tapUsesTheFittedImageBounds() {
  val target=Region("target","fixture",RegionBox(.65f,.3f,.25f,.4f),"object","target")
  var selected:List<Region> = emptyList()
  var clicked=false
  compose.setContent {
   PhotoCanvas(Photo("fixture",width=800,height=400),listOf(target),false,null,
    onTap={selected=it;clicked=true},onLongPress={_,_->},modifier=Modifier.size(300.dp,500.dp))
  }
  compose.onNodeWithContentDescription(imageDescription).performTouchInput {
   click(Offset(width*.75f,height*.5f))
  }
  // Telephoto waits for a possible second tap before dispatching a single tap.
  compose.waitUntil(timeoutMillis=2000) { clicked }
  compose.runOnIdle { assertEquals(listOf(target),selected) }
 }

 @Test fun longPressKeepsTheSameCenterAfterZoom() {
  var selected:Pair<Float,Float>?=null
  compose.setContent {
   PhotoCanvas(Photo("fixture",width=400,height=800),emptyList(),false,null,
    onTap={},onLongPress={x,y->selected=x to y},modifier=Modifier.size(300.dp,500.dp))
  }
  val photo=compose.onNodeWithContentDescription(imageDescription)
  photo.performTouchInput { doubleClick(center) }
  compose.waitForIdle()
  photo.performTouchInput { longClick(center) }
  compose.runOnIdle {
   assertNotNull(selected)
   assertEquals(.5f,selected!!.first,.02f)
   assertEquals(.5f,selected!!.second,.02f)
  }
 }

 @Test fun tapUsesRegionsLoadedAfterThePhoto() {
  val target=Region("target","fixture",RegionBox(.65f,.3f,.25f,.4f),"object","target")
  val regions=mutableStateOf<List<Region>>(emptyList())
  var selected:List<Region> = emptyList()
  var clicked=false
  var tapCallbackVersion=-1
  var longPressCallbackVersion=-1
  compose.setContent {
   val version=regions.value.size
   PhotoCanvas(Photo("fixture",width=800,height=400),regions.value,false,null,
    onTap={selected=it;clicked=true;tapCallbackVersion=version},
    onLongPress={_,_->longPressCallbackVersion=version},modifier=Modifier.size(300.dp,500.dp))
  }
  compose.runOnIdle { regions.value=listOf(target) }
  compose.onNodeWithContentDescription(imageDescription).performTouchInput {
   click(Offset(width*.75f,height*.5f))
  }
  compose.waitUntil(timeoutMillis=2000) { clicked }
  compose.runOnIdle { assertEquals(listOf(target),selected);assertEquals(1,tapCallbackVersion) }
  compose.onNodeWithContentDescription(imageDescription).performTouchInput { longClick(center) }
  compose.runOnIdle { assertEquals(1,longPressCallbackVersion) }
 }
}
