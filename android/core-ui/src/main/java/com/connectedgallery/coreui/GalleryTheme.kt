package com.connectedgallery.coreui

import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.Font
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

val GalleryInk = Color(0xFF292C29)
val GallerySelection = Color(0xFFE2F4B9)
val GalleryEvidence = Color(0xFF285B4C)
val GalleryFont = FontFamily(
    Font(R.font.suit_regular, FontWeight.Normal),
    Font(R.font.suit_semibold, FontWeight.SemiBold),
    Font(R.font.suit_bold, FontWeight.Bold),
)

private val GalleryColors = lightColorScheme(
    primary = GalleryInk, onPrimary = Color(0xFFF5F3EE),
    primaryContainer = GallerySelection, onPrimaryContainer = GalleryInk,
    secondary = GalleryEvidence, onSecondary = Color.White,
    secondaryContainer = Color(0xFFE1EAE3), onSecondaryContainer = GalleryEvidence,
    tertiary = GalleryEvidence, onTertiary = Color.White,
    tertiaryContainer = Color(0xFFE1EAE3), onTertiaryContainer = GalleryEvidence,
    background = Color(0xFFF5F3EE), onBackground = GalleryInk,
    surface = Color(0xFFF5F3EE), onSurface = GalleryInk,
    surfaceVariant = Color(0xFFECEAE4), onSurfaceVariant = Color(0xFF646962),
    surfaceContainer = Color(0xFFECEAE4), surfaceContainerHigh = Color(0xFFE5E4DC),
    outline = Color(0xFF777D73), outlineVariant = Color(0xFFD7DBD1),
    error = Color(0xFFA63E34), onError = Color.White,
)

@Composable fun GalleryTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = GalleryColors,
        typography = Typography(
            displayLarge = TextStyle(fontFamily = GalleryFont, fontWeight = FontWeight.SemiBold, fontSize = 48.sp, lineHeight = 58.sp),
            displayMedium = TextStyle(fontFamily = GalleryFont, fontWeight = FontWeight.SemiBold, fontSize = 40.sp, lineHeight = 50.sp),
            displaySmall = TextStyle(fontFamily = GalleryFont, fontWeight = FontWeight.SemiBold, fontSize = 36.sp, lineHeight = 46.sp),
            headlineLarge = TextStyle(fontFamily = GalleryFont, fontWeight = FontWeight.SemiBold, fontSize = 30.sp, lineHeight = 38.sp, letterSpacing = (-0.6).sp),
            headlineMedium = TextStyle(fontFamily = GalleryFont, fontWeight = FontWeight.SemiBold, fontSize = 26.sp, lineHeight = 34.sp),
            headlineSmall = TextStyle(fontFamily = GalleryFont, fontWeight = FontWeight.SemiBold, fontSize = 24.sp, lineHeight = 32.sp),
            titleLarge = TextStyle(fontFamily = GalleryFont, fontWeight = FontWeight.SemiBold, fontSize = 21.sp, lineHeight = 29.sp),
            titleMedium = TextStyle(fontFamily = GalleryFont, fontWeight = FontWeight.SemiBold, fontSize = 16.sp, lineHeight = 24.sp),
            titleSmall = TextStyle(fontFamily = GalleryFont, fontWeight = FontWeight.SemiBold, fontSize = 14.sp, lineHeight = 22.sp),
            bodyLarge = TextStyle(fontFamily = GalleryFont, fontSize = 16.sp, lineHeight = 25.sp),
            bodyMedium = TextStyle(fontFamily = GalleryFont, fontSize = 15.sp, lineHeight = 23.sp),
            bodySmall = TextStyle(fontFamily = GalleryFont, fontSize = 12.sp, lineHeight = 19.sp),
            labelLarge = TextStyle(fontFamily = GalleryFont, fontWeight = FontWeight.SemiBold, fontSize = 14.sp, lineHeight = 20.sp),
            labelMedium = TextStyle(fontFamily = GalleryFont, fontWeight = FontWeight.SemiBold, fontSize = 12.sp, lineHeight = 18.sp),
            labelSmall = TextStyle(fontFamily = GalleryFont, fontSize = 11.sp, lineHeight = 16.sp),
        ),
        shapes = Shapes(small = RoundedCornerShape(8.dp), medium = RoundedCornerShape(16.dp), large = RoundedCornerShape(24.dp)),
        content = content,
    )
}
