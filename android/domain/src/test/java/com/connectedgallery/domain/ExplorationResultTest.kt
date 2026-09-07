package com.connectedgallery.domain

import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import org.junit.Assert.*
import org.junit.Test

class ExplorationResultTest {
 private val json=Json { ignoreUnknownKeys=true }
 private val grouped=ExplorationResult("병",listOf(ResultItem("a","라벨 확인"),ResultItem("b","병 모양")),
  groups=listOf(ResultGroup("same","같은 라벨","제품명이 일치해요",listOf("a")),ResultGroup("similar","비슷한 병","외형이 비슷해요",listOf("b"))),grouping_status="ready")

 @Test fun oldFlatResultsRemainReadable() {
  val result=json.decodeFromString<ExplorationResult>("""{"label":"연결","items":[{"photo_id":"a"}],"complete":true}""")
  assertEquals("legacy",result.grouping_status)
  assertEquals(listOf("a"),result.items.map { it.photo_id })
  assertFalse(result.hasValidGroups())
  assertEquals(result,result.forAnchor("source"))
 }

 @Test fun groupsAndReasonsSurviveSerialization() {
  val result=json.decodeFromString<ExplorationResult>(json.encodeToString(grouped))
  assertEquals(grouped,result)
  assertTrue(result.hasValidGroups())
 }

 @Test fun onlyAnExactPartitionCanBePresentedAsOrganized() {
  val invalid=listOf(
   grouped.copy(groups=grouped.groups.take(1)),
   grouped.copy(groups=grouped.groups+ResultGroup("extra","다른 것","근거",listOf("outside"))),
   grouped.copy(groups=grouped.groups.map { it.copy(photo_ids=listOf("a")) }),
   grouped.copy(groups=grouped.groups.map { it.copy(id="duplicate") }),
   grouped.copy(groups=grouped.groups.map { it.copy(reason="") })
  )
  invalid.forEach { result ->
   assertFalse(result.hasValidGroups())
   val safe=result.forAnchor("source")
   assertEquals(grouped.items,safe.items)
   assertEquals("failed",safe.grouping_status)
   assertFalse(safe.complete)
   assertTrue(safe.groups.isEmpty())
  }
 }

 @Test fun failedGroupingAndPartialResultsCannotBeReady() {
  val failed=grouped.copy(grouping_status="failed").forAnchor("source")
  assertEquals(grouped.items,failed.items)
  assertFalse(failed.complete)
  assertNull(PreparedExploration("ready",7,failed).readyResult("source"))
  assertNull(PreparedExploration("ready",7,grouped.copy(complete=false)).readyResult("source"))
  assertNull(PreparedExploration("pending",7,grouped).readyResult("source"))
  assertNull(PreparedExploration("ready",7,ExplorationResult()).readyResult("source"))
 }

 @Test fun readyEmptyResultsAreDistinctFromPending() {
  val empty=ExplorationResult(grouping_status="ready")
  assertEquals(empty,PreparedExploration("ready",7,empty).readyResult("source"))
  assertNull(PreparedExploration("pending",7).readyResult("source"))
 }

 @Test fun anchorLeaksCannotBecomeReadyOrStayInDisplayItems() {
  assertNull(PreparedExploration("ready",7,grouped).readyResult("a"))
  val safe=grouped.forAnchor("a")
  assertEquals(listOf("b"),safe.items.map { it.photo_id })
  assertEquals("failed",safe.grouping_status)
 }
}
