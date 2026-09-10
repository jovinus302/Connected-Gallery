package com.connectedgallery.data

import com.connectedgallery.domain.PhotoRefreshFailure
import kotlinx.coroutines.CancellationException

internal suspend fun <T> refreshStage(message: String, action: suspend () -> T): T = try {
 action()
} catch (e: CancellationException) {
 throw e
} catch (e: PhotoRefreshFailure) {
 throw e
} catch (e: Exception) {
 throw PhotoRefreshFailure(message, e)
}
