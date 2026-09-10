package com.connectedgallery.coreui

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.unit.dp
import coil3.compose.AsyncImage
import com.connectedgallery.domain.Photo
import com.connectedgallery.domain.RegionBox

/** Fit both image and outline to the same bounds, retaining the actual selected search region. */
@Composable fun AnchorThumbnail(photo: Photo, region: RegionBox?, modifier: Modifier = Modifier) {
    BoxWithConstraints(modifier.background(GalleryInk), contentAlignment = Alignment.Center) {
        val ratio = photo.width.toFloat().coerceAtLeast(1f) / photo.height.coerceAtLeast(1)
        val fit = if (ratio > maxWidth.value / maxHeight.value) Modifier.fillMaxWidth().aspectRatio(ratio)
            else Modifier.fillMaxHeight().aspectRatio(ratio)
        Box(fit) {
            AsyncImage(photo.local_uri, "선택한 대상의 원본 사진", contentScale = ContentScale.FillBounds, modifier = Modifier.fillMaxSize())
            Canvas(Modifier.fillMaxSize()) {
                region?.let { box ->
                    val origin = Offset(box.x * size.width, box.y * size.height)
                    val bounds = Size(box.width * size.width, box.height * size.height)
                    drawRect(GalleryInk, origin, bounds, style = Stroke(4.dp.toPx()))
                    drawRect(GallerySelection, origin, bounds, style = Stroke(1.5.dp.toPx()))
                }
            }
        }
    }
}
