package com.connectedgallery.data

import com.connectedgallery.domain.ExplorationResult
import com.connectedgallery.domain.PreparedExploration
import kotlinx.coroutines.CancellationException

internal suspend fun preparedOrLive(
 anchorPhotoId:String,
 lookup:suspend ()->PreparedExploration,
 live:suspend ()->ExplorationResult,
 onUpdate:(ExplorationResult)->Unit
):ExplorationResult {
 val prepared=try { lookup().readyResult(anchorPhotoId) }
 catch(e:CancellationException){throw e}
 // Older servers can omit the additive endpoint; continue with their live exploration path.
 catch(_:Exception){null}
 if(prepared!=null) { onUpdate(prepared);return prepared }
 return live()
}
