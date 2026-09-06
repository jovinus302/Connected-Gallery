package com.connectedgallery.domain
import org.junit.Assert.*
import org.junit.Test
class JourneyTest {
 @Test fun yearRetainsAnchorAndNewTapResetsModifiers() {
  val a=SemanticAnchor("one",label="이 사람",kind="person")
  val journey=Journey().open("one").select(a).modify(2015,"related")
  assertEquals(a,journey.current!!.query!!.anchor)
  val opened=journey.open("two")
  assertEquals(2015,opened.current!!.query!!.year)
  val next=opened.select(SemanticAnchor("two",label="해변",kind="place"))
  assertNull(next.current!!.query!!.year)
  assertEquals("related",next.current!!.query!!.direction)
  assertEquals(opened.current,next.back().current)
 }
 @Test fun staleResultsNeverOverwriteNewQuery() {
  val first=Journey().open("one").select(SemanticAnchor("one"))
  val changed=first.modify(2015,"related")
  assertNull(changed.accept(first.revision,ExplorationResult("old")).current!!.result)
  assertEquals("new",changed.accept(changed.revision,ExplorationResult("new")).current!!.result!!.label)
 }
}
