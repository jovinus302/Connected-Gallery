package com.connectedgallery.data

import com.connectedgallery.domain.*
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.runBlocking
import org.junit.Assert.*
import org.junit.Test
import java.io.IOException

class PreparedExplorationFlowTest {
 private val ready=ExplorationResult("병",listOf(ResultItem("target")),groups=listOf(ResultGroup("g","같은 라벨","이름 일치",listOf("target"))),grouping_status="ready")

 @Test fun readyLookupNeverUploadsCropOrCreatesRun()=runBlocking {
  val actions=mutableListOf<String>()
  val result=preparedOrLive("source",lookup={actions.add("read");PreparedExploration("ready",4,ready)},
   live={actions.add("upload-and-run");error("Prepared results must not enter live flow")},onUpdate={actions.add("display")})
  assertEquals(ready,result)
  assertEquals(listOf("read","display"),actions)
 }

 @Test fun pendingAndFailedGroupingEnterLiveFlowOnlyAfterLookup()=runBlocking {
  listOf(PreparedExploration("pending",4),PreparedExploration("ready",4,ready.copy(grouping_status="failed"))).forEach { response ->
   val actions=mutableListOf<String>()
   preparedOrLive("source",lookup={actions.add("read");response},live={actions.add("upload-and-run");ready},onUpdate={actions.add("display")})
   assertEquals(listOf("read","upload-and-run"),actions)
  }
 }

 @Test fun olderEndpointCanFallbackButCancellationCannotStartLiveWork()=runBlocking {
  assertEquals(ready,preparedOrLive("source",lookup={throw IOException("404")},live={ready},onUpdate={}))
  var liveStarted=false
  try {
   preparedOrLive("source",lookup={throw CancellationException("Navigated away")},live={liveStarted=true;ready},onUpdate={})
   fail("Expected cancellation")
  } catch(_:CancellationException) { assertFalse(liveStarted) }
 }
}
