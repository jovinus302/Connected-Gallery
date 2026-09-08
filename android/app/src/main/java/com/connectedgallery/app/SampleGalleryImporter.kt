package com.connectedgallery.app

import android.Manifest
import android.content.ContentResolver
import android.content.ContentUris
import android.content.ContentValues
import android.content.Context
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Environment
import android.provider.MediaStore
import androidx.annotation.RequiresApi
import java.io.InputStream
import java.security.MessageDigest
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext

/** Only image bytes are bundled in the debug source set; no gallery or analysis records are seeded. */
object SampleGalleryImporter {
 private const val assetDirectory="sample-gallery"
 private val sampleName=Regex("cg_sample_\\d{2}\\.png")
 private val importLock=Mutex()

 data class Result(val added:Int,val existing:Int)
 private data class StoredImage(val uri:Uri,val pending:Boolean)

 fun available(context:Context):Boolean=Build.VERSION.SDK_INT>=29 && sampleFiles(context).isNotEmpty()

 fun hasPhotoAccess(context:Context):Boolean {
  val permission=if(Build.VERSION.SDK_INT>=33)Manifest.permission.READ_MEDIA_IMAGES else Manifest.permission.READ_EXTERNAL_STORAGE
  return context.checkSelfPermission(permission)==PackageManager.PERMISSION_GRANTED ||
   (Build.VERSION.SDK_INT>=34 && context.checkSelfPermission(Manifest.permission.READ_MEDIA_VISUAL_USER_SELECTED)==PackageManager.PERMISSION_GRANTED)
 }

 suspend fun importSamples(context:Context,onProgress:suspend (Int,Int)->Unit):Result=withContext(Dispatchers.IO) {
  importLock.withLock {
   if(Build.VERSION.SDK_INT>=29) {
    check(hasPhotoAccess(context)) { "샘플을 갤러리에서 보려면 사진 접근을 허용해 주세요" }
    importImages(context,onProgress)
   } else error("샘플 사진 추가는 Android 10 이상에서 사용할 수 있어요")
  }
 }

 private fun sampleFiles(context:Context):List<String> =
  context.assets.list(assetDirectory).orEmpty().filter { sampleName.matches(it) }.sorted()

 @RequiresApi(29)
 private suspend fun importImages(context:Context,onProgress:suspend (Int,Int)->Unit):Result {
  val files=sampleFiles(context)
  check(files.isNotEmpty()) { "이 앱에는 샘플 사진이 포함되어 있지 않아요" }
  val resolver=context.contentResolver
  val collection=MediaStore.Images.Media.getContentUri(MediaStore.VOLUME_EXTERNAL_PRIMARY)
  val path="${Environment.DIRECTORY_PICTURES}/ConnectedGallerySamples/"
  val existing=findImages(resolver,collection,path)
  var added=0
  var skipped=0
  onProgress(0,files.size)
  for((index,name) in files.withIndex()) {
   currentCoroutineContext().ensureActive()
   val matches=existing[name].orEmpty()
   val published=matches.filterNot { it.pending }
   if(published.isNotEmpty()) {
    // A matching filename must never cause a different existing photo to be overwritten.
    val expected=context.assets.open("$assetDirectory/$name").use(::digest)
    check(published.all { image -> resolver.openInputStream(image.uri)?.use(::digest)?.contentEquals(expected)==true }) {
     "샘플 폴더에 같은 이름의 다른 사진이 있어요. 기존 사진을 유지한 채 추가를 멈췄어요"
    }
    skipped++
   } else {
    check(matches.size<=1) { "샘플 폴더의 미완료 사진을 확인할 수 없어요" }
    val unfinished=matches.singleOrNull()
    if(unfinished!=null) {
     check(owner(resolver,unfinished.uri)==context.packageName) { "이전에 추가하던 사진의 소유권을 확인할 수 없어요" }
    }
    val uri=unfinished?.uri ?: resolver.insert(collection,ContentValues().apply {
     put(MediaStore.Images.Media.DISPLAY_NAME,name)
     put(MediaStore.Images.Media.MIME_TYPE,"image/png")
     put(MediaStore.Images.Media.RELATIVE_PATH,path)
     put(MediaStore.Images.Media.IS_PENDING,1)
    }) ?: error("샘플 사진을 저장할 공간을 만들지 못했어요")
    try {
     context.assets.open("$assetDirectory/$name").use { input ->
      val output=resolver.openOutputStream(uri,"wt") ?: error("샘플 사진을 저장할 수 없어요")
      output.use { input.copyTo(it) }
     }
     currentCoroutineContext().ensureActive()
     check(resolver.update(uri,ContentValues().apply { put(MediaStore.Images.Media.IS_PENDING,0) },null,null)==1) {
      "저장한 샘플 사진을 갤러리에 표시하지 못했어요"
     }
     added++
    } catch(error:Exception) {
     // Only our unpublished insertion is removed; previously published photos are never changed.
     runCatching { resolver.delete(uri,null,null) }.exceptionOrNull()?.let(error::addSuppressed)
     throw error
    }
   }
   onProgress(index+1,files.size)
  }
  return Result(added,skipped)
 }

 @RequiresApi(29)
 private fun findImages(resolver:ContentResolver,collection:Uri,path:String):Map<String,List<StoredImage>> {
  val columns=arrayOf(MediaStore.Images.Media._ID,MediaStore.Images.Media.DISPLAY_NAME,MediaStore.Images.Media.IS_PENDING)
  val selection="${MediaStore.Images.Media.RELATIVE_PATH} = ?"
  val cursor=if(Build.VERSION.SDK_INT>=30) {
   resolver.query(collection,columns,Bundle().apply {
    putString(ContentResolver.QUERY_ARG_SQL_SELECTION,selection)
    putStringArray(ContentResolver.QUERY_ARG_SQL_SELECTION_ARGS,arrayOf(path))
    putInt(MediaStore.QUERY_ARG_MATCH_PENDING,MediaStore.MATCH_INCLUDE)
   },null)
  } else {
   @Suppress("DEPRECATION")
   resolver.query(MediaStore.setIncludePending(collection),columns,selection,arrayOf(path),null)
  } ?: error("기존 샘플 사진을 확인하지 못했어요")
  val result=mutableMapOf<String,MutableList<StoredImage>>()
  cursor.use {
   while(it.moveToNext()) {
    val name=it.getString(1)
    if(sampleName.matches(name))result.getOrPut(name) { mutableListOf() }.add(StoredImage(ContentUris.withAppendedId(collection,it.getLong(0)),it.getInt(2)!=0))
   }
  }
  return result
 }

 @RequiresApi(29)
 private fun owner(resolver:ContentResolver,uri:Uri):String? {
  val columns=arrayOf(MediaStore.Images.Media.OWNER_PACKAGE_NAME)
  val cursor=if(Build.VERSION.SDK_INT>=30) {
   resolver.query(uri,columns,Bundle().apply { putInt(MediaStore.QUERY_ARG_MATCH_PENDING,MediaStore.MATCH_INCLUDE) },null)
  } else {
   @Suppress("DEPRECATION")
   resolver.query(MediaStore.setIncludePending(uri),columns,null,null,null)
  }
  return cursor?.use {
   if(it.moveToFirst())it.getString(0) else null
  }
 }

 private fun digest(input:InputStream):ByteArray {
  val hash=MessageDigest.getInstance("SHA-256")
  val buffer=ByteArray(DEFAULT_BUFFER_SIZE)
  while(true) {
   val count=input.read(buffer)
   if(count<0)break
   hash.update(buffer,0,count)
  }
  return hash.digest()
 }
}
