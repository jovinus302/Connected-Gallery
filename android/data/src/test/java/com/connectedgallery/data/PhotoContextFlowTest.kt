package com.connectedgallery.data

import com.connectedgallery.domain.*
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.runBlocking
import org.junit.Assert.*
import org.junit.Test

class PhotoContextFlowTest {
 private fun value(state:String,revision:Long=3)=ContextState("a",state,revision,context=when(state) {
  "ready" -> PhotoContext("함께 보이는 모습",listOf(ResultGroup("g","주변 장면","실제 사진에서 확인",listOf("b"))))
  "empty" -> PhotoContext("확인한 주변 사진이 없어요")
  else -> null
 })
 @Test fun openingPendingAutomaticallyPreparesAndPolls()=runBlocking {
  var reads=0;var prepares=0;val states=mutableListOf<String>()
  loadPhotoContext("a",read={value(if(reads++==0)"pending" else "ready")},prepare={prepares++;value("running")},pause={},publish={states.add(it.state)})
  assertEquals(listOf("pending","running","ready"),states);assertEquals(1,prepares)
 }
 @Test fun preparedAndConfirmedEmptyNeverCreateWork()=runBlocking {
  for(state in listOf("ready","empty"))loadPhotoContext("a",read={value(state)},prepare={error("Unexpected preparation")},publish={assertEquals(state,it.state)})
 }
 @Test fun failedWorkOnlyRetriesWhenRequested()=runBlocking {
  var prepares=0
  loadPhotoContext("a",read={value("failed")},prepare={prepares++;value("ready")},publish={})
  assertEquals(0,prepares)
  loadPhotoContext("a",retry=true,read={value("failed")},prepare={prepares++;value("ready")},publish={})
  assertEquals(1,prepares)
 }
 @Test fun cancellationCannotPublishOrStartWorkAfterNavigation()=runBlocking {
  try {
   loadPhotoContext("a",read={throw CancellationException()},prepare={error("Unexpected work")},publish={fail("Late publication")})
   fail("Expected cancellation")
  } catch(_:CancellationException) { }
 }
 @Test fun staleSnapshotPreparesOnceForNewRevision()=runBlocking {
  val reads=ArrayDeque(listOf(value("running",1),value("pending",2),value("ready",2)))
  var prepares=0
  loadPhotoContext("a",read={reads.removeFirst()},prepare={prepares++;value("running",2)},pause={},publish={})
  assertEquals(1,prepares)
 }
 @Test fun foreignAndMalformedResponsesAreNeverDisplayed()=runBlocking {
  for(response in listOf(value("ready").copy(photo_id="b"),value("empty").copy(state="ready"))) {
   val states=mutableListOf<String>()
   loadPhotoContext("a",read={response},prepare={error("Unexpected work")},publish={states.add(it.state)})
   assertEquals(listOf("offline"),states)
  }
 }
}
