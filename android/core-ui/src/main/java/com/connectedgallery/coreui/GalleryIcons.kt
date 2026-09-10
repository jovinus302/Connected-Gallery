package com.connectedgallery.coreui

import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.StrokeJoin
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.graphics.vector.PathBuilder
import androidx.compose.ui.graphics.vector.path
import androidx.compose.ui.unit.dp

object GalleryIcons {
    private fun line(name: String, block: PathBuilder.() -> Unit) = ImageVector.Builder(
        name, 24.dp, 24.dp, 24f, 24f, autoMirror = true,
    ).apply {
        path(fill = null, stroke = SolidColor(Color.Black), strokeLineWidth = 1.7f,
            strokeLineCap = StrokeCap.Round, strokeLineJoin = StrokeJoin.Round, pathBuilder = block)
    }.build()

    val Back = line("Back") { moveTo(19f, 12f); lineTo(5f, 12f); moveTo(11f, 5f); lineTo(4f, 12f); lineTo(11f, 19f) }
    val Next = line("Next") { moveTo(9f, 5f); lineTo(16f, 12f); lineTo(9f, 19f) }
    val Close = line("Close") { moveTo(6f, 6f); lineTo(18f, 18f); moveTo(18f, 6f); lineTo(6f, 18f) }
    val Settings = line("Settings") {
        moveTo(4f, 7f); lineTo(8f, 7f); moveTo(12f, 7f); lineTo(20f, 7f)
        moveTo(4f, 17f); lineTo(13f, 17f); moveTo(17f, 17f); lineTo(20f, 17f)
        moveTo(8f, 4f); lineTo(12f, 4f); lineTo(12f, 10f); lineTo(8f, 10f); close()
        moveTo(13f, 14f); lineTo(17f, 14f); lineTo(17f, 20f); lineTo(13f, 20f); close()
    }
    val Photo = line("Photo") {
        moveTo(4f, 3f); lineTo(20f, 3f); lineTo(20f, 21f); lineTo(4f, 21f); close()
        moveTo(4f, 16f); lineTo(10f, 10f); lineTo(15f, 15f); lineTo(17f, 13f); lineTo(20f, 16f)
        moveTo(16f, 7f); lineTo(16.1f, 7f)
    }
}
