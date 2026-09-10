package com.connectedgallery.explore

import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.StateRestorationTester
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.dp
import com.connectedgallery.coreui.GalleryTheme
import com.connectedgallery.domain.Photo
import com.connectedgallery.library.*
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test

class LibraryNavigationDeviceTest {
    @get:Rule val compose = createComposeRule()
    private val photos = (0 until 100).map {
        Photo("photo-$it", width = 400, height = 400, time_source = "exif",
            captured_at = "2026-09-${if (it < 50) "10" else "09"}T12:00:00+09:00")
    }

    @Test fun eachTabRestoresItsScrollAfterOpeningPhotoAndRecreation() {
        val restoration = StateRestorationTester(compose)
        lateinit var state: LibraryState
        restoration.setContent {
            GalleryTheme {
                state = rememberLibraryState()
                var opened by rememberSaveable { mutableStateOf<String?>(null) }
                Surface(Modifier.fillMaxSize()) {
                    if (opened == null) LibraryScreen(photos, { opened = it }, state = state)
                    else Column { Text(opened!!); Button(onClick = { opened = null }) { Text("사진 닫기") } }
                }
            }
        }
        compose.onNodeWithTag("home-grid").performScrollToIndex(24)
        val homePosition = compose.runOnIdle { state.homeScroll.firstVisibleItemIndex to state.homeScroll.firstVisibleItemScrollOffset }
        compose.onNodeWithText("날짜별").performClick()
        compose.onNodeWithTag("dates-grid").performScrollToIndex(26)
        val datePosition = compose.runOnIdle { state.datesScroll.firstVisibleItemIndex to state.datesScroll.firstVisibleItemScrollOffset }
        compose.onAllNodes(hasTestTag("date-photo:photo-24")).onFirst().performClick()
        compose.onNodeWithText("photo-24").assertIsDisplayed()
        compose.onNodeWithText("사진 닫기").performClick()
        compose.onNodeWithText("날짜별").assertIsSelected()
        compose.runOnIdle { assertEquals(datePosition, state.datesScroll.firstVisibleItemIndex to state.datesScroll.firstVisibleItemScrollOffset) }
        restoration.emulateSavedInstanceStateRestore()
        compose.onNodeWithText("날짜별").assertIsSelected()
        compose.runOnIdle { assertEquals(datePosition, state.datesScroll.firstVisibleItemIndex to state.datesScroll.firstVisibleItemScrollOffset) }
        compose.onNodeWithText("홈").performClick()
        compose.runOnIdle { assertEquals(homePosition, state.homeScroll.firstVisibleItemIndex to state.homeScroll.firstVisibleItemScrollOffset) }
    }

    @Test fun datesStayNewestFirstAndUnknownDateStaysSeparate() {
        val mixed = listOf(photos.last(), photos.first(), Photo("unknown"))
        compose.setContent { GalleryTheme { LibraryScreen(mixed, {}) } }
        compose.onNodeWithText("2026년 9월 10일").assertDoesNotExist()
        compose.onNodeWithText("날짜별").performClick()
        val latest = compose.onNodeWithText("2026년 9월 10일").fetchSemanticsNode().boundsInRoot.top
        val older = compose.onNodeWithText("2026년 9월 9일").fetchSemanticsNode().boundsInRoot.top
        val unknown = compose.onNodeWithText("촬영일을 알 수 없는 사진").fetchSemanticsNode().boundsInRoot.top
        assertTrue(latest < older && older < unknown)
        compose.onNodeWithText("홈").performClick()
        compose.onNodeWithTag("dates-grid").assertDoesNotExist()
    }

    @Test fun tabsAndPhotosRemainReachableWithLargeKoreanType() {
        compose.setContent {
            val density = LocalDensity.current
            CompositionLocalProvider(LocalDensity provides Density(density.density, 1.5f)) {
                GalleryTheme {
                    val state = rememberLibraryState()
                    Surface(Modifier.width(320.dp).height(640.dp)) {
                        Column {
                            LibraryHeader(photos.size, {}, {}, state.tab.value)
                            LibraryScreen(photos, {}, Modifier.weight(1f), state)
                        }
                    }
                }
            }
        }
        compose.onNodeWithText("Connected Gallery").assertIsDisplayed()
        compose.onNodeWithText("사진 연결").assertIsDisplayed()
        compose.onNodeWithTag("home-photo:photo-0").assertIsDisplayed()
        compose.onNodeWithText("날짜별").performClick().assertIsSelected()
        compose.onNodeWithTag("date-photo:photo-0").assertIsDisplayed()
    }
}
