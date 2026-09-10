package com.connectedgallery.coreui

import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

val GalleryInk = Color(0xFF171A17)
val GallerySelection = Color(0xFFD3E2B5)

private val GalleryColors = lightColorScheme(
    primary = Color(0xFF526B51), onPrimary = Color.White,
    primaryContainer = Color(0xFFE6ECDF), onPrimaryContainer = Color(0xFF31452E),
    secondary = Color(0xFF65715E), onSecondary = Color.White,
    secondaryContainer = Color(0xFFE6ECDF), onSecondaryContainer = Color(0xFF31452E),
    tertiary = Color(0xFF596C60), onTertiary = Color.White,
    tertiaryContainer = Color(0xFFE1EBE2), onTertiaryContainer = Color(0xFF304739),
    background = Color(0xFFFAF9F6), onBackground = GalleryInk,
    surface = Color(0xFFFAF9F6), onSurface = GalleryInk,
    surfaceVariant = Color(0xFFF0F0E9), onSurfaceVariant = Color(0xFF65685F),
    surfaceContainer = Color(0xFFF1F1EA), surfaceContainerHigh = Color(0xFFECEDE5),
    outline = Color(0xFF81867A), outlineVariant = Color(0xFFE2E4DA),
    error = Color(0xFFA63E34), onError = Color.White,
)

@Composable fun GalleryTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = GalleryColors,
        typography = Typography(
            headlineLarge = TextStyle(fontFamily = FontFamily.SansSerif, fontWeight = FontWeight.SemiBold, fontSize = 32.sp, lineHeight = 40.sp, letterSpacing = (-1).sp),
            headlineMedium = TextStyle(fontWeight = FontWeight.SemiBold, fontSize = 26.sp, lineHeight = 34.sp, letterSpacing = (-0.6).sp),
            titleLarge = TextStyle(fontWeight = FontWeight.SemiBold, fontSize = 21.sp, lineHeight = 29.sp),
            titleMedium = TextStyle(fontWeight = FontWeight.SemiBold, fontSize = 16.sp, lineHeight = 24.sp),
            titleSmall = TextStyle(fontWeight = FontWeight.SemiBold, fontSize = 14.sp, lineHeight = 22.sp),
            bodyLarge = TextStyle(fontSize = 16.sp, lineHeight = 25.sp),
            bodyMedium = TextStyle(fontSize = 14.sp, lineHeight = 22.sp),
            bodySmall = TextStyle(fontSize = 12.sp, lineHeight = 19.sp),
            labelLarge = TextStyle(fontWeight = FontWeight.Medium, fontSize = 14.sp, lineHeight = 20.sp),
            labelMedium = TextStyle(fontWeight = FontWeight.Medium, fontSize = 12.sp, lineHeight = 18.sp),
            labelSmall = TextStyle(fontSize = 11.sp, lineHeight = 16.sp),
        ),
        shapes = Shapes(small = RoundedCornerShape(8.dp), medium = RoundedCornerShape(16.dp), large = RoundedCornerShape(24.dp)),
        content = content,
    )
}
