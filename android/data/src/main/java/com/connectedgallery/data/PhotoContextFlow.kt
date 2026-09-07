package com.connectedgallery.data

import com.connectedgallery.domain.ContextState
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.delay

/** Opening a photo starts missing work once; failed work requires an explicit retry. */
internal suspend fun loadPhotoContext(
 photoId:String,retry:Boolean=false,
 read:suspend ()->ContextState,prepare:suspend ()->ContextState,
 pause:suspend ()->Unit={delay(1500)},publish:(ContextState)->Unit
) {
 try {
  val preparedRevisions=mutableSetOf<Long>()
  var value=read().validatedFor(photoId)
  publish(value)
  if(value.state=="pending" || (retry && value.state=="failed")) {
   preparedRevisions.add(value.revision)
   value=prepare().validatedFor(photoId)
   publish(value)
  }
  while(value.state in setOf("pending","running")) {
   pause()
   value=read().validatedFor(photoId)
   publish(value)
   // A changed gallery snapshot is a new preparation, never an empty result.
   if(value.state=="pending") {
    check(preparedRevisions.add(value.revision)) { "Preparation did not start" }
    value=prepare().validatedFor(photoId)
    publish(value)
   }
  }
 } catch(e:CancellationException) { throw e }
 catch(_:Exception) { publish(ContextState(photoId,state="offline")) }
}
