package com.connectedgallery.coreui

import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.FastOutSlowInEasing
import androidx.compose.animation.core.tween
import androidx.compose.foundation.layout.Box
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.unit.dp

/** Short arrival motion, driven by real content. Compose respects the system animator duration scale. */
@Composable fun GalleryReveal(contentKey: Any?, modifier: Modifier = Modifier, content: @Composable () -> Unit) {
    val progress = remember(contentKey) { Animatable(0f) }
    LaunchedEffect(contentKey) { progress.animateTo(1f, tween(240, easing = FastOutSlowInEasing)) }
    Box(modifier.graphicsLayer {
        alpha = progress.value
        translationY = (1f - progress.value) * 12.dp.toPx()
    }) { content() }
}
