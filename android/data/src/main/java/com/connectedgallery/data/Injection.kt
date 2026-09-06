package com.connectedgallery.data
import android.content.Context
import androidx.room.Room
import androidx.work.*
import com.connectedgallery.domain.GalleryRepository
import dagger.*
import dagger.hilt.*
import dagger.hilt.android.EntryPointAccessors
import dagger.hilt.android.qualifiers.ApplicationContext
import dagger.hilt.components.SingletonComponent
import javax.inject.Singleton

@Module @InstallIn(SingletonComponent::class)
object GalleryModule {
 @Provides @Singleton fun database(@ApplicationContext context:Context)=Room.databaseBuilder(context,GalleryDatabase::class.java,"gallery.db").build()
 @Provides @Singleton fun repository(data:GalleryData):GalleryRepository=data
}
@EntryPoint @InstallIn(SingletonComponent::class)
interface WorkerEntryPoint { fun repository():GalleryRepository }
class SyncWorker(context:Context,params:WorkerParameters):CoroutineWorker(context,params) {
 override suspend fun doWork():Result {
  val repo=EntryPointAccessors.fromApplication(applicationContext,WorkerEntryPoint::class.java).repository()
  return try { repo.refreshAndSync {};Result.success() } catch(e:kotlinx.coroutines.CancellationException){throw e} catch(_:Exception){Result.retry()}
 }
}
fun enqueueSync(context:Context) {
 WorkManager.getInstance(context).enqueueUniqueWork("gallery-sync",ExistingWorkPolicy.KEEP,OneTimeWorkRequestBuilder<SyncWorker>().setBackoffCriteria(BackoffPolicy.EXPONENTIAL,30,java.util.concurrent.TimeUnit.SECONDS).build())
}
