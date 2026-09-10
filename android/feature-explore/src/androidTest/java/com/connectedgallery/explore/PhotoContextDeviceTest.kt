package com.connectedgallery.explore

import com.connectedgallery.coreui.GalleryTheme
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createComposeRule
import com.connectedgallery.domain.*
import kotlinx.coroutines.flow.MutableStateFlow
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test

/** Device UI contract test with deterministic repository fixtures; not semantic quality evidence. */
class PhotoContextDeviceTest {
 @get:Rule val compose=createComposeRule()
 private val canvas="사진. 대상을 누르거나 길게 눌러 탐색하세요"
 private class Repository:GalleryRepository {
  override val photos=MutableStateFlow(listOf("wine","dinner","dessert","park").map { Photo(it,width=400,height=400) })
  var saved=Journey()
  val opened=mutableListOf<String>()
  var failure=false
  var searches=0
  override suspend fun loadJourney()=saved
  override suspend fun saveJourney(journey:Journey) { saved=journey }
  override suspend fun refreshAndSync(progress:(String)->Unit) { }
  override suspend fun analysis(photoId:String)=Analysis(photoId,regions=listOf(Region("subject",photoId,RegionBox(0f,0f,1f,1f),"object",if(photoId=="wine")"와인" else "디저트")))
  override suspend fun context(photoId:String,retry:Boolean,onUpdate:(ContextState)->Unit) {
   opened.add(photoId)
   if(failure && !retry) { onUpdate(ContextState(photoId,"failed"));return }
   val groups=if(photoId=="dinner")listOf(ResultGroup("day","같은 날의 다른 장면","사진을 확인한 테스트용 근거",listOf("dessert"))) else emptyList()
   onUpdate(ContextState(photoId,if(groups.isEmpty())"empty" else "ready",1,context=PhotoContext("$photoId 주변 장면",groups)))
  }
  override suspend fun explore(input:ExploreInput,onUpdate:(ExplorationResult)->Unit):ExplorationResult {
   searches++
   val target=if(input.anchor.photo_id=="wine")"dinner" else "park"
   val result=ExplorationResult("선택한 대상",listOf(ResultItem(target,"open-$target")),groups=listOf(ResultGroup("related","대상과 연결된 사진","테스트용 관계",listOf(target))),grouping_status="ready")
   onUpdate(result);return result
  }
  override suspend fun cancelExploration() { }
  override suspend fun feedback(kind:String,photoId:String?,regionId:String?,value:String) { }
  override suspend fun metric(name:String,value:String) { }
 }
 @Test fun automaticContextConnectThreeHopsAndBackRestoreOnDevice() {
  val repo=Repository();lateinit var vm:GalleryViewModel
  compose.runOnIdle { vm=GalleryViewModel(repo) }
  compose.setContent { GalleryTheme { ExploreScreen(vm) } }
  compose.runOnIdle { vm.open("wine") }
  compose.onNodeWithText("wine 주변 장면").assertIsDisplayed()
  compose.onNodeWithContentDescription(canvas).performTouchInput { click(center) }
  compose.waitUntil(3000) { compose.onAllNodesWithText("이 대상으로 사진 찾기").fetchSemanticsNodes().isNotEmpty() }
  compose.onNodeWithText("이 대상으로 사진 찾기").performClick()
  compose.waitUntil(3000) { vm.journey.value.current?.result!=null }
  compose.onNodeWithContentDescription("open-dinner").performClick()
  compose.onNodeWithText("dinner 주변 장면").assertIsDisplayed()
  compose.onAllNodesWithText("같은 날의 다른 장면")[0].performClick()
  compose.runOnIdle { assertEquals("day",vm.journey.value.current!!.focusedGroup) }
  compose.onNodeWithContentDescription("같은 날의 다른 장면").performClick()
  compose.onNodeWithText("dessert 주변 장면").assertIsDisplayed()
  compose.onNodeWithContentDescription(canvas).performTouchInput { click(center) }
  compose.waitUntil(3000) { compose.onAllNodesWithText("이 대상으로 사진 찾기").fetchSemanticsNodes().isNotEmpty() }
  compose.onNodeWithText("이 대상으로 사진 찾기").performClick()
  compose.waitUntil(3000) { vm.journey.value.current?.result!=null }
  compose.onNodeWithContentDescription("open-park").performClick()
  compose.onNodeWithText("park 주변 장면").assertIsDisplayed()
  compose.onNodeWithContentDescription("돌아가기").performClick()
  compose.runOnIdle { assertEquals("dessert",vm.journey.value.current!!.photoId);assertEquals("park",vm.journey.value.current!!.result!!.items.single().photo_id) }
  repeat(4) { compose.onNodeWithContentDescription("돌아가기").performClick() }
  compose.runOnIdle { assertEquals("wine",vm.journey.value.current!!.photoId);assertEquals("dinner",vm.journey.value.current!!.result!!.items.single().photo_id);assertTrue(repo.opened.containsAll(listOf("wine","dinner","dessert","park"))) }
 }
 @Test fun failureRetryDoesNotPretendContextIsEmpty() {
  val repo=Repository().apply { failure=true };lateinit var vm:GalleryViewModel
  compose.runOnIdle { vm=GalleryViewModel(repo) }
  compose.setContent { GalleryTheme { ExploreScreen(vm) } }
  compose.runOnIdle { vm.open("dinner") }
  compose.onNodeWithText("주변 사진의 맥락을 정리하지 못했어요").assertIsDisplayed()
  compose.onNodeWithText("다시 시도").performClick()
  compose.onNodeWithText("dinner 주변 장면").assertIsDisplayed()
 }
 @Test fun selectionCanBeCancelledWithoutStartingSearchOrLosingContext() {
  val repo=Repository();lateinit var vm:GalleryViewModel
  compose.runOnIdle { vm=GalleryViewModel(repo) }
  compose.setContent { GalleryTheme { ExploreScreen(vm) } }
  compose.runOnIdle { vm.open("dinner") }
  compose.onNodeWithContentDescription(canvas).performTouchInput { click(center) }
  compose.waitUntil(3000) { compose.onAllNodesWithText("이 대상으로 사진 찾기").fetchSemanticsNodes().isNotEmpty() }
  compose.onNodeWithText("이 대상으로 사진 찾기").assertIsDisplayed()
  compose.runOnIdle { assertEquals(0,repo.searches);assertNull(vm.journey.value.current!!.query) }
  compose.onNodeWithContentDescription("돌아가기").performClick()
  compose.onNodeWithText("dinner 주변 장면").assertIsDisplayed()
  compose.runOnIdle { assertEquals("dinner",vm.journey.value.current!!.photoId);assertEquals(0,repo.searches) }
 }
}
