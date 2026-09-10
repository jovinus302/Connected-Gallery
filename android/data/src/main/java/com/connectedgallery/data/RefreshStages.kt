package com.connectedgallery.data

import com.connectedgallery.domain.PhotoRefreshFailure
import kotlinx.coroutines.CancellationException

internal suspend fun <T> refreshStage(message: String, action: suspend () -> T): T = try {
 action()
} catch (e: CancellationException) {
 throw e
} catch (e: PhotoRefreshFailure) {
 throw e
} catch (e: ServerRequestFailure) {
 throw PhotoRefreshFailure("$message\n${e.message}", e)
} catch (e: Exception) {
 throw PhotoRefreshFailure(message, e)
}

internal class ServerRequestFailure(message: String) : java.io.IOException(message)

internal fun serverResponseFailure(code: Int) = ServerRequestFailure(when(code) {
 401, 403 -> "서버 접속 키를 확인해 주세요"
 else -> "분석 서버에서 오류가 발생했어요 ($code)"
})
