package com.connectedgallery.explore

import android.graphics.Bitmap
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.asAndroidBitmap
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.dp
import androidx.test.platform.app.InstrumentationRegistry
import coil3.SingletonImageLoader
import coil3.request.ImageRequest
import com.connectedgallery.coreui.*
import com.connectedgallery.domain.*
import com.connectedgallery.library.*
import java.io.File
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.runBlocking
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test

/** Renders production composables with bundled synthetic photos and offline UI fixtures. */
class GalleryDesignDeviceTest {
    @get:Rule val compose = createComposeRule()
    private val canvas = "사진. 대상을 누르거나 길게 눌러 탐색하세요"
    private val instrumentation = InstrumentationRegistry.getInstrumentation()

    private class Repository(photos: List<Photo>) : GalleryRepository {
        override val photos = MutableStateFlow(photos)
        var searches = 0
        override suspend fun loadJourney() = Journey()
        override suspend fun saveJourney(journey: Journey) {}
        override suspend fun refreshAndSync(progress: (String) -> Unit) {}
        override suspend fun analysis(photoId: String) = Analysis(photoId, regions = listOf(
            Region("bottle", photoId, RegionBox(.16f, .01f, .30f, .94f), "object", "와인")))
        override suspend fun context(photoId: String, retry: Boolean, onUpdate: (ContextState) -> Unit) {
            val group = ResultGroup("scene", "사진 속 다른 장면", "화면 검수용 예시 · 인물과 테이블이 보이는 사진", photos.value.filter { it.id != photoId }.takeLast(3).map { it.id })
            onUpdate(ContextState(photoId, "ready", 1, context = PhotoContext("한 장에서 이어지는 다른 사진을 살펴보세요.", listOf(group))))
        }
        override suspend fun explore(input: ExploreInput, onUpdate: (ExplorationResult) -> Unit): ExplorationResult {
            searches++
            val ids = photos.value.filter { it.id != input.anchor.photo_id }.take(4).map { it.id }
            val result = ExplorationResult("선택한 와인", ids.map { ResultItem(it, "와인병이 보이는 장면") },
                groups = listOf(ResultGroup("wine", "와인병이 보이는 사진", "화면 검수용 예시 · 연결 근거가 이곳에 표시됩니다", ids)), grouping_status = "ready")
            onUpdate(result)
            return result
        }
        override suspend fun cancelExploration() {}
        override suspend fun feedback(kind: String, photoId: String?, regionId: String?, value: String) {}
        override suspend fun metric(name: String, value: String) {}
    }

    private fun repository(): Repository {
        val files = instrumentation.context.assets.list("images")!!.filter { it.endsWith(".jpg") }.sorted()
        val photos = listOf(5, 3, 10, 16, 18, 8, 0, 6, 17).mapIndexed { index, assetIndex ->
            val name = files[assetIndex]
            val file = File(instrumentation.targetContext.cacheDir, name)
            instrumentation.context.assets.open("images/$name").use { input -> file.outputStream().use { input.copyTo(it) } }
            val bounds = android.graphics.BitmapFactory.Options().apply { inJustDecodeBounds = true }
            android.graphics.BitmapFactory.decodeFile(file.absolutePath, bounds)
            Photo("preview-$index", device_id = "synthetic-demo", local_uri = file.absolutePath,
                width = bounds.outWidth, height = bounds.outHeight, time_source = "demo_fixture", captured_at = "2026-09-${if (index < 6) "10" else "09"}T12:00:00+09:00")
        }
        runBlocking {
            val context = instrumentation.targetContext
            photos.forEach { SingletonImageLoader.get(context).execute(ImageRequest.Builder(context).data(it.local_uri).build()) }
        }
        return Repository(photos)
    }

    private fun capture(name: String) {
        compose.waitForIdle()
        val directory = File(instrumentation.targetContext.getExternalFilesDir(null), "design-preview").apply { mkdirs() }
        File(directory, "$name.png").outputStream().use { compose.onRoot().captureToImage().asAndroidBitmap().compress(Bitmap.CompressFormat.PNG, 100, it) }
        println("DESIGN_PREVIEW=${directory.absolutePath}/$name.png")
    }

    @Test fun renderGallerySelectionResultsAndAutomaticContext() {
        val repo = repository()
        lateinit var vm: GalleryViewModel
        compose.runOnIdle { vm = GalleryViewModel(repo) }
        compose.setContent {
            GalleryTheme {
                val journey by vm.journey.collectAsState()
                val photos by repo.photos.collectAsState()
                val libraryState = rememberLibraryState()
                Surface(Modifier.fillMaxSize()) {
                    Column(Modifier.windowInsetsPadding(WindowInsets.safeDrawing)) {
                        if (journey.current == null) {
                            LibraryHeader(photos.size, {}, { IconButton(onClick = {}) { Icon(GalleryIcons.Settings, "설정") } }, libraryState.tab.value)
                            LibraryScreen(photos, vm::open, Modifier.weight(1f), libraryState)
                        } else ExploreScreen(vm, Modifier.weight(1f))
                    }
                }
            }
        }
        compose.onNodeWithText("Connected Gallery").assertIsDisplayed()
        compose.onNodeWithText("홈").assertIsSelected()
        compose.onNodeWithText("최신 날짜순 ↓").assertDoesNotExist()
        capture("01-gallery")
        compose.onNodeWithText("날짜별").performClick().assertIsSelected()
        compose.onNodeWithText("최신 날짜순 ↓").assertIsDisplayed()
        compose.onNodeWithTag("home-grid").assertDoesNotExist()
        val datePhoto = compose.onNodeWithTag("date-photo:preview-0").fetchSemanticsNode().boundsInRoot
        assertEquals(datePhoto.width, datePhoto.height, 1f)
        capture("06-dates")
        compose.onNodeWithTag("date-photo:preview-0").performClick()
        compose.onNodeWithContentDescription("돌아가기").performClick()
        compose.onNodeWithText("날짜별").assertIsSelected()
        compose.onNodeWithText("홈").performClick()
        compose.onNodeWithTag("home-photo:preview-0").performClick()
        compose.onNodeWithText("함께 볼 사진").assertIsDisplayed()
        capture("04-context")
        compose.onNodeWithContentDescription(canvas).performTouchInput { click(androidx.compose.ui.geometry.Offset(width * .30f, height * .5f)) }
        compose.waitUntil(3000) { compose.onAllNodesWithText("이 대상으로 사진 찾기").fetchSemanticsNodes().isNotEmpty() }
        compose.onNodeWithText("이 대상으로 사진 찾기").assertIsDisplayed()
        compose.runOnIdle { assertEquals(0, repo.searches) }
        capture("02-selection")
        compose.onNodeWithText("이 대상으로 사진 찾기").performClick()
        compose.onNodeWithText("연결된 사진").assertIsDisplayed()
        capture("03-results")
        compose.runOnIdle { assertEquals(1, repo.searches) }
    }

    @Test fun manualSelectionRemainsUsableOnSmallScreenWithLargeType() {
        val repo = repository()
        lateinit var vm: GalleryViewModel
        compose.runOnIdle { vm = GalleryViewModel(repo) }
        compose.setContent {
            val density = LocalDensity.current
            CompositionLocalProvider(LocalDensity provides Density(density.density, 1.5f)) {
                GalleryTheme { Surface(Modifier.width(320.dp).height(560.dp)) { ExploreScreen(vm) } }
            }
        }
        compose.runOnIdle { vm.open("preview-0") }
        compose.onNodeWithContentDescription(canvas).performTouchInput { longClick(androidx.compose.ui.geometry.Offset(width * .85f, height * .6f)) }
        compose.onNodeWithText("이 대상으로 사진 찾기").performScrollTo().assertIsDisplayed()
        capture("05-large-type-selection")
        compose.onNodeWithText("이 대상으로 사진 찾기").performClick()
        compose.runOnIdle {
            assertEquals(1, repo.searches)
            assertNotNull(vm.journey.value.current!!.query!!.anchor.box)
        }
    }
}
