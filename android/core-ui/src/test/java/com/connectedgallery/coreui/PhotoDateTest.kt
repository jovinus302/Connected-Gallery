package com.connectedgallery.coreui

import com.connectedgallery.domain.Photo
import java.time.LocalDate
import org.junit.Assert.*
import org.junit.Test

class PhotoDateTest {
    @Test fun captureDatesUseTheContextTimezoneAcrossMidnight() {
        val photo = Photo("p", captured_at = "2026-09-09T16:30:00Z", time_source = "media_store")
        assertEquals(LocalDate.of(2026, 9, 10), photo.galleryDate())
    }

    @Test fun modifiedUnknownAndUnzonedDatesDoNotBecomeCaptureDates() {
        val photo = Photo("p", captured_at = "2026-09-09T16:30:00Z")
        assertNull(photo.galleryDate())
        assertNull(photo.copy(time_source = "modified").galleryDate())
        assertNull(photo.copy(time_source = "exif", captured_at = "2026-09-10T12:00:00").galleryDate())
        assertNull(photo.copy(time_source = "exif", captured_at = null).galleryDate())
    }

    @Test fun demoDateRequiresTheSyntheticDevice() {
        val photo = Photo("p", captured_at = "2026-09-10T12:00:00+09:00", time_source = "demo_fixture")
        assertNull(photo.galleryDate())
        assertEquals(LocalDate.of(2026, 9, 10), photo.copy(device_id = "synthetic-demo").galleryDate())
    }
}
