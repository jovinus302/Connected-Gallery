package com.connectedgallery.data
import androidx.room.*
import kotlinx.coroutines.flow.Flow
@Entity(tableName="cache") data class CacheEntry(@PrimaryKey val key:String,val value:String)
@Dao interface CacheDao {
 @Query("SELECT * FROM cache WHERE `key` LIKE 'photo:%'") fun photos():Flow<List<CacheEntry>>
 @Query("SELECT value FROM cache WHERE `key`=:key") suspend fun get(key:String):String?
 @Insert(onConflict=OnConflictStrategy.REPLACE) suspend fun put(entry:CacheEntry)
 @Insert(onConflict=OnConflictStrategy.REPLACE) suspend fun putAll(entries:List<CacheEntry>)
 @Query("DELETE FROM cache WHERE `key`=:key") suspend fun remove(key:String)
 @Query("DELETE FROM cache WHERE `key` LIKE :prefix") suspend fun clear(prefix:String)
}
@Database(entities=[CacheEntry::class],version=1,exportSchema=false)
abstract class GalleryDatabase:RoomDatabase() { abstract fun cache():CacheDao }
