package com.connectedgallery.domain
import org.junit.Assert.*
import org.junit.Test
class JourneyTest {
 @Test fun sameMomentIsRetiredFromSavedAndBackNavigation() {
  val old=Journey().open("one").select(SemanticAnchor("one")).modify(null,"same_moment").open("two")
  val migrated=old.withoutTimeFilters()
  assertEquals("related",migrated.current!!.query!!.direction)
  assertTrue(migrated.history.all { it.query==null || it.query.direction=="related" })
  assertNull(migrated.current!!.result)
 }
 @Test fun groupedResultsAndAnchorReturnOnBackWithoutAcceptingLateSecondHop() {
  val a=SemanticAnchor("one",region_id="bottle",box=RegionBox(.1f,.1f,.2f,.6f))
  val result=ExplorationResult("병",listOf(ResultItem("two")),groups=listOf(ResultGroup("same","같은 병","라벨 일치",listOf("two"))),grouping_status="ready")
  val selected=Journey().open("one").select(a)
  val first=selected.accept(selected.revision,result).let { it.copy(current=it.current!!.copy(scrollIndex=2,scrollOffset=15)) }
  val opened=first.open("two")
  val second=opened.select(SemanticAnchor("two",region_id="person"))
  val back=second.back().back()
  assertEquals(first.current,back.current)
  assertEquals(a,back.current!!.query!!.anchor)
  assertEquals(result,back.accept(second.revision,ExplorationResult("late")).current!!.result)
  assertEquals(back,back.select(SemanticAnchor("two",region_id="stale-click")))
 }
 @Test fun retiredTimeFiltersCannotHideInCurrentOrBackStack() {
  val anchor=SemanticAnchor("one",label="대상")
  val all=Journey().open("one").select(anchor).let { it.accept(it.revision,ExplorationResult("all")) }
  val dated=all.modify(2024,"related").let { it.accept(it.revision,ExplorationResult("dated")) }.open("two")
  val migrated=dated.withoutTimeFilters()
  assertNull(migrated.current!!.query!!.year)
  assertNull(migrated.current!!.result)
  assertTrue(migrated.history.none { it.query?.year!=null })
  assertEquals(anchor,migrated.current!!.query!!.anchor)
  assertEquals(all.current,migrated.history[1])
  assertTrue(migrated.revision>dated.revision)
  assertNull(migrated.accept(dated.revision,ExplorationResult("stale")).current!!.result)
  assertEquals(migrated,migrated.withoutTimeFilters())
 }
 @Test fun currentMvpJourneysKeepResultsAndScroll() {
  val journey=Journey(current=Frame("one",ExploreInput(SemanticAnchor("one")),ExplorationResult("saved"),3,12),revision=8)
  assertEquals(journey,journey.withoutTimeFilters())
 }
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
