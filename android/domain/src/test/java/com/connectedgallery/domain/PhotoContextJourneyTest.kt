package com.connectedgallery.domain

import kotlinx.serialization.json.Json
import kotlinx.serialization.encodeToString
import org.junit.Assert.*
import org.junit.Test

class PhotoContextJourneyTest {
 @Test fun previousVersionsInheritedQueryCannotReplaceOpenedPhotoContext() {
  val inherited=Journey(current=Frame("b",query=ExploreInput(SemanticAnchor("a")),result=ExplorationResult("old a")))
  val migrated=inherited.withoutTimeFilters()
  assertNull(migrated.current!!.query);assertNull(migrated.current!!.result)
  assertEquals("b",migrated.current!!.photoId)
 }
 @Test fun photoChangesResetQueryAndContextAndBackRestoresGroupAndScroll() {
  val context=ContextState("a","ready",2,context=PhotoContext("보이는 장면",listOf(ResultGroup("g","함께 찍은 사진","확인한 장면",listOf("b")))))
  val start=Journey(current=Frame("a",context=context,scrollIndex=2,scrollOffset=17,rowPositions=mapOf("g" to 3)))
  val focused=start.focus("g")
  val next=focused.open("b")
  assertNull(next.current!!.query);assertNull(next.current!!.context)
  assertEquals(focused.current,next.back().current)
  val restored=next.back().back()
  assertEquals(start.current,restored.current)
  assertEquals(restored,Json.decodeFromString<Journey>(Json.encodeToString(restored)))
 }
 @Test fun contextCanOverlapButCannotContainSourceOrDuplicateMembership() {
  val group=ResultGroup("g","장면","눈으로 확인",listOf("b"))
  val value=ContextState("a","ready",context=PhotoContext("함께 보기",listOf(group,group.copy(id="second"))))
  assertEquals(value,value.validatedFor("a"))
  for(ids in listOf(listOf("a"),listOf("b","b"),emptyList())) {
   try { value.copy(context=PhotoContext("장면",listOf(group.copy(photo_ids=ids)))).validatedFor("a");fail("Invalid context") }
   catch(_:IllegalArgumentException) { }
  }
 }
}
