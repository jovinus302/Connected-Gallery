package com.connectedgallery.coreui
import org.junit.Assert.*
import org.junit.Test
class CoordinateTest {
 @Test fun inverseZoomAndPan() {
  val p=normalizedPoint(450f,180f,1000f,500f,2f,2f,50f,-20f)
  assertEquals(.2f,p.first,.0001f);assertEquals(.2f,p.second,.0001f)
 }
 @Test fun centerPivot() {
  val p=normalizedPoint(500f,250f,1000f,500f,3f,3f,0f,0f,500f,250f)
  assertEquals(.5f,p.first,.0001f);assertEquals(.5f,p.second,.0001f)
 }
}
