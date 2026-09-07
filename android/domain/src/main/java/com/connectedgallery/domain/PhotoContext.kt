package com.connectedgallery.domain

import kotlinx.serialization.Serializable

@Serializable data class CaptureMetadata(val value:String,val source:String,val timezone:String,val date:String)
@Serializable data class PhotoContext(val summary:String,val groups:List<ResultGroup> = emptyList())
@Serializable data class ContextState(
 val photo_id:String,val state:String="pending",val revision:Long=0,
 val capture:CaptureMetadata?=null,val context:PhotoContext?=null,val run_id:String?=null
) {
 fun validatedFor(photoId:String):ContextState {
  require(photo_id==photoId) { "Context belongs to another photo" }
  require(state in setOf("pending","running","ready","empty","failed"))
  if(state in setOf("ready","empty")) {
   val value=requireNotNull(context)
   require(value.summary.isNotBlank() && value.groups.size<=8)
   require((state=="empty")==value.groups.isEmpty())
   require(value.groups.map { it.id }.distinct().size==value.groups.size)
   require(value.groups.sumOf { it.photo_ids.size }<=24)
   require(value.groups.all { group ->
    group.id.isNotBlank() && group.title.isNotBlank() && group.reason.isNotBlank() &&
     group.photo_ids.isNotEmpty() && group.photo_ids.distinct().size==group.photo_ids.size && photoId !in group.photo_ids
   })
  } else require(context==null)
  return this
 }
}
