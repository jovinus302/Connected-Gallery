package com.connectedgallery.data

import com.connectedgallery.domain.PhotoRefreshFailure
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.runBlocking
import org.junit.Assert.*
import org.junit.Test
import java.io.IOException

class RefreshStagesTest {
 @Test fun localFailureStopsBeforeServerStage() = runBlocking {
  var serverCalled=false
  val cause=IOException("local read failed")
  try {
   refreshStage("local") { throw cause }
   refreshStage("server") { serverCalled=true }
   fail("Expected failure")
  } catch(e:PhotoRefreshFailure) {
   assertEquals("local",e.userMessage)
   assertSame(cause,e.cause)
   assertFalse(serverCalled)
  }
 }
 @Test fun serverFailurePreservesLocalResult() = runBlocking {
  val local=mutableListOf<String>()
  refreshStage("local") { local.add("photo") }
  try {
   refreshStage("server") { throw IOException("offline") }
   fail("Expected failure")
  } catch(e:PhotoRefreshFailure) {
   assertEquals("server",e.userMessage)
   assertEquals(listOf("photo"),local)
  }
 }
 @Test fun cancellationIsNotReportedAsFailure() = runBlocking {
  val cancellation=CancellationException("cancelled")
  try {
   refreshStage("failure") { throw cancellation }
   fail("Expected cancellation")
  } catch(e:CancellationException) { assertSame(cancellation,e) }
 }
}
