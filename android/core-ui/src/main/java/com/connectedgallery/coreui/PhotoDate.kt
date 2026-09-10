package com.connectedgallery.coreui

import com.connectedgallery.domain.Photo
import java.time.LocalDate
import java.time.OffsetDateTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.Locale

/** Match the photo-context contract; file modification time is not a capture date. */
fun Photo.galleryDate(): LocalDate? {
    if (time_source !in setOf("exif", "media_store") &&
        !(time_source == "demo_fixture" && device_id == "synthetic-demo")) return null
    return runCatching {
        OffsetDateTime.parse(captured_at).atZoneSameInstant(ZoneId.of("Asia/Seoul")).toLocalDate()
    }.getOrNull()
}

fun LocalDate.galleryLabel(): String = format(DateTimeFormatter.ofPattern("yyyy년 M월 d일", Locale.KOREAN))
